"""Web Push: catálogo de eventos, elegibilidad y encolado tolerante a fallos."""
import logging
import json

from django.conf import settings
from django.core.cache import cache
from django.urls import reverse

from ..models import WebPushPreference

log = logging.getLogger('events')

CATEGORY_FIELDS = {
    'inventario': 'inventario',
    'operaciones': 'operaciones',
    'facturas': 'facturas',
    'backups': 'backups',
    'seguridad': 'seguridad',
}

EVENT_CATEGORIES = {
    'stock_zero': 'inventario',
    'stock_low': 'inventario',
    'pigmentos_resumen': 'inventario',
    'inventario_camiseta_actual': 'inventario',
    'inventario_pigmentos_actual': 'inventario',
    'reporte_stock_bajo': 'inventario',
    'production_created': 'operaciones',
    'conteo_creado': 'operaciones',
    'count_difference': 'operaciones',
    'reporte_produccion_dia': 'operaciones',
    'reporte_salidas_dia': 'operaciones',
    'backup_exitoso': 'backups',
    'backup_fallido': 'backups',
    'failed_login': 'seguridad',
    'axes_lockout': 'seguridad',
    'forbidden_403': 'seguridad',
    'server_error_500': 'seguridad',
    'pago_factura_creado': 'facturas',
    'abono_cliente_creado': 'facturas',
    'factura_vencida': 'facturas',
    'resumen_facturas_vencidas': 'facturas',
}

SECURITY_EVENTS = {
    'failed_login', 'axes_lockout', 'forbidden_403', 'server_error_500',
}


def web_push_configured():
    return bool(
        getattr(settings, 'VAPID_PUBLIC_KEY', '')
        and getattr(settings, 'VAPID_PRIVATE_KEY', '')
        and getattr(settings, 'VAPID_SUBJECT', '')
    )


def user_is_push_eligible(user):
    if not user or not user.is_authenticated or not user.is_active:
        return False
    return user.is_superuser or user.groups.filter(
        name__in=['Administrador', 'Supervisor']).exists()


def user_can_receive_category(user, category):
    if not user_is_push_eligible(user):
        return False
    if category == 'facturas' and not user.has_perm('core.ver_facturas'):
        return False
    if category == 'backups' and not user.has_perm('core.gestionar_backups'):
        return False
    if category == 'seguridad' and not (
        user.is_superuser or user.groups.filter(name='Administrador').exists()
    ):
        return False
    try:
        preference = user.web_push_preference
    except WebPushPreference.DoesNotExist:
        preference = WebPushPreference.objects.create(user=user)
    return bool(getattr(preference, CATEGORY_FIELDS[category]))


def _money(value):
    try:
        return f'L {float(value):,.2f}'
    except (TypeError, ValueError):
        return str(value or '')


