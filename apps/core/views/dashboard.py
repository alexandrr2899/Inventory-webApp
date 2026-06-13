"""dashboard.py — Dashboard principal y centro de alertas operativas."""
from .common import *    # noqa: F401,F403
from .stock import *     # noqa: F401,F403
from .calc import *      # noqa: F401,F403
from .payloads import *  # noqa: F401,F403


# ─── DASHBOARD ────────────────────────────────────────────────────────────────

@login_required
@_timed_view('dashboard')
def dashboard(request):
    hoy = timezone.localdate()
    cache_key = f'dashboard:data:{hoy.isoformat()}'
    salidas_del_dia = _calcular_salidas_camiseta_del_dia(hoy)
    produccion_hoy = _calcular_produccion(hoy, salidas_parciales_hasta=timezone.now())
    produccion_hoy['salidas_del_dia'] = salidas_del_dia['total']
    cached = cache.get(cache_key)
    if cached:
        cached = cached.copy()
        cached['hoy'] = hoy
        cached['salidas_del_dia'] = salidas_del_dia
        cached['produccion_hoy'] = produccion_hoy
        return render(request, 'dashboard.html', cached)

    # Single query: annotate stock total, filter bajo_stock in DB (no N+1)
    items_bajo_stock = list(
        Item.objects
        .filter(activo=True)
        .annotate(stock_calc=_STOCK_ANN)
        .filter(stock_calc__lte=F('stock_minimo'))
        .select_related('categoria')
        .order_by('orden', 'nombre')[:20]
    )

    ultimos_detalles = (
        DetalleMovimiento.objects
        .filter(movimiento__eliminado=False)
        .select_related(
            'item', 'cliente', 'maquina',
            'movimiento', 'movimiento__usuario', 'movimiento__cliente',
        )
        .order_by('-movimiento__fecha')[:10]
    )

    hace_30 = timezone.now() - timedelta(days=30)
    repuestos_top = (
        DetalleMovimiento.objects
        .filter(
            movimiento__tipo_movimiento='salida',
            movimiento__anulado=False,
            movimiento__eliminado=False,
            movimiento__fecha_movimiento__gte=hace_30,
            item__tipo='repuesto',
        )
        .values('item__nombre', 'item__unidad_medida')
        .annotate(total=Sum('cantidad'))
        .order_by('-total')[:5]
    )

    total_bajo_stock = (
        Item.objects
        .filter(activo=True)
        .annotate(stock_calc=_STOCK_ANN)
        .filter(stock_calc__lte=F('stock_minimo'))
        .count()
    )

    total_pendientes_conciliacion = (
        DetalleMovimiento.objects
        .filter(
            pendiente_conciliacion=True,
            movimiento__anulado=False,
            movimiento__eliminado=False,
        )
        .count()
    )

    context = {
        'items_bajo_stock': items_bajo_stock,
        'ultimos_detalles': ultimos_detalles,
        'produccion_hoy': produccion_hoy,
        'salidas_del_dia': salidas_del_dia,
        'repuestos_top': repuestos_top,
        'hoy': hoy,
        'total_bajo_stock': total_bajo_stock,
        'total_pendientes_conciliacion': total_pendientes_conciliacion,
        'total_alertas': total_bajo_stock + total_pendientes_conciliacion,
    }
    cache.set(cache_key, context, 45)
    return render(request, 'dashboard.html', context)


# ─── ALERTAS OPERATIVAS ──────────────────────────────────────────────────────

