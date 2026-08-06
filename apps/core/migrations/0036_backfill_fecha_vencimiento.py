"""Calcula el vencimiento de los documentos que se quedaron sin él.

Hasta ahora el vencimiento solo se calculaba cuando el cliente tenía días de crédito
(`and cliente.dias_credito`), así que los clientes de contado quedaban con
`fecha_vencimiento` NULL y sus facturas nunca podían pasar a 'vencida'. Ahora contado
vence el mismo día del documento; esta migración aplica la regla a lo ya cargado y
recalcula el estado de los que resultaron vencidos.

«Sin identificar» se deja como está: su vencimiento se calcula al identificar el
documento, con los días del cliente real.
"""
from datetime import timedelta
from decimal import Decimal

from django.db import migrations, models
from django.db.models.functions import Coalesce
from django.utils import timezone

NOMBRE_SIN_IDENTIFICAR = 'Sin identificar'


def backfill(apps, schema_editor):
    DocumentoFactura = apps.get_model('core', 'DocumentoFactura')
    sin_vencimiento = (
        DocumentoFactura.objects
        .filter(fecha_vencimiento__isnull=True, fecha_documento__isnull=False)
        .exclude(cliente__nombre=NOMBRE_SIN_IDENTIFICAR)
        .select_related('cliente')
    )
    pendientes = []
    for doc in sin_vencimiento:
        doc.fecha_vencimiento = doc.fecha_documento + timedelta(
            days=doc.cliente.dias_credito or 0)
        pendientes.append(doc)
    DocumentoFactura.objects.bulk_update(pendientes, ['fecha_vencimiento'], batch_size=200)

    # Los que quedaron con fecha pasada y saldo por cobrar pasan a 'vencida'.
    hoy = timezone.localdate()
    vencidos = (
        DocumentoFactura.objects
        .filter(pk__in=[d.pk for d in pendientes], estado_pago='pendiente',
                fecha_vencimiento__lt=hoy)
        .annotate(pagado=Coalesce(
            models.Sum('aplicaciones__monto'),
            models.Value(Decimal('0')),
            output_field=models.DecimalField(max_digits=12, decimal_places=2),
        ))
        .filter(monto_total__gt=models.F('pagado'))
    )
    DocumentoFactura.objects.filter(pk__in=list(vencidos.values_list('pk', flat=True))).update(
        estado_pago='vencida', updated_at=timezone.now())


def revertir(apps, schema_editor):
    """No-op: no hay forma de distinguir el vencimiento calculado del original."""


class Migration(migrations.Migration):
    dependencies = [('core', '0035_web_push')]
    operations = [migrations.RunPython(backfill, revertir)]
