"""
movimientos.py — Entradas, salidas, transferencias y gestión de movimientos.

Incluye salida de producto terminado con stock negativo (pendiente_conciliacion),
edición/anulación/eliminación y exportación CSV.
"""
from .common import *  # noqa: F401,F403
from .stock import *   # noqa: F401,F403


# ─── MOVIMIENTOS ──────────────────────────────────────────────────────────────

@login_required
@permission_required(_perm('ver_inventario'), raise_exception=True)
@_timed_view('movimiento_lista')
def movimiento_lista(request):
    form = FiltroMovimientosForm(request.GET or None)
    movimientos = (
        MovimientoInventario.objects
        .prefetch_related('detalles__item', 'detalles__ubicacion_origen',
                          'detalles__ubicacion_destino', 'detalles__cliente',
                          'detalles__maquina')
        .select_related('usuario', 'usuario_anulacion', 'usuario_edicion',
                        'usuario_eliminacion', 'cliente')
        .annotate(
            num_detalles=Count('detalles', distinct=True),
            num_pendientes=Count(
                'detalles',
                filter=Q(detalles__pendiente_conciliacion=True),
                distinct=True,
            ),
        )
        .order_by('-fecha_movimiento')
    )

    if form.is_valid():
        if form.cleaned_data.get('fecha_inicio'):
            movimientos = movimientos.filter(
                fecha_movimiento__date__gte=form.cleaned_data['fecha_inicio']
            )
        if form.cleaned_data.get('fecha_fin'):
            movimientos = movimientos.filter(
                fecha_movimiento__date__lte=form.cleaned_data['fecha_fin']
            )
        if form.cleaned_data.get('tipo_movimiento'):
            movimientos = movimientos.filter(
                tipo_movimiento=form.cleaned_data['tipo_movimiento']
            )
        if form.cleaned_data.get('item'):
            movimientos = movimientos.filter(
                detalles__item=form.cleaned_data['item']
            ).distinct()

    if request.GET.get('export') == 'csv':
        return _exportar_movimientos_csv(movimientos)

    paginator = Paginator(movimientos, 50)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'movimientos/lista.html', {
        'movimientos': page_obj,
        'page_obj': page_obj,
        'form': form,
    })


