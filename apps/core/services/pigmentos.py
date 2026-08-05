"""
Cobertura de pigmentos: consumo, promedio diario y días restantes de stock.

Fuente única de verdad para el reporte manual
(apps/core/views/reportes.py:reporte_consumo_pigmentos) y para la alerta
programada (apps/core/tasks.py:notify_pigment_coverage). El cálculo vivía solo
dentro de la vista, así que la proyección de "cuántos días me quedan" existía
pero nadie se enteraba de ella salvo que abriera el reporte a mano.
"""
from decimal import Decimal

from django.db.models import DecimalField, Sum, Value
from django.db.models.functions import Coalesce

from ..models import DetalleMovimiento, Item

# Umbrales de cobertura, en días de consumo restante.
DIAS_CRITICO = 3
DIAS_BAJO = 7

ESTADO_LABELS = {
    'ok':          'OK',
    'bajo':        'Bajo',
    'critico':     'Crítico',
    'sin_consumo': 'Sin consumo',
}

_STOCK_ANN = Coalesce(
    Sum('stock__cantidad_actual'),
    Value(Decimal('0')),
    output_field=DecimalField(max_digits=12, decimal_places=2),
)


def pigmentos_activos():
    return (
        Item.objects
        .filter(activo=True, tipo='consumible', categoria__nombre__iexact='Pigmentos')
        .order_by('orden', 'nombre')
    )


def calcular_cobertura(fecha_inicio, fecha_fin, dias_objetivo=14, pigmento_pk=None):
    """
    Calcula consumo y cobertura de cada pigmento activo en el rango dado.

    Consumo = ajustes negativos sobre ítems de categoría Pigmentos.
    Devuelve (resultados, totales) donde cada resultado incluye el `item`,
    consumo del rango, promedio diario, stock actual, días de cobertura,
    pedido sugerido para cubrir `dias_objetivo` y el estado derivado.
    """
    dias_rango = max(1, (fecha_fin - fecha_inicio).days + 1)

    pigmentos_qs = (
        pigmentos_activos()
        .select_related('categoria')
        .annotate(stock_calc=_STOCK_ANN)
    )
    if pigmento_pk:
        pigmentos_qs = pigmentos_qs.filter(pk=pigmento_pk)

    consumos_base = DetalleMovimiento.objects.filter(
        movimiento__tipo_movimiento='ajuste',
        movimiento__anulado=False,
        movimiento__eliminado=False,
        movimiento__fecha_movimiento__date__gte=fecha_inicio,
        movimiento__fecha_movimiento__date__lte=fecha_fin,
        item__tipo='consumible',
        item__categoria__nombre__iexact='Pigmentos',
        cantidad__lt=0,
    )
    if pigmento_pk:
        consumos_base = consumos_base.filter(item_id=pigmento_pk)

    consumo_por_item = {
        row['item_id']: abs(row['total'])
        for row in consumos_base.values('item_id').annotate(total=Sum('cantidad'))
    }

    resultados = []
    total_consumo = Decimal('0')
    total_criticos = 0
    total_pedido = Decimal('0')

    for pig in pigmentos_qs:
        consumo = consumo_por_item.get(pig.pk, Decimal('0'))
        stock = pig.stock_calc or Decimal('0')

        if consumo > 0:
            promedio_diario = consumo / Decimal(str(dias_rango))
            dias_cob = float(stock / promedio_diario) if promedio_diario else None
            pedido = max(Decimal('0'), promedio_diario * Decimal(str(dias_objetivo)) - stock)
        else:
            promedio_diario = Decimal('0')
            dias_cob = None
            pedido = Decimal('0')

        if dias_cob is None:
            estado = 'sin_consumo'
        elif dias_cob < DIAS_CRITICO:
            estado = 'critico'
            total_criticos += 1
        elif dias_cob <= DIAS_BAJO:
            estado = 'bajo'
        else:
            estado = 'ok'

        total_consumo += consumo
        total_pedido += pedido

        resultados.append({
            'item':            pig,
            'consumo':         consumo,
            'promedio_diario': round(promedio_diario, 2),
            'stock':           stock,
            'dias_cobertura':  round(dias_cob, 1) if dias_cob is not None else None,
            'pedido':          round(pedido, 2),
            'estado':          estado,
            'estado_label':    ESTADO_LABELS[estado],
        })

    totales = {
        'dias_rango':     dias_rango,
        'total_consumo':  total_consumo,
        'total_criticos': total_criticos,
        'total_pedido':   total_pedido,
        'consumos_base':  consumos_base,
    }
    return resultados, totales


def payload_cobertura(resultados, fecha_inicio, fecha_fin, dias_objetivo):
    """
    Arma el payload del evento `pigmentos_cobertura` con solo los pigmentos
    que requieren acción (crítico o bajo), ordenados por urgencia.

    Los de estado 'sin_consumo' se omiten a propósito: sin consumo en el rango
    no hay proyección posible y avisarlos sería ruido diario permanente.
    """
    en_riesgo = [r for r in resultados if r['estado'] in ('critico', 'bajo')]
    en_riesgo.sort(key=lambda r: r['dias_cobertura'])

    return {
        'titulo':        'Cobertura de pigmentos',
        'fecha_inicio':  fecha_inicio.isoformat(),
        'fecha_fin':     fecha_fin.isoformat(),
        'dias_objetivo': dias_objetivo,
        'total_criticos': sum(1 for r in en_riesgo if r['estado'] == 'critico'),
        'total_bajos':    sum(1 for r in en_riesgo if r['estado'] == 'bajo'),
        'pigmentos': [
            {
                'item_id':        r['item'].pk,
                'nombre':         r['item'].nombre,
                'codigo':         r['item'].codigo,
                'unidad':         r['item'].unidad_medida,
                'stock':          float(r['stock']),
                'promedio_diario': float(r['promedio_diario']),
                'dias_cobertura': r['dias_cobertura'],
                'pedido':         float(r['pedido']),
                'estado':         r['estado'],
                'estado_label':   r['estado_label'],
            }
            for r in en_riesgo
        ],
    }
