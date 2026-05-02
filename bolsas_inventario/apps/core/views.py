from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib import messages
from django.db.models import Sum, Q, Count
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from datetime import date, timedelta
from decimal import Decimal
import csv
import io
import json

from .models import (
    Item, Categoria, Ubicacion, Stock, Maquina, Cliente,
    MovimientoInventario, Conteo, ConteoDetalle
)
from django.contrib.auth.models import User, Group
from .forms import (
    ItemForm, CategoriaForm, UbicacionForm, MaquinaForm, ClienteForm,
    MovimientoEntradaForm, MovimientoSalidaForm, MovimientoTransferenciaForm,
    ConteoForm, FiltroMovimientosForm, ProduccionForm, ImportarItemsForm,
    UsuarioCrearForm, UsuarioEditarForm,
)
from .services.notifications import notify_stock, send_n8n_event


def _perm(codename):
    """Shorthand permission string for core app."""
    return f'core.{codename}'


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

    produccion_hoy = _calcular_produccion(hoy)

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
@permission_required(_perm('ver_inventario'), raise_exception=True)
def inventario_lista(request):
    q = request.GET.get('q', '').strip()

    qs = Item.objects.select_related('categoria').order_by('nombre')
    if q:
        qs = qs.filter(Q(nombre__icontains=q) | Q(codigo__icontains=q))

    stocks_raw = (
        Stock.objects
        .filter(item__in=qs)
        .select_related('ubicacion')
        .values('item_id', 'ubicacion__nombre', 'cantidad_actual')
    )
    stocks_por_item: dict = {}
    for s in stocks_raw:
        iid = s['item_id']
        stocks_por_item.setdefault(iid, []).append(s)

    items_data = []
    for item in qs:
        item_stocks = stocks_por_item.get(item.pk, [])
        stock_total = sum(s['cantidad_actual'] for s in item_stocks) or Decimal('0')
        bajo = stock_total <= item.stock_minimo
        ub_principal = (
            max(item_stocks, key=lambda s: s['cantidad_actual'])['ubicacion__nombre']
            if item_stocks else '–'
        )
        items_data.append({
            'item': item,
            'stock': stock_total,
            'bajo': bajo,
            'ub_principal': ub_principal,
        })

    context = {'items_data': items_data, 'q': q}
    return render(request, 'inventario/lista.html', context)


@login_required
@permission_required(_perm('ver_inventario'), raise_exception=True)
def item_detalle(request, pk):
    item = get_object_or_404(Item, pk=pk)
    stocks = Stock.objects.filter(item=item).select_related('ubicacion')
    movimientos = MovimientoInventario.objects.filter(item=item).select_related(
        'ubicacion_origen', 'ubicacion_destino', 'usuario'
    ).order_by('-fecha')[:20]

    context = {'item': item, 'stocks': stocks, 'movimientos': movimientos}
    return render(request, 'inventario/detalle.html', context)


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
@permission_required(_perm('ver_inventario'), raise_exception=True)
def movimiento_lista(request):
    form = FiltroMovimientosForm(request.GET or None)
    movimientos = MovimientoInventario.objects.select_related(
        'item', 'usuario', 'ubicacion_origen', 'ubicacion_destino', 'cliente', 'maquina'
    ).order_by('-fecha')

    if form.is_valid():
        if form.cleaned_data.get('fecha_inicio'):
            movimientos = movimientos.filter(fecha_movimiento__date__gte=form.cleaned_data['fecha_inicio'])
        if form.cleaned_data.get('fecha_fin'):
            movimientos = movimientos.filter(fecha_movimiento__date__lte=form.cleaned_data['fecha_fin'])
        if form.cleaned_data.get('tipo_movimiento'):
            movimientos = movimientos.filter(tipo_movimiento=form.cleaned_data['tipo_movimiento'])
        if form.cleaned_data.get('item'):
            movimientos = movimientos.filter(item=form.cleaned_data['item'])

    if request.GET.get('export') == 'csv':
        return _exportar_movimientos_csv(movimientos)

    movimientos = movimientos[:200]
    return render(request, 'movimientos/lista.html', {'movimientos': movimientos, 'form': form})