def event_notification(event_type, payload):
    """Convierte un evento interno en el contenido compacto de una notificación."""
    category = EVENT_CATEGORIES.get(event_type)
    if not category:
        return None
    p = payload or {}
    title = p.get('titulo') or p.get('title') or 'Transformadora de Empaques'
    body = p.get('message') or p.get('mensaje') or ''
    url = '/'
    tag = event_type

    if event_type in ('stock_zero', 'stock_low'):
        zero = event_type == 'stock_zero'
        title = 'Stock agotado' if zero else 'Stock bajo'
        body = f'{p.get("item", "Ítem")}: {p.get("stock_actual", "0")} {p.get("unidad", "")}'.strip()
        if p.get('item_id'):
            url = reverse('item_detalle', args=[p['item_id']])
        else:
            url = reverse('inventario_lista')
        tag = f'stock-{p.get("item_id") or p.get("codigo", "")}'
    elif event_type == 'pigmentos_resumen':
        title = 'Resumen de pigmentos'
        body = f'{p.get("total_bajos", 0)} pigmento(s) con stock bajo o agotado.'
        url = reverse('reporte_stock_bajo')
    elif event_type in ('inventario_camiseta_actual', 'inventario_pigmentos_actual',
                        'reporte_stock_bajo'):
        title = p.get('titulo') or 'Reporte de inventario'
        body = f'Enviado por {p.get("enviado_por", "el sistema")}.'
        url = reverse('notificaciones_panel')
    elif event_type == 'production_created':
        title = 'Producción registrada'
        body = f'{p.get("cantidad", "")} de {p.get("item", "producto")} · {p.get("ubicacion", "")}'.strip(' ·')
        url = reverse('produccion_nueva')
    elif event_type == 'conteo_creado':
        title = f'Conteo registrado · {p.get("tipo_conteo", "Conteo")}'
        cantidad = int(p.get('items_contados', 0) or 0)
        items_label = 'ítem' if cantidad == 1 else 'ítems'
        body = (
            f'{cantidad} {items_label} · {p.get("turno", "")} '
            f'· {p.get("usuario", "")}'
        ).strip(' ·')
        url = reverse('conteo_conciliar', args=[p['conteo_id']])
        tag = f'conteo-{p.get("conteo_id")}-creado'
    elif event_type == 'count_difference':
        cantidad = int(p.get('ajustes_aplicados', 1) or 1)
        ajustes_label = 'ajuste aplicado' if cantidad == 1 else 'ajustes aplicados'
        title = f'Ajustes de conteo #{p.get("conteo_id", "")}'.rstrip('#')
        contexto = ' · '.join(filter(None, [
            p.get('tipo_conteo'), p.get('turno'), p.get('usuario'),
        ]))
        body = f'{cantidad} {ajustes_label}'
        if contexto:
            body = f'{body} · {contexto}'
        if p.get('conteo_id'):
            url = reverse('conteo_detalle', args=[p['conteo_id']])
        else:
            url = reverse('conteo_lista')
        tag = f'conteo-{p.get("conteo_id", "")}-ajustes'
    elif event_type in ('reporte_produccion_dia', 'reporte_salidas_dia'):
        title = p.get('titulo') or (
            'Producción del día' if event_type == 'reporte_produccion_dia'
            else 'Salidas del día')
        body = f'Reporte generado por {p.get("enviado_por", "el sistema")}.'
        url = reverse('notificaciones_panel')
    elif event_type.startswith('backup_'):
        ok = event_type == 'backup_exitoso'
        title = 'Backup completado' if ok else 'Falló el backup'
        body = p.get('archivo') if ok else p.get('mensaje', 'Revisá los logs del servidor.')
        url = reverse('backups_panel')
    elif event_type in SECURITY_EVENTS:
        title = p.get('title') or 'Alerta de seguridad'
        body = p.get('message') or p.get('path') or 'Revisá el evento de seguridad.'
        url = reverse('alertas_centro')
    elif event_type == 'pago_factura_creado':
        title = f'Pago recibido · {_money(p.get("monto"))}'
        body = f'{p.get("cliente", "Cliente")} · {p.get("metodo_pago", "")}'.strip(' ·')
        url = reverse('factura_detalle', args=[p['documento_id']])
        tag = f'pago-{p.get("pago_id")}'
    elif event_type == 'abono_cliente_creado':
        title = f'Abono recibido · {_money(p.get("monto"))}'
        body = f'{p.get("cliente", "Cliente")} · {p.get("metodo_pago", "")}'.strip(' ·')
        url = reverse('cliente_salidas', args=[p['cliente_id']])
        tag = f'abono-{p.get("pago_id")}'
    elif event_type == 'factura_vencida':
        title = f'Factura vencida · {p.get("numero_documento") or "sin número"}'
        body = f'{p.get("cliente", "Cliente")} · saldo {_money(p.get("saldo"))}'
        url = reverse('factura_detalle', args=[p['documento_id']])
        tag = f'factura-vencida-{p.get("documento_id")}'
    elif event_type == 'resumen_facturas_vencidas':
        title = 'Resumen de facturas vencidas'
        cantidad = int(p.get('cantidad', 0) or 0)
        clientes = int(p.get('clientes', 0) or 0)
        documentos_label = 'documento' if cantidad == 1 else 'documentos'
        clientes_label = 'cliente' if clientes == 1 else 'clientes'
        body = (
            f'{cantidad} {documentos_label} de {clientes} {clientes_label} '
            f'· saldo {_money(p.get("saldo_total"))}'
        )
        url = f'{reverse("facturas_lista")}?estado=vencida'
        tag = f'facturas-vencidas-{p.get("fecha", "")}'

    return {
        'event_type': event_type,
        'category': category,
        'title': str(title)[:120],
        'body': str(body)[:240],
        'url': url,
        'tag': tag[:120],
        'icon': '/static/icons/icon-192.png',
        'badge': '/static/icons/icon-192.png',
    }


def enqueue_web_push(event_type, payload):
    """Encola Web Push sin propagar nunca errores al canal webhook."""
    if not web_push_configured() or event_type not in EVENT_CATEGORIES:
        return False
    try:
        from ..tasks import (
            fanout_web_push, flush_count_web_push, flush_security_web_push,
        )
        payload = json.loads(json.dumps(payload or {}, default=str))

        # El reporte automático posterior a la conciliación sigue llegando a
        # n8n/Telegram. En Web Push se omite porque el resumen de ajustes ya
        # representa la misma acción y evita dos avisos consecutivos.
        if (
            payload.get('origen') == 'conciliacion_automatica'
            and event_type in ('inventario_camiseta_actual', 'reporte_produccion_dia')
        ):
            return True

        # Los cambios de stock producidos por una conciliación se consultan en
        # el detalle enlazado desde el resumen del conteo. Los otros canales
        # conservan estas alertas, pero Web Push no muestra una por cada ítem.
        if (
            payload.get('movimiento') == 'ajuste'
            and event_type in ('stock_zero', 'stock_low', 'pigmentos_resumen')
        ):
            return True

        if event_type in SECURITY_EVENTS:
            count_key = f'webpush:security:{event_type}:count'
            payload_key = f'webpush:security:{event_type}:payload'
            lock_key = f'webpush:security:{event_type}:scheduled'
            try:
                cache.incr(count_key)
            except ValueError:
                cache.set(count_key, 1, timeout=600)
            cache.set(payload_key, payload, timeout=600)
            if cache.add(lock_key, True, timeout=360):
                flush_security_web_push.apply_async(args=[event_type], countdown=300)
        elif event_type == 'count_difference' and payload.get('conteo_id'):
            conteo_id = int(payload['conteo_id'])
            count_key = f'webpush:conteo:{conteo_id}:ajustes'
            payload_key = f'webpush:conteo:{conteo_id}:payload'
            lock_key = f'webpush:conteo:{conteo_id}:scheduled'
            try:
                incremento = max(int(payload.get('ajustes_aplicados', 1) or 1), 1)
            except (TypeError, ValueError):
                incremento = 1
            try:
                cache.incr(count_key, incremento)
            except ValueError:
                cache.set(count_key, incremento, timeout=600)
            cache.set(payload_key, payload, timeout=600)
            if cache.add(lock_key, True, timeout=90):
                flush_count_web_push.apply_async(args=[conteo_id], countdown=30)
        else:
            fanout_web_push.delay(event_type, payload)
        return True
    except Exception as exc:
        log.warning('[WEBPUSH] no se pudo encolar %s: %s', event_type, exc)
        return False
