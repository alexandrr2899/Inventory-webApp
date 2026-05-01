from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Q, Count
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from datetime import date, timedelta
from decimal import Decimal
import csv
import json

from .models import (
    Item, Categoria, Ubicacion, Stock, Maquina, Cliente,
    MovimientoInventario, Conteo, ConteoDetalle
)
from .forms import (
    ItemForm, CategoriaForm, UbicacionForm, MaquinaForm, ClienteForm,
    MovimientoEntradaForm, MovimientoSalidaForm, MovimientoTransferenciaForm,
    ConteoForm, FiltroMovimientosForm
)


# ─── DASHBOARD ────────────────────────────────────────────────────────────────

@login_required
def dashboard(request):
    hoy = date.today()

    items_bajo_stock = []
    for item in Item.objects.filter(activo=True):
        if item.bajo_stock():
            items_bajo_stock.append(item)

    ultimos_movimientos = MovimientoInventario.objects.select_related(
        'item', 'usuario', 'ubicacion_origen', 'ubicacion_destino'
    ).order_by('-fecha')[:10]

    # Producción estimada del día
    produccion_hoy = _calcular_produccion(hoy)

    # Repuestos más consumidos (últimos 30 días)
    hace_30 = timezone.now() - timedelta(days=30)
    repuestos_top = (
        MovimientoInventario.objects
        .filter(tipo_movimiento='salida', item__tipo='repuesto', fecha__gte=hace_30)
        .values('item__nombre', 'item__unidad_medida')
        .annotate(total=Sum('cantidad'))
        .order_by('-total')[:5]
    )

    context = {
        'items_bajo_stock': items_bajo_stock,
        'ultimos_movimientos': ultimos_movimientos,
        'produccion_hoy': produccion_hoy,
        'repuestos_top': repuestos_top,
        'hoy': hoy,
        'total_items': Item.objects.filter(activo=True).count(),
        'total_bajo_stock': len(items_bajo_stock),
    }
    return render(request, 'dashboard.html', context)


def _calcular_produccion(fecha):
    """Producción = conteo_tarde - conteo_mañana + salidas_del_día (productos terminados)"""
    try:
        conteo_manana = Conteo.objects.get(fecha=fecha, turno='manana')
        total_manana = ConteoDetalle.objects.filter(
            conteo=conteo_manana, item__tipo='producto'
        ).aggregate(total=Sum('cantidad_contada'))['total'] or Decimal('0')
    except Conteo.DoesNotExist:
        conteo_manana = None
        total_manana = None

    try:
        conteo_tarde = Conteo.objects.get(fecha=fecha, turno='tarde')
        total_tarde = ConteoDetalle.objects.filter(
            conteo=conteo_tarde, item__tipo='producto'
        ).aggregate(total=Sum('cantidad_contada'))['total'] or Decimal('0')
    except Conteo.DoesNotExist:
        conteo_tarde = None
        total_tarde = None

    salidas_hoy = MovimientoInventario.objects.filter(
        tipo_movimiento='salida',
        item__tipo='producto',
        fecha__date=fecha
    ).aggregate(total=Sum('cantidad'))['total'] or Decimal('0')

    produccion = None
    if total_manana is not None and total_tarde is not None:
        produccion = total_tarde - total_manana + salidas_hoy

    return {
        'produccion': produccion,
        'conteo_manana': total_manana,
        'conteo_tarde': total_tarde,
        'salidas': salidas_hoy,
        'tiene_manana': conteo_manana is not None,
        'tiene_tarde': conteo_tarde is not None,
    }


# ─── INVENTARIO ───────────────────────────────────────────────────────────────

