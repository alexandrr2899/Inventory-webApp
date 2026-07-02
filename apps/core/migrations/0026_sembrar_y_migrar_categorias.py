from django.db import migrations


def forwards(apps, schema_editor):
    from apps.core.services.facturas.categorias import sembrar_y_migrar
    sembrar_y_migrar(
        apps.get_model('core', 'CategoriaProducto'),
        apps.get_model('core', 'DocumentoFactura'),
        apps.get_model('core', 'TarifaCliente'),
    )


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0025_documentofactura_categoria_tarifacliente_categoria'),
    ]
    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
