"""
stock.py — Helpers de mutación de stock para movimientos y conteos.

Aplican/revierten el efecto de un DetalleMovimiento sobre la tabla Stock,
calculan stock teórico por fecha_movimiento y cierran pendientes de
conciliación. Toda salida descuenta stock (permite negativo); solo se
excluyen movimientos anulados/eliminados.
"""

from django.db import IntegrityError

from .common import *  # noqa: F401,F403


def _mutar_stock(item, ubicacion, delta):
    """
    Suma `delta` (positivo o negativo) al stock de (item, ubicacion) de forma
    ATÓMICA a nivel de base de datos. Debe llamarse dentro de transaction.atomic().

    Usa un UPDATE con F('cantidad_actual') + delta en lugar de leer→sumar en
    Python→guardar. Esto evita la condición de carrera por "lost update": dos
    requests concurrentes que tocan el mismo Stock ya no se pisan, porque el
    UPDATE de Postgres bloquea la fila hasta el commit de la transacción.

    Si la fila no existe todavía se crea con `delta`. Si dos transacciones
    intentan crearla a la vez, una gana y la otra recibe IntegrityError
    (unique_together item+ubicacion) → se reintenta como UPDATE.
    """
    if ubicacion is None or not delta:
        return
    actualizadas = (
        Stock.objects
        .filter(item=item, ubicacion=ubicacion)
        .update(cantidad_actual=F('cantidad_actual') + delta)
    )
    if actualizadas:
        return
    try:
        Stock.objects.create(item=item, ubicacion=ubicacion, cantidad_actual=delta)
    except IntegrityError:
        # La fila apareció entre el UPDATE y el CREATE (carrera de creación):
        # ahora sí existe, así que aplicamos el delta como UPDATE atómico.
        Stock.objects.filter(item=item, ubicacion=ubicacion).update(
            cantidad_actual=F('cantidad_actual') + delta
        )


def _deltas_detalle(det):
    """
    Devuelve la lista de (ubicacion, delta) que un DetalleMovimiento aplica
    sobre el stock. `_aplicar_efecto_detalle` los suma; `_revertir_efecto_detalle`
    los resta. Centraliza la semántica por tipo de movimiento en un solo lugar.
    """
    tipo = det.movimiento.tipo_movimiento
    if tipo == 'entrada':
        return [(det.ubicacion_destino, det.cantidad)]
    if tipo == 'salida':
        return [(det.ubicacion_origen, -det.cantidad)]
    if tipo == 'ajuste':
        # Ajustes pueden ser positivos o negativos.
        return [(det.ubicacion_destino, det.cantidad)]
    if tipo == 'transferencia':
        return [
            (det.ubicacion_origen, -det.cantidad),
            (det.ubicacion_destino, det.cantidad),
        ]
    return []


def _revertir_efecto_detalle(det):
    """
    Deshace el efecto de stock de un DetalleMovimiento.
    Debe llamarse dentro de transaction.atomic().

    Simétrico con _aplicar_efecto_detalle: aplica los deltas negados de forma
    atómica (F()), permitiendo reversiones sobre filas inexistentes.
    """
    for ubicacion, delta in _deltas_detalle(det):
        _mutar_stock(det.item, ubicacion, -delta)


def _aplicar_efecto_detalle(det):
    """
    Aplica el efecto de stock de un DetalleMovimiento recién creado/editado.
    Debe llamarse dentro de transaction.atomic().

    IMPORTANTE — stock negativo y pendiente_conciliacion:
        El campo `pendiente_conciliacion` es solo INFORMATIVO: marca que la
        salida se permitió con stock insuficiente. NO afecta este cálculo.
        Toda salida descuenta stock, aunque quede negativo. Si no existe fila
        Stock, se crea con la cantidad negativa correspondiente.

        Una salida pendiente debe aparecer en:
          • Stock actual (cantidad_actual), incluido valor negativo.
          • Conteos (stock sistema mostrado al usuario).
          • Reportes / kardex / historial.
          • _stock_en_momento (cálculo de stock teórico).

        Solo movimientos `anulado=True` o `eliminado=True` deben excluirse.
    """
    for ubicacion, delta in _deltas_detalle(det):
        _mutar_stock(det.item, ubicacion, delta)