@login_required
def inventario_lista(request):
    q = request.GET.get('q', '')
    tipo = request.GET.get('tipo', '')
    solo_bajo = request.GET.get('bajo_stock', '')

    items = Item.objects.select_related('categoria').filter(activo=True)

    if q:
        items = items.filter(Q(nombre__icontains=q) | Q(codigo__icontains=q))
    if tipo:
        items = items.filter(tipo=tipo)

    items_con_stock = []
    for item in items:
        stock = item.stock_total()
        bajo = item.bajo_stock()
        if solo_bajo and not bajo:
            continue
        items_con_stock.append({'item': item, 'stock': stock, 'bajo': bajo})

    context = {
        'items_con_stock': items_con_stock,
        'q': q,
        'tipo': tipo,
        'solo_bajo': solo_bajo,
        'tipos': Item.TIPO_CHOICES,
    }
    return render(request, 'inventario/lista.html', context)


@login_required
def item_detalle(request, pk):
    item = get_object_or_404(Item, pk=pk)
    stocks = Stock.objects.filter(item=item).select_related('ubicacion')
    movimientos = MovimientoInventario.objects.filter(item=item).select_related(
        'ubicacion_origen', 'ubicacion_destino', 'usuario'
    ).order_by('-fecha')[:20]

    context = {'item': item, 'stocks': stocks, 'movimientos': movimientos}
    return render(request, 'inventario/detalle.html', context)


@login_required
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
def item_toggle_activo(request, pk):
    item = get_object_or_404(Item, pk=pk)
    item.activo = not item.activo
    item.save()
    estado = 'activado' if item.activo else 'desactivado'
    messages.success(request, f'Ítem "{item.nombre}" {estado}.')
    return redirect('inventario_lista')


@login_required
def ubicacion_lista(request):
    ubicaciones = Ubicacion.objects.all()
    return render(request, 'inventario/ubicaciones.html', {'ubicaciones': ubicaciones})


@login_required
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


# ─── MOVIMIENTOS ──────────────────────────────────────────────────────────────

@login_required
def movimiento_lista(request):
    form = FiltroMovimientosForm(request.GET or None)
    movimientos = MovimientoInventario.objects.select_related(
        'item', 'usuario', 'ubicacion_origen', 'ubicacion_destino', 'cliente', 'maquina'
    ).order_by('-fecha')

    if form.is_valid():
        if form.cleaned_data.get('fecha_inicio'):
            movimientos = movimientos.filter(fecha__date__gte=form.cleaned_data['fecha_inicio'])
        if form.cleaned_data.get('fecha_fin'):
            movimientos = movimientos.filter(fecha__date__lte=form.cleaned_data['fecha_fin'])
        if form.cleaned_data.get('tipo_movimiento'):
            movimientos = movimientos.filter(tipo_movimiento=form.cleaned_data['tipo_movimiento'])
        if form.cleaned_data.get('item'):
            movimientos = movimientos.filter(item=form.cleaned_data['item'])

    # Exportar CSV
    if request.GET.get('export') == 'csv':
        return _exportar_movimientos_csv(movimientos)

    movimientos = movimientos[:200]
    return render(request, 'movimientos/lista.html', {'movimientos': movimientos, 'form': form})


def _exportar_movimientos_csv(movimientos):
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="movimientos.csv"'
    response.write('﻿')  # BOM para Excel
    writer = csv.writer(response)
    writer.writerow(['Fecha', 'Tipo', 'Ítem', 'Código', 'Cantidad', 'Unidad',
                     'Origen', 'Destino', 'Cliente', 'Máquina', 'Motivo', 'Usuario'])
    for m in movimientos:
        writer.writerow([
            m.fecha.strftime('%Y-%m-%d %H:%M'),
            m.get_tipo_movimiento_display(),
            m.item.nombre,
            m.item.codigo,
            m.cantidad,
            m.item.unidad_medida,
            m.ubicacion_origen.nombre if m.ubicacion_origen else '',
            m.ubicacion_destino.nombre if m.ubicacion_destino else '',
            m.cliente.nombre if m.cliente else '',
            m.maquina.nombre if m.maquina else '',
            m.motivo,
            m.usuario.get_full_name() or m.usuario.username,
        ])
    return response


