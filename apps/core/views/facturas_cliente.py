"""facturas_cliente.py — Fragmento AJAX de la tab Facturas en la vista de cliente."""
import logging
from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.views.decorators.cache import never_cache

from .common import *  # noqa: F401,F403

from ..models import Cliente, DocumentoFactura, Pago
from ..forms import AbonoClienteForm, ClienteInlineForm, SaldoInicialForm
from ..services.facturas import clientes, invoice_service, payment_service, status_service

_log = logging.getLogger(__name__)


def _form_errors_json(form):
    return {
        field: [str(error) for error in errors]
        for field, errors in form.errors.items()
    }


def _es_ajax(request):
    return request.headers.get('x-requested-with') == 'XMLHttpRequest'


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
    qs = DocumentoFactura.anotar_pagado(DocumentoFactura.objects.filter(cliente=cliente))

    tipo = request.GET.get('tipo', '')
    if tipo in ('factura', 'envio'):
        qs = qs.filter(tipo_documento=tipo)

    desde = request.GET.get('desde', '')
    hasta = request.GET.get('hasta', '')
    if desde:
        qs = qs.filter(fecha_documento__gte=desde)
    if hasta:
        qs = qs.filter(fecha_documento__lte=hasta)

    activos = list(DocumentoFactura.anotar_pagado(
        DocumentoFactura.objects.filter(cliente=cliente).exclude(estado_pago='anulada')))
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
        'saldo_inicial': invoice_service.saldo_inicial_de(cliente),
    })


@login_required
@permission_required(_perm('gestionar_facturas'), raise_exception=True)
@facturas_enabled
def cliente_saldo_inicial(request, pk):
    """Registra la deuda previa al sistema como documento de apertura del cliente."""
    cliente = get_object_or_404(Cliente, pk=pk)
    if request.method == 'POST':
        form = SaldoInicialForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            try:
                invoice_service.registrar_saldo_inicial(
                    cliente, monto=cd['monto'], fecha=cd['fecha'],
                    notas=cd.get('notas', ''))
            except DjangoValidationError as e:
                form.add_error(None, e.messages[0])
            else:
                messages.success(request, 'Saldo inicial registrado.')
                return redirect('cliente_salidas', pk=cliente.pk)
    else:
        form = SaldoInicialForm(initial={'fecha': timezone.localdate()})
    return render(request, 'facturas/form_saldo_inicial.html', {
        'form': form, 'cliente': cliente,
        'saldo_inicial': invoice_service.saldo_inicial_de(cliente),
    })


@login_required
@permission_required(_perm('registrar_pago_factura'), raise_exception=True)
@facturas_enabled
@never_cache
def cliente_abono_nuevo(request, pk):
    cliente = get_object_or_404(Cliente, pk=pk)
    filas = payment_service.facturas_para_reparto(cliente)
    if request.method == 'POST':
        form = AbonoClienteForm(request.POST, request.FILES,
                                facturas=[(doc, saldo) for doc, saldo, _ in filas])
        if form.is_valid():
            cd = form.cleaned_data
            pago = payment_service.registrar_abono(
                cliente, fecha_pago=cd['fecha_pago'], metodo_pago=cd['metodo_pago'],
                monto=cd['monto'], referencia=cd.get('referencia', ''),
                comprobante=cd.get('comprobante'), notas=cd.get('notas', ''),
                aplicaciones=cd['aplicaciones'],
            )
            _send_event_later('abono_cliente_creado', {
                'pago_id': pago.pk,
                'cliente_id': cliente.pk,
                'cliente': cliente.nombre,
                'monto': str(pago.monto),
                'monto_aplicado': str(pago.monto_aplicado),
                'saldo_sin_aplicar': str(pago.saldo_sin_aplicar),
                'metodo_pago': pago.metodo_pago.nombre,
                'referencia': pago.referencia,
                'registrado_por': request.user.username,
                'aplicaciones': [
                    {
                        'documento_id': apl.documento_id,
                        'numero_documento': apl.documento.numero_documento,
                        'monto': str(apl.monto),
                    }
                    for apl in pago.aplicaciones.select_related('documento')
                ],
            })
            if _es_ajax(request):
                return JsonResponse({'ok': True, 'saldo': str(cliente.saldo_a_favor)})
            messages.success(request, 'Abono registrado.')
            return redirect('cliente_salidas', pk=cliente.pk)
        elif _es_ajax(request):
            return JsonResponse({'ok': False, 'errors': _form_errors_json(form)}, status=400)
    else:
        form = AbonoClienteForm(initial={'fecha_pago': timezone.localdate()})
    return render(request, _plantilla_abono(request), {
        'form': form, 'cliente': cliente,
        'pendientes': _filas_reparto(filas),
        'modo_edicion': False, 'pago': None,
        'action_url': reverse('cliente_abono_nuevo', args=[cliente.pk]),
        'titulo': 'Registrar abono', 'submit_label': 'Registrar abono',
    })


def _plantilla_abono(request):
    return 'facturas/_abono_fragment.html' if _es_ajax(request) else 'facturas/form_abono.html'


def _filas_reparto(filas):
    """Adapta las filas de `facturas_para_reparto` a lo que consume el template."""
    return [
        {'doc': doc, 'saldo': saldo, 'aplicado': aplicado or None}
        for doc, saldo, aplicado in filas
    ]


