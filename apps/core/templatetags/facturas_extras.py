"""Filtros de plantilla del módulo Facturas."""
from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def moneda(value):
    """Formatea un monto como 307,600.00 (coma miles, punto decimal), sin localización."""
    if value in (None, ''):
        return '0.00'
    try:
        return '{:,.2f}'.format(Decimal(str(value)))
    except (InvalidOperation, TypeError, ValueError):
        return value


# Paleta fija de clases Bootstrap para distinguir categorías por color. Como las
# categorías son configurables (no un choices fijo), el color se deriva del pk
# de forma determinística en vez de guardarse en el modelo.
_PALETA_CATEGORIAS = (
    'bg-primary',
    'bg-success',
    'bg-danger',
    'bg-warning text-dark',
    'bg-secondary',
    'bg-dark',
    'bg-info text-dark',
)


@register.filter
def categoria_badge_class(categoria):
    """Clase(s) Bootstrap para el badge de una CategoriaProducto, estable por categoría."""
    if not categoria or not categoria.pk:
        return 'bg-secondary'
    return _PALETA_CATEGORIAS[categoria.pk % len(_PALETA_CATEGORIAS)]