@login_required
def movimiento_entrada(request):
    items = Item.objects.filter(activo=True).order_by('nombre')
    ubicaciones = Ubicacion.objects.all()

    if request.method == 'POST':
        ubicacion_destino_id = request.POST.get('ubicacion_destino')
        motivo = request.POST.get('motivo', '')
        item_ids = request.POST.getlist('item[]')
        cantidades = request.POST.getlist('cantidad[]')

        errores = []

        # Validar encabezado
        try:
            ubicacion_destino = Ubicacion.objects.get(pk=ubicacion_destino_id)
        except Ubicacion.DoesNotExist:
            errores.append('Debes seleccionar una ubicación de destino.')
            ubicacion_destino = None

        # Validar filas
        filas_validas = []
        for i, (item_id, cant_str) in enumerate(zip(item_ids, cantidades), 1):
            cant_str = cant_str.strip()
            if not item_id and not cant_str:
                continue  # fila vacía, ignorar
            if not item_id:
                errores.append(f'Fila {i}: selecciona un ítem.')
                continue
            if not cant_str:
                errores.append(f'Fila {i}: ingresa una cantidad.')
                continue
            try:
                cantidad = Decimal(cant_str)
                if cantidad <= 0:
                    raise ValueError
            except (ValueError, Exception):
                errores.append(f'Fila {i}: cantidad inválida.')
                continue
            try:
                item = Item.objects.get(pk=item_id, activo=True)
            except Item.DoesNotExist:
                errores.append(f'Fila {i}: ítem no encontrado.')
                continue
            filas_validas.append((item, cantidad))

        if not filas_validas:
            errores.append('Agrega al menos un ítem con cantidad.')

        if errores:
            for e in errores:
                messages.error(request, e)
        elif ubicacion_destino:
            with transaction.atomic():
                for item, cantidad in filas_validas:
                    MovimientoInventario.objects.create(
                        item=item,
                        tipo_movimiento='entrada',
                        cantidad=cantidad,
                        ubicacion_destino=ubicacion_destino,
                        motivo=motivo,
                        usuario=request.user,
                    )
            messages.success(request, f'{len(filas_validas)} entrada(s) registrada(s) exitosamente.')
            return redirect('movimiento_lista')

    context = {'items': items, 'ubicaciones': ubicaciones}
    return render(request, 'movimientos/entrada.html', context)


