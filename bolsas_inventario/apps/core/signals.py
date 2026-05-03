"""
Señales de seguridad para envío de eventos webhook.

Conectadas en CoreConfig.ready() (apps.py).
"""

import logging

from django.contrib.auth.signals import user_login_failed
from django.dispatch import receiver

security_log = logging.getLogger('security')


def _ip_from_request(request):
    if request is None:
        return 'unknown'
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', 'unknown')


# ── Login fallido ─────────────────────────────────────────────────────────────

@receiver(user_login_failed)
def on_login_failed(sender, credentials, request, **kwargs):
    from .services.notifications import send_security_event

    username   = credentials.get('username', '') if credentials else ''
    ip         = _ip_from_request(request)
    path       = request.path if request else '/login/'
    user_agent = request.META.get('HTTP_USER_AGENT', '')[:200] if request else ''

    send_security_event(
        'failed_login',
        title    = '⚠️ Intento de login fallido',
        user     = username,
        ip       = ip,
        path     = path,
        user_agent = user_agent,
        message  = f'Credenciales incorrectas para "{username}" desde {ip}',
    )


# ── Bloqueo por brute-force (django-axes) ────────────────────────────────────

def on_axes_lockout(request, credentials, *args, **kwargs):
    """
    Conectada manualmente en apps.py porque axes usa su propio sistema
    de señales (no django.dispatch estándar en todas las versiones).
    """
    from .services.notifications import send_security_event

    username   = credentials.get('username', '') if credentials else ''
    ip         = _ip_from_request(request)
    path       = request.path if request else '/login/'
    user_agent = request.META.get('HTTP_USER_AGENT', '')[:200] if request else ''

    send_security_event(
        'axes_lockout',
        title    = '🔒 IP bloqueada por múltiples intentos fallidos',
        user     = username,
        ip       = ip,
        path     = path,
        user_agent = user_agent,
        message  = f'IP {ip} bloqueada tras superar el límite de intentos fallidos',
    )
