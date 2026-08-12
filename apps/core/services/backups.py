"""
Ejecución del backup de PostgreSQL y archivos media.

Compartido entre el panel web (apps/core/views/admin_ops.py) y la tarea
programada de Celery (apps/core/tasks.py:scheduled_backup) para que ambos
caminos produzcan exactamente el mismo artefacto y el mismo registro
BackupJob. Antes la lógica vivía solo en la vista, así que un backup solo
existía si alguien se acordaba de hacer clic.
"""
import logging
import os
import subprocess
from datetime import datetime as dt_datetime
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from ..models import BackupJob

event_log = logging.getLogger('events')


def backup_root():
    root_env = os.environ.get('BACKUP_ROOT')
    if root_env:
        return Path(root_env).resolve()
    base_dir = Path(os.environ.get('BACKUP_DIR', settings.BASE_DIR / 'backups'))
    return (base_dir / 'postgres').resolve()


def format_size(size):
    if size >= 1024 * 1024:
        return f'{size / (1024 * 1024):.1f} MB'
    if size >= 1024:
        return f'{size / 1024:.1f} KB'
    return f'{size} B'


def listar_backups():
    root = backup_root()
    if not root.exists():
        return []

    backups = []
    paths = list(root.glob('*.tar.gz')) + list(root.glob('*.sql.gz'))
    for path in sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True):
        stat = path.stat()
        backups.append({
            'filename': path.name,
            'relative_path': f'postgres/{path.name}',
            'created_at': timezone.localtime(
                dt_datetime.fromtimestamp(stat.st_mtime, tz=timezone.get_current_timezone())
            ),
            'size': stat.st_size,
            'size_label': format_size(stat.st_size),
            'estado': 'disponible' if stat.st_size > 0 else 'vacío',
        })
    return backups


def backup_env(root):
    env = os.environ.copy()
    env.update({
        'POSTGRES_HOST': env.get('POSTGRES_HOST') or env.get('DB_HOST') or 'db',
        'POSTGRES_PORT': env.get('POSTGRES_PORT') or env.get('DB_PORT') or '5432',
        'POSTGRES_DB': env.get('POSTGRES_DB') or env.get('DB_NAME') or 'bolsas_inventario',
        'POSTGRES_USER': env.get('POSTGRES_USER') or env.get('DB_USER') or 'bolsas_user',
        'POSTGRES_PASSWORD': env.get('POSTGRES_PASSWORD') or env.get('DB_PASSWORD') or '',
        'BACKUP_ROOT': str(root),
        'MEDIA_ROOT': str(settings.MEDIA_ROOT),
        'BACKUP_RETENTION_DAYS': env.get('BACKUP_RETENTION_DAYS', '14'),
    })
    return env


