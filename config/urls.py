import logging
import os

from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django.views.generic import TemplateView
from django.http import Http404, HttpResponseForbidden, HttpResponseServerError
from django.template.loader import render_to_string
from decouple import config

from apps.core.net import get_client_ip as _get_client_ip

# URL del panel admin leída del entorno — nunca exponer la ruta real en código.
# En Portainer: ADMIN_URL=mi-ruta-secreta/  (sin / inicial, con / final)
def _normalize_admin_url(value):
    value = (value or 'gestion-interna/').strip().lstrip('/')
    if not value:
        value = 'gestion-interna/'
    if not value.endswith('/'):
        value = f'{value}/'
    return value


_ADMIN_URL = _normalize_admin_url(
    os.environ.get('ADMIN_URL') or config('ADMIN_URL', default='gestion-interna/')
)

security_log = logging.getLogger('security')


def _admin_not_found(request, *args, **kwargs):
    """Devuelve 404 para cualquier acceso a /admin/ — evita fingerprinting."""
    raise Http404


# ── Handlers globales de error ────────────────────────────────────────────────

def handler403(request, exception=None):
    """403 Forbidden — log + evento webhook + respuesta HTML."""
    from apps.core.services.notifications import send_security_event
    user = request.user.username if request.user.is_authenticated else 'anon'
    ip   = _get_client_ip(request)
    send_security_event(
        'forbidden_403',
        title      = '🚫 Acceso prohibido (403)',
        user       = user,
        ip         = ip,
        path       = request.path,
        user_agent = request.META.get('HTTP_USER_AGENT', '')[:200],
        message    = f'403 Forbidden — usuario={user} path={request.path}',
    )
    try:
        html = render_to_string('errors/403.html', request=request)
    except Exception:
        html = '<h1>403 — Acceso prohibido</h1>'
    return HttpResponseForbidden(html)


def handler500(request):
    """500 Internal Server Error — log + evento webhook + respuesta HTML."""
    from apps.core.services.notifications import send_security_event
    user = request.user.username if (hasattr(request, 'user') and request.user.is_authenticated) else 'anon'
    ip   = _get_client_ip(request)
    send_security_event(
        'server_error_500',
        title      = '🔥 Error interno del servidor (500)',
        user       = user,
        ip         = ip,
        path       = request.path,
        user_agent = request.META.get('HTTP_USER_AGENT', '')[:200],
        message    = f'500 Internal Server Error — usuario={user} path={request.path}',
    )
    try:
        html = render_to_string('errors/500.html')
    except Exception:
        html = '<h1>500 — Error interno</h1>'
    return HttpResponseServerError(html)


urlpatterns = [
    # Admin en ruta configurable (nunca /admin/).
    path(_ADMIN_URL, admin.site.urls),

    # Bloquear /admin/ con 404 para evitar que escáneres detecten Django.
    path('admin/', _admin_not_found),
    path('admin/<path:rest>', _admin_not_found),

    path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),

    # PWA — must be served from root scope
    path('manifest.json', TemplateView.as_view(
        template_name='manifest.json',
        content_type='application/manifest+json',
    ), name='manifest'),
    path('service-worker.js', TemplateView.as_view(
        template_name='service-worker.js',
        content_type='application/javascript',
    ), name='service_worker'),

    path('', include('apps.core.urls')),
]

# Registrar handlers de error (Django los busca en el ROOT_URLCONF)
handler403 = handler403  # noqa: F811
handler500 = handler500  # noqa: F811
