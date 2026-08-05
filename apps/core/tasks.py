"""Tareas Celery: Web Push, facturas vencidas, backup programado y pigmentos."""
import json
import logging
from datetime import timedelta
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

# Reintentos por defecto para tareas disparadas por beat o por eventos: sin
# esto, un hipo transitorio de DB o Redis descarta la tarea en silencio y la
# alerta simplemente nunca llega. `acks_late` hace que una tarea interrumpida
# por un worker caído se vuelva a encolar en lugar de perderse; los duplicados
# que eso pueda causar los colapsa el `tag` de la notificación en el navegador.
RETRY_KWARGS = {
    'autoretry_for': (Exception,),
    'max_retries': 3,
    'retry_backoff': 30,
    'retry_backoff_max': 300,
    'retry_jitter': True,
    'acks_late': True,
}


@shared_task(**RETRY_KWARGS)
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


@shared_task(**RETRY_KWARGS)
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


@shared_task(**RETRY_KWARGS)
def flush_count_web_push(conteo_id):
    """Agrupa los ajustes aplicados al mismo conteo en una sola notificación."""
    count_key = f'webpush:conteo:{conteo_id}:ajustes'
    payload_key = f'webpush:conteo:{conteo_id}:payload'
    lock_key = f'webpush:conteo:{conteo_id}:scheduled'
    count = int(cache.get(count_key, 0) or 0)
    payload = cache.get(payload_key, {}) or {}
    cache.delete_many([count_key, payload_key, lock_key])
    if count <= 0:
        return 0
    payload = dict(payload)
    payload['conteo_id'] = conteo_id
    payload['ajustes_aplicados'] = count
    return fanout_web_push('count_difference', payload)


def _reserve_scheduled_event(key, event_type):
    try:
        with transaction.atomic():
            WebPushScheduledEvent.objects.create(key=key, event_type=event_type)
        return True
    except IntegrityError:
        return False


@shared_task(**RETRY_KWARGS)
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


@shared_task(**RETRY_KWARGS)
def notify_pigment_coverage(dias_analisis=30, dias_objetivo=14):
    """
    Avisa qué pigmentos se van a acabar antes de `dias_objetivo`.

    El reporte de consumo ya proyectaba los días de cobertura, pero solo
    cuando alguien lo abría a mano. Esto lo vuelve proactivo: una vez por día,
    y solo si hay pigmentos en estado crítico o bajo.
    """
    from .services.notifications import send_event
    from .services.pigmentos import calcular_cobertura, payload_cobertura

    hoy = timezone.localdate()
    fecha_inicio = hoy - timedelta(days=dias_analisis)

    resultados, _ = calcular_cobertura(
        fecha_inicio, hoy, dias_objetivo=dias_objetivo)
    payload = payload_cobertura(resultados, fecha_inicio, hoy, dias_objetivo)

    # Sin pigmentos en riesgo no se consume la clave diaria: si el stock cae
    # más tarde ese mismo día, la alerta todavía puede salir.
    if not payload['pigmentos']:
        return {'enviado': False, 'en_riesgo': 0}

    if not _reserve_scheduled_event(
        f'cobertura_pigmentos:{hoy.isoformat()}', 'pigmentos_cobertura'
    ):
        return {'enviado': False, 'en_riesgo': len(payload['pigmentos'])}

    log.info(
        '[EVENT] pigmentos_cobertura criticos=%s bajos=%s',
        payload['total_criticos'], payload['total_bajos'],
    )
    send_event('pigmentos_cobertura', payload)
    return {'enviado': True, 'en_riesgo': len(payload['pigmentos'])}


# El límite global (CELERY_TASK_TIME_LIMIT=60s) mataría un pg_dump a mitad y
# dejaría un .sql.gz truncado. El script ya se autolimita con
# BACKUP_TIMEOUT_SECONDS (300s por defecto); este techo queda por encima.
@shared_task(time_limit=1800, soft_time_limit=1500, **RETRY_KWARGS)
def scheduled_backup():
    """
    Backup automático de PostgreSQL.

    Hasta ahora el backup solo existía si un humano entraba al panel y hacía
    clic; sin esto, un descuido de una semana equivale a una semana sin
    respaldo. `ejecutar_backup` nunca levanta excepción — reporta el fallo por
    el evento `backup_fallido` — así que devolvemos el estado sin reintentar
    un pg_dump completo.
    """
    from .services.backups import ejecutar_backup

    resultado = ejecutar_backup(usuario=None, origen='programado')
    return {
        'ok': resultado['ok'],
        'archivo': resultado['backup']['relative_path'] if resultado['backup'] else '',
        'mensaje': resultado['mensaje'],
    }
