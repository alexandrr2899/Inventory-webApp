"""Context processors de core."""
from django.conf import settings


def facturas_flags(request):
    """Expone el estado del módulo Facturas y el contador de pendientes de revisión."""
    enabled = getattr(settings, 'FACTURAS_MODULE_ENABLED', False)
    por_revisar = 0
    user = getattr(request, 'user', None)
    if enabled and user is not None and user.is_authenticated and user.has_perm('core.ver_facturas'):
        from .models import DocumentoFactura
        por_revisar = DocumentoFactura.objects.filter(estado_revision='pendiente').count()
    return {
        'facturas_enabled': enabled,
        'facturas_por_revisar': por_revisar,
    }
