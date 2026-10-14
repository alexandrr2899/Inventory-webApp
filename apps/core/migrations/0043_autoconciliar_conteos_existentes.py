"""Conciliar conteos históricos que siguieron a salidas con stock negativo."""

from datetime import timedelta
from decimal import Decimal

from django.db import migrations
from django.db.models import F, Q
from django.utils import timezone


def conciliar_existentes(apps, schema_editor):
    Conteo = apps.get_model('core', 'Conteo')
    ConteoDetalle = apps.get_model('core', 'ConteoDetalle')
    DetalleMovimiento = apps.get_model('core', 'DetalleMovimiento')
    MovimientoInventario = apps.get_model('core', 'MovimientoInventario')
    Stock = apps.get_model('core', 'Stock')
    alias = schema_editor.connection.alias

    # Un conteo posterior ya ajustado es el punto de referencia vigente.
    # Rehacer ajustes anteriores a ese punto duplicaría stock histórico.
    ultimo_ajuste = {}
    for detalle in ConteoDetalle.objects.using(alias).filter(
        ajuste_aplicado=True, conteo__anulado=False,
    ).select_related('conteo'):
        clave = (detalle.item_id, detalle.ubicacion_id)
        fecha = detalle.conteo.fecha_hora_conteo
        ultimo_ajuste[clave] = max(fecha, ultimo_ajuste.get(clave, fecha))

    conteos = Conteo.objects.using(alias).filter(anulado=False).order_by('fecha_hora_conteo', 'pk')
    for conteo in conteos.iterator():
        detalles = list(ConteoDetalle.objects.using(alias).filter(conteo_id=conteo.pk))
        if not detalles:
            continue
        umbral = conteo.fecha_hora_conteo.replace(second=0, microsecond=0) + timedelta(minutes=1)
        pendientes = set(DetalleMovimiento.objects.using(alias).filter(
            pendiente_conciliacion=True,
            movimiento__anulado=False,
            movimiento__eliminado=False,
            movimiento__fecha_movimiento__lt=umbral,
            item_id__in=[d.item_id for d in detalles],
            ubicacion_origen_id__in=[d.ubicacion_id for d in detalles],
        ).values_list('item_id', 'ubicacion_origen_id'))
        if not pendientes:
            continue

        candidatos = []
        for detalle in detalles:
            clave = (detalle.item_id, detalle.ubicacion_id)
            if clave not in pendientes or detalle.ajuste_aplicado:
                continue
            if ultimo_ajuste.get(clave, conteo.fecha_hora_conteo) > conteo.fecha_hora_conteo:
                continue
            # Un ajuste posterior ya pudo haber corregido ese faltante.
            # En ese caso no inventamos otra entrada al reconstruir el pasado.
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
            for mov in posteriores.values_list('cantidad', 'ubicacion_origen_id', 'ubicacion_destino_id'):
                cantidad, origen, destino = mov
                if destino == detalle.ubicacion_id:
                    neto += cantidad
                if origen == detalle.ubicacion_id:
                    neto -= cantidad
            teorico = actual - neto
            if teorico < 0:
                candidatos.append((detalle, detalle.cantidad_contada - teorico))

        if not candidatos:
            continue

        for detalle, diferencia in candidatos:
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
            Stock.objects.using(alias).filter(
                item_id=detalle.item_id, ubicacion_id=detalle.ubicacion_id,
            ).update(cantidad_actual=F('cantidad_actual') + diferencia)
            DetalleMovimiento.objects.using(alias).filter(
                item_id=detalle.item_id,
                ubicacion_origen_id=detalle.ubicacion_id,
                pendiente_conciliacion=True,
                movimiento__anulado=False,
                movimiento__eliminado=False,
                movimiento__fecha_movimiento__lt=umbral,
            ).update(pendiente_conciliacion=False, fecha_conciliacion=timezone.now())
            ConteoDetalle.objects.using(alias).filter(pk=detalle.pk).update(
                diferencia_final=diferencia, ajuste_aplicado=True,
            )

        # Dejar el resto del conteo calculado para que el estado refleje si
        # existen diferencias que todavía requieren revisión manual.
        candidatos_ids = {detalle.pk for detalle, _ in candidatos}
        for detalle in detalles:
            if detalle.ajuste_aplicado or detalle.pk in candidatos_ids:
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
            for cantidad, origen, destino in posteriores.values_list('cantidad', 'ubicacion_origen_id', 'ubicacion_destino_id'):
                if destino == detalle.ubicacion_id:
                    neto += cantidad
                if origen == detalle.ubicacion_id:
                    neto -= cantidad
            ConteoDetalle.objects.using(alias).filter(pk=detalle.pk).update(
                diferencia_final=detalle.cantidad_contada - (actual - neto)
            )
        sin_aplicar = ConteoDetalle.objects.using(alias).filter(conteo_id=conteo.pk, ajuste_aplicado=False).exclude(diferencia_final=0).exists()
        Conteo.objects.using(alias).filter(pk=conteo.pk).update(
            estado='parcial' if sin_aplicar else 'conciliado'
        )


class Migration(migrations.Migration):
    dependencies = [('core', '0042_gasto_preservar_usuario')]

    operations = [migrations.RunPython(conciliar_existentes, migrations.RunPython.noop)]
