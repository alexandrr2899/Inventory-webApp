"""
conteos.py — Vistas de conteos físicos y conciliación.

Crear conteo, conciliar (stock teórico por fecha_movimiento), aplicar ajustes,
cerrar conciliación, anular. Tras una conciliación de Camiseta dispara el
reenvío automático del inventario a n8n (helpers en payloads.py).
"""

from .common import *    # noqa: F401,F403
from .stock import *     # noqa: F401,F403
from .calc import *      # noqa: F401,F403
from .payloads import *  # noqa: F401,F403


# ─── CONTEOS ──────────────────────────────────────────────────────────────────

@login_required
def conteo_anular(request, pk):
    """
    Anulación lógica de un conteo: revierte en stock todos los ajustes de
    conciliación generados por este conteo, marca cada movimiento de ajuste
    como anulado, y finalmente marca el conteo como anulado.
    No elimina ningún registro.
    """
    if not (request.user.has_perm(_perm('anular_conteo')) or request.user.is_superuser):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied

    conteo = get_object_or_404(
        Conteo.objects.select_related('usuario'),
        pk=pk,
    )

    if conteo.anulado:
        messages.warning(request, 'Este conteo ya estaba anulado.')
        return redirect('conteo_detalle', pk=pk)

    # Movimientos de ajuste vinculados a este conteo (por motivo)
    ajustes_qs = (
        MovimientoInventario.objects
        .filter(
            tipo_movimiento='ajuste',
            motivo__contains=f'Conteo #{conteo.pk}',
            anulado=False,
            eliminado=False,
        )
        .prefetch_related(
            'detalles__item',
            'detalles__ubicacion_origen',
            'detalles__ubicacion_destino',
        )
    )
    ajustes = list(ajustes_qs)

    if request.method == 'POST':
        motivo = request.POST.get('motivo_anulacion', '').strip()
        if not motivo:
            messages.error(request, 'El motivo de anulación es obligatorio.')
        else:
            ahora = timezone.now()
            with transaction.atomic():
                for mov_ajuste in ajustes:
                    _revertir_todos_los_detalles(mov_ajuste)
                    mov_ajuste.anulado           = True
                    mov_ajuste.fecha_anulacion   = ahora
                    mov_ajuste.usuario_anulacion = request.user
                    mov_ajuste.motivo_anulacion  = f'Anulación de Conteo #{conteo.pk} — {motivo}'
                    mov_ajuste.save(update_fields=[
                        'anulado', 'fecha_anulacion', 'usuario_anulacion', 'motivo_anulacion',
                    ])
                    for det in mov_ajuste.detalles.select_related('item').all():
                        notify_stock(det.item, movimiento='anulacion', usuario=request.user.username)

                conteo.anulado           = True
                conteo.fecha_anulacion   = ahora
                conteo.usuario_anulacion = request.user
                conteo.motivo_anulacion  = motivo
                conteo.save(update_fields=[
                    'anulado', 'fecha_anulacion', 'usuario_anulacion', 'motivo_anulacion',
                ])

            security_log.info(
                'Conteo #%s ANULADO por %s — %s ajuste(s) revertido(s) — %s',
                conteo.pk, request.user.username, len(ajustes), motivo,
            )
            messages.success(
                request,
                f'Conteo #{conteo.pk} anulado. {len(ajustes)} ajuste(s) de conciliación revertido(s).'
            )
            return redirect('conteo_lista')

    return render(request, 'conteos/anular.html', {
        'conteo': conteo,
        'ajustes': ajustes,
    })


@login_required
@permission_required(_perm('registrar_conteo'), raise_exception=True)
@_timed_view('conteo_lista')
def conteo_lista(request):
    qs = (
        Conteo.objects
        .select_related('usuario')
        .annotate(num_detalles=Count('detalles'))
        .order_by('-fecha', 'turno')
    )
    paginator = Paginator(qs, 30)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'conteos/lista.html', {'conteos': page_obj, 'page_obj': page_obj})


