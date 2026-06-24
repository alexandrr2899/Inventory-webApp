"""facturas.py — Vistas del módulo Facturas (dashboard, listado, detalle, alta)."""
from .common import *  # noqa: F401,F403

from ..models import DocumentoFactura, TarifaCliente, PagoFactura
from ..forms import DocumentoUploadForm, DocumentoEditarForm
from ..services.facturas import invoice_service, status_service


@login_required
@permission_required(_perm('ver_facturas'), raise_exception=True)
@facturas_enabled
def facturas_dashboard(request):
    hoy = timezone.localdate()
    inicio_mes = hoy.replace(day=1)
    docs_mes = DocumentoFactura.objects.filter(fecha_documento__gte=inicio_mes)
    activos = DocumentoFactura.objects.exclude(estado_pago='anulada')

    total_facturado = sum((d.monto_total for d in activos), Decimal('0'))
    total_cobrado = sum((d.monto_pagado for d in activos), Decimal('0'))
    ctx = {
        'total_docs_mes': docs_mes.count(),
        'total_facturado': total_facturado,
        'total_cobrado': total_cobrado,
        'total_pendiente': total_facturado - total_cobrado,
        'total_vencido': sum((d.saldo_pendiente for d in activos.filter(estado_pago='vencida')), Decimal('0')),
        'facturas_pendientes': activos.filter(tipo_documento='factura', estado_pago__in=['pendiente', 'vencida']).count(),
        'envios_pendientes': activos.filter(tipo_documento='envio', estado_pago__in=['pendiente', 'vencida']).count(),
    }
    return render(request, 'facturas/dashboard.html', ctx)


@login_required
@permission_required(_perm('ver_facturas'), raise_exception=True)
@facturas_enabled
def facturas_lista(request):
    qs = DocumentoFactura.objects.select_related('cliente').all()
    tipo = request.GET.get('tipo', '')
    cliente_id = request.GET.get('cliente', '')
    producto = request.GET.get('producto', '')
    estado = request.GET.get('estado', '')
    desde = request.GET.get('desde', '')
    hasta = request.GET.get('hasta', '')

    if tipo:
        qs = qs.filter(tipo_documento=tipo)
    if cliente_id:
        qs = qs.filter(cliente_id=cliente_id)
    if producto:
        qs = qs.filter(producto=producto)
    if estado:
        qs = qs.filter(estado_pago=estado)
    if desde:
        qs = qs.filter(fecha_documento__gte=desde)
    if hasta:
        qs = qs.filter(fecha_documento__lte=hasta)

    ctx = {
        'documentos': qs,
        'clientes': Cliente.objects.order_by('nombre'),
        'filtros': {
            'tipo': tipo, 'cliente': cliente_id, 'producto': producto,
            'estado': estado, 'desde': desde, 'hasta': hasta,
        },
        'tipo_choices': DocumentoFactura.TIPO_CHOICES,
        'estado_choices': DocumentoFactura.ESTADO_PAGO_CHOICES,
        'producto_choices': DocumentoFactura._meta.get_field('producto').choices,
    }
    return render(request, 'facturas/lista.html', ctx)


@login_required
@permission_required(_perm('ver_facturas'), raise_exception=True)
@facturas_enabled
def factura_detalle(request, pk):
    doc = get_object_or_404(DocumentoFactura.objects.select_related('cliente'), pk=pk)
    return render(request, 'facturas/detalle.html', {
        'doc': doc,
        'pagos': doc.pagos.all(),
    })


@login_required
@permission_required(_perm('gestionar_facturas'), raise_exception=True)
@facturas_enabled
def factura_upload(request):
    texto_extraido = ''
    if request.method == 'POST':
        form = DocumentoUploadForm(request.POST, request.FILES)
        if form.is_valid():
            cliente = form.cleaned_data['cliente']
            tipo = form.cleaned_data['tipo_documento']
            producto = form.cleaned_data['producto']
            archivo = form.cleaned_data['archivo_pdf']

            datos = {}
            if archivo:
                prev = invoice_service.previsualizar(tipo, archivo)
                datos = prev['datos']
                texto_extraido = prev['texto_extraido']

            doc = invoice_service.crear_documento(
                cliente=cliente, tipo_documento=tipo, archivo=archivo,
                producto=producto or datos.get('producto'),
                datos=datos, texto_extraido=texto_extraido,
            )
            messages.success(request, 'Documento creado. Revisá y editá los campos.')
            return redirect('factura_editar', pk=doc.pk)
    else:
        form = DocumentoUploadForm()
    return render(request, 'facturas/form_upload.html', {'form': form})


@login_required
@permission_required(_perm('gestionar_facturas'), raise_exception=True)
@facturas_enabled
def factura_editar(request, pk):
    doc = get_object_or_404(DocumentoFactura, pk=pk)
    if request.method == 'POST':
        form = DocumentoEditarForm(request.POST, instance=doc)
        if form.is_valid():
            doc = form.save()
            status_service.actualizar_estado_pago(doc)
            messages.success(request, 'Documento actualizado.')
            return redirect('factura_detalle', pk=doc.pk)
    else:
        form = DocumentoEditarForm(instance=doc)
    return render(request, 'facturas/form_editar.html', {'form': form, 'doc': doc})


@login_required
@permission_required(_perm('gestionar_facturas'), raise_exception=True)
@facturas_enabled
@require_POST
def factura_revisar(request, pk):
    doc = get_object_or_404(DocumentoFactura, pk=pk)
    doc.estado_revision = 'revisada'
    doc.save(update_fields=['estado_revision', 'updated_at'])
    messages.success(request, 'Documento marcado como revisado.')
    return redirect('factura_detalle', pk=doc.pk)


@login_required
@permission_required(_perm('anular_factura'), raise_exception=True)
@facturas_enabled
@require_POST
def factura_anular(request, pk):
    doc = get_object_or_404(DocumentoFactura, pk=pk)
    doc.estado_pago = 'anulada'
    doc.save(update_fields=['estado_pago', 'updated_at'])
    messages.success(request, 'Documento anulado.')
    return redirect('factura_detalle', pk=doc.pk)
