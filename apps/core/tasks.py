"""Tareas Celery para entrega Web Push y facturas vencidas."""
import json
import logging
from decimal import Decimal

from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import (
    DocumentoFactura, WebPushScheduledEvent, WebPushSubscription,
)
from .services.web_push import (
    event_notification, user_can_receive_category, web_push_configured,
)

log = logging.getLogger('events')


@shared_task
def fanout_web_push(event_type, payload):
    notification = event_notification(event_type, payload)
    if not notification or not web_push_configured():
        return 0
    subscriptions = WebPushSubscription.objects.select_related('user').all()
    count = 0
    for subscription in subscriptions:
        if user_can_receive_category(subscription.user, notification['category']):
            deliver_web_push.delay(subscription.pk, notification)
            count += 1
    return count


@shared_task(bind=True, max_retries=3)
def deliver_web_push(self, subscription_id, notification):
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        log.error('[WEBPUSH] pywebpush no está instalado')
        return False

    try:
        subscription = WebPushSubscription.objects.get(pk=subscription_id)
    except WebPushSubscription.DoesNotExist:
        return False

    info = {
        'endpoint': subscription.endpoint,
        'keys': {'p256dh': subscription.p256dh, 'auth': subscription.auth},
    }
    try:
        webpush(
            subscription_info=info,
            data=json.dumps(notification, ensure_ascii=False),
            vapid_private_key=settings.VAPID_PRIVATE_KEY,
            vapid_claims={'sub': settings.VAPID_SUBJECT},
            timeout=8,
        )
    except WebPushException as exc:
        status = getattr(getattr(exc, 'response', None), 'status_code', None)
        if status in (404, 410):
            subscription.delete()
            return False
        subscription.last_error = str(exc)[:300]
        subscription.save(update_fields=['last_error', 'updated_at'])
        raise self.retry(exc=exc, countdown=30 * (2 ** self.request.retries))
    except Exception as exc:
        subscription.last_error = str(exc)[:300]
        subscription.save(update_fields=['last_error', 'updated_at'])
        raise self.retry(exc=exc, countdown=30 * (2 ** self.request.retries))

    subscription.last_success_at = timezone.now()
    subscription.last_error = ''
    subscription.save(update_fields=['last_success_at', 'last_error', 'updated_at'])
    return True


@shared_task
def flush_security_web_push(event_type):
    count_key = f'webpush:security:{event_type}:count'
    payload_key = f'webpush:security:{event_type}:payload'
    lock_key = f'webpush:security:{event_type}:scheduled'
    count = int(cache.get(count_key, 0) or 0)
    payload = cache.get(payload_key, {}) or {}
    cache.delete_many([count_key, payload_key, lock_key])
    if count > 1:
        payload = dict(payload)
        payload['title'] = f'{count} alertas de seguridad'
        payload['message'] = (
            f'Se agruparon {count} eventos «{event_type}». '
            f'Último: {payload.get("message", "")}'
        )
    return fanout_web_push(event_type, payload)


def _reserve_scheduled_event(key, event_type):
    try:
        with transaction.atomic():
            WebPushScheduledEvent.objects.create(key=key, event_type=event_type)
        return True
    except IntegrityError:
        return False


@shared_task
def notify_overdue_invoices():
    """Envía un único resumen diario de documentos vencidos, una vez por fecha."""
    if not web_push_configured():
        return {'individuales': 0, 'resumen': False}
    today = timezone.localdate()
    qs = DocumentoFactura.anotar_pagado(
        DocumentoFactura.objects.select_related('cliente').filter(
            estado_pago__in=['pendiente', 'vencida'],
            fecha_vencimiento__lt=today,
        )
    )
    overdue = [doc for doc in qs if doc.saldo_pendiente > 0]

    # No generar ruido (ni consumir la clave diaria) cuando no hay deuda vencida.
    if not overdue:
        return {'individuales': 0, 'resumen': False}

    summary_key = f'resumen_facturas_vencidas:{today.isoformat()}'
    summary_sent = _reserve_scheduled_event(
        summary_key, 'resumen_facturas_vencidas')
    if summary_sent:
        total = sum((doc.saldo_pendiente for doc in overdue), Decimal('0'))
        fanout_web_push.delay('resumen_facturas_vencidas', {
            'fecha': today.isoformat(),
            'cantidad': len(overdue),
            'clientes': len({doc.cliente_id for doc in overdue}),
            'saldo_total': str(total),
        })
    return {'individuales': 0, 'resumen': summary_sent}
