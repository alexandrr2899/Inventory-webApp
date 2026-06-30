"""metodos_pago.py — CRUD de métodos de pago."""
from .common import *  # noqa: F401,F403

from ..models import MetodoPago
from ..forms import MetodoPagoForm


@login_required
@permission_required(_perm('gestionar_metodos_pago'), raise_exception=True)
def metodo_pago_lista(request):
    metodos = MetodoPago.objects.all()
    return render(request, 'metodos_pago/lista.html', {'metodos': metodos})


@login_required
@permission_required(_perm('gestionar_metodos_pago'), raise_exception=True)
def metodo_pago_crear(request):
    if request.method == 'POST':
        form = MetodoPagoForm(request.POST)
        if form.is_valid():
            m = form.save()
            messages.success(request, f'Método "{m.nombre}" creado.')
            return redirect('metodo_pago_lista')
    else:
        form = MetodoPagoForm()
    return render(request, 'metodos_pago/form.html', {'form': form, 'titulo': 'Nuevo método de pago'})


@login_required
@permission_required(_perm('gestionar_metodos_pago'), raise_exception=True)
def metodo_pago_editar(request, pk):
    metodo = get_object_or_404(MetodoPago, pk=pk)
    if request.method == 'POST':
        form = MetodoPagoForm(request.POST, instance=metodo)
        if form.is_valid():
            form.save()
            messages.success(request, f'Método "{metodo.nombre}" actualizado.')
            return redirect('metodo_pago_lista')
    else:
        form = MetodoPagoForm(instance=metodo)
    return render(request, 'metodos_pago/form.html', {
        'form': form, 'titulo': f'Editar: {metodo.nombre}', 'metodo': metodo})


@login_required
@permission_required(_perm('gestionar_metodos_pago'), raise_exception=True)
@require_POST
def metodo_pago_toggle_activo(request, pk):
    metodo = get_object_or_404(MetodoPago, pk=pk)
    metodo.activo = not metodo.activo
    metodo.save(update_fields=['activo'])
    messages.success(request, f'Método "{metodo.nombre}" {"activado" if metodo.activo else "desactivado"}.')
    return redirect('metodo_pago_lista')
