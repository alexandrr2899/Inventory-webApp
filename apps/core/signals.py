import logging

from django.contrib.auth.signals import user_login_failed
from django.dispatch import receiver

security_log = logging.getLogger('security')


def _ip_from_request(request):
    if request is None:
        return 'N/A'
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', 'N/A')


@receiver(user_login_failed)
def on_login_failed(sender, credentials, request, **kwargs):
    try:
        from .services.notifications import send_security_event

        username   = (credentials.get('username', '') if credentials else '') or 'N/A'
        ip         = _ip_from_request(request)
        path       = request.path if request else '/login/'
        user_agent = request.META.get('HTTP_USER_AGENT', '')[:200] if request else ''

        security_log.warning('[SECURITY] failed_login user=%s ip=%s path=%s', username, ip, path)

        send_security_event(
            'failed_login',
            title      = '⚠️ Intento de login fallido',
            user       = username,
            ip         = ip,
            path       = path,
            user_agent = user_agent,
            message    = f'Credenciales incorrectas para "{username}" desde {ip}',
        )
    except Exception as exc:
        security_log.error('on_login_failed handler error: %s', exc)


def on_axes_lockout(sender=None, request=None, credentials=None,
                    username=None, ip_address=None, **kwargs):
    try:
        from .services.notifications import send_security_event

        if credentials:
            user = credentials.get('username', '') or username or 'N/A'
        else:
            user = username or 'N/A'

        ip = ip_address or _ip_from_request(request)

        path       = request.path       if request else '/login/'
        user_agent = request.META.get('HTTP_USER_AGENT', '')[:200] if request else ''

        security_log.warning('[SECURITY] axes_lockout user=%s ip=%s path=%s', user, ip, path)

        send_security_event(
            'axes_lockout',
            title      = '🔒 Bloqueo por intentos fallidos',
            user       = user,
            ip         = ip,
            path       = path,
            user_agent = user_agent,
            message    = f'IP/usuario bloqueado por múltiples intentos fallidos (user={user}, ip={ip})',
        )
    except Exception as exc:
        security_log.error('on_axes_lockout handler error: %s', exc)
