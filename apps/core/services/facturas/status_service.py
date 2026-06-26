"""status_service — cálculo del estado de pago de un documento."""
from django.utils import timezone


def calcular_estado_pago(documento):
    """Devuelve el estado de pago calculado SIN guardar.

    Reglas:
      - 'anulada' es manual y nunca se sobrescribe.
      - saldo <= 0            → 'pagada'
      - saldo > 0 y vencido   → 'vencida'
      - saldo > 0 y no vencido→ 'pendiente'
    """
    if documento.estado_pago == 'anulada':
        return 'anulada'

    # Solo "pagada" si hay un monto real cubierto. Un documento con monto_total=0
    # (p. ej. sin montos extraídos del PDF) NO debe marcarse pagada al crearse.
    if documento.monto_total and documento.saldo_pendiente <= 0:
        return 'pagada'

    venc = documento.fecha_vencimiento
    if venc and timezone.localdate() > venc:
        return 'vencida'
    return 'pendiente'


def actualizar_estado_pago(documento, *, guardar=True):
    """Calcula y asigna el estado; persiste si guardar=True. Si el estado no cambia, no se hace save (no-op intencional)."""
    nuevo = calcular_estado_pago(documento)
    if documento.estado_pago != nuevo:
        documento.estado_pago = nuevo
        if guardar and documento.pk:
            documento.save(update_fields=['estado_pago', 'updated_at'])
    return nuevo