def _exportar_movimientos_csv(movimientos):
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="movimientos.csv"'
    response.write('﻿')  # BOM para Excel
    writer = csv.writer(response)
    writer.writerow(['Fecha Movimiento', 'Fecha Registro', 'Tipo', 'Ítem', 'Código', 'Cantidad', 'Unidad',
                     'Origen', 'Destino', 'Cliente', 'Máquina', 'Motivo', 'Usuario'])
    for m in movimientos:
        writer.writerow([
            m.fecha_movimiento.strftime('%Y-%m-%d %H:%M'),
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
@permission_required(_perm('registrar_entrada'), raise_exception=True)
def movimiento_entrada(request):
    items = Item.objects.filter(activo=True).order_by('nombre')
    ubicaciones = Ubicacion.objects.all()

    if request.method == 'POST':
        ubicacion_destino_id = request.POST.get('ubicacion_destino')
        motivo = request.POST.get('motivo', '')
        fecha_mov_str = request.POST.get('fecha_movimiento', '').strip()
        item_ids = request.POST.getlist('item[]')
        cantidades = request.POST.getlist('cantidad[]')

        errores = []

        try:
            ubicacion_destino = Ubicacion.objects.get(pk=ubicacion_destino_id)
        except Ubicacion.DoesNotExist:
            errores.append('Debes seleccionar una ubicación de destino.')
            ubicacion_destino = None

        # Parsear fecha_movimiento
        fecha_movimiento = timezone.now()
        if fecha_mov_str:
            try:
                from django.utils.dateparse import parse_datetime
                parsed = parse_datetime(fecha_mov_str)
                if parsed:
                    fecha_movimiento = timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed
            except Exception:
                pass

        filas_validas = []
        for i, (item_id, cant_str) in enumerate(zip(item_ids, cantidades), 1):
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
                        fecha_movimiento=fecha_movimiento,
                        usuario=request.user,
                    )
                    send_n8n_event('movement_created', {
                        'tipo': 'entrada', 'item': item.nombre, 'codigo': item.codigo,
                        'cantidad': str(cantidad), 'ubicacion': ubicacion_destino.nombre,
                        'usuario': request.user.username,
                    })
                    notify_stock(item)
            messages.success(request, f'{len(filas_validas)} entrada(s) registrada(s) exitosamente.')
            return redirect('movimiento_lista')

    context = {'items': items, 'ubicaciones': ubicaciones}
    return render(request, 'movimientos/entrada.html', context)


@login_required
@permission_required(_perm('registrar_salida'), raise_exception=True)
def movimiento_salida(request):
    items = Item.objects.filter(activo=True).order_by('nombre')
    ubicaciones = Ubicacion.objects.all()
    clientes = Cliente.objects.filter(activo=True).order_by('nombre')
    maquinas = Maquina.objects.filter(activo=True).order_by('nombre')
    items_tipos = {str(i.pk): i.tipo for i in items}

    if request.method == 'POST':
        motivo = request.POST.get('motivo', '')
        fecha_mov_str = request.POST.get('fecha_movimiento', '').strip()
        item_ids = request.POST.getlist('item[]')
        cantidades = request.POST.getlist('cantidad[]')
        ubicacion_ids = request.POST.getlist('ubicacion_origen[]')
        cliente_ids = request.POST.getlist('cliente[]')
        maquina_ids = request.POST.getlist('maquina[]')

        # Parsear fecha_movimiento
        fecha_movimiento = timezone.now()
        if fecha_mov_str:
            try:
                from django.utils.dateparse import parse_datetime
                parsed = parse_datetime(fecha_mov_str)
                if parsed:
                    fecha_movimiento = timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed
            except Exception:
                pass

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
                        fecha_movimiento=fecha_movimiento,
                        usuario=request.user,
                    )
                    send_n8n_event('movement_created', {
                        'tipo': 'salida', 'item': item.nombre, 'codigo': item.codigo,
                        'cantidad': str(cantidad), 'ubicacion': ubicacion.nombre,
                        'cliente': cliente.nombre if cliente else None,
                        'usuario': request.user.username,
                    })
                    notify_stock(item)
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
@permission_required(_perm('registrar_entrada'), raise_exception=True)
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
@permission_required(_perm('registrar_conteo'), raise_exception=True)
def conteo_lista(request):
    conteos = Conteo.objects.select_related('usuario').order_by('-fecha', 'turno')[:60]
    return render(request, 'conteos/lista.html', {'conteos': conteos})


