"""produccion.py — Registro de producción (entrada de PT)."""
from .common import *  # noqa: F401,F403
from .stock import *   # noqa: F401,F403


# ─── PRODUCCIÓN ───────────────────────────────────────────────────────────────

@login_required
@permission_required(_perm('registrar_produccion'), raise_exception=True)
def produccion_nueva(request):
    ubicaciones = Ubicacion.objects.all()

    if request.method == 'POST':
        form = ProduccionForm(request.POST)
        if form.is_valid():
            item = form.cleaned_data['item']
            cantidad = form.cleaned_data['cantidad']
            ubicacion = form.cleaned_data['ubicacion_destino']
            fecha_movimiento = form.cleaned_data['fecha_movimiento']
            motivo = form.cleaned_data.get('motivo', '') or f'Producción registrada'

            if timezone.is_naive(fecha_movimiento):
                fecha_movimiento = timezone.make_aware(fecha_movimiento)

            with transaction.atomic():
                mov_prod = MovimientoInventario.objects.create(
                    tipo_movimiento='entrada',
                    motivo=motivo,
                    fecha_movimiento=fecha_movimiento,
                    usuario=request.user,
                )
                det_prod = DetalleMovimiento.objects.create(
                    movimiento=mov_prod,
                    item=item,
                    cantidad=cantidad,
                    ubicacion_destino=ubicacion,
                )
                _aplicar_efecto_detalle(det_prod)

            send_event('production_created', {
                'item': item.nombre, 'codigo': item.codigo,
                'cantidad': str(cantidad), 'ubicacion': ubicacion.ruta_completa,
                'usuario': request.user.username,
                'fecha_movimiento': fecha_movimiento.isoformat(),
            })
            notify_stock(item, movimiento='produccion', usuario=request.user.username)

            messages.success(request, f'Producción registrada: {cantidad} {item.unidad_medida} de {item.nombre}.')
            return redirect('produccion_nueva')
    else:
        form = ProduccionForm(initial={
            'fecha_movimiento': timezone.localtime(timezone.now()).strftime('%Y-%m-%dT%H:%M'),
        })

    return render(request, 'produccion/form.html', {
        'form': form,
        'ubicaciones': ubicaciones,
    })
