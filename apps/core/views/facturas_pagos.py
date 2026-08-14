"""facturas_pagos.py — Registro, comprobantes y borrado de pagos."""
from .common import *  # noqa: F401,F403

import mimetypes
import os

from ..models import DocumentoFactura, Pago, AplicacionPago
from ..forms import PagoFacturaForm
from ..services.facturas import payment_service


@login_required
@facturas_enabled
def pago_comprobante(request, pk):
    """Sirve un comprobante desde MEDIA_ROOT sin publicar todo `/media/`."""
    permisos = (
        _perm('ver_facturas'),
        _perm('registrar_pago_factura'),
        _perm('gestionar_metodos_pago'),
    )
    if not request.user.is_superuser and not any(
        request.user.has_perm(permiso) for permiso in permisos
    ):
        raise PermissionDenied

    pago = get_object_or_404(Pago, pk=pk)
    if not pago.comprobante:
        raise Http404('El pago no tiene comprobante.')
    try:
        archivo = pago.comprobante.open('rb')
    except (FileNotFoundError, OSError, ValueError):
        raise Http404('Archivo no encontrado.')

    nombre = os.path.basename(pago.comprobante.name) or f'comprobante-{pago.pk}'
    content_type = mimetypes.guess_type(nombre)[0] or 'application/octet-stream'
    return FileResponse(
        archivo, content_type=content_type, as_attachment=False, filename=nombre,
    )


@login_required
@permission_required(_perm('registrar_pago_factura'), raise_exception=True)
@facturas_enabled
def factura_pago_nuevo(request, pk):
    doc = get_object_or_404(DocumentoFactura, pk=pk)
    if doc.estado_pago == 'anulada':
        messages.error(request, 'No se puede registrar un pago sobre un documento anulado.')
        return redirect('factura_detalle', pk=doc.pk)
    if request.method == 'POST':
        form = PagoFacturaForm(request.POST, request.FILES)
        if form.is_valid():
            cd = form.cleaned_data
            pago = payment_service.registrar_abono(
                doc.cliente,
                fecha_pago=cd['fecha_pago'], metodo_pago=cd['metodo_pago'],
                monto=cd['monto'], referencia=cd.get('referencia', ''),
                comprobante=cd.get('comprobante'), notas=cd.get('notas', ''),
                aplicaciones=[(doc, cd['monto'])],
            )
            _send_event_later('pago_factura_creado', {
                'pago_id': pago.pk,
                'documento_id': doc.pk,
                'numero_documento': doc.numero_documento,
                'cliente_id': doc.cliente_id,
                'cliente': doc.cliente.nombre,
                'monto': str(pago.monto),
                'metodo_pago': pago.metodo_pago.nombre,
                'referencia': pago.referencia,
                'registrado_por': request.user.username,
            })
            messages.success(request, 'Pago registrado.')
            return redirect('factura_detalle', pk=doc.pk)
    else:
        form = PagoFacturaForm(initial={'fecha_pago': timezone.localdate()})
    return render(request, 'facturas/form_pago.html', {'form': form, 'doc': doc})


@login_required
@permission_required(_perm('registrar_pago_factura'), raise_exception=True)
@facturas_enabled
@require_POST
def factura_pago_borrar(request, pk):
    apl = get_object_or_404(AplicacionPago, pk=pk)
    doc_pk = apl.documento_id
    pago = apl.pago
    # ¿La aplicación cubría el pago completo? (sin saldo a favor asociado)
    era_pago_completo = apl.monto == pago.monto
    apl.delete()  # signal recalcula el estado del documento
    # Solo se elimina el Pago si era un pago por factura completo y ya no le
    # quedan aplicaciones; si había saldo a favor, el dinero vuelve a quedar
    # disponible como crédito del cliente y el Pago se conserva.
    if era_pago_completo and not pago.aplicaciones.exists():
        pago.delete()
    messages.success(request, 'Pago eliminado.')
    return redirect('factura_detalle', pk=doc_pk)