@login_required
@permission_required(_perm('registrar_conteo'), raise_exception=True)
def conteo_nuevo(request):
    hoy = date.today()
    ubicaciones = list(Ubicacion.objects.all())

    stocks_map = {}
    for s in Stock.objects.select_related('item', 'ubicacion').filter(item__activo=True):
        stocks_map[(s.item_id, s.ubicacion_id)] = s.cantidad_actual

    stocks_totales = {}
    for s in Stock.objects.filter(item__activo=True).values('item_id').annotate(t=Sum('cantidad_actual')):
        stocks_totales[s['item_id']] = s['t'] or Decimal('0')

    all_items = list(
        Item.objects.filter(activo=True)
        .select_related('categoria')
        .order_by('orden', 'nombre')
    )

    def _clasificar(item):
        cat = (item.categoria.nombre if item.categoria else '').lower()
        nom = item.nombre.lower()
        if item.tipo == 'producto' and ('camiseta' in cat or 'camiseta' in nom):
            return 'camiseta'
        if item.tipo == 'consumible' and ('pigment' in cat or 'pigment' in nom):
            return 'pigmentos'
        if item.tipo == 'producto' and ('lisa' in cat or 'lisa' in nom):
            return 'lisa'
        return 'otros'

    def _build_item_dict(item):
        stocks_by_ub = {
            str(upk): str(qty)
            for (ipk, upk), qty in stocks_map.items()
            if ipk == item.pk
        }
        best_ub = max(stocks_by_ub, key=lambda k: Decimal(stocks_by_ub[k]), default=None)
        return {
            'pk': item.pk,
            'nombre': item.nombre,
            'codigo': item.codigo,
            'categoria': item.categoria.nombre if item.categoria else '',
            'unidad': item.unidad_medida,
            'stock_total': str(stocks_totales.get(item.pk, Decimal('0'))),
            'default_ub': int(best_ub) if best_ub else (ubicaciones[0].pk if ubicaciones else None),
            'stocks_by_ub': stocks_by_ub,
        }

    items_por_tipo = {'camiseta': [], 'pigmentos': [], 'lisa': [], 'otros': []}
    for item in all_items:
        items_por_tipo[_clasificar(item)].append(_build_item_dict(item))

    items_por_tipo_json = _json_safe(items_por_tipo)
    all_items_json = _json_safe([_build_item_dict(item) for item in all_items])
    ubicaciones_json = _json_safe([
        {'pk': u.pk, 'nombre': u.nombre, 'tipo': u.get_tipo_display()}
        for u in ubicaciones
    ])

    if request.method == 'POST':
        form = ConteoForm(request.POST)

        item_ids = request.POST.getlist('item[]')
        ubicacion_ids = request.POST.getlist('ubicacion[]')
        cantidades = request.POST.getlist('cantidad_contada[]')

        # Lista ordenada: [{item_id, ub_id, cant}] para todos los ítems con cantidad
        filas_previas = [
            {'item_id': iid, 'ub_id': uid, 'cant': cant}
            for iid, uid, cant in zip(item_ids, ubicacion_ids, cantidades)
            if cant.strip()
        ]
        filas_previas_json = _json_safe(filas_previas)
        tipo_conteo_previo = request.POST.get('tipo_conteo', 'camiseta')

        def _render_error(f):
            return render(request, 'conteos/form.html', {
                'form': f,
                'items_por_tipo_json': items_por_tipo_json,
                'all_items_json': all_items_json,
                'ubicaciones_json': ubicaciones_json,
                'hoy': hoy,
                'filas_previas_json': filas_previas_json,
                'tipo_conteo_inicial': tipo_conteo_previo,
                'tipos_conteo_fijos': ['camiseta', 'pigmentos', 'lisa'],
            })

        if not form.is_valid():
            return _render_error(form)

        fecha = form.cleaned_data['fecha']
        turno = form.cleaned_data['turno']
        tipo_conteo = form.cleaned_data['tipo_conteo']

        if Conteo.objects.filter(fecha=fecha, turno=turno, tipo_conteo=tipo_conteo, anulado=False).exists():
            label_tipo = dict(Conteo.TIPO_CONTEO_CHOICES).get(tipo_conteo, tipo_conteo)
            label_turno = dict(Conteo.TURNO_CHOICES).get(turno, turno)
            messages.error(
                request,
                f'Ya existe un conteo de {label_tipo} - {label_turno} para {fecha}.'
            )
            return _render_error(form)

        errores = []
        filas = []

        for i, (item_id, ub_id, cant_str) in enumerate(
            zip(item_ids, ubicacion_ids, cantidades), 1
        ):
            cant_str = cant_str.strip()
            if not cant_str:
                continue
            if not item_id:
                errores.append(f'Fila {i}: ítem inválido.')
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
            return _render_error(form)

        if not filas:
            messages.error(request, 'Ingresá al menos una cantidad en el conteo.')
            return _render_error(form)

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

        label_tipo = dict(Conteo.TIPO_CONTEO_CHOICES).get(conteo.tipo_conteo, conteo.tipo_conteo)
        messages.success(
            request,
            f'Conteo {label_tipo} - {conteo.get_turno_display()} registrado con {len(filas)} ítem(s). '
            f'Revisá la conciliación para calcular diferencias.'
        )
        return redirect('conteo_conciliar', pk=conteo.pk)

    form = ConteoForm(initial={
        'fecha': hoy,
        'tipo_conteo': 'camiseta',
        'fecha_hora_conteo': timezone.localtime(timezone.now()).strftime('%Y-%m-%dT%H:%M'),
    })
    return render(request, 'conteos/form.html', {
        'form': form,
        'items_por_tipo_json': items_por_tipo_json,
        'all_items_json': all_items_json,
        'ubicaciones_json': ubicaciones_json,
        'hoy': hoy,
        'filas_previas_json': '[]',
        'tipo_conteo_inicial': 'camiseta',
        'tipos_conteo_fijos': ['camiseta', 'pigmentos', 'lisa'],
    })


