"""Cálculos financieros compartidos por Contabilidad y Rendimiento."""
from decimal import Decimal

from django.db.models import Count, DecimalField, Sum, Value
from django.db.models.functions import Coalesce

from ..models import DocumentoFactura, Gasto


ZERO = Decimal('0.00')
MONEY_FIELD = DecimalField(max_digits=14, decimal_places=2)


def ingresos_por_tipo(desde, hasta):
    """Ingresos documentados, independientemente de su estado de cobro."""
    resultado = {
        'factura': {'total': ZERO, 'documentos': 0},
        'envio': {'total': ZERO, 'documentos': 0},
    }
    filas = (
        DocumentoFactura.objects
        .filter(
            fecha_documento__range=(desde, hasta),
            tipo_documento__in=('factura', 'envio'),
        )
        .exclude(estado_pago='anulada')
        .values('tipo_documento')
        .annotate(total=Sum('monto_total'), documentos=Count('id'))
    )
    for fila in filas:
        resultado[fila['tipo_documento']] = {
            'total': fila['total'] or ZERO,
            'documentos': fila['documentos'],
        }
    return resultado


def total_gastos(gastos):
    """Suma un queryset de gastos con cero decimal como valor neutro."""
    return gastos.aggregate(
        total=Coalesce(Sum('monto'), Value(ZERO), output_field=MONEY_FIELD)
    )['total']


def resumen_financiero(desde, hasta):
    """Devuelve las cifras canónicas del período.

    Los KPI siempre representan el período completo. Los filtros analíticos de
    gastos se calculan por separado para no presentar un subconjunto como
    "utilidad neta".
    """
    ingresos = ingresos_por_tipo(desde, hasta)
    gastos = Gasto.objects.filter(fecha__range=(desde, hasta))
    gastos_del_periodo = total_gastos(gastos)
    facturas = ingresos['factura']['total']
    envios = ingresos['envio']['total']
    ingreso_total = facturas + envios
    utilidad = ingreso_total - gastos_del_periodo
    margen = (
        (utilidad / ingreso_total * Decimal('100')).quantize(Decimal('0.01'))
        if ingreso_total != 0 else ZERO
    )
    return {
        'ingresos_facturas': facturas,
        'ingresos_envios': envios,
        'ingreso_total': ingreso_total,
        'gastos_totales': gastos_del_periodo,
        'utilidad': utilidad,
        'margen': margen,
        'documentos_factura': ingresos['factura']['documentos'],
        'documentos_envio': ingresos['envio']['documentos'],
    }


def gastos_por_categoria(gastos):
    return list(
        gastos.values('categoria_id', 'categoria__nombre')
        .annotate(total=Sum('monto'), cantidad=Count('id'))
        .order_by('categoria__orden', 'categoria__nombre')
    )
