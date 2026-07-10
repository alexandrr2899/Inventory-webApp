"""facturas_cliente.py — Fragmento AJAX de la tab Facturas en la vista de cliente."""
from decimal import Decimal, InvalidOperation

from .common import *  # noqa: F401,F403

from ..models import Cliente, DocumentoFactura, Pago
from ..forms import AbonoClienteForm, ClienteInlineForm
from ..services.facturas import payment_service


def _form_errors_json(form):
    return {
        field: [str(error) for error in errors]
        for field, errors in form.errors.items()
    }


@login_required
@permission_required(_perm('gestionar_facturas'), raise_exception=True)
@facturas_enabled
@require_POST
def cliente_crear_inline(request):
    form = ClienteInlineForm(request.POST)
    if not form.is_valid():
        return JsonResponse({'ok': False, 'errors': _form_errors_json(form)}, status=400)

    nombre = form.cleaned_data['nombre'].strip()
    duplicado = Cliente.objects.filter(nombre__iexact=nombre).first()
    if duplicado and request.POST.get('forzar') != '1':
        return JsonResponse({
            'ok': False,
            'duplicado': {'id': duplicado.pk, 'nombre': duplicado.nombre},
        })

    cliente = form.save()
    return JsonResponse({
        'ok': True,
        'cliente': {'id': cliente.pk, 'nombre': cliente.nombre},
    }, status=201)


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
        'abonos': cliente.pagos.select_related('metodo_pago')[:50],
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
            aplicaciones, tiene_edicion = _leer_reparto(request, pendientes)
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
        'form': form, 'cliente': cliente,
        'pendientes': [{'doc': d, 'aplicado': None} for d in pendientes],
        'modo_edicion': False, 'pago': None,
        'action_url': reverse('cliente_abono_nuevo', args=[cliente.pk]),
        'titulo': 'Registrar abono', 'submit_label': 'Registrar abono',
    })


def _leer_reparto(request, docs):
    """Construye (aplicaciones, tiene_edicion) desde los campos aplicar_<pk>.

    `docs`: iterable de DocumentoFactura. Devuelve una lista de (doc, monto) para
    todos los valores numéricos válidos (incluyendo 0, que fija la factura en 0),
    y un flag que indica si hubo algún valor numérico — si no hubo ninguno, el
    llamador auto-reparte.
    """
    aplicaciones = []
    tiene_edicion = False
    for doc in docs:
        raw = request.POST.get(f'aplicar_{doc.pk}')
        if raw in (None, ''):
            continue
        try:
            monto = Decimal(raw)
        except (InvalidOperation, ValueError):
            continue
        tiene_edicion = True
        aplicaciones.append((doc, monto))
    return aplicaciones, tiene_edicion


@login_required
@permission_required(_perm('registrar_pago_factura'), raise_exception=True)
@facturas_enabled
def cliente_abono_editar(request, pk):
    pago = get_object_or_404(Pago, pk=pk)
    cliente = pago.cliente
    # Reparto: facturas pendientes + las ya aplicadas por ESTE pago (aunque este
    # abono las haya dejado en saldo 0), para poder redistribuir hacia ellas.
    apps_list = list(pago.aplicaciones.select_related('documento'))
    aplicado_por_doc = {}
    for a in apps_list:
        aplicado_por_doc[a.documento_id] = aplicado_por_doc.get(a.documento_id, Decimal('0')) + a.monto
    docs = {d.pk: d for d in payment_service._facturas_pendientes(cliente)}
    for a in apps_list:
        docs.setdefault(a.documento_id, a.documento)
    docs = sorted(docs.values(), key=lambda d: (d.fecha_documento, d.created_at))

    if request.method == 'POST':
        form = AbonoClienteForm(request.POST, request.FILES)
        if form.is_valid():
            cd = form.cleaned_data
            aplicaciones, tiene_edicion = _leer_reparto(request, docs)
            payment_service.editar_abono(
                pago, fecha_pago=cd['fecha_pago'], metodo_pago=cd['metodo_pago'],
                monto=cd['monto'], referencia=cd.get('referencia', ''),
                comprobante=cd.get('comprobante'), notas=cd.get('notas', ''),
                aplicaciones=aplicaciones if tiene_edicion else None,
            )
            messages.success(request, 'Abono actualizado.')
            return redirect('cliente_salidas', pk=cliente.pk)
    else:
        form = AbonoClienteForm(initial={
            'fecha_pago': pago.fecha_pago, 'metodo_pago': pago.metodo_pago_id,
            'monto': pago.monto, 'referencia': pago.referencia, 'notas': pago.notas,
        })
    return render(request, 'facturas/form_abono.html', {
        'form': form, 'cliente': cliente,
        'pendientes': [{'doc': d, 'aplicado': aplicado_por_doc.get(d.pk)} for d in docs],
        'modo_edicion': True, 'pago': pago,
        'action_url': reverse('cliente_abono_editar', args=[pago.pk]),
        'titulo': 'Editar abono', 'submit_label': 'Guardar cambios',
    })


@login_required
@permission_required(_perm('registrar_pago_factura'), raise_exception=True)
@facturas_enabled
@require_POST
def cliente_abono_borrar(request, pk):
    pago = get_object_or_404(Pago, pk=pk)
    cliente_pk = pago.cliente_id
    pago.delete()  # cascade borra aplicaciones; señales recalculan facturas
    messages.success(request, 'Abono eliminado.')
    return redirect('cliente_salidas', pk=cliente_pk)
