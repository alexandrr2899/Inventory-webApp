"""metodos_pago.py — CRUD de métodos de pago y sus movimientos."""
from .common import *  # noqa: F401,F403

from ..models import MetodoPago, Pago
from ..forms import MetodoPagoForm


def _parse_fecha(raw, default):
    if not raw:
        return default
    try:
        return dt_datetime.strptime(raw, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return default


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
            metodo = form.save()
            messages.success(request, f'Método "{metodo.nombre}" actualizado.')
            return redirect('metodo_pago_lista')
    else:
        form = MetodoPagoForm(instance=metodo)
    return render(request, 'metodos_pago/form.html', {
        'form': form, 'titulo': f'Editar: {metodo.nombre}', 'metodo': metodo})


@login_required
@permission_required(_perm('gestionar_metodos_pago'), raise_exception=True)
def metodo_pago_movimientos(request, pk):
    """Lista los abonos (Pago) recibidos con este método, con total y filtro de fechas."""
    metodo = get_object_or_404(MetodoPago, pk=pk)
    hoy = timezone.localdate()
    hasta = _parse_fecha(request.GET.get('hasta'), hoy)
    desde = _parse_fecha(request.GET.get('desde'), hoy.replace(day=1))

    qs = (Pago.objects
          .filter(metodo_pago=metodo, fecha_pago__range=[desde, hasta])
          .select_related('cliente')
          .prefetch_related('aplicaciones__documento')
          .order_by('-fecha_pago', '-created_at'))

    total = qs.aggregate(s=Coalesce(
        Sum('monto'), Value(Decimal('0')),
        output_field=DecimalField(max_digits=12, decimal_places=2)))['s']

    paginator = Paginator(qs, 50)
    page = paginator.get_page(request.GET.get('page'))

    return render(request, 'metodos_pago/movimientos.html', {
        'metodo': metodo,
        'pagos': page,
        'page_obj': page,
        'total': total,
        'desde': desde,
        'hasta': hasta,
    })


@login_required
@permission_required(_perm('gestionar_metodos_pago'), raise_exception=True)
@require_POST
def metodo_pago_toggle_activo(request, pk):
    metodo = get_object_or_404(MetodoPago, pk=pk)
    metodo.activo = not metodo.activo
    metodo.save(update_fields=['activo'])
    messages.success(request, f'Método "{metodo.nombre}" {"activado" if metodo.activo else "desactivado"}.')
    return redirect('metodo_pago_lista')