def _revertir_todos_los_detalles(mov):
    """Revierte el stock de TODOS los detalles de un movimiento cabecera."""
    for det in mov.detalles.select_related(
        'item', 'ubicacion_origen', 'ubicacion_destino'
    ).all():
        _revertir_efecto_detalle(det)


def _stock_en_momento(item, ubicacion, fecha_hora):
    """
    Stock teórico de un ítem/ubicación en un momento dado, usando
    fecha_movimiento como timestamp oficial de cada movimiento.

    Algoritmo:
      1. Parte del stock actual (incluye TODOS los movimientos aplicados,
         incluyendo salidas con pendiente_conciliacion=True).
      2. Resta el efecto neto de los movimientos con fecha_movimiento > fecha_hora
         (ocurrieron después del momento de interés → deben excluirse).

    NO filtra por pendiente_conciliacion: una salida pendiente cuenta para
    el stock igual que cualquier otra. Solo se excluyen movimientos anulados
    o eliminados.

    Esto es correcto independientemente de cuándo se registró cada movimiento
    en el sistema: lo que importa es su fecha_movimiento.
    """
    stock_obj = Stock.objects.filter(item=item, ubicacion=ubicacion).first()
    stock_actual = stock_obj.cantidad_actual if stock_obj else Decimal('0')

    # Movimientos cuya fecha_movimiento es POSTERIOR al momento del conteo.
    # Estos ya están aplicados al stock actual pero no debían estarlo al conteo.
    post_movs = (
        DetalleMovimiento.objects
        .filter(
            item=item,
            movimiento__anulado=False,
            movimiento__eliminado=False,
            movimiento__fecha_movimiento__gt=fecha_hora,
        )
        .filter(Q(ubicacion_destino=ubicacion) | Q(ubicacion_origen=ubicacion))
        .only('cantidad', 'ubicacion_origen_id', 'ubicacion_destino_id')
    )

    # Efecto neto de esos movimientos post-conteo sobre esta ubicación
    net_post = Decimal('0')
    for pm in post_movs:
        if pm.ubicacion_destino_id == ubicacion.pk:
            net_post += pm.cantidad   # entró a esta ubicación
        if pm.ubicacion_origen_id == ubicacion.pk:
            net_post -= pm.cantidad   # salió de esta ubicación

    # Stock al momento del conteo = stock actual − efecto de post-conteo
    return stock_actual - net_post


def _movimiento_editable(mov):
    """Retorna True si el movimiento puede ser editado/anulado."""
    return not mov.anulado and not mov.eliminado


def _cerrar_pendientes_conciliacion(item, ubicacion):
    """
    Después de aplicar un ajuste, revisa si el stock del ítem en la ubicación
    es ahora ≥ 0 y, de ser así, cierra (marca como conciliadas) todas las líneas
    de DetalleMovimiento que estén pendientes para ese ítem/ubicación.

    Debe llamarse dentro de transaction.atomic().
    """
    stock_obj = Stock.objects.filter(item=item, ubicacion=ubicacion).first()
    if not stock_obj or stock_obj.cantidad_actual < Decimal('0'):
        return 0

    ahora = timezone.now()
    pendientes = DetalleMovimiento.objects.filter(
        item=item,
        ubicacion_origen=ubicacion,
        pendiente_conciliacion=True,
        movimiento__anulado=False,
        movimiento__eliminado=False,
    )
    n = pendientes.update(pendiente_conciliacion=False, fecha_conciliacion=ahora)
    return n


# Exporta solo los helpers de stock (los nombres de common ya vienen de allí).
__all__ = [
    '_mutar_stock',
    '_deltas_detalle',
    '_revertir_efecto_detalle',
    '_aplicar_efecto_detalle',
    '_revertir_todos_los_detalles',
    '_stock_en_momento',
    '_movimiento_editable',
    '_cerrar_pendientes_conciliacion',
]
