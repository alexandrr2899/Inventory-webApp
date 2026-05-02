from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_alter_item_options'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='item',
            options={
                'ordering': ['nombre'],
                'permissions': [
                    ('ver_inventario', 'Puede ver el inventario'),
                    ('crear_item', 'Puede crear ítems'),
                    ('editar_item', 'Puede editar ítems'),
                    ('registrar_entrada', 'Puede registrar entradas'),
                    ('registrar_salida', 'Puede registrar salidas'),
                    ('registrar_conteo', 'Puede registrar conteos físicos'),
                    ('aplicar_conciliacion', 'Puede aplicar conciliación'),
                    ('importar_excel', 'Puede importar ítems desde Excel'),
                    ('ver_reportes', 'Puede ver reportes'),
                    ('registrar_produccion', 'Puede registrar producción'),
                ],
                'verbose_name': 'Ítem',
                'verbose_name_plural': 'Ítems',
            },
        ),
        migrations.AddIndex(
            model_name='item',
            index=models.Index(fields=['activo', 'tipo'], name='item_activo_tipo_idx'),
        ),
        migrations.AddIndex(
            model_name='movimientoinventario',
            index=models.Index(fields=['fecha_movimiento'], name='mov_fecha_mov_idx'),
        ),
        migrations.AddIndex(
            model_name='movimientoinventario',
            index=models.Index(fields=['item', 'tipo_movimiento'], name='mov_item_tipo_idx'),
        ),
        migrations.AddIndex(
            model_name='movimientoinventario',
            index=models.Index(fields=['tipo_movimiento', 'fecha_movimiento'], name='mov_tipo_fecha_idx'),
        ),
    ]