def verificar_integridad(path):
    """
    Comprueba que el archivo no esté corrupto ni truncado (`gzip -t`). En el
    formato completo también exige que exista `database.sql.gz` dentro del tar.

    Un backup que existe pero no se puede descomprimir es peor que no tener
    backup, porque da falsa confianza. Esto no valida que el SQL restaure
    correctamente — para eso hace falta el drill descrito en RESTORE.md — pero
    sí detecta el modo de falla más común (dump interrumpido a medias).
    """
    timeout = int(os.environ.get('BACKUP_TIMEOUT_SECONDS', '900'))
    try:
        result = subprocess.run(
            ['gzip', '-t', str(path)],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except Exception as exc:
        event_log.warning('[BACKUP] no se pudo verificar %s: %s', path.name, exc)
        return False, f'No se pudo verificar el archivo: {exc}'
    if result.returncode != 0:
        return False, (result.stderr or 'gzip -t falló').strip()[:300]

    if path.name.endswith('.tar.gz'):
        try:
            result = subprocess.run(
                ['tar', '-tzf', str(path), 'database.sql.gz'],
                capture_output=True, text=True, timeout=timeout, check=False,
            )
        except Exception as exc:
            return False, f'No se pudo inspeccionar el archivo: {exc}'
        if result.returncode != 0:
            return False, 'El backup no contiene database.sql.gz.'
    return True, ''


def _ejecutar_post_hook(path):
    """
    Copia fuera del host. Opcional y controlada por el operador vía
    BACKUP_POST_HOOK (ruta a un script que recibe el archivo como argv[1]).

    Sin esto el backup vive en el mismo disco que la base: si se pierde el
    host se pierden las dos cosas a la vez. Se ejecuta sin shell y su falla
    NO invalida el backup local, que ya está en disco y verificado.
    """
    hook = (os.environ.get('BACKUP_POST_HOOK') or '').strip()
    if not hook:
        return None

    hook_path = Path(hook)
    if not hook_path.exists():
        event_log.error('[BACKUP] BACKUP_POST_HOOK no existe: %s', hook)
        return False

    try:
        result = subprocess.run(
            [str(hook_path), str(path)],
            capture_output=True, text=True,
            timeout=int(os.environ.get('BACKUP_HOOK_TIMEOUT_SECONDS', '600')),
            check=False,
        )
    except Exception as exc:
        event_log.error('[BACKUP] post-hook falló para %s: %s', path.name, exc)
        return False

    if result.returncode != 0:
        event_log.error(
            '[BACKUP] post-hook returncode=%s stderr=%s',
            result.returncode, result.stderr[-1000:],
        )
        return False

    event_log.info('[BACKUP] copia externa completada para %s', path.name)
    return True


def ejecutar_backup(usuario=None, origen='manual'):
    """
    Corre el script de backup y registra el BackupJob correspondiente.

    `usuario=None` corresponde al backup programado (Celery). Devuelve un dict
    con `ok`, `job`, `backup` (metadatos del archivo) y `mensaje`.
    Nunca levanta excepción: los fallos se reportan en el dict y en el evento
    `backup_fallido`.
    """
    from .notifications import send_event

    job = BackupJob.objects.create(usuario=usuario)
    root = backup_root()
    script_path = (Path(settings.BASE_DIR) / 'scripts' / 'backup_postgres.sh').resolve()
    timeout = int(os.environ.get('BACKUP_TIMEOUT_SECONDS', '900'))
    actor = usuario.username if usuario else f'sistema ({origen})'
    before = {b['filename'] for b in listar_backups()}

    ok = False
    newest = None
    mensaje = ''

    try:
        if not script_path.exists():
            raise FileNotFoundError('Script de backup no encontrado.')

        root.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            ['sh', str(script_path)],
            cwd=str(settings.BASE_DIR),
            env=backup_env(root),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

        after = listar_backups()
        newest = next(
            (b for b in after if b['filename'] not in before),
            after[0] if after else None,
        )

        if result.returncode == 0 and newest and newest['size'] > 0:
            integro, detalle = verificar_integridad(root / newest['filename'])
            if integro:
                ok = True
            else:
                mensaje = f'El backup se generó pero está corrupto: {detalle}'
                event_log.error(
                    'backup_corrupto user=%s archivo=%s detalle=%s',
                    actor, newest['relative_path'], detalle,
                )
        else:
            mensaje = 'El backup no se pudo completar. Revisar logs del servidor.'
            event_log.error(
                'backup_failed user=%s returncode=%s stdout=%s stderr=%s',
                actor, result.returncode,
                result.stdout[-2000:], result.stderr[-2000:],
            )

        if ok:
            job.estado = 'exitoso'
            job.archivo = newest['relative_path']
            job.tamano = newest['size']
            event_log.info('[EVENT] backup_exitoso user=%s archivo=%s', actor, newest['relative_path'])
            _ejecutar_post_hook(root / newest['filename'])
            send_event('backup_exitoso', {
                'archivo': newest['relative_path'],
                'tamano': newest['size'],
                'usuario': actor,
                'origen': origen,
                'fecha': timezone.localtime().strftime('%Y-%m-%d'),
                'hora': timezone.localtime().strftime('%H:%M:%S'),
            })
        else:
            job.estado = 'fallido'
            job.mensaje_error = mensaje
            send_event('backup_fallido', {
                'usuario': actor,
                'origen': origen,
                'mensaje': mensaje or 'El proceso de backup finalizó con error.',
            })

    except subprocess.TimeoutExpired:
        mensaje = 'El backup excedió el tiempo máximo permitido.'
        job.estado = 'fallido'
        job.mensaje_error = mensaje
        event_log.error('backup_timeout user=%s timeout=%s', actor, timeout)
        send_event('backup_fallido', {
            'usuario': actor, 'origen': origen, 'mensaje': mensaje,
        })
    except Exception as exc:
        mensaje = 'No se pudo iniciar el backup.'
        job.estado = 'fallido'
        job.mensaje_error = mensaje
        event_log.exception('backup_exception user=%s error=%s', actor, exc)
        send_event('backup_fallido', {
            'usuario': actor, 'origen': origen, 'mensaje': mensaje,
        })
    finally:
        job.fecha_fin = timezone.now()
        job.save(update_fields=[
            'fecha_fin', 'estado', 'archivo', 'tamano', 'mensaje_error',
        ])

    return {'ok': ok, 'job': job, 'backup': newest if ok else None, 'mensaje': mensaje}
