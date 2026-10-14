"""Cerrar diferencias de producto en conteos históricos todavía abiertos."""

from datetime import timedelta
from decimal import Decimal

from django.db import migrations
from django.db.models import F, Q
from django.utils import timezone


def conciliar_productos_existentes(apps, schema_editor):
    Conteo = apps.get_model('core', 'Conteo')
    ConteoDetalle = apps.get_model('core', 'ConteoDetalle')
    DetalleMovimiento = apps.get_model('core', 'DetalleMovimiento')
    MovimientoInventario = apps.get_model('core', 'MovimientoInventario')
    Stock = apps.get_model('core', 'Stock')
    alias = schema_editor.connection.alias

    # Un conteo físico posterior reemplaza al anterior como referencia de
    # stock. Migrar el anterior encima del posterior duplicaría ajustes.
    ultimo_conteo = {}
    for detalle in ConteoDetalle.objects.using(alias).filter(
        conteo__anulado=False, item__tipo='producto',
    ).select_related('conteo'):
        clave = (detalle.item_id, detalle.ubicacion_id)
        fecha = detalle.conteo.fecha_hora_conteo
        ultimo_conteo[clave] = max(fecha, ultimo_conteo.get(clave, fecha))

    conteos = Conteo.objects.using(alias).filter(
        anulado=False, estado__in=['pendiente', 'parcial'],
    ).order_by('fecha_hora_conteo', 'pk')
    for conteo in conteos.iterator():
        detalles = list(ConteoDetalle.objects.using(alias).filter(
            conteo_id=conteo.pk, item__tipo='producto', ajuste_aplicado=False,
        ))
        if not detalles:
            continue
        umbral = conteo.fecha_hora_conteo.replace(second=0, microsecond=0) + timedelta(minutes=1)
        aplicado = False
        for detalle in detalles:
            clave = (detalle.item_id, detalle.ubicacion_id)
            if ultimo_conteo[clave] > conteo.fecha_hora_conteo:
                continue
            # Un ajuste posterior ya pudo corregir esta diferencia.
            if DetalleMovimiento.objects.using(alias).filter(
                item_id=detalle.item_id,
                ubicacion_destino_id=detalle.ubicacion_id,
                movimiento__tipo_movimiento='ajuste',
                movimiento__anulado=False,
                movimiento__eliminado=False,
                movimiento__fecha_movimiento__gte=umbral,
            ).exists():
                continue

            actual = Stock.objects.using(alias).filter(
                item_id=detalle.item_id, ubicacion_id=detalle.ubicacion_id,
            ).values_list('cantidad_actual', flat=True).first() or Decimal('0')
            posteriores = DetalleMovimiento.objects.using(alias).filter(
                item_id=detalle.item_id,
                movimiento__anulado=False,
                movimiento__eliminado=False,
                movimiento__fecha_movimiento__gte=umbral,
            ).filter(Q(ubicacion_origen_id=detalle.ubicacion_id) | Q(ubicacion_destino_id=detalle.ubicacion_id))
            neto = Decimal('0')
            for cantidad, origen, destino in posteriores.values_list(
                'cantidad', 'ubicacion_origen_id', 'ubicacion_destino_id',
            ):
                if destino == detalle.ubicacion_id:
                    neto += cantidad
                if origen == detalle.ubicacion_id:
                    neto -= cantidad
            diferencia = detalle.cantidad_contada - (actual - neto)
            if diferencia:
                movimiento = MovimientoInventario.objects.using(alias).create(
                    tipo_movimiento='ajuste',
                    fecha=timezone.now(),
                    fecha_movimiento=conteo.fecha_hora_conteo,
                    motivo=f'Ajuste por conciliación automática — Conteo #{conteo.pk} ({conteo.turno} {conteo.fecha})',
                    usuario_id=conteo.usuario_id,
                )
                DetalleMovimiento.objects.using(alias).create(
                    movimiento_id=movimiento.pk,
                    item_id=detalle.item_id,
                    cantidad=diferencia,
                    ubicacion_destino_id=detalle.ubicacion_id,
                )
                actualizados = Stock.objects.using(alias).filter(
                    item_id=detalle.item_id, ubicacion_id=detalle.ubicacion_id,
                ).update(cantidad_actual=F('cantidad_actual') + diferencia)
                if not actualizados:
                    Stock.objects.using(alias).create(
                        item_id=detalle.item_id,
                        ubicacion_id=detalle.ubicacion_id,
                        cantidad_actual=diferencia,
                    )
            ConteoDetalle.objects.using(alias).filter(pk=detalle.pk).update(
                diferencia_final=diferencia,
                ajuste_aplicado=bool(diferencia),
            )
            DetalleMovimiento.objects.using(alias).filter(
                item_id=detalle.item_id,
                ubicacion_origen_id=detalle.ubicacion_id,
                pendiente_conciliacion=True,
                movimiento__anulado=False,
                movimiento__eliminado=False,
                movimiento__fecha_movimiento__lt=umbral,
            ).update(pendiente_conciliacion=False, fecha_conciliacion=timezone.now())
            aplicado = True

        if aplicado:
            sin_resolver = ConteoDetalle.objects.using(alias).filter(conteo_id=conteo.pk).filter(
                Q(diferencia_final__isnull=True) |
                (Q(ajuste_aplicado=False) & ~Q(diferencia_final=0))
            ).exists()
            Conteo.objects.using(alias).filter(pk=conteo.pk).update(
                estado='parcial' if sin_resolver else 'conciliado'
            )


class Migration(migrations.Migration):
    dependencies = [('core', '0043_autoconciliar_conteos_existentes')]

    operations = [migrations.RunPython(conciliar_productos_existentes, migrations.RunPython.noop)]
