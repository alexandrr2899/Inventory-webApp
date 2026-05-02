from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_remove_conteo_ajuste_aplicado_and_more'),
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
    ]
