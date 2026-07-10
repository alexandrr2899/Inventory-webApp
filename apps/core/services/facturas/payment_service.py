"""payment_service — registro de abonos y reparto entre facturas."""
from decimal import Decimal

from django.db import transaction

from apps.core.models import Pago, AplicacionPago
from . import status_service


def _facturas_pendientes(cliente):
    """Facturas no anuladas con saldo, de la más vieja a la más nueva."""
    docs = (cliente.documentos
            .exclude(estado_pago='anulada')
            .order_by('fecha_documento', 'created_at'))
    return [d for d in docs if d.saldo_pendiente > 0]


def proponer_reparto(cliente, monto):
    """Reparto sugerido por antigüedad SIN persistir: lista de (documento, monto)."""
    restante = Decimal(monto)
    reparto = []
    for doc in _facturas_pendientes(cliente):
        if restante <= 0:
            break
        aplicar = min(doc.saldo_pendiente, restante)
        if aplicar > 0:
            reparto.append((doc, aplicar))
            restante -= aplicar
    return reparto


def _aplicar_reparto(pago, aplicaciones):
    """Crea las AplicacionPago de `pago` según `aplicaciones` (lista de (doc, monto)).

    Si `aplicaciones` es None, auto-reparte por antigüedad. Cada aplicación se
    topa al saldo de la factura y a lo que resta del pago; el remanente queda
    como saldo a favor del cliente.
    """
    if aplicaciones is None:
        aplicaciones = proponer_reparto(pago.cliente, pago.monto)
    restante = pago.monto
    for documento, monto_aplicar in aplicaciones:
        if restante <= 0:
            break
        monto_aplicar = min(Decimal(monto_aplicar), documento.saldo_pendiente, restante)
        if monto_aplicar > 0:
            AplicacionPago.objects.create(pago=pago, documento=documento, monto=monto_aplicar)
            restante -= monto_aplicar


@transaction.atomic
def registrar_abono(cliente, *, fecha_pago, metodo_pago, monto,
                    referencia='', comprobante=None, notas='', aplicaciones=None):
    """Crea un Pago y reparte su monto entre facturas.

    `aplicaciones`: lista opcional de (documento, monto). Si es None se auto-reparte
    por antigüedad.
    """
    pago = Pago.objects.create(
        cliente=cliente, fecha_pago=fecha_pago, metodo_pago=metodo_pago,
        monto=Decimal(monto), referencia=referencia, comprobante=comprobante, notas=notas,
    )
    _aplicar_reparto(pago, aplicaciones)
    return pago


@transaction.atomic
def editar_abono(pago, *, fecha_pago, metodo_pago, monto,
                 referencia='', comprobante=None, notas='', aplicaciones=None):
    """Actualiza un Pago y rehace su reparto entre facturas.

    Borra las AplicacionPago existentes y las vuelve a crear con la misma lógica
    de `registrar_abono`. El comprobante solo se reemplaza si `comprobante` no es
    None (para no borrar el archivo existente al editar sin subir uno nuevo).
    """
    pago.fecha_pago = fecha_pago
    pago.metodo_pago = metodo_pago
    pago.monto = Decimal(monto)
    pago.referencia = referencia
    pago.notas = notas
    if comprobante is not None:
        pago.comprobante = comprobante
    pago.save()
    pago.aplicaciones.all().delete()
    _aplicar_reparto(pago, aplicaciones)
    return pago


@transaction.atomic
def aplicar_saldo_a_favor(documento):
    """Aplica crédito disponible del cliente a `documento` (pagos más viejos primero).

    Devuelve el monto total aplicado.
    """
    aplicado = Decimal('0.00')
    if documento.estado_pago == 'anulada':
        return aplicado
    pagos = documento.cliente.pagos.order_by('fecha_pago', 'created_at')
    for pago in pagos:
        saldo_doc = documento.saldo_pendiente
        if saldo_doc <= 0:
            break
        disponible = pago.saldo_sin_aplicar
        if disponible <= 0:
            continue
        usar = min(disponible, saldo_doc)
        AplicacionPago.objects.create(pago=pago, documento=documento, monto=usar)
        aplicado += usar
    return aplicado


@transaction.atomic
def liberar_aplicaciones(documento):
    """Elimina las aplicaciones de una factura; el dinero vuelve a saldo a favor."""
    documento.aplicaciones.all().delete()
