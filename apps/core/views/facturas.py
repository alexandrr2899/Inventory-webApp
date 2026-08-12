"""facturas.py — Vistas del módulo Facturas (dashboard, listado, detalle, alta)."""
from .common import *  # noqa: F401,F403

from urllib.parse import urlsplit

from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.clickjacking import xframe_options_sameorigin

from ..models import (
    AplicacionPago, CategoriaProducto, DocumentoFactura, MetodoPago, TarifaCliente,
)
from ..forms import DocumentoUploadForm, DocumentoEditarForm
from ..services.facturas import clientes, invoice_service, status_service, payment_service


def _safe_return_url(request):
    fallback = reverse('facturas_lista')
    url = request.POST.get('next') or request.GET.get('next') or ''
    if url_has_allowed_host_and_scheme(
        url=url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        parts = urlsplit(url)
        path = parts.path
        if not path.startswith('/'):
            return fallback
        query = f'?{parts.query}' if parts.query else ''
        return f'{path}{query}'
    return fallback


@login_required
@permission_required(_perm('ver_facturas'), raise_exception=True)
@facturas_enabled
def facturas_lista(request):
    # Los filtros se arman sobre un queryset SIN anotar: `anotar_pagado` mete
    # un JOIN a aplicaciones que multiplicaría las filas de cualquier
    # .aggregate() posterior. La anotación se agrega recién sobre la página.
    qs = DocumentoFactura.objects.all()
    tipo = request.GET.get('tipo', '')
    cliente_id = request.GET.get('cliente', '')
    categoria_id = request.GET.get('categoria', '')
    estado = request.GET.get('estado', '')
    revision = request.GET.get('revision', '')
    q = request.GET.get('q', '').strip()
    desde = request.GET.get('desde', '')
    hasta = request.GET.get('hasta', '')

    hoy = timezone.localdate()
    if q:
        qs = qs.filter(Q(numero_documento__icontains=q) | Q(cliente__nombre__icontains=q))
    if revision in ('pendiente', 'revisada', 'error'):
        qs = qs.filter(estado_revision=revision)
    if tipo:
        qs = qs.filter(tipo_documento=tipo)
    if cliente_id:
        qs = qs.filter(cliente_id=cliente_id)
    if categoria_id:
        qs = qs.filter(categoria_id=categoria_id)
    # Estado lógico (vencida/pendiente se calculan por fecha, sin depender de un cron).
    if estado == 'pagada':
        qs = qs.filter(estado_pago='pagada')
    elif estado == 'anulada':
        qs = qs.filter(estado_pago='anulada')
    elif estado == 'vencida':
        qs = qs.filter(estado_pago__in=['pendiente', 'vencida'], fecha_vencimiento__lt=hoy)
    elif estado == 'pendiente':
        qs = qs.filter(estado_pago__in=['pendiente', 'vencida']).filter(
            Q(fecha_vencimiento__gte=hoy) | Q(fecha_vencimiento__isnull=True))
    else:
        # "Todas" no incluye anuladas (solo se ven en su propia pestaña).
        qs = qs.exclude(estado_pago='anulada')
    if desde:
        qs = qs.filter(fecha_documento__gte=desde)
    if hasta:
        qs = qs.filter(fecha_documento__lte=hasta)

    qs = qs.order_by('-fecha_documento', '-created_at')

    # Resumen calculado en la BD sobre el conjunto YA filtrado (el rango de
    # fechas afecta también a los totales mostrados arriba de la tabla). Antes
    # se sumaba en Python recorriendo TODOS los documentos, lo que obligaba a
    # traerlos completos a memoria y crecía sin techo con los años.
    activos = qs.exclude(estado_pago='anulada')
    total_facturado = activos.aggregate(t=Sum('monto_total'))['t'] or Decimal('0')
    total_cobrado = AplicacionPago.objects.filter(
        documento__in=activos).aggregate(t=Sum('monto'))['t'] or Decimal('0')

    # Vencido = saldo de lo que ya pasó su fecha. Se calcula como
    # (facturado − cobrado) del subconjunto vencido: un documento saldado
    # aporta cero, igual que el criterio de `esta_vencida`.
    vencidas = activos.filter(fecha_vencimiento__lt=hoy)
    vencido_facturado = vencidas.aggregate(t=Sum('monto_total'))['t'] or Decimal('0')
    vencido_cobrado = AplicacionPago.objects.filter(
        documento__in=vencidas).aggregate(t=Sum('monto'))['t'] or Decimal('0')

    resumen = {
        'total_documentos': qs.count(),
        'total_facturado': total_facturado,
        'total_cobrado': total_cobrado,
        'total_pendiente': total_facturado - total_cobrado,
        'total_vencido': max(Decimal('0'), vencido_facturado - vencido_cobrado),
    }

    paginator = Paginator(
        DocumentoFactura.anotar_pagado(qs.select_related('cliente', 'categoria')),
        100,
    )
    page_obj = paginator.get_page(request.GET.get('page'))

    ctx = {
        'documentos': page_obj,
        'page_obj': page_obj,
        'resumen': resumen,
        # El contador "por revisar" lo aporta el context processor (facturas_por_revisar).
        'clientes': Cliente.objects.order_by('nombre'),
        'filtros': {
            'tipo': tipo, 'cliente': cliente_id, 'categoria': categoria_id,
            'estado': estado, 'revision': revision, 'q': q,
            'desde': desde, 'hasta': hasta,
        },
        'tipo_choices': DocumentoFactura.TIPO_CHOICES,
        'estado_choices': DocumentoFactura.ESTADO_PAGO_CHOICES,
        'categorias': CategoriaProducto.objects.filter(activa=True),
        # El modal de pago rápido (_modal_pago.html, incluido en lista.html) itera
        # `metodos_pago`; sin esto el <select> de método sale vacío al pagar desde la lista.
        'metodos_pago': MetodoPago.objects.filter(activo=True),
        'return_url': request.get_full_path(),
        # Se resuelve una sola vez acá y el template compara por id. Una propiedad
        # del modelo dispararía una consulta por fila.
        'sin_identificar_id': clientes.cliente_sin_identificar().pk,
    }
    return render(request, 'facturas/lista.html', ctx)


@login_required
@permission_required(_perm('ver_facturas'), raise_exception=True)
@facturas_enabled
def factura_detalle(request, pk):
    doc = get_object_or_404(
        DocumentoFactura.anotar_pagado(
            DocumentoFactura.objects.select_related('cliente')
        ),
        pk=pk,
    )
    return render(request, 'facturas/detalle.html', {
        'doc': doc,
        'aplicaciones': doc.aplicaciones.select_related('pago', 'pago__metodo_pago'),
        'metodos_pago': MetodoPago.objects.filter(activo=True),
        'return_url': _safe_return_url(request),
    })


@login_required
@permission_required(_perm('ver_facturas'), raise_exception=True)
@facturas_enabled
@xframe_options_sameorigin
def factura_pdf(request, pk):
    """Sirve el PDF del documento de forma protegida (inline para previsualizar).

    El media no se publica directamente; este endpoint exige el permiso de facturas.
    """
    doc = get_object_or_404(DocumentoFactura, pk=pk)
    if not doc.archivo_pdf:
        raise Http404('El documento no tiene PDF.')
    try:
        archivo = doc.archivo_pdf.open('rb')
    except (FileNotFoundError, ValueError):
        raise Http404('Archivo no encontrado.')
    # Sanear el nombre (entra en una cabecera HTTP): sin comillas ni saltos de línea.
    nombre = str(doc.numero_documento or doc.pk)
    nombre = nombre.replace('"', '').replace('\r', '').replace('\n', '').strip() or str(doc.pk)
    resp = FileResponse(archivo, content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="{nombre}.pdf"'
    return resp


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
            categoria = form.cleaned_data['categoria']
            archivo = form.cleaned_data['archivo_pdf']

            # Auto-detección del tipo desde el nombre del archivo si no se eligió.
            if not tipo:
                nombre = getattr(archivo, 'name', '') if archivo else ''
                tipo = invoice_service.detectar_tipo(nombre)

            datos = {}
            if archivo:
                prev = invoice_service.previsualizar(tipo, archivo)
                datos = prev['datos']
                texto_extraido = prev['texto_extraido']

            doc = invoice_service.crear_documento(
                cliente=cliente, tipo_documento=tipo, archivo=archivo,
                categoria=categoria,
                datos=datos, texto_extraido=texto_extraido,
            )
            payment_service.aplicar_saldo_a_favor(doc)
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
    return_url = _safe_return_url(request)
    if request.method == 'POST':
        form = DocumentoEditarForm(request.POST, instance=doc)
        if form.is_valid():
            doc = form.save()
            payment_service.aplicar_saldo_a_favor(doc)
            if request.POST.get('accion') == 'guardar_revisar':
                doc.estado_revision = 'revisada'
                doc.save(update_fields=['estado_revision', 'updated_at'])
                messages.success(request, 'Documento actualizado y marcado como revisado.')
                status_service.actualizar_estado_pago(doc)
                return redirect(return_url)
            else:
                messages.success(request, 'Documento actualizado.')
            status_service.actualizar_estado_pago(doc)
            return redirect('factura_detalle', pk=doc.pk)
    else:
        form = DocumentoEditarForm(instance=doc)
    # Mapa cliente→días de crédito para calcular el vencimiento en vivo en el form.
    dias_credito = {str(c.pk): c.dias_credito for c in Cliente.objects.all()}
    return render(request, 'facturas/form_editar.html', {
        'form': form, 'doc': doc, 'dias_credito_json': _json_safe(dias_credito),
        'return_url': return_url,
    })


@login_required
@permission_required(_perm('gestionar_facturas'), raise_exception=True)
@facturas_enabled
@require_POST
def factura_revisar(request, pk):
    doc = get_object_or_404(DocumentoFactura, pk=pk)
    doc.estado_revision = 'revisada'
    doc.save(update_fields=['estado_revision', 'updated_at'])
    messages.success(request, 'Documento marcado como revisado.')
    return redirect(_safe_return_url(request))


@login_required
@permission_required(_perm('anular_factura'), raise_exception=True)
@facturas_enabled
@require_POST
def factura_anular(request, pk):
    doc = get_object_or_404(DocumentoFactura, pk=pk)
    doc.estado_pago = 'anulada'
    doc.save(update_fields=['estado_pago', 'updated_at'])
    payment_service.liberar_aplicaciones(doc)
    messages.success(request, 'Documento anulado.')
    return redirect('factura_detalle', pk=doc.pk)
