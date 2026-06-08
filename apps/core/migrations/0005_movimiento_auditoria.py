"""
0005 — Campos de auditoría en MovimientoInventario
    - editado / fecha_edicion / usuario_edicion / motivo_edicion
    - anulado / fecha_anulacion / usuario_anulacion / motivo_anulacion
    - eliminado / fecha_eliminacion / usuario_eliminacion / motivo_eliminacion
    - Índice compuesto (anulado, eliminado)
    - Permisos: editar_movimiento, anular_movimiento, eliminar_movimiento
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_add_indexes'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [

        # ── Edición ──────────────────────────────────────────────────────────
        migrations.AddField(
            model_name='movimientoinventario',
            name='editado',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='movimientoinventario',
            name='fecha_edicion',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='movimientoinventario',
            name='usuario_edicion',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='movimientos_editados',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='movimientoinventario',
            name='motivo_edicion',
            field=models.TextField(blank=True),
        ),

        # ── Anulación ─────────────────────────────────────────────────────────
        migrations.AddField(
            model_name='movimientoinventario',
            name='anulado',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='movimientoinventario',
            name='fecha_anulacion',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='movimientoinventario',
            name='usuario_anulacion',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='movimientos_anulados',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='movimientoinventario',
            name='motivo_anulacion',
            field=models.TextField(blank=True),
        ),

        # ── Eliminación lógica ────────────────────────────────────────────────
        migrations.AddField(
            model_name='movimientoinventario',
            name='eliminado',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='movimientoinventario',
            name='fecha_eliminacion',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='movimientoinventario',
            name='usuario_eliminacion',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='movimientos_eliminados',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='movimientoinventario',
            name='motivo_eliminacion',
            field=models.TextField(blank=True),
        ),

        # ── Índice de estado ──────────────────────────────────────────────────
        migrations.AddIndex(
            model_name='movimientoinventario',
            index=models.Index(fields=['anulado', 'eliminado'], name='mov_estado_idx'),
        ),

        # ── Permisos en MovimientoInventario ──────────────────────────────────
        migrations.AlterModelOptions(
            name='movimientoinventario',
            options={
                'ordering': ['-fecha'],
                'permissions': [
                    ('editar_movimiento',   'Puede editar movimientos'),
                    ('anular_movimiento',   'Puede anular movimientos'),
                    ('eliminar_movimiento', 'Puede eliminar movimientos (lógico)'),
                ],
                'verbose_name': 'Movimiento',
                'verbose_name_plural': 'Movimientos',
            },
        ),
    ]
