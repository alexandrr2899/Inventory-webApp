"""migracion — convierte PagoFactura viejos en Pago + AplicacionPago.

Recibe las clases como argumentos para poder usarse tanto desde una
data migration (modelos históricos) como desde los tests (modelos reales).
"""

TIPO_LABELS = {
    'efectivo': 'Efectivo',
    'transferencia': 'Transferencia',
    'deposito': 'Depósito',
    'cheque': 'Cheque',
    'tarjeta': 'Tarjeta',
    'otro': 'Otro',
}


def migrar_pagos_a_abonos(PagoFactura, Pago, AplicacionPago, MetodoPago):
    metodos = {}  # tipo string -> instancia MetodoPago

    def metodo_para(tipo):
        tipo = tipo or 'otro'
        if tipo not in metodos:
            obj, _ = MetodoPago.objects.get_or_create(
                tipo=tipo, defaults={'nombre': TIPO_LABELS.get(tipo, tipo.title())},
            )
            metodos[tipo] = obj
        return metodos[tipo]

    for pf in PagoFactura.objects.all().select_related('documento'):
        pago = Pago.objects.create(
            cliente_id=pf.documento.cliente_id,
            fecha_pago=pf.fecha_pago,
            metodo_pago=metodo_para(pf.metodo_pago),
            monto=pf.monto,
            referencia=pf.referencia,
            comprobante=pf.comprobante,
            notas=pf.notas,
        )
        AplicacionPago.objects.create(pago=pago, documento_id=pf.documento_id, monto=pf.monto)