@login_required
@permission_required(_perm('registrar_pago_factura'), raise_exception=True)
@facturas_enabled
@never_cache
def cliente_abono_editar(request, pk):
    pago = get_object_or_404(Pago, pk=pk)
    cliente = pago.cliente
    # El saldo de cada factura se calcula como si este abono no existiera: las que él
    # mismo dejó en cero vuelven a mostrar su saldo completo, que es lo que se puede
    # redistribuir (editar_abono borra las aplicaciones antes de repartir de nuevo).
    filas = payment_service.facturas_para_reparto(cliente, pago=pago)

    if request.method == 'POST':
        form = AbonoClienteForm(request.POST, request.FILES,
                                facturas=[(doc, saldo) for doc, saldo, _ in filas])
        if form.is_valid():
            cd = form.cleaned_data
            payment_service.editar_abono(
                pago, fecha_pago=cd['fecha_pago'], metodo_pago=cd['metodo_pago'],
                monto=cd['monto'], referencia=cd.get('referencia', ''),
                comprobante=cd.get('comprobante'), notas=cd.get('notas', ''),
                aplicaciones=cd['aplicaciones'],
            )
            if _es_ajax(request):
                return JsonResponse({'ok': True, 'saldo': str(cliente.saldo_a_favor)})
            messages.success(request, 'Abono actualizado.')
            return redirect('cliente_salidas', pk=cliente.pk)
        elif _es_ajax(request):
            return JsonResponse({'ok': False, 'errors': _form_errors_json(form)}, status=400)
    else:
        form = AbonoClienteForm(initial={
            'fecha_pago': pago.fecha_pago, 'metodo_pago': pago.metodo_pago_id,
            'monto': pago.monto, 'referencia': pago.referencia, 'notas': pago.notas,
        })
    return render(request, _plantilla_abono(request), {
        'form': form, 'cliente': cliente,
        'pendientes': _filas_reparto(filas),
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


@login_required
@permission_required(_perm('gestionar_facturas'), raise_exception=True)
@facturas_enabled
@require_POST
def factura_identificar(request, pk):
    """Asigna el cliente real a un documento que la ingesta dejó sin identificar.

    Identificar el documento es la acción principal; guardar el alias es un efecto
    secundario. Si el alias falla, el documento se identifica igual y el aviso
    viaja en la respuesta: nunca se pierde la acción que importaba por culpa de la
    que no.
    """
    doc = get_object_or_404(DocumentoFactura.objects.select_related('cliente'), pk=pk)
    sin_identificar = clientes.cliente_sin_identificar()
    if doc.cliente_id != sin_identificar.pk:
        return JsonResponse({
            'ok': False,
            'errors': {'__all__': [f'Ya fue identificado como {doc.cliente.nombre}.']},
        }, status=409)

    # Django castea el pk a int al evaluar el queryset: un valor no numérico
    # (p. ej. 'abc') levantaría ValueError y reventaría como 500. Lo parseamos
    # a mano para que un pk inválido caiga en el mismo 400 que un pk vacío.
    cliente_id = request.POST.get('cliente') or ''
    try:
        cliente = Cliente.objects.filter(pk=int(cliente_id)).first()
    except (TypeError, ValueError):
        cliente = None
    if cliente is None:
        return JsonResponse(
            {'ok': False, 'errors': {'cliente': ['Elegí un cliente.']}}, status=400)
    if cliente.pk == sin_identificar.pk:
        return JsonResponse({
            'ok': False,
            'errors': {'cliente': ['Elegí un cliente real, no «Sin identificar».']},
        }, status=400)

    aviso = ''
    if request.POST.get('guardar_alias') == '1' and doc.cliente_sugerido:
        # El alias es un efecto secundario: cualquier falla (incluso una
        # inesperada) degrada a un aviso, nunca hace fracasar la identificación.
        try:
            _alias, error = clientes.crear_alias(cliente, doc.cliente_sugerido)
            aviso = error or ''
        except Exception:
            _log.exception('Fallo inesperado al crear alias para el cliente %s', cliente.pk)
            aviso = 'No se pudo guardar el alias; el documento se identificó igual.'

    doc.cliente = cliente
    campos = ['cliente', 'updated_at']
    # El documento entró bajo "Sin identificar", que nunca recibe vencimiento, así que
    # suele llegar sin él. Se calcula con el mismo guardia que usa invoice_service:
    # solo si está vacío, para no pisar una fecha del PDF ni una que puso una persona.
    if not doc.fecha_vencimiento:
        doc.fecha_vencimiento = invoice_service.calcular_vencimiento(cliente, doc.fecha_documento)
        campos.append('fecha_vencimiento')

    revisada = request.POST.get('marcar_revisado') == '1'
    if revisada:
        doc.estado_revision = 'revisada'
        campos.append('estado_revision')
    doc.save(update_fields=campos)

    # El documento cambió de cliente: puede corresponderle saldo a favor del real,
    # y su estado de pago depende del vencimiento que acabamos de calcular.
    payment_service.aplicar_saldo_a_favor(doc)
    status_service.actualizar_estado_pago(doc)

    return JsonResponse({
        'ok': True,
        'cliente_nombre': cliente.nombre,
        'revisada': revisada,
        'aviso': aviso,
    })
