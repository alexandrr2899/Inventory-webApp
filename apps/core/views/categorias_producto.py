"""categorias_producto.py — CRUD de categorías de producto."""
from .common import *  # noqa: F401,F403

from ..models import CategoriaProducto
from ..forms import CategoriaProductoForm


@login_required
@permission_required(_perm('gestionar_categorias_producto'), raise_exception=True)
def categoria_producto_lista(request):
    categorias = CategoriaProducto.objects.all()
    return render(request, 'categorias_producto/lista.html', {'categorias': categorias})


@login_required
@permission_required(_perm('gestionar_categorias_producto'), raise_exception=True)
def categoria_producto_crear(request):
    if request.method == 'POST':
        form = CategoriaProductoForm(request.POST)
        if form.is_valid():
            c = form.save()
            messages.success(request, f'Categoría "{c.nombre}" creada.')
            return redirect('categoria_producto_lista')
    else:
        form = CategoriaProductoForm()
    return render(request, 'categorias_producto/form.html',
                  {'form': form, 'titulo': 'Nueva categoría de producto'})


@login_required
@permission_required(_perm('gestionar_categorias_producto'), raise_exception=True)
def categoria_producto_editar(request, pk):
    categoria = get_object_or_404(CategoriaProducto, pk=pk)
    if request.method == 'POST':
        form = CategoriaProductoForm(request.POST, instance=categoria)
        if form.is_valid():
            categoria = form.save()
            messages.success(request, f'Categoría "{categoria.nombre}" actualizada.')
            return redirect('categoria_producto_lista')
    else:
        form = CategoriaProductoForm(instance=categoria)
    return render(request, 'categorias_producto/form.html',
                  {'form': form, 'titulo': f'Editar: {categoria.nombre}', 'categoria': categoria})


@login_required
@permission_required(_perm('gestionar_categorias_producto'), raise_exception=True)
@require_POST
def categoria_producto_toggle_activo(request, pk):
    categoria = get_object_or_404(CategoriaProducto, pk=pk)
    categoria.activa = not categoria.activa
    categoria.save(update_fields=['activa'])
    messages.success(request, f'Categoría "{categoria.nombre}" {"activada" if categoria.activa else "desactivada"}.')
    return redirect('categoria_producto_lista')
