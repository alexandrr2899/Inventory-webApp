from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('core', '0014_performance_indexes'),
    ]

    operations = [
        migrations.CreateModel(
            name='BackupJob',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('fecha_inicio', models.DateTimeField(default=django.utils.timezone.now)),
                ('fecha_fin', models.DateTimeField(blank=True, null=True)),
                ('estado', models.CharField(choices=[('ejecutando', 'Ejecutando'), ('exitoso', 'Exitoso'), ('fallido', 'Fallido')], default='ejecutando', max_length=20)),
                ('archivo', models.CharField(blank=True, max_length=255)),
                ('tamano', models.PositiveBigIntegerField(default=0)),
                ('mensaje_error', models.TextField(blank=True)),
                ('usuario', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Trabajo de backup',
                'verbose_name_plural': 'Trabajos de backup',
                'ordering': ['-fecha_inicio'],
                'permissions': [('gestionar_backups', 'Puede gestionar backups')],
            },
        ),
    ]
