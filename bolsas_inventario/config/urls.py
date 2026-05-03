from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django.views.generic import TemplateView
from django.http import Http404
from decouple import config

# URL del panel admin leída del entorno — nunca exponer la ruta real en código.
# En .env: ADMIN_URL=mi-ruta-secreta/  (con barra final, sin /)
_ADMIN_URL = config('ADMIN_URL', default='gestion-interna/')


def _admin_not_found(request):
    """Devuelve 404 para cualquier acceso a /admin/ — evita fingerprinting."""
    raise Http404


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
