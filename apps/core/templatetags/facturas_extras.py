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
