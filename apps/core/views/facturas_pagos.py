"""facturas_pagos.py — Registro y borrado de pagos."""
from .common import *  # noqa: F401,F403

from ..models import DocumentoFactura, PagoFactura
from ..forms import PagoFacturaForm
from ..services.facturas import payment_service


@login_required
@permission_required(_perm('registrar_pago_factura'), raise_exception=True)
@facturas_enabled
def factura_pago_nuevo(request, pk):
    doc = get_object_or_404(DocumentoFactura, pk=pk)
    if request.method == 'POST':
        form = PagoFacturaForm(request.POST, request.FILES)
        if form.is_valid():
            cd = form.cleaned_data
            payment_service.registrar_pago(
                doc,
                fecha_pago=cd['fecha_pago'],
                metodo_pago=cd['metodo_pago'],
                monto=cd['monto'],
                referencia=cd.get('referencia', ''),
                comprobante=cd.get('comprobante'),
                notas=cd.get('notas', ''),
            )
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
    pago = get_object_or_404(PagoFactura, pk=pk)
    doc_pk = pago.documento_id
    pago.delete()  # el signal post_delete recalcula el estado
    messages.success(request, 'Pago eliminado.')
    return redirect('factura_detalle', pk=doc_pk)
