"""
payloads.py — Builders de payloads para n8n/Telegram y helpers de notificación.

Construyen los dicts que se envían como eventos (inventario camiseta, pigmentos,
stock bajo, producción del día, salidas del día) y el catálogo _REPORTES_MANUALES.
Incluye los helpers de envío automático tras conciliación de camiseta.
Compartido por dashboard, reportes, notificaciones y conteos.
"""

from .common import *  # noqa: F401,F403
from .calc import *    # noqa: F401,F403


def _puede_enviar_notificaciones(user):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=['Administrador', 'Supervisor']).exists()


def _decimal_payload(value):
    if value is None:
        return None
    return float(value)


def _fecha_hora_payload():
    ahora = timezone.localtime(timezone.now())
    return ahora.strftime('%d/%m/%Y'), ahora.strftime('%H:%M')


def _inventario_camiseta_actual():
    orden_operativo = [
        'Bolsa Camiseta Grande',
        'Bolsa Camiseta Mediana',
        'Bolsa Camiseta Pequeña',
        'Bolsa Camiseta Grande Negra',
        'Bolsa Camiseta Mediana Negra',
        'Bolsa Camiseta Pequeña Negra',
    ]
    orden_map = {nombre.lower(): idx for idx, nombre in enumerate(orden_operativo)}
    items = list(
        Item.objects
        .filter(activo=True, tipo='producto')
        .filter(Q(nombre__icontains='camiseta') | Q(categoria__nombre__icontains='camiseta'))
        .select_related('categoria')
        .annotate(stock_calc=_STOCK_ANN)
    )
    items.sort(key=lambda item: (orden_map.get(item.nombre.lower(), 999), item.orden, item.nombre))
    return [
        {
            'nombre': item.nombre,
            'codigo': item.codigo,
            'stock_actual': _decimal_payload(item.stock_calc),
            'unidad': item.unidad_medida,
        }
        for item in items
    ]


def _payload_inventario_camiseta():
    fecha, hora = _fecha_hora_payload()

    return {
        'titulo': 'Inventario actual de Camiseta',
        'fecha': fecha,
        'hora': hora,
        'items': _inventario_camiseta_actual(),
    }


def _enviar_inventario_camiseta_post_conciliacion(conteo_pk, conteo_tipo, usuario=''):
    """
    Reenvía el inventario actual de Camiseta a n8n (mismo evento y payload que
    el envío manual: event_type='inventario_camiseta_actual').

    Debe invocarse SOLO vía transaction.on_commit(), es decir, después de que
    los ajustes de conciliación quedaron persistidos. Si el conteo no es de
    tipo 'camiseta', no hace nada.

    El fallo del webhook NUNCA debe afectar la conciliación: se captura y se
    registra como warning/error, pero no se propaga.
    """
    event_log.info(
        '[CONCILIACION] on_commit ejecutado — conteo_pk=%s tipo=%r usuario=%s',
        conteo_pk, conteo_tipo, usuario,
    )
    if conteo_tipo != 'camiseta':
        event_log.info(
            '[CONCILIACION] Conteo #%s tipo=%r — no es camiseta, se omite el envío.',
            conteo_pk, conteo_tipo,
        )
        return
    try:
        payload = _payload_inventario_camiseta()
        payload['origen'] = 'conciliacion_automatica'
        payload['conteo_id'] = conteo_pk
        if usuario:
            payload['enviado_por'] = usuario
        ok = send_event('inventario_camiseta_actual', payload)
        if ok:
            event_log.info(
                'Inventario camiseta enviado automáticamente tras conciliación #%s',
                conteo_pk,
            )
        else:
            event_log.warning(
                'No se pudo enviar inventario camiseta tras conciliación #%s '
                '(webhook sin configurar o n8n no respondió). La conciliación NO se afecta.',
                conteo_pk,
            )
    except Exception:
        # Nunca romper la conciliación por un fallo de notificación
        event_log.exception(
            'Error al enviar inventario camiseta tras conciliación #%s. '
            'La conciliación se completó correctamente de todas formas.',
            conteo_pk,
        )


