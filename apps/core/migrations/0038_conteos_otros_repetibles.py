from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0037_tipo_documento_apertura'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='conteo',
            name='conteo_activo_unico',
        ),
        migrations.AddConstraint(
            model_name='conteo',
            constraint=models.UniqueConstraint(
                fields=['fecha', 'turno', 'tipo_conteo'],
                condition=Q(anulado=False) & ~Q(tipo_conteo='otros'),
                name='conteo_activo_unico',
            ),
        ),
    ]
