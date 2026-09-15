import logging

from django.contrib.auth.signals import user_login_failed
from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from .models import AplicacionPago, Gasto
from .net import get_client_ip
from .services.facturas import status_service


@receiver(post_save, sender=AplicacionPago)
def _aplicacion_guardada(sender, instance, **kwargs):
    status_service.actualizar_estado_pago(instance.documento)


@receiver(post_delete, sender=AplicacionPago)
def _aplicacion_borrada(sender, instance, **kwargs):
    from .models import DocumentoFactura
    if DocumentoFactura.objects.filter(pk=instance.documento_id).exists():
        status_service.actualizar_estado_pago(instance.documento)


def _borrar_archivo_al_confirmar(storage, name):
    if name:
        transaction.on_commit(lambda: storage.delete(name))


@receiver(pre_save, sender=Gasto)
def _limpiar_comprobante_reemplazado(sender, instance, **kwargs):
    if not instance.pk:
        return
    anterior = sender.objects.filter(pk=instance.pk).only('comprobante').first()
    if anterior and anterior.comprobante and anterior.comprobante.name != instance.comprobante.name:
        instance._comprobante_anterior = (
            anterior.comprobante.storage, anterior.comprobante.name,
        )


@receiver(post_save, sender=Gasto)
def _confirmar_limpieza_comprobante_reemplazado(sender, instance, **kwargs):
    anterior = getattr(instance, '_comprobante_anterior', None)
    if anterior:
        _borrar_archivo_al_confirmar(*anterior)
        del instance._comprobante_anterior


@receiver(post_delete, sender=Gasto)
def _limpiar_comprobante_eliminado(sender, instance, **kwargs):
    if instance.comprobante:
        _borrar_archivo_al_confirmar(instance.comprobante.storage, instance.comprobante.name)

security_log = logging.getLogger('security')


def _ip_from_request(request):
    if request is None:
        return 'N/A'
    return get_client_ip(request)


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
