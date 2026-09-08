"""Panel autenticado de salud de dependencias y procesos operativos."""
from datetime import timedelta
import os

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.shortcuts import render
from django.utils import timezone
from redis import Redis

from ..models import BackupJob, DocumentoFactura, SystemHeartbeat, WebPushScheduledEvent
from ..services.backups import listar_backups
from .common import login_required, _perm, _timed_view


def _check(nombre, estado, detalle, *, checked_at=None):
    return {
        'nombre': nombre,
        'estado': estado,
        'detalle': detalle,
        'checked_at': checked_at or timezone.now(),
    }


def _age_label(value):
    if value is None:
        return 'sin registro'
    seconds = max(0, int((timezone.now() - value).total_seconds()))
    if seconds < 120:
        return f'hace {seconds} s'
    if seconds < 7200:
        return f'hace {seconds // 60} min'
    return f'hace {seconds // 3600} h'


def collect_operational_health():
    checks = []

    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
        checks.append(_check('Base de datos', 'ok', 'PostgreSQL responde.'))
    except Exception:
        checks.append(_check('Base de datos', 'error', 'PostgreSQL no responde.'))

    cache_key = f'health-panel:{os.getpid()}'
    try:
        cache.set(cache_key, 'ok', 10)
        cache_ok = cache.get(cache_key) == 'ok'
        cache.delete(cache_key)
        if not cache_ok:
            raise RuntimeError('lectura inconsistente')
        checks.append(_check('Redis caché', 'ok', 'Lectura y escritura correctas.'))
    except Exception:
        checks.append(_check('Redis caché', 'error', 'No se pudo escribir y leer la caché.'))

    try:
        broker = Redis.from_url(settings.CELERY_BROKER_URL, socket_timeout=2)
        broker.ping()
        queued = broker.llen('celery')
        warning_limit = getattr(settings, 'CELERY_QUEUE_WARNING_SIZE', 100)
        checks.append(_check(
            'Cola Celery', 'warning' if queued >= warning_limit else 'ok',
            f'{queued} tarea(s) pendiente(s).',
        ))
    except Exception:
        checks.append(_check(
            'Cola Celery', 'error', 'El broker de tareas no responde.'))

    heartbeat = SystemHeartbeat.objects.filter(name='celery').first()
    heartbeat_limit = timezone.now() - timedelta(minutes=3)
    if heartbeat and heartbeat.last_seen_at >= heartbeat_limit:
        checks.append(_check(
            'Celery beat + worker', 'ok',
            f'Último latido {_age_label(heartbeat.last_seen_at)}.',
            checked_at=heartbeat.last_seen_at,
        ))
    else:
        checks.append(_check(
            'Celery beat + worker', 'error',
            f'No hay un latido reciente ({_age_label(heartbeat.last_seen_at if heartbeat else None)}).',
            checked_at=heartbeat.last_seen_at if heartbeat else None,
        ))

    latest_success = BackupJob.objects.filter(estado='exitoso').first()
    backup_limit = timezone.now() - timedelta(
        hours=getattr(settings, 'BACKUP_HEALTH_MAX_HOURS', 30))
    if latest_success and latest_success.fecha_fin and latest_success.fecha_fin >= backup_limit:
        checks.append(_check(
            'Backup local', 'ok',
            f'Último respaldo {_age_label(latest_success.fecha_fin)}.',
            checked_at=latest_success.fecha_fin,
        ))
    else:
        checks.append(_check(
            'Backup local', 'warning',
            f'No hay respaldo exitoso reciente ({_age_label(latest_success.fecha_fin if latest_success else None)}).',
            checked_at=latest_success.fecha_fin if latest_success else None,
        ))

    hook_configured = bool((os.environ.get('BACKUP_POST_HOOK') or '').strip())
    if not hook_configured:
        checks.append(_check(
            'Copia externa', 'warning', 'BACKUP_POST_HOOK no está configurado.'))
    elif latest_success and latest_success.copia_externa == 'exitosa':
        checks.append(_check(
            'Copia externa', 'ok',
            f'Última copia {_age_label(latest_success.fecha_copia_externa)}.',
            checked_at=latest_success.fecha_copia_externa,
        ))
    else:
        checks.append(_check(
            'Copia externa', 'error', 'El último respaldo no llegó al destino externo.'))

    failed_events = WebPushScheduledEvent.objects.exclude(last_error='').count()
    checks.append(_check(
        'Eventos programados', 'warning' if failed_events else 'ok',
        f'{failed_events} evento(s) con error.' if failed_events else 'Sin errores de encolado.',
    ))

    ingest_error = SystemHeartbeat.objects.filter(name='ingest_error').first()
    ingest_success = SystemHeartbeat.objects.filter(name='ingest_success').first()
    unresolved_ingest = (
        ingest_error
        and (not ingest_success or ingest_error.last_seen_at > ingest_success.last_seen_at)
    )
    checks.append(_check(
        'Ingesta automática', 'warning' if unresolved_ingest else 'ok',
        ('El último intento no pudo procesarse.' if unresolved_ingest else
         f'Sin fallos pendientes; último éxito {_age_label(ingest_success.last_seen_at if ingest_success else None)}.'),
        checked_at=(ingest_error.last_seen_at if unresolved_ingest else
                    ingest_success.last_seen_at if ingest_success else None),
    ))

    restore_test = SystemHeartbeat.objects.filter(name='restore_test').first()
    restore_limit = timezone.now() - timedelta(
        days=getattr(settings, 'RESTORE_TEST_MAX_DAYS', 90))
    restore_ok = restore_test and restore_test.last_seen_at >= restore_limit
    checks.append(_check(
        'Prueba de restauración', 'ok' if restore_ok else 'warning',
        (f'Verificada {_age_label(restore_test.last_seen_at)}.' if restore_ok else
         f'No hay una prueba reciente ({_age_label(restore_test.last_seen_at if restore_test else None)}).'),
        checked_at=restore_test.last_seen_at if restore_test else None,
    ))

    integrations = [
        ('Ingesta de facturas', bool(settings.FACTURAS_INGEST_TOKEN)),
        ('API de Jaime', bool(settings.JAIME_API_TOKEN)),
        ('Webhook n8n', bool(settings.N8N_WEBHOOK_URL)),
        ('Web Push', all((settings.VAPID_PUBLIC_KEY, settings.VAPID_PRIVATE_KEY, settings.VAPID_SUBJECT))),
    ]

    severity = {'ok': 0, 'warning': 1, 'error': 2}
    overall = max(checks, key=lambda row: severity[row['estado']])['estado']
    return {
        'checks': checks,
        'overall': overall,
        'integrations': integrations,
        'latest_job': BackupJob.objects.first(),
        'backup_count': len(listar_backups()),
        'ingest_errors': DocumentoFactura.objects.filter(
            estado_revision='error').count(),
        'generated_at': timezone.now(),
    }


@login_required
@_timed_view('operational_health')
def operational_health(request):
    if not (request.user.is_superuser or request.user.has_perm(
            _perm('ver_salud_operativa'))):
        raise PermissionDenied
    return render(request, 'salud/operativa.html', collect_operational_health())
