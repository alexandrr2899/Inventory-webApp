"""estado_cuenta_service — arma los datos del estado de cuenta por cliente."""
from decimal import Decimal


def _fecha_cancelacion(doc):
    """Fecha del abono que cerró la factura (saldo 0), o None si aún tiene saldo."""
    if doc.saldo_pendiente > 0:
        return None
    fechas = [a.pago.fecha_pago for a in doc.aplicaciones.select_related('pago')]
    return max(fechas) if fechas else None


def build(cliente, desde, hasta):
    """Datos del estado de cuenta de `cliente` en el rango [desde, hasta] (inclusive)."""
    docs = (cliente.documentos
            .filter(tipo_documento__in=('factura', 'envio'),
                    fecha_documento__gte=desde, fecha_documento__lte=hasta)
            .exclude(estado_pago='anulada')
            .select_related('categoria')
            .order_by('fecha_documento', 'created_at'))
    filas = []
    tot_libras = tot_valor = tot_pago = Decimal('0')
    for doc in docs:
        libras = doc.total_libras or Decimal('0')
        valor = doc.monto_total or Decimal('0')
        pago = doc.monto_pagado
        etiqueta = doc.numero_documento or str(doc.pk)
        if doc.tipo_documento == 'envio':
            etiqueta = f'Envio {etiqueta}'
        filas.append({
            'subcliente': doc.subcliente,
            'producto': doc.categoria.nombre if doc.categoria else '',
            'color': doc.categoria.color if doc.categoria else '',
            'etiqueta': etiqueta,
            'fecha': doc.fecha_documento,
            'libras': libras,
            'precio': doc.precio_por_libra,
            'valor': valor,
            'pago': pago,
            'fecha_cancelacion': _fecha_cancelacion(doc),
        })
        tot_libras += libras
        tot_valor += valor
        tot_pago += pago
    return {
        'cliente': cliente,
        'desde': desde, 'hasta': hasta,
        'filas': filas,
        'totales': {
            'libras': tot_libras, 'valor': tot_valor, 'pago': tot_pago,
            'saldo': tot_valor - tot_pago,
        },
    }
