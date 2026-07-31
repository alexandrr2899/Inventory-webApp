from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0034_backfill_cliente_sugerido'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='WebPushScheduledEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.CharField(max_length=180, unique=True)),
                ('event_type', models.CharField(max_length=80)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'verbose_name': 'Evento Web Push programado',
                'verbose_name_plural': 'Eventos Web Push programados',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='WebPushSubscription',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('endpoint', models.TextField(unique=True)),
                ('p256dh', models.TextField()),
                ('auth', models.TextField()),
                ('user_agent', models.CharField(blank=True, max_length=300)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('last_success_at', models.DateTimeField(blank=True, null=True)),
                ('last_error', models.CharField(blank=True, max_length=300)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='web_push_subscriptions', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Suscripción Web Push',
                'verbose_name_plural': 'Suscripciones Web Push',
                'ordering': ['-updated_at'],
            },
        ),
        migrations.CreateModel(
            name='WebPushPreference',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('inventario', models.BooleanField(default=True)),
                ('operaciones', models.BooleanField(default=True)),
                ('facturas', models.BooleanField(default=True)),
                ('backups', models.BooleanField(default=True)),
                ('seguridad', models.BooleanField(default=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='web_push_preference', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Preferencia Web Push',
                'verbose_name_plural': 'Preferencias Web Push',
            },
        ),
    ]
