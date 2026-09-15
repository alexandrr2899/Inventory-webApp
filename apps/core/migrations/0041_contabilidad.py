import django.db.models.deletion
import django.utils.timezone
import django.core.validators
import apps.core.validators
from decimal import Decimal
from django.conf import settings
from django.db import migrations, models


def sembrar_categorias(apps, schema_editor):
    CategoriaGasto = apps.get_model('core', 'CategoriaGasto')
    nombres = [
        ('Energía', 10),
        ('Alquiler/local', 20),
        ('Empleados/planilla', 30),
        ('Materia prima', 40),
        ('Otros', 50),
    ]
    for nombre, orden in nombres:
        CategoriaGasto.objects.get_or_create(nombre=nombre, defaults={'orden': orden})


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('core', '0040_operational_health'),
    ]

    operations = [
        migrations.CreateModel(
            name='CategoriaGasto',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nombre', models.CharField(max_length=100, unique=True)),
                ('descripcion', models.TextField(blank=True, verbose_name='Descripción')),
                ('orden', models.PositiveIntegerField(default=0)),
                ('activa', models.BooleanField(default=True)),
            ],
            options={
                'verbose_name': 'Categoría de gasto',
                'verbose_name_plural': 'Categorías de gasto',
                'ordering': ['orden', 'nombre'],
                'permissions': [('ver_contabilidad', 'Puede ver Contabilidad'), ('administrar_gastos', 'Puede administrar gastos'), ('administrar_categorias_gasto', 'Puede administrar categorías de gasto')],
            },
        ),
        migrations.CreateModel(
            name='Gasto',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('fecha', models.DateField(default=django.utils.timezone.localdate)),
                ('descripcion', models.CharField(max_length=240, verbose_name='Descripción')),
                ('monto', models.DecimalField(decimal_places=2, max_digits=12, validators=[django.core.validators.MinValueValidator(Decimal('0.01'))], verbose_name='Monto total pagado')),
                ('proveedor', models.CharField(blank=True, max_length=160, verbose_name='Proveedor/beneficiario')),
                ('referencia', models.CharField(blank=True, max_length=120)),
                ('notas', models.TextField(blank=True)),
                ('comprobante', models.FileField(blank=True, null=True, upload_to='contabilidad/comprobantes/%Y/%m/', validators=[apps.core.validators.validar_comprobante_gasto])),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('categoria', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='gastos', to='core.categoriagasto')),
                ('metodo_pago', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='gastos', to='core.metodopago', verbose_name='Método de pago')),
                ('registrado_por', models.ForeignKey(editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='gastos_registrados', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Gasto',
                'verbose_name_plural': 'Gastos',
                'ordering': ['-fecha', '-created_at'],
                'indexes': [models.Index(fields=['fecha'], name='gasto_fecha_idx'), models.Index(fields=['categoria', 'fecha'], name='gasto_cat_fecha_idx')],
                'constraints': [models.CheckConstraint(condition=models.Q(('monto__gt', 0)), name='gasto_monto_positivo')],
            },
        ),
        migrations.RunPython(sembrar_categorias, migrations.RunPython.noop),
    ]
