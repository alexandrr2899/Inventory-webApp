from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0038_conteos_otros_repetibles'),
    ]

    operations = [
        migrations.AddField(
            model_name='ubicacion',
            name='padre',
            field=models.ForeignKey(
                blank=True, help_text='Ejemplo: Estante 1 puede estar dentro de Oficina 1.',
                null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name='sububicaciones', to='core.ubicacion',
                verbose_name='Ubicación superior',
            ),
        ),
        migrations.AlterField(
            model_name='ubicacion',
            name='tipo',
            field=models.CharField(
                choices=[('planta', 'Planta'), ('oficina', 'Oficina'),
                         ('casa', 'Casa'), ('bodega', 'Bodega'),
                         ('produccion', 'Producción'), ('estante', 'Estante'),
                         ('gaveta', 'Gaveta')],
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='item',
            name='ubicacion_predeterminada',
            field=models.ForeignKey(
                blank=True,
                help_text='Ubicación que se seleccionará automáticamente al escanear el QR.',
                null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name='items_predeterminados', to='core.ubicacion',
                verbose_name='Ubicación predeterminada',
            ),
        ),
    ]