@login_required
@permission_required(_perm('registrar_conteo'), raise_exception=True)
def conteo_detalle(request, pk):
    conteo = get_object_or_404(Conteo, pk=pk)
    detalles = conteo.detalles.select_related('item', 'ubicacion').order_by('item__orden', 'item__nombre')
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
    if conteo.anulado:
        messages.error(request, 'Este conteo está anulado y no puede conciliarse.')
        return redirect('conteo_detalle', pk=pk)
    detalles = conteo.detalles.select_related('item', 'ubicacion').order_by('item__orden', 'item__nombre')

    plan = []
    with transaction.atomic():
        for detalle in detalles:
            # Stock teórico al momento del conteo usando fecha_movimiento como
            # timestamp oficial. No depende de cuándo se registró el movimiento.
            stock_teorico = _stock_en_momento(
                detalle.item, detalle.ubicacion, conteo.fecha_hora_conteo
            )
            diferencia_final = detalle.cantidad_contada - stock_teorico

            # Persistir diferencia_final si cambió
            if detalle.diferencia_final != diferencia_final:
                detalle.diferencia_final = diferencia_final
                ConteoDetalle.objects.filter(pk=detalle.pk).update(
                    diferencia_final=diferencia_final
                )

            # Movimientos registrados DESPUÉS del conteo pero con fecha_movimiento
            # ANTES del conteo. Se muestran para transparencia: ya están
            # correctamente incluidos en stock_teorico (no son "atrasados" — son
            # movimientos reales anteriores al conteo, solo ingresados tarde).
            movs_tardios = (
                DetalleMovimiento.objects
                .filter(
                    item=detalle.item,
                    movimiento__anulado=False,
                    movimiento__eliminado=False,
                    movimiento__fecha__gt=conteo.fecha_hora_conteo,
                    movimiento__fecha_movimiento__lte=conteo.fecha_hora_conteo,
                )
                .filter(
                    Q(ubicacion_destino=detalle.ubicacion)
                    | Q(ubicacion_origen=detalle.ubicacion)
                )
                .select_related(
                    'movimiento', 'movimiento__usuario',
                    'ubicacion_origen', 'ubicacion_destino',
                )
                .order_by('movimiento__fecha_movimiento')
            )

            plan.append({
                'detalle': detalle,
                'stock_teorico': stock_teorico,
                'diferencia_final': diferencia_final,
                'movs_tardios': movs_tardios,   # solo informativos
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
    if conteo.anulado:
        messages.error(request, 'Este conteo está anulado.')
        return redirect('conteo_detalle', pk=pk)
    estado_antes = conteo.estado
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
        mov_ajuste = MovimientoInventario.objects.create(
            tipo_movimiento='ajuste',
            motivo=f'Ajuste por conciliación — Conteo #{conteo.pk} ({conteo.get_turno_display()} {conteo.fecha})',
            usuario=request.user,
        )
        det_ajuste = DetalleMovimiento.objects.create(
            movimiento=mov_ajuste,
            item=detalle.item,
            cantidad=detalle.diferencia_final,
            ubicacion_destino=detalle.ubicacion,
        )
        _aplicar_efecto_detalle(det_ajuste)
        _cerrar_pendientes_conciliacion(detalle.item, detalle.ubicacion)
        ConteoDetalle.objects.filter(pk=detalle.pk).update(ajuste_aplicado=True)
        conteo.refresh_from_db()
        conteo.actualizar_estado()
        # Si este ajuste cerró la conciliación, reenviar inventario camiseta (1 vez)
        _notificar_si_conciliacion_completa(conteo, estado_antes, request.user.username)

    send_event('count_difference', {
        'conteo_id': conteo.pk, 'item': detalle.item.nombre, 'codigo': detalle.item.codigo,
        'diferencia': str(detalle.diferencia_final), 'ubicacion': detalle.ubicacion.nombre,
        'usuario': request.user.username,
    })
    notify_stock(detalle.item, movimiento='ajuste', usuario=request.user.username)
    messages.success(request, f'Ajuste aplicado: {detalle.item.nombre} ({detalle.diferencia_final:+g} {detalle.item.unidad_medida}).')
    return redirect('conteo_conciliar', pk=pk)


@login_required
@permission_required(_perm('aplicar_conciliacion'), raise_exception=True)
def conteo_ajustar_todos(request, pk):
    if request.method != 'POST':
        return redirect('conteo_conciliar', pk=pk)

    conteo = get_object_or_404(Conteo, pk=pk)
    if conteo.anulado:
        messages.error(request, 'Este conteo está anulado.')
        return redirect('conteo_detalle', pk=pk)
    estado_antes = conteo.estado
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
            mov_ajuste = MovimientoInventario.objects.create(
                tipo_movimiento='ajuste',
                motivo=f'Ajuste por conciliación — Conteo #{conteo.pk} ({conteo.get_turno_display()} {conteo.fecha})',
                usuario=request.user,
            )
            det_ajuste = DetalleMovimiento.objects.create(
                movimiento=mov_ajuste,
                item=detalle.item,
                cantidad=detalle.diferencia_final,
                ubicacion_destino=detalle.ubicacion,
            )
            _aplicar_efecto_detalle(det_ajuste)
            _cerrar_pendientes_conciliacion(detalle.item, detalle.ubicacion)
            count += 1
        ConteoDetalle.objects.filter(
            conteo=conteo, ajuste_aplicado=False,
            diferencia_final__isnull=False
        ).exclude(diferencia_final=0).update(ajuste_aplicado=True)
        conteo.refresh_from_db()
        conteo.actualizar_estado()
        # Si quedó conciliado, reenviar inventario camiseta (1 vez)
        _notificar_si_conciliacion_completa(conteo, estado_antes, request.user.username)

    send_event('count_difference', {
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
    if conteo.anulado:
        messages.error(request, 'Este conteo está anulado.')
        return redirect('conteo_detalle', pk=pk)
    estado_antes = conteo.estado

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

    with transaction.atomic():
        conteo.estado = 'conciliado'
        conteo.save(update_fields=['estado'])
        # Reenviar inventario camiseta (1 vez) si recién ahora quedó conciliado
        _notificar_si_conciliacion_completa(conteo, estado_antes, request.user.username)

    messages.success(request, 'Conteo marcado como conciliado.')
    return redirect('conteo_detalle', pk=pk)


