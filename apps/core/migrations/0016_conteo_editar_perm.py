from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0015_backupjob'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='conteo',
            options={
                'ordering': ['-fecha', 'turno'],
                'permissions': [
                    ('editar_conteo', 'Puede editar conteos'),
                    ('anular_conteo', 'Puede anular conteos'),
                ],
                'verbose_name': 'Conteo',
                'verbose_name_plural': 'Conteos',
            },
        ),
    ]
