"""facturas_cliente.py — Fragmento AJAX de la tab Facturas en la vista de cliente."""
from .common import *  # noqa: F401,F403

from ..models import Cliente, DocumentoFactura


@login_required
@permission_required(_perm('ver_facturas'), raise_exception=True)
@facturas_enabled
def cliente_facturas_fragment(request, pk):
    cliente = get_object_or_404(Cliente, pk=pk)
    qs = DocumentoFactura.objects.filter(cliente=cliente)

    tipo = request.GET.get('tipo', '')
    if tipo in ('factura', 'envio'):
        qs = qs.filter(tipo_documento=tipo)

    desde = request.GET.get('desde', '')
    hasta = request.GET.get('hasta', '')
    if desde:
        qs = qs.filter(fecha_documento__gte=desde)
    if hasta:
        qs = qs.filter(fecha_documento__lte=hasta)

    activos = DocumentoFactura.objects.filter(cliente=cliente).exclude(estado_pago='anulada')
    total_facturado = sum((d.monto_total for d in activos), Decimal('0'))
    total_pagado = sum((d.monto_pagado for d in activos), Decimal('0'))
    resumen = {
        'total_facturado': total_facturado,
        'total_pagado': total_pagado,
        'total_pendiente': total_facturado - total_pagado,
        'total_vencido': sum((d.saldo_pendiente for d in activos.filter(estado_pago='vencida')), Decimal('0')),
        'num_facturas': activos.filter(tipo_documento='factura').count(),
        'num_envios': activos.filter(tipo_documento='envio').count(),
    }
    return render(request, 'facturas/_tab_cliente.html', {
        'cliente': cliente,
        'documentos': qs.order_by('-fecha_documento'),
        'resumen': resumen,
        'tipo_filtro': tipo,
        'desde': desde,
        'hasta': hasta,
    })
