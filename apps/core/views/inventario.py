"""
inventario.py — Ítems, ubicaciones, kardex/historial.
"""
from .common import *  # noqa: F401,F403
from .stock import *   # noqa: F401,F403
from django.http import HttpResponseBadRequest

# ─── TABS DEL INVENTARIO ──────────────────────────────────────────────────────
# Definición canónica (orden por defecto + metadata de presentación). El orden
# real lo guarda InventarioConfig; get_orden_tabs() reconcilia ambos.
TABS_INVENTARIO = [
    {'clave': 'todos',      'etiqueta': 'Todos'},
    {'clave': 'producto',   'etiqueta': 'Producto',   'color': '#198754'},
    {'clave': 'repuesto',   'etiqueta': 'Repuesto'},
    {'clave': 'consumible', 'etiqueta': 'Consumible'},
    {'clave': 'bajo_stock', 'etiqueta': 'Bajo stock', 'danger': True},
]
TABS_CLAVES = [t['clave'] for t in TABS_INVENTARIO]
_TABS_POR_CLAVE = {t['clave']: t for t in TABS_INVENTARIO}

# Columnas ordenables de la tabla → campo ORM (se usa en una tarea posterior)
ORDEN_COLS = {
    'nombre':    'nombre',
    'codigo':    'codigo',
    'tipo':      'tipo',
    'categoria': 'categoria__nombre',
    'stock':     'stock_calc',
}


def get_orden_tabs():
    """
    Devuelve las tabs en el orden guardado (InventarioConfig singleton),
    reconciliado con el set canónico: respeta el orden guardado para claves
    válidas (sin duplicar), y agrega al final cualquier tab canónica ausente.
    Descarta claves desconocidas. Siempre devuelve las 5 tabs con su metadata.
    """
    from ..models import InventarioConfig
    config, _ = InventarioConfig.objects.get_or_create(pk=1)
    ordenadas = []
    vistas = set()
    for clave in (config.orden_tabs or []):
        if clave in _TABS_POR_CLAVE and clave not in vistas:
            ordenadas.append(clave)
            vistas.add(clave)
    for clave in TABS_CLAVES:
        if clave not in vistas:
            ordenadas.append(clave)
            vistas.add(clave)
    return [_TABS_POR_CLAVE[c] for c in ordenadas]


@login_required
@require_POST
@permission_required(_perm('ordenar_tabs_inventario'), raise_exception=True)
def inventario_tabs_orden(request):
    """Persiste el orden global de tabs. Body JSON: {"orden": [clave, ...]}."""
    from ..models import InventarioConfig
    try:
        nuevo = json.loads(request.body).get('orden')
    except (ValueError, TypeError, AttributeError):
        return HttpResponseBadRequest('JSON inválido.')

    if (not isinstance(nuevo, list)
            or len(nuevo) != len(TABS_CLAVES)
            or set(nuevo) != set(TABS_CLAVES)):
        return HttpResponseBadRequest(
            'El orden debe ser una permutación exacta de las tabs.'
        )

    config, _ = InventarioConfig.objects.get_or_create(pk=1)
    config.orden_tabs = nuevo
    config.save(update_fields=['orden_tabs'])
    return JsonResponse({'ok': True})


# ─── INVENTARIO ───────────────────────────────────────────────────────────────