@login_required
@permission_required(_perm('registrar_conteo'), raise_exception=True)
def conteo_nuevo(request):
    hoy = date.today()
    items = Item.objects.filter(activo=True).order_by('tipo', 'nombre')
    ubicaciones = Ubicacion.objects.all()

    # Stock actual por (item, ubicacion) para mostrar en el formulario
    stocks_map = {}
    for s in Stock.objects.select_related('item', 'ubicacion').filter(item__activo=True):
        stocks_map[(s.item_id, s.ubicacion_id)] = s.cantidad_actual

    # Stock total por item (para mostrar en el selector)
    stocks_totales = {}
    for s in Stock.objects.filter(item__activo=True).values('item_id').annotate(t=Sum('cantidad_actual')):
        stocks_totales[s['item_id']] = s['t'] or Decimal('0')

    items_json = json.dumps([
        {
            'pk': item.pk,
            'nombre': item.nombre,
            'codigo': item.codigo,
            'tipo': item.tipo,
            'tipo_display': item.get_tipo_display(),
            'unidad': item.unidad_medida,
            'stock_total': str(stocks_totales.get(item.pk, Decimal('0'))),
        }
        for item in items
    ])

    ubicaciones_json = json.dumps([
        {'pk': u.pk, 'nombre': u.nombre, 'tipo': u.get_tipo_display()}
        for u in ubicaciones
    ])

    if request.method == 'POST':
        form = ConteoForm(request.POST)
        if not form.is_valid():
            return render(request, 'conteos/form.html', {
                'form': form, 'items_json': items_json,
                'ubicaciones_json': ubicaciones_json, 'hoy': hoy
            })

        fecha = form.cleaned_data['fecha']
        turno = form.cleaned_data['turno']

        if Conteo.objects.filter(fecha=fecha, turno=turno).exists():
            messages.error(request, f'Ya existe un conteo de {dict(Conteo.TURNO_CHOICES)[turno]} para {fecha}.')
            return render(request, 'conteos/form.html', {
                'form': form, 'items_json': items_json,
                'ubicaciones_json': ubicaciones_json, 'hoy': hoy
            })

        item_ids = request.POST.getlist('item[]')
        ubicacion_ids = request.POST.getlist('ubicacion[]')
        cantidades = request.POST.getlist('cantidad_contada[]')

        errores = []
        filas = []

        for i, (item_id, ub_id, cant_str) in enumerate(
            zip(item_ids, ubicacion_ids, cantidades), 1
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
            if not ub_id:
                errores.append(f'Fila {i}: selecciona una ubicación.')
                continue

            try:
                cantidad_contada = Decimal(cant_str)
            except Exception:
                errores.append(f'Fila {i}: cantidad inválida.')
                continue
            if cantidad_contada < 0:
                errores.append(f'Fila {i}: la cantidad no puede ser negativa.')
                continue

            try:
                item = Item.objects.get(pk=item_id, activo=True)
            except Item.DoesNotExist:
                errores.append(f'Fila {i}: ítem no encontrado.')
                continue
            try:
                ubicacion = Ubicacion.objects.get(pk=ub_id)
            except Ubicacion.DoesNotExist:
                errores.append(f'Fila {i}: ubicación no encontrada.')
                continue

            cantidad_sistema = stocks_map.get((item.pk, ubicacion.pk), Decimal('0'))
            filas.append((item, ubicacion, cantidad_contada, cantidad_sistema))

        if errores:
            for e in errores:
                messages.error(request, e)
            return render(request, 'conteos/form.html', {
                'form': form, 'items_json': items_json,
                'ubicaciones_json': ubicaciones_json, 'hoy': hoy
            })

        if not filas:
            messages.error(request, 'Debes ingresar al menos un ítem con cantidad.')
            return render(request, 'conteos/form.html', {
                'form': form, 'items_json': items_json,
                'ubicaciones_json': ubicaciones_json, 'hoy': hoy
            })

        with transaction.atomic():
            conteo = form.save(commit=False)
            conteo.usuario = request.user
            conteo.save()
            for item, ubicacion, cantidad_contada, cantidad_sistema in filas:
                ConteoDetalle.objects.create(
                    conteo=conteo,
                    item=item,
                    ubicacion=ubicacion,
                    cantidad_contada=cantidad_contada,
                    cantidad_sistema_al_conteo=cantidad_sistema,
                )

        messages.success(
            request,
            f'Conteo de {conteo.get_turno_display()} registrado con {len(filas)} ítem(s). '
            f'Revisá la conciliación para calcular diferencias.'
        )
        return redirect('conteo_conciliar', pk=conteo.pk)

    form = ConteoForm(initial={
        'fecha': hoy,
        'fecha_hora_conteo': timezone.now().strftime('%Y-%m-%dT%H:%M'),
    })
    return render(request, 'conteos/form.html', {
        'form': form,
        'items_json': items_json,
        'ubicaciones_json': ubicaciones_json,
        'hoy': hoy,
    })


@login_required
@permission_required(_perm('registrar_conteo'), raise_exception=True)
def conteo_detalle(request, pk):
    conteo = get_object_or_404(Conteo, pk=pk)
    detalles = conteo.detalles.select_related('item', 'ubicacion').order_by('item__nombre')
    total_contado = detalles.aggregate(t=Sum('cantidad_contada'))['t'] or 0
    total_dif_original = detalles.aggregate(t=Sum('diferencia_original'))['t'] or 0

    context = {
        'conteo': conteo,
        'detalles': detalles,
        'total_contado': total_contado,
        'total_dif_original': total_dif_original,
    }
    return render(request, 'conteos/detalle.html', context)


@login_required
@permission_required(_perm('aplicar_conciliacion'), raise_exception=True)
def conteo_conciliar(request, pk):
    conteo = get_object_or_404(Conteo, pk=pk)
    detalles = conteo.detalles.select_related('item', 'ubicacion').order_by('item__nombre')

    plan = []
    with transaction.atomic():
        for detalle in detalles:
            # Movimientos atrasados: registrados DESPUÉS del conteo, pero con fecha_movimiento
            # ANTERIOR al momento del conteo → debían haber sido parte del stock al contar
            late_movs = MovimientoInventario.objects.filter(
                item=detalle.item,
                fecha__gt=conteo.fecha_hora_conteo,
                fecha_movimiento__lte=conteo.fecha_hora_conteo,
            ).filter(
                Q(ubicacion_destino=detalle.ubicacion) | Q(ubicacion_origen=detalle.ubicacion)
            ).select_related('ubicacion_origen', 'ubicacion_destino', 'usuario')

            late_entradas = late_movs.filter(
                tipo_movimiento='entrada',
                ubicacion_destino=detalle.ubicacion,
            ).aggregate(s=Sum('cantidad'))['s'] or Decimal('0')

            late_salidas = late_movs.filter(
                tipo_movimiento='salida',
                ubicacion_origen=detalle.ubicacion,
            ).aggregate(s=Sum('cantidad'))['s'] or Decimal('0')

            stock_teorico = detalle.cantidad_sistema_al_conteo + late_entradas - late_salidas
            diferencia_final = detalle.cantidad_contada - stock_teorico

            # Guardar diferencia_final calculada si cambió
            if detalle.diferencia_final != diferencia_final:
                detalle.diferencia_final = diferencia_final
                ConteoDetalle.objects.filter(pk=detalle.pk).update(diferencia_final=diferencia_final)

            plan.append({
                'detalle': detalle,
                'late_movimientos': late_movs,
                'late_entradas': late_entradas,
                'late_salidas': late_salidas,
                'stock_teorico': stock_teorico,
                'diferencia_final': diferencia_final,
            })

    return render(request, 'conteos/conciliar.html', {
        'conteo': conteo,
        'plan': plan,
    })


@login_required
@permission_required(_perm('aplicar_conciliacion'), raise_exception=True)
def conteo_ajustar_detalle(request, pk, det_pk):
    if request.method != 'POST':
        return redirect('conteo_conciliar', pk=pk)

    conteo = get_object_or_404(Conteo, pk=pk)
    detalle = get_object_or_404(ConteoDetalle, pk=det_pk, conteo=conteo)

    if detalle.ajuste_aplicado:
        messages.warning(request, 'Este ajuste ya fue aplicado.')
        return redirect('conteo_conciliar', pk=pk)

    if detalle.diferencia_final is None:
        messages.error(request, 'Primero calculá la diferencia final en la pantalla de conciliación.')
        return redirect('conteo_conciliar', pk=pk)

    if detalle.diferencia_final == 0:
        messages.info(request, f'{detalle.item.nombre}: no hay diferencia que ajustar.')
        return redirect('conteo_conciliar', pk=pk)

    with transaction.atomic():
        MovimientoInventario.objects.create(
            item=detalle.item,
            tipo_movimiento='ajuste',
            cantidad=detalle.diferencia_final,
            ubicacion_destino=detalle.ubicacion,
            motivo=f'Ajuste por conciliación — Conteo #{conteo.pk} ({conteo.get_turno_display()} {conteo.fecha})',
            usuario=request.user,
        )
        ConteoDetalle.objects.filter(pk=detalle.pk).update(ajuste_aplicado=True)
        conteo.refresh_from_db()
        conteo.actualizar_estado()

    send_n8n_event('count_difference', {
        'conteo_id': conteo.pk, 'item': detalle.item.nombre, 'codigo': detalle.item.codigo,
        'diferencia': str(detalle.diferencia_final), 'ubicacion': detalle.ubicacion.nombre,
        'usuario': request.user.username,
    })
    notify_stock(detalle.item)
    messages.success(request, f'Ajuste aplicado: {detalle.item.nombre} ({detalle.diferencia_final:+g} {detalle.item.unidad_medida}).')
    return redirect('conteo_conciliar', pk=pk)


@login_required
@permission_required(_perm('aplicar_conciliacion'), raise_exception=True)
def conteo_ajustar_todos(request, pk):
    if request.method != 'POST':
        return redirect('conteo_conciliar', pk=pk)

    conteo = get_object_or_404(Conteo, pk=pk)
    detalles = conteo.detalles.filter(
        ajuste_aplicado=False,
        diferencia_final__isnull=False,
    ).exclude(diferencia_final=0).select_related('item', 'ubicacion')

    if not detalles.exists():
        messages.info(request, 'No hay ajustes pendientes con diferencia.')
        return redirect('conteo_conciliar', pk=pk)

    count = 0
    with transaction.atomic():
        for detalle in detalles:
            MovimientoInventario.objects.create(
                item=detalle.item,
                tipo_movimiento='ajuste',
                cantidad=detalle.diferencia_final,
                ubicacion_destino=detalle.ubicacion,
                motivo=f'Ajuste por conciliación — Conteo #{conteo.pk} ({conteo.get_turno_display()} {conteo.fecha})',
                usuario=request.user,
            )
            count += 1
        ConteoDetalle.objects.filter(
            conteo=conteo, ajuste_aplicado=False,
            diferencia_final__isnull=False
        ).exclude(diferencia_final=0).update(ajuste_aplicado=True)
        conteo.refresh_from_db()
        conteo.actualizar_estado()

    send_n8n_event('count_difference', {
        'conteo_id': conteo.pk, 'ajustes_aplicados': count,
        'usuario': request.user.username,
    })
    messages.success(request, f'{count} ajuste(s) aplicado(s) exitosamente.')
    return redirect('conteo_conciliar', pk=pk)


@login_required
@permission_required(_perm('aplicar_conciliacion'), raise_exception=True)
def conteo_marcar_conciliado(request, pk):
    if request.method != 'POST':
        return redirect('conteo_conciliar', pk=pk)

    conteo = get_object_or_404(Conteo, pk=pk)

    # Verificar que no queden diferencias sin ajustar
    pendientes = conteo.detalles.filter(
        ajuste_aplicado=False,
        diferencia_final__isnull=False,
    ).exclude(diferencia_final=0).count()

    sin_calcular = conteo.detalles.filter(diferencia_final__isnull=True).count()

    if sin_calcular > 0:
        messages.warning(request, f'Hay {sin_calcular} línea(s) sin diferencia calculada. Abrí la conciliación primero.')
        return redirect('conteo_conciliar', pk=pk)

    if pendientes > 0:
        messages.warning(request, f'Hay {pendientes} ajuste(s) pendiente(s) con diferencia. Aplicalos o ignoralos antes de cerrar.')
        return redirect('conteo_conciliar', pk=pk)

    conteo.estado = 'conciliado'
    conteo.save(update_fields=['estado'])
    messages.success(request, 'Conteo marcado como conciliado.')
    return redirect('conteo_detalle', pk=pk)


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
@permission_required(_perm('ver_reportes'), raise_exception=True)
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
@permission_required(_perm('ver_reportes'), raise_exception=True)
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


# ─── PRODUCCIÓN ───────────────────────────────────────────────────────────────

@login_required
@permission_required(_perm('registrar_produccion'), raise_exception=True)
def produccion_nueva(request):
    ubicaciones = Ubicacion.objects.all()

    if request.method == 'POST':
        form = ProduccionForm(request.POST)
        if form.is_valid():
            item = form.cleaned_data['item']
            cantidad = form.cleaned_data['cantidad']
            ubicacion = form.cleaned_data['ubicacion_destino']
            fecha_movimiento = form.cleaned_data['fecha_movimiento']
            motivo = form.cleaned_data.get('motivo', '') or f'Producción registrada'

            if timezone.is_naive(fecha_movimiento):
                fecha_movimiento = timezone.make_aware(fecha_movimiento)

            with transaction.atomic():
                MovimientoInventario.objects.create(
                    item=item,
                    tipo_movimiento='entrada',
                    cantidad=cantidad,
                    ubicacion_destino=ubicacion,
                    motivo=motivo,
                    fecha_movimiento=fecha_movimiento,
                    usuario=request.user,
                )

            send_n8n_event('production_created', {
                'item': item.nombre, 'codigo': item.codigo,
                'cantidad': str(cantidad), 'ubicacion': ubicacion.nombre,
                'usuario': request.user.username,
                'fecha_movimiento': fecha_movimiento.isoformat(),
            })
            notify_stock(item)

            messages.success(request, f'Producción registrada: {cantidad} {item.unidad_medida} de {item.nombre}.')
            return redirect('produccion_nueva')
    else:
        form = ProduccionForm(initial={
            'fecha_movimiento': timezone.now().strftime('%Y-%m-%dT%H:%M'),
        })

    return render(request, 'produccion/form.html', {
        'form': form,
        'ubicaciones': ubicaciones,
    })


# ─── IMPORTAR EXCEL ───────────────────────────────────────────────────────────

@login_required
@permission_required(_perm('importar_excel'), raise_exception=True)
def importar_items(request):
    resultados = None

    if request.method == 'POST':
        form = ImportarItemsForm(request.POST, request.FILES)
        if form.is_valid():
            archivo = request.FILES['archivo']
            resultados = _procesar_excel_items(archivo)
    else:
        form = ImportarItemsForm()

    return render(request, 'importar/form.html', {
        'form': form,
        'resultados': resultados,
    })


def _procesar_excel_items(archivo):
    try:
        import openpyxl
    except ImportError:
        return {'error': 'openpyxl no está instalado.', 'creados': 0, 'actualizados': 0, 'errores': []}

    creados = 0
    actualizados = 0
    errores = []

    try:
        wb = openpyxl.load_workbook(archivo, read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
    except Exception as e:
        return {'error': f'No se pudo leer el archivo: {e}', 'creados': 0, 'actualizados': 0, 'errores': []}

    if not rows:
        return {'error': 'El archivo está vacío.', 'creados': 0, 'actualizados': 0, 'errores': []}

    # First row must be headers; find column indices
    headers = [str(h).strip().lower() if h else '' for h in rows[0]]
    col = {name: headers.index(name) for name in ('codigo', 'nombre', 'tipo', 'unidad_medida') if name in headers}

    required = ['codigo', 'nombre', 'tipo', 'unidad_medida']
    missing = [r for r in required if r not in col]
    if missing:
        return {
            'error': f'Columnas requeridas faltantes: {", ".join(missing)}.',
            'creados': 0, 'actualizados': 0, 'errores': [],
        }

    col_opt = lambda name: headers.index(name) if name in headers else None
    idx_desc = col_opt('descripcion')
    idx_cat = col_opt('categoria')
    idx_min = col_opt('stock_minimo')

    TIPOS_VALIDOS = {'producto', 'repuesto', 'consumible'}

    for row_num, row in enumerate(rows[1:], start=2):
        try:
            codigo = str(row[col['codigo']] or '').strip()
            nombre = str(row[col['nombre']] or '').strip()
            tipo = str(row[col['tipo']] or '').strip().lower()
            unidad = str(row[col['unidad_medida']] or '').strip()

            if not codigo or not nombre:
                errores.append(f'Fila {row_num}: código o nombre vacío, se omite.')
                continue
            if tipo not in TIPOS_VALIDOS:
                errores.append(f'Fila {row_num} ({codigo}): tipo "{tipo}" inválido (usar: producto/repuesto/consumible).')
                continue
            if not unidad:
                errores.append(f'Fila {row_num} ({codigo}): unidad de medida requerida.')
                continue

            descripcion = str(row[idx_desc] or '').strip() if idx_desc is not None else ''

            categoria = None
            if idx_cat is not None and row[idx_cat]:
                cat_nombre = str(row[idx_cat]).strip()
                if cat_nombre:
                    categoria, _ = Categoria.objects.get_or_create(nombre=cat_nombre)

            stock_minimo = Decimal('0')
            if idx_min is not None and row[idx_min] is not None:
                try:
                    stock_minimo = Decimal(str(row[idx_min]))
                except Exception:
                    pass

            item, created = Item.objects.update_or_create(
                codigo=codigo,
                defaults={
                    'nombre': nombre,
                    'tipo': tipo,
                    'unidad_medida': unidad,
                    'descripcion': descripcion,
                    'categoria': categoria,
                    'stock_minimo': stock_minimo,
                    'activo': True,
                },
            )
            if created:
                creados += 1
            else:
                actualizados += 1

        except Exception as e:
            errores.append(f'Fila {row_num}: error inesperado — {e}')

    return {'creados': creados, 'actualizados': actualizados, 'errores': errores, 'error': None}


@login_required
@permission_required(_perm('importar_excel'), raise_exception=True)
def descargar_plantilla(request):
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
    except ImportError:
        messages.error(request, 'openpyxl no está instalado.')
        return redirect('importar_items')

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Items'

    headers = ['codigo', 'nombre', 'tipo', 'unidad_medida', 'stock_minimo', 'categoria', 'descripcion']
    header_fill = PatternFill('solid', fgColor='003087')
    header_font = Font(bold=True, color='FFFFFF')

    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center')

    # Example rows
    ejemplos = [
        ['BOLSA-001', 'Bolsa de polietileno 10x15', 'producto', 'unidad', 100, 'Bolsas', ''],
        ['REP-001', 'Rodamiento 6205', 'repuesto', 'pieza', 5, 'Repuestos', 'Para máquina selladora'],
        ['CONS-001', 'Cinta adhesiva', 'consumible', 'rollo', 10, 'Consumibles', ''],
    ]
    for row_data in ejemplos:
        ws.append(row_data)

    for col in ws.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        ws.column_dimensions[col[0].column_letter].width = max(12, max_len + 4)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    response = HttpResponse(
        buf.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = 'attachment; filename="plantilla_items.xlsx"'
    return response


# ─── USUARIOS ─────────────────────────────────────────────────────────────────

def _staff_required(view_func):
    """Restrict view to staff/superusers only."""
    from functools import wraps
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login
            return redirect_to_login(request.get_full_path())
        if not (request.user.is_staff or request.user.is_superuser):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied
        return view_func(request, *args, **kwargs)
    return _wrapped


def _get_grupo(user):
    return user.groups.first().name if user.groups.exists() else ''


@login_required
@_staff_required
def usuario_lista(request):
    usuarios = (
        User.objects.prefetch_related('groups')
        .order_by('username')
    )
    data = [
        {'user': u, 'grupo': _get_grupo(u)}
        for u in usuarios
    ]
    return render(request, 'usuarios/lista.html', {'data': data})


@login_required
@_staff_required
def usuario_crear(request):
    if request.method == 'POST':
        form = UsuarioCrearForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            user = User.objects.create_user(
                username=cd['username'],
                password=cd['password'],
                first_name=cd.get('first_name', ''),
                last_name=cd.get('last_name', ''),
                email=cd.get('email', ''),
            )
            grupo_nombre = cd.get('grupo')
            if grupo_nombre:
                try:
                    grupo = Group.objects.get(name=grupo_nombre)
                    user.groups.set([grupo])
                except Group.DoesNotExist:
                    pass
            messages.success(request, f'Usuario "{user.username}" creado exitosamente.')
            return redirect('usuario_lista')
    else:
        form = UsuarioCrearForm()

    return render(request, 'usuarios/form.html', {'form': form, 'titulo': 'Nuevo Usuario'})


@login_required
@_staff_required
def usuario_editar(request, pk):
    usuario = get_object_or_404(User, pk=pk)

    if request.method == 'POST':
        form = UsuarioEditarForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            usuario.first_name = cd.get('first_name', '')
            usuario.last_name = cd.get('last_name', '')
            usuario.email = cd.get('email', '')
            usuario.is_active = cd.get('is_active', True)

            nueva_pass = cd.get('nueva_password')
            if nueva_pass:
                usuario.set_password(nueva_pass)

            usuario.save()

            grupo_nombre = cd.get('grupo')
            if grupo_nombre:
                try:
                    grupo = Group.objects.get(name=grupo_nombre)
                    usuario.groups.set([grupo])
                except Group.DoesNotExist:
                    usuario.groups.clear()
            else:
                usuario.groups.clear()

            messages.success(request, f'Usuario "{usuario.username}" actualizado.')
            return redirect('usuario_lista')
    else:
        form = UsuarioEditarForm(initial={
            'first_name': usuario.first_name,
            'last_name': usuario.last_name,
            'email': usuario.email,
            'is_active': usuario.is_active,
            'grupo': _get_grupo(usuario),
        })

    return render(request, 'usuarios/form.html', {
        'form': form,
        'titulo': f'Editar: {usuario.username}',
        'usuario': usuario,
    })
