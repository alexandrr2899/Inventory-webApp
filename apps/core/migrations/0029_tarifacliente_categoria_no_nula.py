from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    """Hace TarifaCliente.categoria obligatoria a nivel de esquema.

    Escrita a mano (sin makemigrations) para evitar el prompt interactivo de
    Django sobre valores nulos: la migración 0026 ya garantiza que toda
    TarifaCliente tiene categoria asignada (mapea a 'Otro' cuando no hay match),
    así que no se necesita default ni backfill aquí.
    """

    dependencies = [
        ('core', '0028_remove_documentofactura_producto_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='tarifacliente',
            name='categoria',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='tarifas', to='core.categoriaproducto',
            ),
        ),
    ]
