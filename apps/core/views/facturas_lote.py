"""facturas_lote.py — Subida en bloque de PDFs con revisión y auto-emparejado."""
from .common import *  # noqa: F401,F403

from ..models import Cliente, DocumentoFactura
from ..services.facturas import bulk_service


@login_required
@permission_required(_perm('gestionar_facturas'), raise_exception=True)
@facturas_enabled
def factura_lote(request):
    if request.method == 'POST':
        archivos = request.FILES.getlist('archivos')
        if not archivos:
            messages.error(request, 'Seleccioná al menos un PDF.')
            return redirect('factura_lote')
        batch_id, filas = bulk_service.procesar_archivos(archivos)
        return render(request, 'facturas/lote_revisar.html', {
            'batch_id': batch_id,
            'filas': filas,
            'clientes': Cliente.objects.filter(activo=True).order_by('nombre'),
            'tipo_choices': DocumentoFactura.TIPO_CHOICES,
            'producto_choices': DocumentoFactura._meta.get_field('producto').choices,
        })
    return render(request, 'facturas/form_lote.html')


@login_required
@permission_required(_perm('gestionar_facturas'), raise_exception=True)
@facturas_enabled
@require_POST
def factura_lote_confirmar(request):
    batch_id = request.POST.get('batch_id', '')
    try:
        total = int(request.POST.get('total_filas', '0'))
    except ValueError:
        total = 0

    filas = []
    for i in range(total):
        p = f'fila-{i}-'
        if not request.POST.get(p + 'archivo'):
            continue
        filas.append({
            'archivo': request.POST.get(p + 'archivo', ''),
            'cliente_id': request.POST.get(p + 'cliente', ''),
            'tipo': request.POST.get(p + 'tipo', 'factura'),
            'numero_documento': request.POST.get(p + 'numero_documento', ''),
            'fecha_documento': request.POST.get(p + 'fecha_documento', ''),
            'producto': request.POST.get(p + 'producto', ''),
            'total_libras': request.POST.get(p + 'total_libras', ''),
            'subtotal': request.POST.get(p + 'subtotal', ''),
            'isv': request.POST.get(p + 'isv', ''),
            'monto_total': request.POST.get(p + 'monto_total', ''),
        })

    creados, errores = bulk_service.crear_desde_lote(batch_id, filas)
    if creados:
        messages.success(request, f'{creados} documento(s) creado(s) como pendientes de revisión.')
    if errores:
        detalle = ', '.join(f'{a} ({m})' for a, m in errores)
        messages.warning(request, f'No se crearon {len(errores)}: {detalle}')
    return redirect('facturas_lista')
