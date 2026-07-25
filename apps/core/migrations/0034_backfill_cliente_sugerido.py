"""Llena `cliente_sugerido` de los documentos que la ingesta dejó sin identificar.

El nombre estaba enterrado como prosa dentro de `notas`. Se copia al campo nuevo y
`notas` se deja intacta: sigue siendo la nota para humanos.
"""
from django.db import migrations

from ._0034_backfill_cliente_sugerido_helpers import extraer_sugerido


def backfill(apps, schema_editor):
    DocumentoFactura = apps.get_model('core', 'DocumentoFactura')
    pendientes = []
    for doc in DocumentoFactura.objects.exclude(notas='').only('id', 'notas'):
        sugerido = extraer_sugerido(doc.notas)
        if sugerido:
            doc.cliente_sugerido = sugerido[:200]
            pendientes.append(doc)
    DocumentoFactura.objects.bulk_update(pendientes, ['cliente_sugerido'], batch_size=200)


def revertir(apps, schema_editor):
    DocumentoFactura = apps.get_model('core', 'DocumentoFactura')
    DocumentoFactura.objects.update(cliente_sugerido='')


class Migration(migrations.Migration):
    dependencies = [('core', '0033_documentofactura_cliente_sugerido')]
    operations = [migrations.RunPython(backfill, revertir)]
