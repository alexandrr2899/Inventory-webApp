from django.db import migrations


def forwards(apps, schema_editor):
    from apps.core.services.facturas.migracion import migrar_pagos_a_abonos
    PagoFactura = apps.get_model('core', 'PagoFactura')
    Pago = apps.get_model('core', 'Pago')
    AplicacionPago = apps.get_model('core', 'AplicacionPago')
    MetodoPago = apps.get_model('core', 'MetodoPago')
    migrar_pagos_a_abonos(PagoFactura, Pago, AplicacionPago, MetodoPago)


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0021_pago_aplicacionpago_and_more'),
    ]
    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