@login_required
def movimiento_salida(request):
    items = Item.objects.filter(activo=True).order_by('nombre')
    ubicaciones = Ubicacion.objects.all()
    clientes = Cliente.objects.filter(activo=True).order_by('nombre')
    maquinas = Maquina.objects.filter(activo=True).order_by('nombre')
    items_tipos = {str(i.pk): i.tipo for i in items}

    if request.method == 'POST':
        motivo = request.POST.get('motivo', '')
        item_ids = request.POST.getlist('item[]')
        cantidades = request.POST.getlist('cantidad[]')
        ubicacion_ids = request.POST.getlist('ubicacion_origen[]')
        cliente_ids = request.POST.getlist('cliente[]')
        maquina_ids = request.POST.getlist('maquina[]')

        errores = []
        filas_validas = []

        for i, (item_id, cant_str, ub_id, cli_id, maq_id) in enumerate(
            zip(item_ids, cantidades, ubicacion_ids, cliente_ids, maquina_ids), 1
        ):
            cant_str = cant_str.strip()
            if not item_id and not cant_str:
                continue
            if not item_id:
                errores.append(f'Fila {i}: selecciona un ítem.')
                continue
            if not cant_str:
                errores.append(f'Fila {i}: ingresa una cantidad.')
                continue
            try:
                cantidad = Decimal(cant_str)
                if cantidad <= 0:
                    raise ValueError
            except (ValueError, Exception):
                errores.append(f'Fila {i}: cantidad inválida.')
                continue
            try:
                item = Item.objects.get(pk=item_id, activo=True)
            except Item.DoesNotExist:
                errores.append(f'Fila {i}: ítem no encontrado.')
                continue
            if not ub_id:
                errores.append(f'Fila {i} ({item.nombre}): selecciona ubicación de origen.')
                continue
            try:
                ubicacion = Ubicacion.objects.get(pk=ub_id)
            except Ubicacion.DoesNotExist:
                errores.append(f'Fila {i}: ubicación no encontrada.')
                continue

            # Validar stock suficiente
            try:
                stock = Stock.objects.get(item=item, ubicacion=ubicacion)
                if stock.cantidad_actual < cantidad:
                    errores.append(
                        f'Fila {i} ({item.nombre}): stock insuficiente. '
                        f'Disponible: {stock.cantidad_actual} {item.unidad_medida}.'
                    )
                    continue
            except Stock.DoesNotExist:
                errores.append(f'Fila {i} ({item.nombre}): no hay stock en esa ubicación.')
                continue

            # Validar cliente/máquina según tipo
            cliente = None
            maquina = None
            if item.tipo == 'producto':
                if not cli_id:
                    errores.append(f'Fila {i} ({item.nombre}): selecciona un cliente.')
                    continue
                try:
                    cliente = Cliente.objects.get(pk=cli_id)
                except Cliente.DoesNotExist:
                    errores.append(f'Fila {i}: cliente no encontrado.')
                    continue
            elif item.tipo == 'repuesto':
                if not maq_id:
                    errores.append(f'Fila {i} ({item.nombre}): selecciona una máquina.')
                    continue
                try:
                    maquina = Maquina.objects.get(pk=maq_id)
                except Maquina.DoesNotExist:
                    errores.append(f'Fila {i}: máquina no encontrada.')
                    continue
            elif item.tipo == 'consumible' and maq_id:
                try:
                    maquina = Maquina.objects.get(pk=maq_id)
                except Maquina.DoesNotExist:
                    pass

            filas_validas.append((item, cantidad, ubicacion, cliente, maquina))

        if not filas_validas and not errores:
            errores.append('Agrega al menos un ítem con cantidad.')

        if errores:
            for e in errores:
                messages.error(request, e)
        else:
            with transaction.atomic():
                for item, cantidad, ubicacion, cliente, maquina in filas_validas:
                    MovimientoInventario.objects.create(
                        item=item,
                        tipo_movimiento='salida',
                        cantidad=cantidad,
                        ubicacion_origen=ubicacion,
                        cliente=cliente,
                        maquina=maquina,
                        motivo=motivo,
                        usuario=request.user,
                    )
            messages.success(request, f'{len(filas_validas)} salida(s) registrada(s) exitosamente.')
            return redirect('movimiento_lista')

    context = {
        'items': items,
        'ubicaciones': ubicaciones,
        'clientes': clientes,
        'maquinas': maquinas,
        'items_tipos_json': json.dumps(items_tipos),
    }
    return render(request, 'movimientos/salida.html', context)


@login_required
def movimiento_transferencia(request):
    if request.method == 'POST':
        form = MovimientoTransferenciaForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                MovimientoInventario.objects.create(
                    item=form.cleaned_data['item'],
                    tipo_movimiento='transferencia',
                    cantidad=form.cleaned_data['cantidad'],
                    ubicacion_origen=form.cleaned_data['ubicacion_origen'],
                    ubicacion_destino=form.cleaned_data['ubicacion_destino'],
                    motivo=form.cleaned_data.get('motivo', ''),
                    usuario=request.user,
                )
            messages.success(request, 'Transferencia registrada.')
            return redirect('movimiento_lista')
    else:
        form = MovimientoTransferenciaForm()

    return render(request, 'movimientos/transferencia.html', {'form': form})


# ─── CONTEOS ──────────────────────────────────────────────────────────────────

@login_required
def conteo_lista(request):
    conteos = Conteo.objects.select_related('usuario').order_by('-fecha', 'turno')[:60]
    return render(request, 'conteos/lista.html', {'conteos': conteos})