@login_required
@permission_required(_perm('ver_inventario'), raise_exception=True)
@_timed_view('alertas_centro')
def alertas_centro(request):
    cache_key = 'alertas:centro:v1'
    cached = cache.get(cache_key)
    if cached:
        return render(request, 'alertas/centro.html', cached)

    now = timezone.now()
    alertas = []

    items_bajo = list(
        Item.objects
        .filter(activo=True)
        .select_related('categoria')
        .annotate(stock_calc=_STOCK_ANN)
        .filter(stock_calc__lte=F('stock_minimo'))
        .order_by('stock_calc', 'orden', 'nombre')[:60]
    )
    for item in items_bajo:
        stock = item.stock_calc or Decimal('0')
        severidad = 'critica' if stock <= 0 else 'alta'
        alertas.append({
            'tipo': 'Stock',
            'severidad': severidad,
            'icono': 'bi-exclamation-octagon-fill' if severidad == 'critica' else 'bi-exclamation-triangle-fill',
            'titulo': f'{item.nombre} sin stock' if stock <= 0 else f'{item.nombre} bajo mínimo',
            'detalle': f'{stock} {item.unidad_medida} disponible · mínimo {item.stock_minimo}',
            'fecha': now,
            'referencia': item.codigo,
            'url': reverse('item_detalle', args=[item.pk]),
            'accion': 'Revisar ítem',
        })

    pigmentos_criticos = [
        item for item in items_bajo
        if item.tipo == 'consumible'
        and item.categoria
        and item.categoria.nombre.lower().strip() == 'pigmentos'
    ]
    fecha_inicio_pig = (now.date() - timedelta(days=30))
    pigmentos_qs = list(
        Item.objects
        .filter(activo=True, tipo='consumible', categoria__nombre__iexact='Pigmentos')
        .select_related('categoria')
        .annotate(stock_calc=_STOCK_ANN)
        .order_by('orden', 'nombre')[:40]
    )
    consumo_pigmentos = {
        row['item_id']: abs(row['total'])
        for row in (
            DetalleMovimiento.objects
            .filter(
                movimiento__tipo_movimiento='ajuste',
                movimiento__anulado=False,
                movimiento__eliminado=False,
                movimiento__fecha_movimiento__date__gte=fecha_inicio_pig,
                movimiento__fecha_movimiento__date__lte=now.date(),
                item__tipo='consumible',
                item__categoria__nombre__iexact='Pigmentos',
                cantidad__lt=0,
            )
            .values('item_id')
            .annotate(total=Sum('cantidad'))
        )
    }
    pigmentos_panel = []
    for pig in pigmentos_qs:
        consumo_30 = consumo_pigmentos.get(pig.pk, Decimal('0'))
        stock = pig.stock_calc or Decimal('0')
        promedio = consumo_30 / Decimal('30') if consumo_30 > 0 else Decimal('0')
        dias_cobertura = (stock / promedio) if promedio > 0 else None
        pedido = max(Decimal('0'), promedio * Decimal('14') - stock) if promedio > 0 else Decimal('0')
        if dias_cobertura is None:
            estado = 'Sin dato'
        elif dias_cobertura < 3:
            estado = 'Crítico'
        elif dias_cobertura <= 7:
            estado = 'Bajo'
        else:
            estado = 'OK'
        pigmentos_panel.append({
            'item': pig,
            'stock': stock,
            'consumo_30': consumo_30,
            'dias_cobertura': round(dias_cobertura, 1) if dias_cobertura is not None else None,
            'pedido': round(pedido, 2),
            'estado': estado,
        })

    conteos_pendientes = list(
        Conteo.objects
        .filter(anulado=False)
        .exclude(estado='conciliado')
        .select_related('usuario')
        .annotate(num_detalles=Count('detalles'))
        .order_by('-fecha', 'turno')[:25]
    )
    for conteo in conteos_pendientes:
        alertas.append({
            'tipo': 'Conteo',
            'severidad': 'media',
            'icono': 'bi-clipboard-data-fill',
            'titulo': f'Conteo {conteo.get_tipo_conteo_display()} pendiente',
            'detalle': f'{conteo.get_turno_display()} · {conteo.num_detalles} línea(s)',
            'fecha': conteo.fecha_hora_conteo,
            'referencia': conteo.fecha.strftime('%d/%m/%Y'),
            'url': reverse('conteo_detalle', args=[conteo.pk]),
            'accion': 'Revisar conteo',
        })

    pendientes_stock = list(
        DetalleMovimiento.objects
        .filter(
            pendiente_conciliacion=True,
            movimiento__anulado=False,
            movimiento__eliminado=False,
        )
        .select_related('item', 'ubicacion_origen', 'movimiento', 'movimiento__usuario')
        .order_by('-movimiento__fecha_movimiento')[:40]
    )
    for det in pendientes_stock:
        alertas.append({
            'tipo': 'Conciliación',
            'severidad': 'alta',
            'icono': 'bi-arrow-repeat',
            'titulo': f'Salida pendiente de conciliación: {det.item.nombre}',
            'detalle': f'{det.cantidad} {det.item.unidad_medida} · {det.ubicacion_origen.nombre if det.ubicacion_origen else "Sin ubicación"}',
            'fecha': det.movimiento.fecha_movimiento,
            'referencia': f'Op. #{det.movimiento_id}',
            'url': reverse('movimiento_detalle', args=[det.movimiento_id]),
            'accion': 'Ver movimiento',
        })

    movimientos_auditados = list(
        MovimientoInventario.objects
        .filter(Q(anulado=True) | Q(eliminado=True))
        .select_related('usuario', 'usuario_anulacion', 'usuario_eliminacion')
        .prefetch_related('detalles__item')
        .order_by('-fecha_movimiento')[:25]
    )
    for mov in movimientos_auditados:
        if mov.eliminado:
            titulo = f'Movimiento eliminado #{mov.pk}'
            fecha = mov.fecha_eliminacion or mov.fecha_movimiento
            detalle = mov.motivo_eliminacion or 'Eliminación lógica registrada'
            severidad = 'media'
        else:
            titulo = f'Movimiento anulado #{mov.pk}'
            fecha = mov.fecha_anulacion or mov.fecha_movimiento
            detalle = mov.motivo_anulacion or 'Anulación registrada'
            severidad = 'baja'
        alertas.append({
            'tipo': 'Auditoría',
            'severidad': severidad,
            'icono': 'bi-shield-exclamation',
            'titulo': titulo,
            'detalle': detalle,
            'fecha': fecha,
            'referencia': mov.get_tipo_movimiento_display(),
            'url': reverse('movimiento_detalle', args=[mov.pk]),
            'accion': 'Ver auditoría',
        })

    alertas.sort(key=lambda a: a['fecha'] or now, reverse=True)
    context = {
        'alertas': alertas[:120],
        'total_alertas': len(alertas),
        'total_stock': len(items_bajo),
        'total_stock_cero': sum(1 for item in items_bajo if (item.stock_calc or Decimal('0')) <= 0),
        'total_pigmentos': len(pigmentos_criticos),
        'total_conteos': len(conteos_pendientes),
        'total_pendientes_stock': len(pendientes_stock),
        'total_auditados': len(movimientos_auditados),
        'pigmentos_panel': pigmentos_panel[:12],
    }
    cache.set(cache_key, context, 60)
    return render(request, 'alertas/centro.html', context)
