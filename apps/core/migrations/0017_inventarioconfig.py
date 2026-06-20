from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0016_conteo_editar_perm'),
    ]

    operations = [
        migrations.CreateModel(
            name='InventarioConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('orden_tabs', models.JSONField(default=list)),
            ],
            options={
                'verbose_name': 'Configuración de inventario',
                'verbose_name_plural': 'Configuración de inventario',
                'permissions': [('ordenar_tabs_inventario', 'Puede ordenar las tabs del inventario')],
            },
        ),
    ]
