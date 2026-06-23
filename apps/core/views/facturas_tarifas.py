"""facturas_tarifas.py — CRUD de tarifas por cliente."""
from .common import *  # noqa: F401,F403

from ..models import Cliente, TarifaCliente
from ..forms import TarifaClienteForm


@login_required
@permission_required(_perm('gestionar_tarifas'), raise_exception=True)
@facturas_enabled
def cliente_tarifas(request, pk):
    cliente = get_object_or_404(Cliente, pk=pk)
    if request.method == 'POST':
        form = TarifaClienteForm(request.POST)
        if form.is_valid():
            tarifa = form.save(commit=False)
            tarifa.cliente = cliente
            # Si se marca activa, desactivar otras activas del mismo producto.
            if tarifa.activa:
                TarifaCliente.objects.filter(
                    cliente=cliente, producto=tarifa.producto, activa=True,
                ).update(activa=False)
            tarifa.save()
            messages.success(request, 'Tarifa guardada.')
            return redirect('cliente_tarifas', pk=cliente.pk)
    else:
        form = TarifaClienteForm(initial={'fecha_inicio': timezone.localdate()})
    return render(request, 'facturas/tarifas.html', {
        'cliente': cliente,
        'form': form,
        'tarifas': cliente.tarifas.all(),
    })


@login_required
@permission_required(_perm('gestionar_tarifas'), raise_exception=True)
@facturas_enabled
@require_POST
def cliente_tarifa_toggle(request, pk):
    tarifa = get_object_or_404(TarifaCliente, pk=pk)
    if not tarifa.activa:
        TarifaCliente.objects.filter(
            cliente=tarifa.cliente, producto=tarifa.producto, activa=True,
        ).update(activa=False)
    tarifa.activa = not tarifa.activa
    tarifa.save(update_fields=['activa'])
    messages.success(request, 'Tarifa actualizada.')
    return redirect('cliente_tarifas', pk=tarifa.cliente_id)
