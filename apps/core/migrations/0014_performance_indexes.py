from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0013_alter_detallemovimiento_id'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='detallemovimiento',
            index=models.Index(fields=['item', 'movimiento'], name='det_item_mov_idx'),
        ),
        migrations.AddIndex(
            model_name='detallemovimiento',
            index=models.Index(fields=['ubicacion_origen'], name='det_ub_orig_idx'),
        ),
        migrations.AddIndex(
            model_name='detallemovimiento',
            index=models.Index(fields=['ubicacion_destino'], name='det_ub_dest_idx'),
        ),
        migrations.AddIndex(
            model_name='detallemovimiento',
            index=models.Index(fields=['pendiente_conciliacion'], name='det_pend_conc_idx'),
        ),
        migrations.AddIndex(
            model_name='conteo',
            index=models.Index(fields=['fecha', 'turno', 'tipo_conteo', 'anulado'], name='conteo_fecha_tipo_idx'),
        ),
        migrations.AddIndex(
            model_name='conteo',
            index=models.Index(fields=['estado', 'anulado'], name='conteo_estado_idx'),
        ),
    ]