@login_required
def conteo_nuevo(request):
    hoy = date.today()
    items_productos = Item.objects.filter(tipo='producto', activo=True).order_by('nombre')

    # Stock actual por item (suma de todas las ubicaciones)
    stock_por_item = {}
    for item in items_productos:
        stock_por_item[item.pk] = item.stock_total()

    ubicaciones = Ubicacion.objects.all()

    if request.method == 'POST':
        form = ConteoForm(request.POST)
        if form.is_valid():
            fecha = form.cleaned_data['fecha']
            turno = form.cleaned_data['turno']

            # Verificar si ya existe
            if Conteo.objects.filter(fecha=fecha, turno=turno).exists():
                messages.error(request, f'Ya existe un conteo de {turno} para {fecha}.')
                return redirect('conteo_lista')

            with transaction.atomic():
                conteo = form.save(commit=False)
                conteo.usuario = request.user
                conteo.save()

                # Guardar detalles
                ubicacion_default = request.POST.get('ubicacion_default')
                ubicacion_obj = None
                if ubicacion_default:
                    try:
                        ubicacion_obj = Ubicacion.objects.get(pk=ubicacion_default)
                    except Ubicacion.DoesNotExist:
                        pass

                for item in items_productos:
                    key = f'cantidad_{item.pk}'
                    cantidad_str = request.POST.get(key, '').strip()
                    if cantidad_str == '':
                        continue
                    try:
                        cantidad_contada = Decimal(cantidad_str)
                    except Exception:
                        continue

                    # Ubicación por item o la default
                    ub_key = f'ubicacion_{item.pk}'
                    ub_id = request.POST.get(ub_key, ubicacion_default)
                    try:
                        ub = Ubicacion.objects.get(pk=ub_id)
                    except Ubicacion.DoesNotExist:
                        ub = ubicacion_obj
                    if not ub:
                        continue

                    cantidad_sistema = stock_por_item.get(item.pk, Decimal('0'))

                    ConteoDetalle.objects.create(
                        conteo=conteo,
                        item=item,
                        ubicacion=ub,
                        cantidad_contada=cantidad_contada,
                        cantidad_sistema=cantidad_sistema,
                    )

            messages.success(request, f'Conteo de {conteo.get_turno_display()} registrado.')
            return redirect('conteo_detalle', pk=conteo.pk)
    else:
        form = ConteoForm(initial={'fecha': hoy})

    items_para_conteo = [
        {'item': item, 'stock': stock_por_item.get(item.pk, Decimal('0'))}
        for item in items_productos
    ]

    context = {
        'form': form,
        'items_para_conteo': items_para_conteo,
        'ubicaciones': ubicaciones,
        'hoy': hoy,
    }
    return render(request, 'conteos/form.html', context)


@login_required
def conteo_detalle(request, pk):
    conteo = get_object_or_404(Conteo, pk=pk)
    detalles = conteo.detalles.select_related('item', 'ubicacion').order_by('item__nombre')
    total_contado = detalles.aggregate(t=Sum('cantidad_contada'))['t'] or 0
    total_diferencia = detalles.aggregate(t=Sum('diferencia'))['t'] or 0
    hay_diferencias = detalles.exclude(diferencia=0).exists()

    context = {
        'conteo': conteo,
        'detalles': detalles,
        'total_contado': total_contado,
        'total_diferencia': total_diferencia,
        'hay_diferencias': hay_diferencias,
    }
    return render(request, 'conteos/detalle.html', context)


