from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_item_orden'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ── MovimientoInventario: tipo_salida y cliente ───────────────────────
        migrations.AddField(
            model_name='movimientoinventario',
            name='tipo_salida',
            field=models.CharField(
                blank=True,
                choices=[
                    ('producto_terminado', 'Producto Terminado'),
                    ('repuestos',          'Repuestos'),
                    ('consumibles',        'Consumibles'),
                    ('otros',              'Otros'),
                ],
                default='',
                max_length=30,
                verbose_name='Tipo de salida',
            ),
        ),
        migrations.AddField(
            model_name='movimientoinventario',
            name='cliente',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='movimientos_cabecera',
                to='core.cliente',
                verbose_name='Cliente',
            ),
        ),
        # ── DetalleMovimiento: pendiente_conciliacion y fecha_conciliacion ────
        migrations.AddField(
            model_name='detallemovimiento',
            name='pendiente_conciliacion',
            field=models.BooleanField(
                default=False,
                help_text='True cuando la salida se aprobó con stock insuficiente y aún no se ha conciliado.',
                verbose_name='Pendiente conciliación',
            ),
        ),
        migrations.AddField(
            model_name='detallemovimiento',
            name='fecha_conciliacion',
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name='Fecha de conciliación',
            ),
        ),
    ]
