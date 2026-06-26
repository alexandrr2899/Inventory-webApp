"""payment_service — registro de pagos y recálculo del estado del documento."""
from django.db import transaction

from apps.core.models import PagoFactura
from . import status_service


@transaction.atomic
def registrar_pago(documento, *, fecha_pago, metodo_pago, monto,
                   referencia='', comprobante=None, notas=''):
    """Crea un PagoFactura y recalcula el estado del documento."""
    pago = PagoFactura.objects.create(
        documento=documento,
        fecha_pago=fecha_pago,
        metodo_pago=metodo_pago,
        monto=monto,
        referencia=referencia,
        comprobante=comprobante,
        notas=notas,
    )
    # El signal post_save ya recalcula; recargamos para reflejarlo en la instancia.
    documento.refresh_from_db()
    return pago
