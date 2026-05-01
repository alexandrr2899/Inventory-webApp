from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django.views.generic import TemplateView

urlpatterns = [
    path('admin/', admin.site.urls),
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