@login_required
@permission_required(_perm('ver_inventario'), raise_exception=True)
@_timed_view('inventario_lista')
def inventario_lista(request):
    q = request.GET.get('q', '').strip()

    qs = (
        Item.objects
        .filter(activo=True)
        .select_related('categoria')
        .annotate(stock_calc=_STOCK_ANN)
        .order_by('orden', 'nombre')
    )
    if q:
        qs = qs.filter(Q(nombre__icontains=q) | Q(codigo__icontains=q))

    paginator = Paginator(qs, 100)
    page_obj = paginator.get_page(request.GET.get('page'))
    page_items = list(page_obj.object_list)

    # Second query: principal location per item (max stock)
    stocks_raw = (
        Stock.objects
        .filter(item__in=page_items)
        .values('item_id', 'ubicacion__nombre', 'cantidad_actual')
    )
    ub_map: dict = {}
    for s in stocks_raw:
        iid = s['item_id']
        if iid not in ub_map or s['cantidad_actual'] > ub_map[iid][0]:
            ub_map[iid] = (s['cantidad_actual'], s['ubicacion__nombre'])

    # Pendientes de conciliación por ítem (salidas con stock insuficiente activas)
    pendientes_map: dict = {}
    pend_qs = (
        DetalleMovimiento.objects
        .filter(
            item__in=page_items,
            pendiente_conciliacion=True,
            movimiento__anulado=False,
            movimiento__eliminado=False,
        )
        .values('item_id')
        .annotate(n=Count('pk'))
    )
    for row in pend_qs:
        pendientes_map[row['item_id']] = row['n']

    items_data = [
        {
            'item': item,
            'stock': item.stock_calc,
            'bajo': item.stock_calc <= item.stock_minimo,
            'negativo': item.stock_calc < 0,
            'pendientes': pendientes_map.get(item.pk, 0),
            'ub_principal': ub_map.get(item.pk, (None, '–'))[1],
        }
        for item in page_items
    ]

    context = {'items_data': items_data, 'q': q, 'page_obj': page_obj}
    return render(request, 'inventario/lista.html', context)


@login_required
@permission_required(_perm('ver_inventario'), raise_exception=True)
def item_detalle(request, pk):
    item = get_object_or_404(Item, pk=pk)
    stocks = Stock.objects.filter(item=item).select_related('ubicacion')
    # Últimas líneas que afectan este ítem (sin movimientos eliminados)
    detalles_recientes = (
        DetalleMovimiento.objects
        .filter(item=item, movimiento__eliminado=False)
        .select_related(
            'movimiento', 'movimiento__usuario',
            'ubicacion_origen', 'ubicacion_destino', 'cliente', 'maquina',
        )
        .order_by('-movimiento__fecha_movimiento')[:20]
    )
    context = {'item': item, 'stocks': stocks, 'detalles_recientes': detalles_recientes}
    return render(request, 'inventario/detalle.html', context)


@login_required
@permission_required(_perm('ver_inventario'), raise_exception=True)
def item_historial(request, pk):
    item = get_object_or_404(Item, pk=pk)
    tipo_filtro   = request.GET.get('tipo',   '').strip()
    estado_filtro = request.GET.get('estado', '').strip()

    # Líneas que afectan este ítem (kardex por detalle, con FK al movimiento cabecera)
    todos = list(
        DetalleMovimiento.objects
        .filter(item=item)
        .select_related(
            'movimiento',
            'movimiento__usuario',
            'movimiento__usuario_edicion',
            'movimiento__usuario_anulacion',
            'movimiento__usuario_eliminacion',
            'ubicacion_origen', 'ubicacion_destino',
            'cliente', 'maquina',
        )
        .order_by('movimiento__fecha_movimiento', 'movimiento__fecha', 'movimiento__pk', 'pk')
    )

    def _delta_activo(det):
        mov = det.movimiento
        if mov.anulado or mov.eliminado:
            return Decimal('0')
        t = mov.tipo_movimiento
        if t == 'entrada':
            return det.cantidad
        if t == 'salida':
            return -det.cantidad
        if t == 'ajuste':
            return det.cantidad
        return Decimal('0')

    kardex = []
    acum = Decimal('0')
    for det in todos:
        d = _delta_activo(det)
        stock_antes   = acum
        stock_despues = acum + d
        acum = stock_despues
        kardex.append({
            'det':          det,
            'mov':          det.movimiento,   # alias conveniente para la plantilla
            'delta':        d,
            'stock_antes':  stock_antes,
            'stock_despues': stock_despues,
            'afecta_stock': not (det.movimiento.anulado or det.movimiento.eliminado),
        })

    kardex.reverse()

    tipos_validos = ('entrada', 'salida', 'ajuste', 'transferencia')
    tipo_filtro_clean = tipo_filtro if tipo_filtro in tipos_validos else ''

    kardex_filtrado = kardex
    if tipo_filtro_clean:
        kardex_filtrado = [
            k for k in kardex_filtrado
            if k['mov'].tipo_movimiento == tipo_filtro_clean
        ]

    if estado_filtro == 'activos':
        kardex_filtrado = [
            k for k in kardex_filtrado
            if not k['mov'].anulado and not k['mov'].eliminado
        ]
    elif estado_filtro == 'anulados':
        kardex_filtrado = [k for k in kardex_filtrado if k['mov'].anulado]
    elif estado_filtro == 'eliminados':
        kardex_filtrado = [k for k in kardex_filtrado if k['mov'].eliminado]

    total_general    = len(kardex)
    total_activos    = sum(1 for k in kardex if not k['mov'].anulado and not k['mov'].eliminado)
    total_anulados   = sum(1 for k in kardex if k['mov'].anulado)
    total_eliminados = sum(1 for k in kardex if k['mov'].eliminado)

    paginator = Paginator(kardex_filtrado, 20)
    page_obj  = paginator.get_page(request.GET.get('page', 1))

    return render(request, 'inventario/historial.html', {
        'item':             item,
        'page_obj':         page_obj,
        'tipo_filtro':      tipo_filtro_clean,
        'estado_filtro':    estado_filtro,
        'total':            len(kardex_filtrado),
        'total_general':    total_general,
        'total_activos':    total_activos,
        'total_anulados':   total_anulados,
        'total_eliminados': total_eliminados,
    })