def _exportar_movimientos_csv(movimientos):
    """Exporta cada LÍNEA (DetalleMovimiento) como una fila CSV, con datos del cabecera."""
    class Echo:
        def write(self, value):
            return value

    writer = csv.writer(Echo())

    def rows():
        yield '﻿'
        yield writer.writerow([
            'Movimiento #', 'Fecha Movimiento', 'Fecha Registro', 'Tipo',
            'Ítem', 'Código', 'Cantidad', 'Unidad',
            'Origen', 'Destino', 'Cliente', 'Máquina', 'Motivo', 'Usuario',
            'Estado',
        ])
        detalles = (
            DetalleMovimiento.objects
            .filter(movimiento__in=movimientos.values('pk'))
            .select_related(
                'movimiento', 'movimiento__usuario',
                'item', 'ubicacion_origen', 'ubicacion_destino', 'cliente', 'maquina',
            )
            .order_by('-movimiento__fecha_movimiento', 'movimiento_id', 'id')
            .iterator(chunk_size=500)
        )
        for det in detalles:
            mov = det.movimiento
            estado = ('Anulado' if mov.anulado else
                      'Eliminado' if mov.eliminado else
                      'Editado' if mov.editado else 'Activo')
            yield writer.writerow([
                mov.pk,
                timezone.localtime(mov.fecha_movimiento).strftime('%Y-%m-%d %H:%M'),
                timezone.localtime(mov.fecha).strftime('%Y-%m-%d %H:%M'),
                mov.get_tipo_movimiento_display(),
                det.item.nombre,
                det.item.codigo,
                det.cantidad,
                det.item.unidad_medida,
                det.ubicacion_origen.nombre if det.ubicacion_origen else '',
                det.ubicacion_destino.nombre if det.ubicacion_destino else '',
                det.cliente.nombre if det.cliente else '',
                det.maquina.nombre if det.maquina else '',
                mov.motivo,
                mov.usuario.get_full_name() or mov.usuario.username,
                estado,
            ])

    response = StreamingHttpResponse(rows(), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="movimientos.csv"'
    return response


@login_required
@permission_required(_perm('registrar_entrada'), raise_exception=True)
def movimiento_entrada(request):
    items = Item.objects.filter(activo=True).order_by('orden', 'nombre')
    ubicaciones = Ubicacion.objects.all()
    item_id_inicial = request.GET.get('item', '')

    items_json = _json_safe([
        {'pk': it.pk, 'nombre': it.nombre, 'codigo': it.codigo, 'unidad': it.unidad_medida}
        for it in items
    ])
    ubicaciones_json = _json_safe([
        {'pk': u.pk, 'nombre': u.nombre, 'tipo': u.get_tipo_display()}
        for u in ubicaciones
    ])

    if request.method == 'POST':
        ubicacion_destino_id = request.POST.get('ubicacion_destino', '').strip()
        motivo = request.POST.get('motivo', '')
        fecha_mov_str = request.POST.get('fecha_movimiento', '').strip()
        item_ids = request.POST.getlist('item[]')
        cantidades = request.POST.getlist('cantidad[]')

        errores = []
        ubicacion_destino = None

        try:
            ubicacion_destino = Ubicacion.objects.get(pk=ubicacion_destino_id)
        except (Ubicacion.DoesNotExist, ValueError):
            errores.append('Debes seleccionar una ubicación de destino.')

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
                cantidad = _parse_cantidad_entera(cant_str)
            except ValueError as exc:
                if 'enteros' in str(exc):
                    errores.append('Las cantidades de inventario deben ser números enteros.')
                else:
                    errores.append(f'Fila {i}: cantidad inválida.')
                continue
            except (ValueError, Exception):
                errores.append(f'Fila {i}: cantidad inválida.')
                continue
            try:
                item = Item.objects.get(pk=item_id, activo=True)
            except Item.DoesNotExist:
                errores.append(f'Fila {i}: ítem no encontrado.')
                continue
            filas_validas.append((item, cantidad))

        if not filas_validas and not errores:
            errores.append('Agrega al menos un ítem con cantidad.')

        if errores:
            for e in errores:
                messages.error(request, e)
            filas_previas = [
                {'item_id': iid, 'cantidad': cant}
                for iid, cant in zip(item_ids, cantidades)
                if iid or cant.strip()
            ]
            return render(request, 'movimientos/entrada.html', {
                'items_json': items_json,
                'ubicaciones_json': ubicaciones_json,
                'item_id_inicial': item_id_inicial,
                'ub_destino_previo': ubicacion_destino_id,
                'motivo_previo': motivo,
                'fecha_mov_previo': fecha_mov_str,
                'filas_previas_json': _json_safe(filas_previas),
            })

        with transaction.atomic():
            mov = MovimientoInventario.objects.create(
                tipo_movimiento='entrada',
                motivo=motivo,
                fecha_movimiento=fecha_movimiento,
                usuario=request.user,
            )
            for item, cantidad in filas_validas:
                det = DetalleMovimiento.objects.create(
                    movimiento=mov,
                    item=item,
                    cantidad=cantidad,
                    ubicacion_destino=ubicacion_destino,
                )
                _aplicar_efecto_detalle(det)
                _send_event_later('movement_created', {
                    'tipo': 'entrada', 'item': item.nombre, 'codigo': item.codigo,
                    'cantidad': str(cantidad), 'ubicacion': ubicacion_destino.nombre,
                    'usuario': request.user.username,
                })
                _notify_stock_later(item, movimiento='entrada', usuario=request.user.username)
        messages.success(
            request,
            f'Movimiento #{mov.pk} registrado con {len(filas_validas)} ítem(s).'
        )
        return redirect('movimiento_detalle', pk=mov.pk)

    return render(request, 'movimientos/entrada.html', {
        'items_json': items_json,
        'ubicaciones_json': ubicaciones_json,
        'item_id_inicial': item_id_inicial,
        'filas_previas_json': '[]',
    })


@login_required
@permission_required(_perm('registrar_salida'), raise_exception=True)
def movimiento_salida(request):
    """
    Registro de salidas con cuatro tabs:

    • Producto Terminado  — filas dinámicas (usuario agrega solo los necesarios),
                           dropdown filtrado a productos, orden por item.orden,
                           cliente a nivel de cabecera, permite stock negativo
                           (marca pendiente_conciliacion=True en cada línea).
                           Usa campos item_pt[] y cantidad_pt[] para evitar
                           colisión con los tabs de filas dinámicas (item[], cantidad[]).
    • Repuestos           — filas dinámicas, bloquea si stock insuficiente.
    • Consumibles         — filas dinámicas, bloquea si stock insuficiente.
    • Otros               — filas dinámicas, bloquea si stock insuficiente.
    """
    from django.utils.dateparse import parse_datetime

    # ── Datos maestros ────────────────────────────────────────────────────────
    items_producto   = list(Item.objects.filter(activo=True, tipo='producto')
                            .order_by('orden', 'nombre'))
    items_repuesto   = list(Item.objects.filter(activo=True, tipo='repuesto')
                            .order_by('orden', 'nombre'))
    items_consumible = list(Item.objects.filter(activo=True, tipo='consumible')
                            .order_by('orden', 'nombre'))
    items_otros      = list(Item.objects.filter(activo=True)
                            .exclude(tipo__in=['producto', 'repuesto', 'consumible'])
                            .order_by('orden', 'nombre'))

    ubicaciones = list(Ubicacion.objects.all().order_by('nombre'))
    clientes    = list(Cliente.objects.filter(activo=True).order_by('nombre'))
    maquinas    = list(Maquina.objects.filter(activo=True).order_by('nombre'))

    # ── Stock por item {item_pk: {ub_pk: stock_actual}} ───────────────────────
    stocks_qs = Stock.objects.select_related('item', 'ubicacion').all()
    stocks_por_item = {}
    for s in stocks_qs:
        stocks_por_item.setdefault(s.item_id, {})[s.ubicacion_id] = float(s.cantidad_actual)

    # ── JSON para JavaScript ──────────────────────────────────────────────────
    def _items_json(lst):
        return _json_safe([
            {'pk': it.pk, 'nombre': it.nombre, 'codigo': it.codigo,
             'tipo': it.tipo, 'unidad': it.unidad_medida}
            for it in lst
        ])

    ubicaciones_json = _json_safe([
        {'pk': u.pk, 'nombre': u.nombre, 'tipo': u.get_tipo_display()}
        for u in ubicaciones
    ])
    clientes_json = _json_safe([
        {'pk': c.pk, 'nombre': c.nombre} for c in clientes
    ])
    maquinas_json = _json_safe([
        {'pk': m.pk, 'nombre': m.nombre} for m in maquinas
    ])
    stocks_json = _json_safe(stocks_por_item)

    def _parse_fecha(fecha_str):
        if not fecha_str:
            return timezone.now()
        try:
            parsed = parse_datetime(fecha_str.strip())
            if parsed:
                return timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed
        except Exception:
            pass
        return timezone.now()

    # ── Contexto base (GET y re-render en error) ───────────────────────────────
    def _ctx(extra=None):
        ctx = {
            'items_producto_json':   _items_json(items_producto),
            'items_repuesto_json':   _items_json(items_repuesto),
            'items_consumible_json': _items_json(items_consumible),
            'items_otros_json':      _items_json(items_otros),
            'ubicaciones_json':      ubicaciones_json,
            'clientes_json':         clientes_json,
            'maquinas_json':         maquinas_json,
            'stocks_json':           stocks_json,
            'ubicaciones':           ubicaciones,
            'clientes':              clientes,
        }
        if extra:
            ctx.update(extra)
        return ctx

    if request.method != 'POST':
        tab_inicial = request.GET.get('tab', 'producto_terminado')
        item_id_inicial = request.GET.get('item', '')
        return render(request, 'movimientos/salida.html',
                      _ctx({'tab_inicial': tab_inicial,
                            'item_id_inicial': item_id_inicial,
                            'filas_pt_previas_json': '[]',
                            'filas_previas_json': '[]'}))

    # ═══════════════════════════════════════════════════════════════════════════
    # POST
    # ═══════════════════════════════════════════════════════════════════════════
    tipo_salida   = request.POST.get('tipo_salida', 'producto_terminado')
    motivo        = request.POST.get('motivo', '').strip()
    fecha_mov_str = request.POST.get('fecha_movimiento', '')
    fecha_movimiento = _parse_fecha(fecha_mov_str)

    errores      = []
    filas_validas = []   # (item, cantidad, ubicacion, pendiente, maquina)

    # ── TAB: Producto Terminado ────────────────────────────────────────────────
    if tipo_salida == 'producto_terminado':
        cliente_id  = request.POST.get('cliente_header', '').strip()
        ub_pt_id    = request.POST.get('ubicacion_origen_pt', '').strip()

        # Filas dinámicas PT usan nombres distintos (item_pt[], cantidad_pt[])
        # para evitar colisión con los tabs de rep/con/otros (item[], cantidad[])
        item_ids_pt  = request.POST.getlist('item_pt[]')
        cantidades_pt = request.POST.getlist('cantidad_pt[]')

        cliente = None
        if not cliente_id:
            errores.append('Selecciona un cliente.')
        else:
            try:
                cliente = Cliente.objects.get(pk=cliente_id)
            except Cliente.DoesNotExist:
                errores.append('Cliente no encontrado.')

        ubicacion_pt = None
        if not ub_pt_id:
            errores.append('Selecciona la ubicación de origen.')
        else:
            try:
                ubicacion_pt = Ubicacion.objects.get(pk=ub_pt_id)
            except Ubicacion.DoesNotExist:
                errores.append('Ubicación no encontrada.')

        items_producto_map = {str(it.pk): it for it in items_producto}
        for i, (item_id, cant_str) in enumerate(zip(item_ids_pt, cantidades_pt), 1):
            cant_str = cant_str.strip()
            if not item_id and not cant_str:
                continue
            if not item_id:
                errores.append(f'Fila {i}: selecciona un producto.')
                continue
            if not cant_str:
                errores.append(f'Fila {i}: ingresa una cantidad.')
                continue
            try:
                cantidad = _parse_cantidad_entera(cant_str)
            except ValueError as exc:
                if 'enteros' in str(exc):
                    errores.append('Las cantidades de inventario deben ser números enteros.')
                else:
                    errores.append(f'Fila {i}: cantidad inválida.')
                continue
            except (ValueError, Exception):
                errores.append(f'Fila {i}: cantidad inválida.')
                continue
            it = items_producto_map.get(str(item_id))
            if not it:
                errores.append(f'Fila {i}: producto no encontrado.')
                continue
            filas_validas.append((it, cantidad, None, True, None))

        if not filas_validas and not errores:
            errores.append('Agrega al menos un producto con cantidad.')

        if errores:
            for e in errores:
                messages.error(request, e)
            filas_pt_previas = [
                {'item_id': iid, 'cantidad': cant}
                for iid, cant in zip(item_ids_pt, cantidades_pt)
                if iid or cant.strip()
            ]
            return render(request, 'movimientos/salida.html',
                          _ctx({'tab_inicial': 'producto_terminado',
                                'motivo_previo': motivo,
                                'fecha_mov_previo': fecha_mov_str,
                                'cliente_previo': cliente_id,
                                'ub_pt_previo': ub_pt_id,
                                'filas_pt_previas_json': _json_safe(filas_pt_previas),
                                'filas_previas_json': '[]'}))

        # Todo OK → guardar
        with transaction.atomic():
            mov = MovimientoInventario.objects.create(
                tipo_movimiento='salida',
                tipo_salida='producto_terminado',
                motivo=motivo,
                fecha_movimiento=fecha_movimiento,
                usuario=request.user,
                cliente=cliente,
            )
            pendientes_creados = []
            for it, cantidad, _, _pendiente, _maq in filas_validas:
                # Calcular si habrá stock negativo
                stock_ub = Stock.objects.filter(item=it, ubicacion=ubicacion_pt).first()
                stock_actual = stock_ub.cantidad_actual if stock_ub else Decimal('0')
                pendiente = stock_actual < cantidad

                det = DetalleMovimiento.objects.create(
                    movimiento=mov,
                    item=it,
                    cantidad=cantidad,
                    ubicacion_origen=ubicacion_pt,
                    cliente=cliente,
                    pendiente_conciliacion=pendiente,
                )
                _aplicar_efecto_detalle(det)
                if pendiente:
                    pendientes_creados.append(det)
                _send_event_later('movement_created', {
                    'tipo': 'salida', 'item': it.nombre, 'codigo': it.codigo,
                    'cantidad': str(cantidad), 'ubicacion': ubicacion_pt.nombre,
                    'cliente': cliente.nombre if cliente else None,
                    'pendiente_conciliacion': pendiente,
                    'usuario': request.user.username,
                })
                _notify_stock_later(it, movimiento='salida', usuario=request.user.username)

            # Notificar pendientes
            for det in pendientes_creados:
                _send_event_later('salida_pendiente_conciliacion', {
                    'movimiento_pk': mov.pk,
                    'item': det.item.nombre, 'codigo': det.item.codigo,
                    'cantidad': str(det.cantidad),
                    'ubicacion': ubicacion_pt.nombre,
                    'cliente': cliente.nombre,
                    'usuario': request.user.username,
                })

        n_pendientes = len(pendientes_creados)
        msg = f'Movimiento #{mov.pk} registrado con {len(filas_validas)} ítem(s).'
        if n_pendientes:
            msg += f' ⚠️ {n_pendientes} línea(s) con stock insuficiente marcada(s) como pendiente(s) de conciliación.'
        messages.success(request, msg)
        return redirect('movimiento_detalle', pk=mov.pk)

    # ── TABS: Repuestos / Consumibles / Otros (filas dinámicas) ───────────────
    item_ids      = request.POST.getlist('item[]')
    cantidades    = request.POST.getlist('cantidad[]')
    ubicacion_ids = request.POST.getlist('ubicacion_origen[]')
    maquina_ids   = request.POST.getlist('maquina[]')

    all_items_qs = {str(it.pk): it for it in
                    Item.objects.filter(activo=True)
                    .exclude(tipo='producto')}

    for i, (item_id, cant_str, ub_id, maq_id) in enumerate(
        zip(item_ids, cantidades, ubicacion_ids, maquina_ids), 1
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
            cantidad = _parse_cantidad_entera(cant_str)
        except ValueError as exc:
            if 'enteros' in str(exc):
                errores.append('Las cantidades de inventario deben ser números enteros.')
            else:
                errores.append(f'Fila {i}: cantidad inválida.')
            continue
        except (ValueError, Exception):
            errores.append(f'Fila {i}: cantidad inválida.')
            continue

        item = all_items_qs.get(str(item_id))
        if not item:
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

        # Bloquear si stock insuficiente (repuestos/consumibles/otros)
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

        maquina = None
        if maq_id:
            try:
                maquina = Maquina.objects.get(pk=maq_id)
            except Maquina.DoesNotExist:
                pass

        # Repuesto requiere máquina
        if item.tipo == 'repuesto' and not maquina:
            errores.append(f'Fila {i} ({item.nombre}): selecciona una máquina.')
            continue

        filas_validas.append((item, cantidad, ubicacion, False, maquina))

    if not filas_validas and not errores:
        errores.append('Agrega al menos un ítem con cantidad.')

    if errores:
        for e in errores:
            messages.error(request, e)
        filas_previas = [
            {'item_id': iid, 'cantidad': cant, 'ub_id': ub, 'maq_id': maq}
            for iid, cant, ub, maq
            in zip(item_ids, cantidades, ubicacion_ids, maquina_ids)
            if iid or cant.strip()
        ]
        return render(request, 'movimientos/salida.html',
                      _ctx({'tab_inicial': tipo_salida,
                            'motivo_previo': motivo,
                            'fecha_mov_previo': fecha_mov_str,
                            'filas_previas_json': _json_safe(filas_previas)}))

    with transaction.atomic():
        mov = MovimientoInventario.objects.create(
            tipo_movimiento='salida',
            tipo_salida=tipo_salida,
            motivo=motivo,
            fecha_movimiento=fecha_movimiento,
            usuario=request.user,
        )
        for it, cantidad, ubicacion, _pendiente, maquina in filas_validas:
            det = DetalleMovimiento.objects.create(
                movimiento=mov,
                item=it,
                cantidad=cantidad,
                ubicacion_origen=ubicacion,
                maquina=maquina,
            )
            _aplicar_efecto_detalle(det)
            _send_event_later('movement_created', {
                'tipo': 'salida', 'item': it.nombre, 'codigo': it.codigo,
                'cantidad': str(cantidad), 'ubicacion': ubicacion.nombre,
                'usuario': request.user.username,
            })
            _notify_stock_later(it, movimiento='salida', usuario=request.user.username)

    messages.success(
        request,
        f'Movimiento #{mov.pk} registrado con {len(filas_validas)} ítem(s).'
    )
    return redirect('movimiento_detalle', pk=mov.pk)


@login_required
@permission_required(_perm('registrar_entrada'), raise_exception=True)
def movimiento_transferencia(request):
    if request.method == 'POST':
        form = MovimientoTransferenciaForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                mov = MovimientoInventario.objects.create(
                    tipo_movimiento='transferencia',
                    motivo=form.cleaned_data.get('motivo', ''),
                    usuario=request.user,
                )
                det = DetalleMovimiento.objects.create(
                    movimiento=mov,
                    item=form.cleaned_data['item'],
                    cantidad=form.cleaned_data['cantidad'],
                    ubicacion_origen=form.cleaned_data['ubicacion_origen'],
                    ubicacion_destino=form.cleaned_data['ubicacion_destino'],
                )
                _aplicar_efecto_detalle(det)
            messages.success(request, f'Transferencia registrada (Movimiento #{mov.pk}).')
            return redirect('movimiento_detalle', pk=mov.pk)
    else:
        form = MovimientoTransferenciaForm()

    return render(request, 'movimientos/transferencia.html', {'form': form})


# ─── DETALLE / GESTIÓN DE MOVIMIENTOS ────────────────────────────────────────

@login_required
@permission_required(_perm('ver_inventario'), raise_exception=True)
def movimiento_detalle(request, pk):
    """Vista de detalle de un Movimiento (cabecera + líneas)."""
    mov = get_object_or_404(
        MovimientoInventario.objects.select_related(
            'usuario', 'usuario_edicion', 'usuario_anulacion', 'usuario_eliminacion'
        ).prefetch_related(
            'detalles__item', 'detalles__ubicacion_origen',
            'detalles__ubicacion_destino', 'detalles__cliente', 'detalles__maquina',
        ),
        pk=pk,
    )
    return render(request, 'movimientos/detalle.html', {'mov': mov})


@login_required
@permission_required(_perm('editar_movimiento'), raise_exception=True)
def movimiento_editar(request, pk):
    """
    Edita un movimiento existente.
    Permite cambiar la fecha, motivo y las cantidades/ubicaciones por línea.
    Flujo: revertir todos los detalles → guardar cambios → re-aplicar detalles.
    Todo en transaction.atomic().
    """
    mov = get_object_or_404(
        MovimientoInventario.objects.prefetch_related(
            'detalles__item', 'detalles__ubicacion_origen',
            'detalles__ubicacion_destino', 'detalles__cliente', 'detalles__maquina',
        ).select_related('usuario'),
        pk=pk,
    )

    if not _movimiento_editable(mov):
        messages.error(request, 'Este movimiento está anulado o eliminado y no puede editarse.')
        return redirect('movimiento_detalle', pk=pk)

    ubicaciones = Ubicacion.objects.all()
    clientes    = Cliente.objects.filter(activo=True).order_by('nombre')
    maquinas    = Maquina.objects.filter(activo=True).order_by('nombre')

    if request.method == 'POST':
        motivo_edicion = request.POST.get('motivo_edicion', '').strip()
        nuevo_motivo   = request.POST.get('motivo', mov.motivo)
        nueva_fecha_str = request.POST.get('fecha_movimiento', '').strip()

        if not motivo_edicion:
            messages.error(request, 'El motivo de edición es obligatorio.')
        else:
            nueva_fecha = mov.fecha_movimiento
            if nueva_fecha_str:
                from django.utils.dateparse import parse_datetime
                parsed = parse_datetime(nueva_fecha_str)
                if parsed:
                    nueva_fecha = timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed

            # Recoger nuevas cantidades por detalle
            det_cantidades   = request.POST.getlist('det_cantidad[]')
            det_ids          = request.POST.getlist('det_id[]')
            det_ub_origen    = request.POST.getlist('det_ub_origen[]')
            det_ub_destino   = request.POST.getlist('det_ub_destino[]')

            errores = []
            nuevos_valores = []
            detalles = list(mov.detalles.all())

            # Emparejar cada detalle con su fila del POST por det_id (no por
            # posición): el índice posicional es frágil si el formulario reordena
            # filas y podría aplicar cantidades a la línea equivocada.
            pos_por_id = {str(did): i for i, did in enumerate(det_ids)}

            for i, det in enumerate(detalles):
                idx = pos_por_id.get(str(det.pk))
                if idx is None:
                    errores.append(f'Línea {i+1} ({det.item.nombre}): datos del formulario incompletos.')
                    continue

                cant_str = det_cantidades[idx].strip() if idx < len(det_cantidades) else ''
                try:
                    nueva_cant = _parse_cantidad_entera(cant_str)
                except ValueError as exc:
                    if 'enteros' in str(exc):
                        errores.append('Las cantidades de inventario deben ser números enteros.')
                    else:
                        errores.append(f'Línea {i+1} ({det.item.nombre}): cantidad inválida.')
                    continue
                except Exception:
                    errores.append(f'Línea {i+1} ({det.item.nombre}): cantidad inválida.')
                    continue

                ub_or_id  = det_ub_origen[idx]  if idx < len(det_ub_origen)  else ''
                ub_dst_id = det_ub_destino[idx] if idx < len(det_ub_destino) else ''
                nueva_ub_origen  = Ubicacion.objects.filter(pk=ub_or_id).first()  if ub_or_id  else None
                nueva_ub_destino = Ubicacion.objects.filter(pk=ub_dst_id).first() if ub_dst_id else None
                nuevos_valores.append((det, nueva_cant, nueva_ub_origen, nueva_ub_destino))

            if errores:
                for e in errores:
                    messages.error(request, e)
            else:
                with transaction.atomic():
                    # 1. Revertir todos los detalles originales
                    _revertir_todos_los_detalles(mov)
                    # 2. Actualizar cabecera
                    mov.motivo           = nuevo_motivo
                    mov.fecha_movimiento = nueva_fecha
                    mov.editado          = True
                    mov.fecha_edicion    = timezone.now()
                    mov.usuario_edicion  = request.user
                    mov.motivo_edicion   = motivo_edicion
                    mov.save(update_fields=[
                        'motivo', 'fecha_movimiento',
                        'editado', 'fecha_edicion', 'usuario_edicion', 'motivo_edicion',
                    ])
                    # 3. Actualizar detalles y re-aplicar stock
                    for det, nueva_cant, nueva_ub_origen, nueva_ub_destino in nuevos_valores:
                        det.cantidad          = nueva_cant
                        det.ubicacion_origen  = nueva_ub_origen
                        det.ubicacion_destino = nueva_ub_destino
                        det.save(update_fields=['cantidad', 'ubicacion_origen', 'ubicacion_destino'])
                        _aplicar_efecto_detalle(det)
                        _notify_stock_later(det.item, movimiento='edicion', usuario=request.user.username)

                security_log.info(
                    'Movimiento #%s editado por %s — %s',
                    mov.pk, request.user.username, motivo_edicion,
                )
                messages.success(request, f'Movimiento #{mov.pk} editado correctamente.')
                return redirect('movimiento_detalle', pk=mov.pk)

    return render(request, 'movimientos/editar.html', {
        'mov': mov,
        'ubicaciones': ubicaciones,
        'clientes': clientes,
        'maquinas': maquinas,
    })


@login_required
@permission_required(_perm('anular_movimiento'), raise_exception=True)
def movimiento_anular(request, pk):
    """
    Anula un movimiento completo: revierte el stock de TODOS sus detalles y
    marca la cabecera como anulada. No lo borra — queda visible con badge «Anulado».
    """
    mov = get_object_or_404(
        MovimientoInventario.objects.prefetch_related(
            'detalles__item', 'detalles__ubicacion_origen', 'detalles__ubicacion_destino'
        ).select_related('usuario'),
        pk=pk,
    )

    if mov.anulado:
        messages.warning(request, 'Este movimiento ya estaba anulado.')
        return redirect('movimiento_detalle', pk=pk)
    if mov.eliminado:
        messages.error(request, 'No se puede anular un movimiento eliminado.')
        return redirect('movimiento_detalle', pk=pk)

    if request.method == 'POST':
        motivo = request.POST.get('motivo_anulacion', '').strip()
        if not motivo:
            messages.error(request, 'El motivo de anulación es obligatorio.')
        else:
            with transaction.atomic():
                _revertir_todos_los_detalles(mov)
                mov.anulado           = True
                mov.fecha_anulacion   = timezone.now()
                mov.usuario_anulacion = request.user
                mov.motivo_anulacion  = motivo
                mov.save(update_fields=[
                    'anulado', 'fecha_anulacion', 'usuario_anulacion', 'motivo_anulacion'
                ])
                for det in mov.detalles.select_related('item').all():
                    _notify_stock_later(det.item, movimiento='anulacion', usuario=request.user.username)

            security_log.info(
                'Movimiento #%s ANULADO por %s — %s',
                mov.pk, request.user.username, motivo,
            )
            messages.success(
                request,
                f'Movimiento #{mov.pk} anulado. Stock revertido en {mov.detalles.count()} ítem(s).'
            )
            return redirect('movimiento_lista')

    return render(request, 'movimientos/anular.html', {'mov': mov})


@login_required
@permission_required(_perm('eliminar_movimiento'), raise_exception=True)
def movimiento_eliminar(request, pk):
    """
    Eliminación lógica de un movimiento.
    Si no estaba anulado, revierte el stock de todos sus detalles.
    Requiere doble confirmación y motivo.
    """
    mov = get_object_or_404(
        MovimientoInventario.objects.prefetch_related(
            'detalles__item', 'detalles__ubicacion_origen', 'detalles__ubicacion_destino'
        ).select_related('usuario'),
        pk=pk,
    )

    if mov.eliminado:
        messages.warning(request, 'Este movimiento ya estaba eliminado.')
        return redirect('movimiento_lista')

    if mov.anulado and not request.user.is_superuser:
        messages.error(request, 'Solo un superusuario puede eliminar un movimiento ya anulado.')
        return redirect('movimiento_detalle', pk=pk)

    if request.method == 'POST':
        confirmacion = request.POST.get('confirmacion', '').strip()
        motivo = request.POST.get('motivo_eliminacion', '').strip()

        if confirmacion != 'ELIMINAR':
            messages.error(request, 'Escribe ELIMINAR en el campo de confirmación.')
        elif not motivo:
            messages.error(request, 'El motivo de eliminación es obligatorio.')
        else:
            with transaction.atomic():
                # Solo revertir si no estaba ya anulado (el anulado ya lo revirtió)
                if not mov.anulado:
                    _revertir_todos_los_detalles(mov)
                mov.eliminado           = True
                mov.fecha_eliminacion   = timezone.now()
                mov.usuario_eliminacion = request.user
                mov.motivo_eliminacion  = motivo
                mov.save(update_fields=[
                    'eliminado', 'fecha_eliminacion', 'usuario_eliminacion', 'motivo_eliminacion'
                ])
                if not mov.anulado:
                    for det in mov.detalles.select_related('item').all():
                        _notify_stock_later(det.item, movimiento='eliminacion',
                                            usuario=request.user.username)

            security_log.warning(
                'Movimiento #%s ELIMINADO por %s — %s',
                mov.pk, request.user.username, motivo,
            )
            messages.success(request, f'Movimiento #{mov.pk} eliminado lógicamente.')
            return redirect('movimiento_lista')

    return render(request, 'movimientos/eliminar.html', {'mov': mov})