def _notificar_si_conciliacion_completa(conteo, estado_antes, usuario=''):
    """
    Programa (vía transaction.on_commit) el reenvío del inventario camiseta
    SOLO cuando el conteo recién transiciona a 'conciliado'.

    Garantiza exactamente UN envío por conteo: si ya estaba 'conciliado' antes
    de esta operación, no hace nada. Debe llamarse dentro de transaction.atomic()
    después de que el estado del conteo quedó actualizado.
    """
    event_log.info(
        '[CONCILIACION] Conteo #%s tipo=%r estado_antes=%r estado_actual=%r usuario=%s',
        conteo.pk, conteo.tipo_conteo, estado_antes, conteo.estado, usuario,
    )
    if conteo.estado != 'conciliado':
        event_log.info(
            '[CONCILIACION] Conteo #%s — estado actual no es conciliado (%r), no se envía.',
            conteo.pk, conteo.estado,
        )
        return
    if estado_antes == 'conciliado':
        event_log.info(
            '[CONCILIACION] Conteo #%s — ya estaba conciliado antes, no se reenvía.',
            conteo.pk,
        )
        return
    _conteo_pk, _conteo_tipo, _usuario = conteo.pk, conteo.tipo_conteo, usuario
    event_log.info(
        '[CONCILIACION] Conteo #%s tipo=%r — programando envío inventario camiseta.',
        _conteo_pk, _conteo_tipo,
    )
    transaction.on_commit(
        lambda: _enviar_inventario_camiseta_post_conciliacion(_conteo_pk, _conteo_tipo, _usuario)
    )


def _payload_inventario_pigmentos():
    from ..services.notifications import generar_resumen_pigmentos
    payload = generar_resumen_pigmentos()
    payload['titulo'] = 'Inventario actual de Pigmentos'
    return payload


def _payload_stock_bajo():
    fecha, hora = _fecha_hora_payload()
    items = (
        Item.objects
        .filter(activo=True)
        .select_related('categoria')
        .annotate(stock_calc=_STOCK_ANN)
        .filter(stock_calc__lte=F('stock_minimo'))
        .order_by('stock_calc', 'orden', 'nombre')
    )
    bajo = []
    cero = []
    for item in items:
        fila = {
            'nombre': item.nombre,
            'codigo': item.codigo,
            'tipo': item.tipo,
            'categoria': item.categoria.nombre if item.categoria else '',
            'stock_actual': _decimal_payload(item.stock_calc),
            'stock_minimo': _decimal_payload(item.stock_minimo),
            'unidad': item.unidad_medida,
        }
        if item.stock_calc <= 0:
            cero.append(fila)
        else:
            bajo.append(fila)
    return {
        'titulo': 'Reporte de stock bajo',
        'fecha': fecha,
        'hora': hora,
        'total': len(bajo) + len(cero),
        'total_bajo': len(bajo),
        'total_cero': len(cero),
        'stock_bajo': bajo,
        'stock_cero': cero,
    }


def _salidas_camiseta_detalle_dia(fecha_operativa):
    inicio, fin = _rango_local_dia(fecha_operativa)
    detalles = (
        DetalleMovimiento.objects
        .filter(
            movimiento__tipo_movimiento='salida',
            movimiento__anulado=False,
            movimiento__eliminado=False,
            movimiento__fecha_movimiento__gte=inicio,
            movimiento__fecha_movimiento__lt=fin,
        )
        .filter(_filtro_detalle_camiseta())
        .select_related('movimiento', 'movimiento__cliente', 'item', 'item__categoria')
        .order_by('movimiento__fecha_movimiento', 'movimiento_id', 'item__orden', 'item__nombre')
    )

    movimientos = {}
    total = Decimal('0')
    por_producto = {}

    for det in detalles:
        mov = det.movimiento
        cliente = mov.cliente or det.cliente
        grupo = movimientos.setdefault(mov.pk, {
            'movimiento': mov,
            'cliente': cliente.nombre if cliente else 'Sin cliente',
            'items': [],
            'total': Decimal('0'),
        })
        grupo['items'].append(det)
        grupo['total'] += det.cantidad
        total += det.cantidad

        producto = por_producto.setdefault(det.item_id, {
            'item': det.item,
            'cantidad': Decimal('0'),
        })
        producto['cantidad'] += det.cantidad

    salidas = []
    for grupo in movimientos.values():
        mov = grupo['movimiento']
        fecha_local = timezone.localtime(mov.fecha_movimiento)
        items = []
        for det in sorted(grupo['items'], key=lambda d: _orden_operativo_producto(d.item)):
            items.append({
                'nombre': det.item.nombre,
                'codigo': det.item.codigo,
                'cantidad': _decimal_payload(det.cantidad),
                'unidad': det.item.unidad_medida,
            })
        salidas.append({
            'movimiento_id': mov.pk,
            'fecha': fecha_local.strftime('%d/%m/%Y'),
            'hora': fecha_local.strftime('%H:%M'),
            'cliente': grupo['cliente'],
            'items': items,
            'total_movimiento': _decimal_payload(grupo['total']),
        })

    total_por_producto = []
    for data in sorted(por_producto.values(), key=lambda d: _orden_operativo_producto(d['item'])):
        item = data['item']
        total_por_producto.append({
            'nombre': item.nombre,
            'codigo': item.codigo,
            'cantidad': _decimal_payload(data['cantidad']),
            'unidad': item.unidad_medida,
        })

    return {
        'total': total,
        'detalle': salidas,
        'por_producto': total_por_producto,
        'inicio': inicio,
        'fin': fin,
    }


