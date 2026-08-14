"""Endpoints JSON read-only respaldados por los modelos reales de core."""

from decimal import Decimal

from django.db.models import DecimalField, F, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.utils import timezone

from apps.core.models import Cliente, DocumentoFactura, Item

from .auth import jaime_read_only


DEFAULT_LIMIT = 20
MAX_LIMIT = 100


def _success(data):
    return JsonResponse({'ok': True, 'data': data})


def _error(code, detail, status=400):
    return JsonResponse(
        {'ok': False, 'error': code, 'detail': detail},
        status=status,
    )


def _number(value):
    """Convierte Decimal a un número JSON (JSON no tiene un tipo decimal)."""
    return float(value or Decimal('0'))


def _parse_limit(request):
    raw = request.GET.get('limite')
    if raw in (None, ''):
        return DEFAULT_LIMIT, None
    try:
        limit = int(raw)
    except (TypeError, ValueError):
        return None, _error('parametro_invalido', 'limite debe ser un entero entre 1 y 100.')
    if limit < 1 or limit > MAX_LIMIT:
        return None, _error('parametro_invalido', 'limite debe estar entre 1 y 100.')
    return limit, None


def _cliente_filter(request):
    raw = request.GET.get('cliente_id')
    if raw in (None, ''):
        return None, None
    try:
        cliente_id = int(raw)
    except (TypeError, ValueError):
        return None, _error('parametro_invalido', 'cliente_id debe ser un entero positivo.')
    if cliente_id < 1:
        return None, _error('parametro_invalido', 'cliente_id debe ser un entero positivo.')
    if not Cliente.objects.filter(pk=cliente_id).exists():
        return None, _error('cliente_no_encontrado', 'El cliente solicitado no existe.', 404)
    return cliente_id, None


def _documentos_con_saldo(cliente_id=None):
    qs = DocumentoFactura.objects.exclude(estado_pago='anulada').select_related('cliente')
    if cliente_id is not None:
        qs = qs.filter(cliente_id=cliente_id)
    qs = DocumentoFactura.anotar_pagado(qs)
    return qs.filter(monto_total__gt=F('pagado_ann'))


def _factura_data(documento, *, include_days=False):
    data = {
        'id': documento.pk,
        'numero': documento.numero_documento or None,
        'tipo': documento.tipo_documento,
        'cliente_id': documento.cliente_id,
        'cliente': documento.cliente.nombre,
        'fecha': documento.fecha_documento.isoformat() if documento.fecha_documento else None,
        'vencimiento': (
            documento.fecha_vencimiento.isoformat()
            if documento.fecha_vencimiento else None
        ),
        'total': _number(documento.monto_total),
        'pagado': _number(documento.monto_pagado),
        'saldo': _number(documento.saldo_pendiente),
        'vencida': documento.esta_vencida,
    }
    if include_days:
        data['dias_vencida'] = documento.dias_atraso
    return data


@jaime_read_only
def buscar_clientes(request):
    query = request.GET.get('q', '').strip()
    if not query:
        return _error('parametro_requerido', 'El parámetro q es obligatorio.')

    clientes = (
        Cliente.objects
        .filter(
            Q(nombre__icontains=query)
            | Q(rtn__icontains=query)
            | Q(telefono__icontains=query)
            | Q(aliases__alias__icontains=query)
        )
        .distinct()
        .order_by('nombre')[:20]
    )
    return _success([
        {
            'id': cliente.pk,
            'nombre': cliente.nombre,
            'rtn': cliente.rtn or None,
            'telefono': cliente.telefono or None,
        }
        for cliente in clientes
    ])


@jaime_read_only
def saldo_cliente(request, cliente_id):
    try:
        cliente = Cliente.objects.get(pk=cliente_id)
    except Cliente.DoesNotExist:
        return _error('cliente_no_encontrado', 'El cliente solicitado no existe.', 404)

    documentos = list(_documentos_con_saldo(cliente.pk))
    vencidos = [documento for documento in documentos if documento.esta_vencida]
    saldo = sum((documento.saldo_pendiente for documento in documentos), Decimal('0'))
    saldo_vencido = sum(
        (documento.saldo_pendiente for documento in vencidos), Decimal('0')
    )
    return _success({
        'cliente_id': cliente.pk,
        'cliente': cliente.nombre,
        'saldo_pendiente': _number(saldo),
        'cantidad_facturas_pendientes': len(documentos),
        'cantidad_facturas_vencidas': len(vencidos),
        'saldo_vencido': _number(saldo_vencido),
    })


@jaime_read_only
def facturas_pendientes(request):
    limit, error = _parse_limit(request)
    if error:
        return error
    cliente_id, error = _cliente_filter(request)
    if error:
        return error

    documentos = list(
        _documentos_con_saldo(cliente_id)
        .order_by(F('fecha_documento').asc(nulls_last=True), 'created_at')[:limit]
    )
    total = sum((documento.saldo_pendiente for documento in documentos), Decimal('0'))
    return _success({
        'facturas': [_factura_data(documento) for documento in documentos],
        'resumen': {
            'cantidad': len(documentos),
            'total_pendiente': _number(total),
        },
    })


@jaime_read_only
def facturas_vencidas(request):
    limit, error = _parse_limit(request)
    if error:
        return error
    cliente_id, error = _cliente_filter(request)
    if error:
        return error

    documentos = list(
        _documentos_con_saldo(cliente_id)
        .filter(fecha_vencimiento__lt=timezone.localdate())
        .order_by('fecha_vencimiento', 'fecha_documento', 'created_at')[:limit]
    )
    total = sum((documento.saldo_pendiente for documento in documentos), Decimal('0'))
    return _success({
        'facturas': [
            _factura_data(documento, include_days=True) for documento in documentos
        ],
        'resumen': {
            'cantidad': len(documentos),
            'total_vencido': _number(total),
        },
    })


@jaime_read_only
def consultar_inventario(request):
    limit, error = _parse_limit(request)
    if error:
        return error
    query = request.GET.get('q', '').strip()

    stock_field = DecimalField(max_digits=12, decimal_places=2)
    items = (
        Item.objects
        .filter(activo=True)
        .select_related('categoria')
        .annotate(
            existencia=Coalesce(
                Sum('stock__cantidad_actual'),
                Value(Decimal('0')),
                output_field=stock_field,
            )
        )
    )
    if query:
        items = items.filter(
            Q(codigo__icontains=query)
            | Q(nombre__icontains=query)
            | Q(descripcion__icontains=query)
            | Q(categoria__nombre__icontains=query)
        )
    items = items.order_by('orden', 'nombre')[:limit]

    return _success([
        {
            'id': item.pk,
            'codigo': item.codigo,
            'nombre': item.nombre,
            'descripcion': item.descripcion or None,
            'existencia': _number(item.existencia),
            'unidad': item.unidad_medida,
            'tipo': item.tipo,
            'categoria': item.categoria.nombre if item.categoria else None,
        }
        for item in items
    ])
