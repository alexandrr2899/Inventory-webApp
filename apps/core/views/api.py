"""api.py — Endpoints JSON internos."""
from .common import *  # noqa: F401,F403


# ─── API ──────────────────────────────────────────────────────────────────────

@login_required
@permission_required(_perm('editar_item'), raise_exception=True)
@require_POST
def api_categoria_nueva(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    try:
        data = json.loads(request.body)
        nombre = data.get('nombre', '').strip()
        if not nombre:
            return JsonResponse({'error': 'Nombre requerido'}, status=400)
        cat, created = Categoria.objects.get_or_create(nombre=nombre)
        return JsonResponse({'id': cat.pk, 'nombre': cat.nombre, 'created': created})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@login_required
def api_item_info(request, pk):
    item = get_object_or_404(Item, pk=pk)
    stocks = Stock.objects.filter(item=item).select_related(
        'ubicacion', 'ubicacion__padre', 'ubicacion__padre__padre',
        'ubicacion__padre__padre__padre',
    )
    return JsonResponse({
        'tipo': item.tipo,
        'unidad_medida': item.unidad_medida,
        'stock_total': str(item.stock_total()),
        'stocks': [
            {'ubicacion_id': s.ubicacion_id, 'ubicacion': s.ubicacion.ruta_completa,
             'cantidad': str(s.cantidad_actual)}
            for s in stocks
        ]
    })