@login_required
def conteo_ajustar(request, pk):
    conteo = get_object_or_404(Conteo, pk=pk)

    if conteo.ajuste_aplicado:
        messages.warning(request, 'El ajuste ya fue aplicado para este conteo.')
        return redirect('conteo_detalle', pk=pk)

    if request.method == 'POST':
        detalles_con_diferencia = conteo.detalles.exclude(diferencia=0)

        if not detalles_con_diferencia.exists():
            messages.info(request, 'No hay diferencias que ajustar.')
            return redirect('conteo_detalle', pk=pk)

        with transaction.atomic():
            for detalle in detalles_con_diferencia:
                MovimientoInventario.objects.create(
                    item=detalle.item,
                    tipo_movimiento='ajuste',
                    cantidad=detalle.diferencia,
                    ubicacion_destino=detalle.ubicacion,
                    motivo=f'Ajuste por conteo físico #{conteo.pk} - {conteo.get_turno_display()} {conteo.fecha}',
                    usuario=request.user,
                )
            conteo.ajuste_aplicado = True
            conteo.save()

        messages.success(request, 'Ajuste de inventario aplicado exitosamente.')
        return redirect('conteo_detalle', pk=pk)

    # GET: mostrar confirmación
    detalles = conteo.detalles.exclude(diferencia=0).select_related('item', 'ubicacion')
    return render(request, 'conteos/confirmar_ajuste.html', {
        'conteo': conteo, 'detalles': detalles
    })


# ─── MÁQUINAS ─────────────────────────────────────────────────────────────────

@login_required
def maquina_lista(request):
    maquinas = Maquina.objects.order_by('nombre')
    return render(request, 'maquinas/lista.html', {'maquinas': maquinas})


@login_required
def maquina_crear(request):
    if request.method == 'POST':
        form = MaquinaForm(request.POST)
        if form.is_valid():
            m = form.save()
            messages.success(request, f'Máquina "{m.nombre}" creada.')
            return redirect('maquina_lista')
    else:
        form = MaquinaForm()
    return render(request, 'maquinas/form.html', {'form': form, 'titulo': 'Nueva Máquina'})


@login_required
def maquina_editar(request, pk):
    maquina = get_object_or_404(Maquina, pk=pk)
    if request.method == 'POST':
        form = MaquinaForm(request.POST, instance=maquina)
        if form.is_valid():
            form.save()
            messages.success(request, f'Máquina "{maquina.nombre}" actualizada.')
            return redirect('maquina_lista')
    else:
        form = MaquinaForm(instance=maquina)
    return render(request, 'maquinas/form.html', {
        'form': form, 'titulo': f'Editar: {maquina.nombre}', 'maquina': maquina
    })


@login_required
def maquina_toggle_activo(request, pk):
    maquina = get_object_or_404(Maquina, pk=pk)
    maquina.activo = not maquina.activo
    maquina.save()
    messages.success(request, f'Máquina "{maquina.nombre}" {"activada" if maquina.activo else "desactivada"}.')
    return redirect('maquina_lista')


# ─── CLIENTES ─────────────────────────────────────────────────────────────────

@login_required
def cliente_lista(request):
    q = request.GET.get('q', '')
    clientes = Cliente.objects.order_by('nombre')
    if q:
        clientes = clientes.filter(Q(nombre__icontains=q) | Q(rtn__icontains=q))
    return render(request, 'clientes/lista.html', {'clientes': clientes, 'q': q})


@login_required
def cliente_crear(request):
    if request.method == 'POST':
        form = ClienteForm(request.POST)
        if form.is_valid():
            c = form.save()
            messages.success(request, f'Cliente "{c.nombre}" creado.')
            return redirect('cliente_lista')
    else:
        form = ClienteForm()
    return render(request, 'clientes/form.html', {'form': form, 'titulo': 'Nuevo Cliente'})


@login_required
def cliente_editar(request, pk):
    cliente = get_object_or_404(Cliente, pk=pk)
    if request.method == 'POST':
        form = ClienteForm(request.POST, instance=cliente)
        if form.is_valid():
            form.save()
            messages.success(request, f'Cliente "{cliente.nombre}" actualizado.')
            return redirect('cliente_lista')
    else:
        form = ClienteForm(instance=cliente)
    return render(request, 'clientes/form.html', {
        'form': form, 'titulo': f'Editar: {cliente.nombre}', 'cliente': cliente
    })