def _texto_salidas_dia_telegram(salidas_detalle, total):
    if not salidas_detalle:
        return '📤 Salidas del día\nSin salidas de producto terminado registradas.'

    bloques = ['📤 Salidas del día']
    for salida in salidas_detalle:
        bloques.append(f'👤 Cliente: {salida["cliente"]}')
        for item in salida['items']:
            bloques.append(f'• {item["nombre"]}: {item["cantidad"]:g} {item["unidad"]}')
        bloques.append(f'Total: {salida["total_movimiento"]:g} Fardo')
        bloques.append('')
    bloques.append(f'Total salidas del día: {_decimal_payload(total):g} Fardo')
    return '\n'.join(bloques).strip()


def _payload_produccion_dia():
    fecha_operativa = timezone.localdate()
    fecha, hora = _fecha_hora_payload()
    produccion = _calcular_produccion(fecha_operativa)
    salidas_completas = _salidas_camiseta_detalle_dia(fecha_operativa)

    salidas_calculo_total = (produccion['salidas_dia'] or Decimal('0')) + (produccion['salidas_noche'] or Decimal('0'))

    return {
        'titulo': 'Reporte de producción del día',
        'fecha': fecha,
        'hora': hora,
        'fecha_operativa': fecha_operativa.isoformat(),
        'produccion_dia': _decimal_payload(produccion['produccion_dia']),
        'produccion_noche': _decimal_payload(produccion['produccion_noche']),
        'produccion_total': _decimal_payload(produccion['produccion_total']),
        'salidas_dia': _decimal_payload(produccion['salidas_dia']),
        'salidas_noche': _decimal_payload(produccion['salidas_noche']),
        'salidas_calculo': {
            'dia': _decimal_payload(produccion['salidas_dia']),
            'noche': _decimal_payload(produccion['salidas_noche']),
            'total': _decimal_payload(salidas_calculo_total),
        },
        'inventario_actual': _inventario_camiseta_actual(),
        'salidas_dia_total': _decimal_payload(salidas_completas['total']),
        'salidas_del_dia_detalle': salidas_completas['detalle'],
        'salidas_del_dia_por_producto': salidas_completas['por_producto'],
        'salidas_del_dia_texto': _texto_salidas_dia_telegram(
            salidas_completas['detalle'],
            salidas_completas['total'],
        ),
    }