@login_required
@permission_required(_perm('crear_item'), raise_exception=True)
def item_crear(request):
    if request.method == 'POST':
        form = ItemForm(request.POST)
        if form.is_valid():
            item = form.save()
            messages.success(request, f'Ítem "{item.nombre}" creado exitosamente.')
            return redirect('item_detalle', pk=item.pk)
    else:
        form = ItemForm()

    categorias = Categoria.objects.all()
    return render(request, 'inventario/form.html', {
        'form': form, 'titulo': 'Nuevo Ítem', 'categorias': categorias
    })


@login_required
@permission_required(_perm('editar_item'), raise_exception=True)
def item_editar(request, pk):
    item = get_object_or_404(Item, pk=pk)
    if request.method == 'POST':
        form = ItemForm(request.POST, instance=item)
        if form.is_valid():
            form.save()
            messages.success(request, f'Ítem "{item.nombre}" actualizado.')
            return redirect('item_detalle', pk=item.pk)
    else:
        form = ItemForm(instance=item)

    return render(request, 'inventario/form.html', {
        'form': form, 'titulo': f'Editar: {item.nombre}', 'item': item
    })


@login_required
@permission_required(_perm('editar_item'), raise_exception=True)
@require_POST
def item_toggle_activo(request, pk):
    item = get_object_or_404(Item, pk=pk)
    item.activo = not item.activo
    item.save()
    estado = 'activado' if item.activo else 'desactivado'
    messages.success(request, f'Ítem "{item.nombre}" {estado}.')
    return redirect('inventario_lista')


@login_required
@permission_required(_perm('ver_inventario'), raise_exception=True)
def ubicacion_lista(request):
    ubicaciones = Ubicacion.objects.all()
    return render(request, 'inventario/ubicaciones.html', {'ubicaciones': ubicaciones})


@login_required
@permission_required(_perm('editar_item'), raise_exception=True)
def ubicacion_crear(request):
    if request.method == 'POST':
        form = UbicacionForm(request.POST)
        if form.is_valid():
            u = form.save()
            messages.success(request, f'Ubicación "{u.nombre}" creada.')
            return redirect('ubicacion_lista')
    else:
        form = UbicacionForm()
    return render(request, 'inventario/ubicacion_form.html', {
        'form': form, 'titulo': 'Nueva Ubicación'
    })


@login_required
@permission_required(_perm('editar_item'), raise_exception=True)
def ubicacion_editar(request, pk):
    ubicacion = get_object_or_404(Ubicacion, pk=pk)
    if request.method == 'POST':
        form = UbicacionForm(request.POST, instance=ubicacion)
        if form.is_valid():
            form.save()
            messages.success(request, f'Ubicación "{ubicacion.nombre}" actualizada.')
            return redirect('ubicacion_lista')
    else:
        form = UbicacionForm(instance=ubicacion)
    return render(request, 'inventario/ubicacion_form.html', {
        'form': form, 'titulo': f'Editar: {ubicacion.nombre}', 'ubicacion': ubicacion
    })