@login_required
def cliente_toggle_activo(request, pk):
    cliente = get_object_or_404(Cliente, pk=pk)
    cliente.activo = not cliente.activo
    cliente.save()
    messages.success(request, f'Cliente "{cliente.nombre}" {"activado" if cliente.activo else "desactivado"}.')
    return redirect('cliente_lista')


# ─── REPORTES ─────────────────────────────────────────────────────────────────

@login_required
def reporte_stock_bajo(request):
    items_bajo = []
    for item in Item.objects.filter(activo=True).select_related('categoria'):
        stock = item.stock_total()
        if stock <= item.stock_minimo:
            items_bajo.append({'item': item, 'stock': stock, 'deficit': item.stock_minimo - stock})

    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="stock_bajo.csv"'
        response.write('﻿')
        writer = csv.writer(response)
        writer.writerow(['Código', 'Nombre', 'Tipo', 'Categoría', 'Stock Actual', 'Stock Mínimo', 'Déficit', 'Unidad'])
        for r in items_bajo:
            writer.writerow([
                r['item'].codigo, r['item'].nombre,
                r['item'].get_tipo_display(),
                r['item'].categoria.nombre if r['item'].categoria else '',
                r['stock'], r['item'].stock_minimo, r['deficit'],
                r['item'].unidad_medida
            ])
        return response

    return render(request, 'reportes/stock_bajo.html', {'items_bajo': items_bajo})


@login_required
def reporte_produccion(request):
    fecha_str = request.GET.get('fecha', '')
    if fecha_str:
        try:
            from datetime import datetime
            fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
        except ValueError:
            fecha = date.today()
    else:
        fecha = date.today()

    produccion = _calcular_produccion(fecha)

    # Detalle por item
    detalle_manana = []
    detalle_tarde = []
    if produccion['tiene_manana']:
        conteo_m = Conteo.objects.get(fecha=fecha, turno='manana')
        detalle_manana = ConteoDetalle.objects.filter(
            conteo=conteo_m, item__tipo='producto'
        ).select_related('item')

    if produccion['tiene_tarde']:
        conteo_t = Conteo.objects.get(fecha=fecha, turno='tarde')
        detalle_tarde = ConteoDetalle.objects.filter(
            conteo=conteo_t, item__tipo='producto'
        ).select_related('item')

    salidas_detalle = MovimientoInventario.objects.filter(
        tipo_movimiento='salida', item__tipo='producto', fecha__date=fecha
    ).select_related('item', 'cliente')

    context = {
        'fecha': fecha,
        'produccion': produccion,
        'detalle_manana': detalle_manana,
        'detalle_tarde': detalle_tarde,
        'salidas_detalle': salidas_detalle,
    }
    return render(request, 'reportes/produccion.html', context)


# ─── API ──────────────────────────────────────────────────────────────────────

@login_required
def api_categoria_nueva(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    try:
        data = json.loads(request.body)
        nombre = data.get('nombre', '').strip()
        if not nombre:
            return JsonResponse({'error': 'Nombre requerido'}, status=400)
        cat, created = Categoria.objects.get_or_create(nombre=nombre)
        return JsonResponse({'id': cat.pk, 'nombre': cat.nombre, 'created': created})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@login_required
def api_item_info(request, pk):
    item = get_object_or_404(Item, pk=pk)
    stocks = list(Stock.objects.filter(item=item).values('ubicacion__id', 'ubicacion__nombre', 'cantidad_actual'))
    return JsonResponse({
        'tipo': item.tipo,
        'unidad_medida': item.unidad_medida,
        'stock_total': str(item.stock_total()),
        'stocks': [
            {'ubicacion_id': s['ubicacion__id'], 'ubicacion': s['ubicacion__nombre'],
             'cantidad': str(s['cantidad_actual'])}
            for s in stocks
        ]
    })
