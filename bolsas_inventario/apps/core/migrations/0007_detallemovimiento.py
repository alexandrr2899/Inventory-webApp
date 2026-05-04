"""
Migration 0007 — Introduce DetalleMovimiento.

Steps (all in one transaction-safe migration):
 1. Create the DetalleMovimiento table.
 2. For every existing MovimientoInventario row, create a matching
    DetalleMovimiento so historic data is preserved.
 3. Drop the item-specific columns from MovimientoInventario (item,
    cantidad, ubicacion_origen, ubicacion_destino, cliente, maquina).
 4. Drop the composite index mov_item_tipo_idx that referenced `item`.
"""

from django.db import migrations, models
import django.db.models.deletion


# ── data migration ─────────────────────────────────────────────────────────────

def crear_detalles(apps, schema_editor):
    """
    For each existing flat MovimientoInventario, create one DetalleMovimiento.
    We access both models through the migration state (not the live import)
    so this is safe regardless of the current model definition.
    """
    Mov = apps.get_model('core', 'MovimientoInventario')
    Det = apps.get_model('core', 'DetalleMovimiento')

    for mov in Mov.objects.all():
        if mov.item_id is None:
            continue                         # already migrated / empty row
        Det.objects.create(
            movimiento_id=mov.pk,
            item_id=mov.item_id,
            cantidad=mov.cantidad,
            ubicacion_origen_id=mov.ubicacion_origen_id,
            ubicacion_destino_id=mov.ubicacion_destino_id,
            cliente_id=mov.cliente_id,
            maquina_id=mov.maquina_id,
        )


def borrar_detalles(apps, schema_editor):
    """Reverse: wipe all DetalleMovimiento (do NOT restore columns — not needed for dev)."""
    Det = apps.get_model('core', 'DetalleMovimiento')
    Det.objects.all().delete()


# ── migration ──────────────────────────────────────────────────────────────────

class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_conteo_tipo_conteo'),
    ]

    operations = [

        # 1 ── Create DetalleMovimiento table ───────────────────────────────────
        migrations.CreateModel(
            name='DetalleMovimiento',
            fields=[
                ('id', models.AutoField(
                    auto_created=True, primary_key=True,
                    serialize=False, verbose_name='ID',
                )),
                ('cantidad', models.DecimalField(decimal_places=2, max_digits=12)),
                ('movimiento', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='detalles',
                    to='core.movimientoinventario',
                    verbose_name='Movimiento',
                )),
                ('item', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    to='core.item',
                )),
                ('ubicacion_origen', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='detalles_origen',
                    to='core.ubicacion',
                    verbose_name='Ubicación origen',
                )),
                ('ubicacion_destino', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='detalles_destino',
                    to='core.ubicacion',
                    verbose_name='Ubicación destino',
                )),
                ('cliente', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    to='core.cliente',
                )),
                ('maquina', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    to='core.maquina',
                    verbose_name='Máquina',
                )),
            ],
            options={
                'verbose_name': 'Línea de movimiento',
                'verbose_name_plural': 'Líneas de movimiento',
                'ordering': ['id'],
            },
        ),

        # 2 ── Migrate existing data ─────────────────────────────────────────────
        migrations.RunPython(crear_detalles, reverse_code=borrar_detalles),

        # 3 ── Drop composite index that references `item` ───────────────────────
        migrations.RemoveIndex(
            model_name='movimientoinventario',
            name='mov_item_tipo_idx',
        ),

        # 4 ── Remove item-specific columns from MovimientoInventario ────────────
        migrations.RemoveField(model_name='movimientoinventario', name='item'),
        migrations.RemoveField(model_name='movimientoinventario', name='cantidad'),
        migrations.RemoveField(model_name='movimientoinventario', name='ubicacion_origen'),
        migrations.RemoveField(model_name='movimientoinventario', name='ubicacion_destino'),
        migrations.RemoveField(model_name='movimientoinventario', name='cliente'),
        migrations.RemoveField(model_name='movimientoinventario', name='maquina'),
    ]
