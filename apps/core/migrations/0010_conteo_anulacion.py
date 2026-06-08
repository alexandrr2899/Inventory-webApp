from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0009_salida_tipo_conciliacion'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='conteo',
            name='anulado',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='conteo',
            name='fecha_anulacion',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='conteo',
            name='usuario_anulacion',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='conteos_anulados',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='conteo',
            name='motivo_anulacion',
            field=models.TextField(blank=True),
        ),
        migrations.AlterModelOptions(
            name='conteo',
            options={
                'ordering': ['-fecha', 'turno'],
                'permissions': [('anular_conteo', 'Puede anular conteos')],
                'verbose_name': 'Conteo',
                'verbose_name_plural': 'Conteos',
            },
        ),
    ]
