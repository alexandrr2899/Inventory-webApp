from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_movimiento_auditoria'),
    ]

    operations = [
        migrations.AddField(
            model_name='conteo',
            name='tipo_conteo',
            field=models.CharField(
                choices=[
                    ('camiseta', 'Camiseta'),
                    ('pigmentos', 'Pigmentos'),
                    ('lisa', 'Lisa'),
                    ('otros', 'Otros'),
                ],
                default='otros',
                max_length=20,
                verbose_name='Tipo de conteo',
            ),
        ),
        migrations.AlterUniqueTogether(
            name='conteo',
            unique_together={('fecha', 'turno', 'tipo_conteo')},
        ),
    ]
