from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0039_ubicaciones_jerarquicas'),
    ]

    operations = [
        migrations.AddField(
            model_name='documentofactura',
            name='ingest_fingerprint',
            field=models.CharField(
                blank=True,
                editable=False,
                help_text='SHA-256 del archivo recibido por la ingesta automática.',
                max_length=64,
                null=True,
                unique=True,
            ),
        ),
        migrations.AddField(
            model_name='backupjob',
            name='copia_externa',
            field=models.CharField(
                choices=[
                    ('no_configurada', 'No configurada'),
                    ('exitosa', 'Exitosa'),
                    ('fallida', 'Fallida'),
                ],
                default='no_configurada',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='backupjob',
            name='fecha_copia_externa',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='webpushscheduledevent',
            name='enqueued_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='webpushscheduledevent',
            name='last_error',
            field=models.CharField(blank=True, max_length=300),
        ),
        migrations.CreateModel(
            name='SystemHeartbeat',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=80, unique=True)),
                ('last_seen_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('details', models.JSONField(blank=True, default=dict)),
            ],
            options={
                'verbose_name': 'Señal de salud del sistema',
                'verbose_name_plural': 'Señales de salud del sistema',
            },
        ),
        migrations.AlterModelOptions(
            name='backupjob',
            options={
                'ordering': ['-fecha_inicio'],
                'permissions': [
                    ('gestionar_backups', 'Puede gestionar backups'),
                    ('ver_salud_operativa', 'Puede ver la salud operativa'),
                ],
                'verbose_name': 'Trabajo de backup',
                'verbose_name_plural': 'Trabajos de backup',
            },
        ),
    ]