def _payload_salidas_dia():
    fecha_operativa = timezone.localdate()
    fecha, hora = _fecha_hora_payload()
    inicio, fin = _rango_local_dia(fecha_operativa)
    detalles = (
        DetalleMovimiento.objects
        .filter(
            movimiento__tipo_movimiento='salida',
            movimiento__anulado=False,
            movimiento__eliminado=False,
            movimiento__fecha_movimiento__gte=inicio,
            movimiento__fecha_movimiento__lt=fin,
            item__tipo='producto',
        )
        .select_related('movimiento', 'item', 'cliente', 'movimiento__cliente')
        .order_by('cliente__nombre', 'movimiento__cliente__nombre', 'item__orden', 'item__nombre')
    )

    grupos = {}
    total = Decimal('0')
    for det in detalles:
        cliente = det.cliente or det.movimiento.cliente
        cliente_nombre = cliente.nombre if cliente else 'Sin cliente'
        grupo = grupos.setdefault(cliente_nombre, {'cliente': cliente_nombre, 'total': Decimal('0'), 'items': []})
        grupo['total'] += det.cantidad
        total += det.cantidad
        grupo['items'].append({
            'movimiento_id': det.movimiento_id,
            'hora': timezone.localtime(det.movimiento.fecha_movimiento).strftime('%H:%M'),
            'nombre': det.item.nombre,
            'codigo': det.item.codigo,
            'cantidad': _decimal_payload(det.cantidad),
            'unidad': det.item.unidad_medida,
        })

    salidas = []
    for grupo in grupos.values():
        salidas.append({
            'cliente': grupo['cliente'],
            'total': _decimal_payload(grupo['total']),
            'items': grupo['items'],
        })

    return {
        'titulo': 'Reporte de salidas del día',
        'fecha': fecha,
        'hora': hora,
        'fecha_operativa': fecha_operativa.isoformat(),
        'total_salidas': _decimal_payload(total),
        'clientes': salidas,
    }


_REPORTES_MANUALES = {
    'inventario_camiseta': {
        'titulo': 'Inventario Camiseta',
        'descripcion': 'Stock actual de productos Camiseta en orden operativo.',
        'event_type': 'inventario_camiseta_actual',
        'builder': _payload_inventario_camiseta,
        'icono': 'bi-bag-check-fill',
        'color': 'primary',
    },
    'inventario_pigmentos': {
        'titulo': 'Inventario Pigmentos',
        'descripcion': 'Stock, mínimo y estado de pigmentos.',
        'event_type': 'inventario_pigmentos_actual',
        'builder': _payload_inventario_pigmentos,
        'icono': 'bi-droplet-half',
        'color': 'info',
    },
    'stock_bajo': {
        'titulo': 'Stock bajo',
        'descripcion': 'Ítems activos separados entre bajo y cero.',
        'event_type': 'reporte_stock_bajo',
        'builder': _payload_stock_bajo,
        'icono': 'bi-exclamation-triangle-fill',
        'color': 'warning',
    },
    'produccion_dia': {
        'titulo': 'Producción del día',
        'descripcion': 'Producción día/noche con conteos usados y salidas incluidas.',
        'event_type': 'reporte_produccion_dia',
        'builder': _payload_produccion_dia,
        'icono': 'bi-graph-up-arrow',
        'color': 'success',
    },
    'salidas_dia': {
        'titulo': 'Salidas del día',
        'descripcion': 'Salidas activas de producto terminado agrupadas por cliente.',
        'event_type': 'reporte_salidas_dia',
        'builder': _payload_salidas_dia,
        'icono': 'bi-arrow-up-circle-fill',
        'color': 'danger',
    },
}


def _orden_operativo_producto(item):
    orden = [
        'bolsa camiseta grande',
        'bolsa camiseta mediana',
        'bolsa camiseta pequeña',
        'bolsa camiseta pequena',
        'bolsa camiseta grande negra',
        'bolsa camiseta mediana negra',
        'bolsa camiseta pequeña negra',
        'bolsa camiseta pequena negra',
    ]
    nombre = item.nombre.lower().strip()
    try:
        pos = orden.index(nombre)
    except ValueError:
        pos = 999
    return (pos, item.orden, item.nombre)



__all__ = [
    '_puede_enviar_notificaciones', '_decimal_payload', '_fecha_hora_payload',
    '_inventario_camiseta_actual', '_payload_inventario_camiseta',
    '_enviar_inventario_camiseta_post_conciliacion', '_notificar_si_conciliacion_completa',
    '_payload_inventario_pigmentos', '_payload_stock_bajo', '_salidas_camiseta_detalle_dia',
    '_texto_salidas_dia_telegram', '_payload_produccion_dia', '_payload_salidas_dia',
    '_REPORTES_MANUALES', '_orden_operativo_producto',
]
