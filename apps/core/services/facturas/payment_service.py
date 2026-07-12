"""payment_service — registro de abonos y reparto entre facturas."""
from decimal import Decimal

from django.db import transaction
from django.core.exceptions import ValidationError

from apps.core.models import Pago, AplicacionPago, DocumentoFactura
from . import status_service


def _validar_monto_positivo(monto):
    monto = Decimal(monto)
    if monto <= 0:
        raise ValidationError('El monto debe ser mayor que cero.')
    return monto


def _facturas_base(cliente, *, bloquear=False):
    qs = cliente.documentos.exclude(estado_pago='anulada')
    if bloquear:
        qs = qs.select_for_update()
    return qs.order_by('fecha_documento', 'created_at')


def _facturas_pendientes(cliente, *, bloquear=False):
    """Facturas no anuladas con saldo, de la más vieja a la más nueva."""
    docs = _facturas_base(cliente, bloquear=bloquear)
    return [d for d in docs if d.saldo_pendiente > 0]


def proponer_reparto(cliente, monto, excluir=None, *, bloquear=False):
    """Reparto sugerido por antigüedad SIN persistir: lista de (documento, monto).

    `excluir`: conjunto opcional de pks de facturas a saltar (p. ej. las que el
    usuario fijó manualmente en el formulario).
    """
    excluir = excluir or set()
    restante = _validar_monto_positivo(monto)
    reparto = []
    for doc in _facturas_pendientes(cliente, bloquear=bloquear):
        if restante <= 0:
            break
        if doc.pk in excluir:
            continue
        aplicar = min(doc.saldo_pendiente, restante)
        if aplicar > 0:
            reparto.append((doc, aplicar))
            restante -= aplicar
    return reparto


def _aplicar_reparto(pago, aplicaciones):
    """Crea las AplicacionPago de `pago`.

    `aplicaciones`: lista de (doc, monto) EXPLÍCITOS del usuario (un monto 0
    significa "no aplicar a esta factura, pero déjala fija"). Las facturas
    listadas quedan fijas a su monto (topado a su saldo y al remanente del
    pago); el remanente se reparte por antigüedad entre las facturas pendientes
    NO listadas. Si `aplicaciones` es None, se reparte todo automáticamente.
    """
    restante = pago.monto
    fijas = set()
    for documento, monto_aplicar in (aplicaciones or []):
        fijas.add(documento.pk)
        if restante <= 0:
            continue
        # Refrescar la factura bloqueada antes de leer saldo_pendiente.
        documento = DocumentoFactura.objects.select_for_update().get(pk=documento.pk)
        monto_aplicar = min(Decimal(monto_aplicar), documento.saldo_pendiente, restante)
        if monto_aplicar > 0:
            AplicacionPago.objects.create(pago=pago, documento=documento, monto=monto_aplicar)
            restante -= monto_aplicar
    # Remanente: auto-repartir por antigüedad entre las pendientes no fijadas.
    if restante > 0:
        for documento, monto_aplicar in proponer_reparto(
            pago.cliente, restante, excluir=fijas, bloquear=True):
            AplicacionPago.objects.create(pago=pago, documento=documento, monto=monto_aplicar)


@transaction.atomic
def registrar_abono(cliente, *, fecha_pago, metodo_pago, monto,
                    referencia='', comprobante=None, notas='', aplicaciones=None):
    """Crea un Pago y reparte su monto entre facturas.

    `aplicaciones`: lista opcional de (documento, monto). Si es None se auto-reparte
    por antigüedad.
    """
    monto = _validar_monto_positivo(monto)
    _facturas_pendientes(cliente, bloquear=True)
    pago = Pago.objects.create(
        cliente=cliente, fecha_pago=fecha_pago, metodo_pago=metodo_pago,
        monto=monto, referencia=referencia, comprobante=comprobante, notas=notas,
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
    monto = _validar_monto_positivo(monto)
    pago = Pago.objects.select_for_update(of=('self',)).select_related('cliente').get(pk=pago.pk)
    _facturas_pendientes(pago.cliente, bloquear=True)
    pago.fecha_pago = fecha_pago
    pago.metodo_pago = metodo_pago
    pago.monto = monto
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
    documento = DocumentoFactura.objects.select_for_update(of=('self',)).select_related('cliente').get(pk=documento.pk)
    if documento.estado_pago == 'anulada':
        return aplicado
    _facturas_pendientes(documento.cliente, bloquear=True)
    pagos = documento.cliente.pagos.select_for_update().order_by('fecha_pago', 'created_at')
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
