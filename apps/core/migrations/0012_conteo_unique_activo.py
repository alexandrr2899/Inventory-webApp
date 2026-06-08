from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0010_conteo_anulacion'),
    ]

    operations = [
        # Eliminar la restricción unique_together existente
        migrations.AlterUniqueTogether(
            name='conteo',
            unique_together=set(),
        ),
        # Agregar índice único parcial: solo conteos activos (anulado=False)
        migrations.AddConstraint(
            model_name='conteo',
            constraint=models.UniqueConstraint(
                fields=['fecha', 'turno', 'tipo_conteo'],
                condition=Q(anulado=False),
                name='conteo_activo_unico',
            ),
        ),
    ]
