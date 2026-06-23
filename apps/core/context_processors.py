"""Context processors de core."""
from django.conf import settings


def facturas_flags(request):
    """Expone el estado del módulo Facturas a todas las plantillas."""
    return {
        'facturas_enabled': getattr(settings, 'FACTURAS_MODULE_ENABLED', False),
    }
