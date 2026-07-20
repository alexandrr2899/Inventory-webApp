"""busqueda.py — Búsqueda global combinada de clientes y facturas."""
from decimal import Decimal

from django.db.models import Sum, Q, Value, DecimalField
from django.db.models.functions import Coalesce

from .common import *  # noqa: F401,F403

from ..models import Cliente, DocumentoFactura, AplicacionPago

_LIMITE = 6
_DEC = DecimalField(max_digits=12, decimal_places=2)


def _saldos_por_cliente(cliente_ids):
    """{cliente_id: saldo_adeudado} en 2 consultas (Σ monto_total − Σ aplicaciones)."""
    if not cliente_ids:
        return {}
    docs = (DocumentoFactura.objects
            .filter(cliente_id__in=cliente_ids).exclude(estado_pago='anulada')
            .values('cliente_id')
            .annotate(total=Coalesce(Sum('monto_total'), Value(Decimal('0')), output_field=_DEC)))
    total_docs = {r['cliente_id']: r['total'] for r in docs}
    aplic = (AplicacionPago.objects
             .filter(documento__cliente_id__in=cliente_ids)
             .exclude(documento__estado_pago='anulada')
             .values('documento__cliente_id')
             .annotate(total=Coalesce(Sum('monto'), Value(Decimal('0')), output_field=_DEC)))
    total_aplic = {r['documento__cliente_id']: r['total'] for r in aplic}
    return {cid: total_docs.get(cid, Decimal('0')) - total_aplic.get(cid, Decimal('0'))
            for cid in cliente_ids}


@login_required
@permission_required(_perm('ver_facturas'), raise_exception=True)
@facturas_enabled
def buscar_global(request):
    q = (request.GET.get('q') or '').strip()
    if len(q) < 2:
        return JsonResponse({'clientes': [], 'facturas': []})

    puede_abonar = request.user.has_perm(_perm('registrar_pago_factura'))

    clientes_qs = list(Cliente.objects.filter(nombre__icontains=q).order_by('nombre')[:_LIMITE])
    saldos = _saldos_por_cliente([c.pk for c in clientes_qs])
    clientes = [{
        'id': c.pk, 'nombre': c.nombre,
        'saldo': str(saldos.get(c.pk, Decimal('0'))),
        'url': reverse('cliente_salidas', args=[c.pk]),
        'puede_abonar': puede_abonar,
    } for c in clientes_qs]

    facturas_qs = DocumentoFactura.anotar_pagado(
        DocumentoFactura.objects
        .filter(Q(numero_documento__icontains=q) | Q(cliente__nombre__icontains=q))
        .exclude(estado_pago='anulada')
        .select_related('cliente')
        .order_by('-fecha_documento', '-created_at'))[:_LIMITE]
    facturas = [{
        'id': d.pk, 'numero': d.numero_documento or str(d.pk),
        'cliente': d.cliente.nombre, 'tipo': d.tipo_documento,
        'estado': 'vencida' if d.esta_vencida else d.estado_pago,
        'saldo': str(d.saldo_pendiente),
        'url': reverse('factura_detalle', args=[d.pk]),
    } for d in facturas_qs]

    return JsonResponse({'clientes': clientes, 'facturas': facturas})
