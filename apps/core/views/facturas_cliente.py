"""facturas_cliente.py — Fragmento AJAX de la tab Facturas en la vista de cliente."""
from .common import *  # noqa: F401,F403

from ..models import Cliente, DocumentoFactura
from ..forms import AbonoClienteForm
from ..services.facturas import payment_service


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

    activos = list(DocumentoFactura.objects.filter(cliente=cliente).exclude(estado_pago='anulada'))
    total_facturado = sum((d.monto_total for d in activos), Decimal('0'))
    total_pagado = sum((d.monto_pagado for d in activos), Decimal('0'))
    resumen = {
        'total_facturado': total_facturado,
        'total_pagado': total_pagado,
        'total_pendiente': total_facturado - total_pagado,
        # "Vencido" dinámico (igual que la lista): no depende de estado_pago recalculado.
        'total_vencido': sum((d.saldo_pendiente for d in activos if d.esta_vencida), Decimal('0')),
        'num_facturas': sum(1 for d in activos if d.tipo_documento == 'factura'),
        'num_envios': sum(1 for d in activos if d.tipo_documento == 'envio'),
    }
    return render(request, 'facturas/_tab_cliente.html', {
        'cliente': cliente,
        'documentos': qs.order_by('-fecha_documento'),
        'resumen': resumen,
        'tipo_filtro': tipo,
        'desde': desde,
        'hasta': hasta,
        'return_url': reverse('cliente_salidas', args=[cliente.pk]),
    })


@login_required
@permission_required(_perm('registrar_pago_factura'), raise_exception=True)
@facturas_enabled
def cliente_abono_nuevo(request, pk):
    cliente = get_object_or_404(Cliente, pk=pk)
    pendientes = payment_service._facturas_pendientes(cliente)
    if request.method == 'POST':
        form = AbonoClienteForm(request.POST, request.FILES)
        if form.is_valid():
            cd = form.cleaned_data
            # Construir aplicaciones desde los campos aplicar_<pk> si vienen
            aplicaciones = []
            tiene_edicion = False
            for doc in pendientes:
                raw = request.POST.get(f'aplicar_{doc.pk}')
                if raw not in (None, ''):
                    tiene_edicion = True
                    monto = Decimal(raw)
                    if monto > 0:
                        aplicaciones.append((doc, monto))
            payment_service.registrar_abono(
                cliente, fecha_pago=cd['fecha_pago'], metodo_pago=cd['metodo_pago'],
                monto=cd['monto'], referencia=cd.get('referencia', ''),
                comprobante=cd.get('comprobante'), notas=cd.get('notas', ''),
                aplicaciones=aplicaciones if tiene_edicion else None,
            )
            messages.success(request, 'Abono registrado.')
            return redirect('cliente_salidas', pk=cliente.pk)
    else:
        form = AbonoClienteForm(initial={'fecha_pago': timezone.localdate()})
    return render(request, 'facturas/form_abono.html', {
        'form': form, 'cliente': cliente, 'pendientes': pendientes,
    })
