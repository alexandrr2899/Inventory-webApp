"""
Servicio de notificaciones via webhook HTTP.

Envia eventos estructurados a N8N_WEBHOOK_URL (u otro receptor).
Si la variable está vacía, todas las funciones son no-op: nunca rompen el flujo.

Estructura de cada POST:
{
    "event_type": "<tipo>",
    "source": "inventory_app",
    "timestamp": "2026-05-03T14:32:01.123456+00:00",
    "payload": { ... }
}
"""

import logging
from decimal import Decimal

import requests
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

event_log    = logging.getLogger('events')
security_log = logging.getLogger('security')

# ─────────────────────────────────────────────────────────────────────────────
# Emojis para pigmentos (coincidencia por substring, case-insensitive)
# ─────────────────────────────────────────────────────────────────────────────
_PIGMENTO_EMOJIS = [
    ('carbonato', '⚪'),
    ('slip',      '🧪'),
    ('azul',      '🔵'),
    ('rojo',      '🔴'),
    ('amarillo',  '🟡'),
    ('naranja',   '🟠'),
    ('negro',     '⚫'),
    ('blanco',    '⚪'),
]


def _emoji_pigmento(nombre: str) -> str:
    nombre_lower = nombre.lower()
    for keyword, emoji in _PIGMENTO_EMOJIS:
        if keyword in nombre_lower:
            return emoji
    return '📦'


# ─────────────────────────────────────────────────────────────────────────────
# Envío base
# ─────────────────────────────────────────────────────────────────────────────

def send_event(event_type: str, payload: dict) -> bool:
    """
    Envía un evento al webhook configurado en N8N_WEBHOOK_URL.
    - Silencioso: los errores se loguean pero NUNCA interrumpen la request.
    - Si N8N_WEBHOOK_URL está vacío, retorna False inmediatamente.
    """
    url = getattr(settings, 'N8N_WEBHOOK_URL', None)
    webhook_ok = False

    body = {
        'event_type': event_type,
        'source': 'inventory_app',
        'timestamp': timezone.localtime(timezone.now()).isoformat(),
        'payload': payload,
    }

    if url:
        try:
            resp = requests.post(url, json=body, timeout=5)
            resp.raise_for_status()
            webhook_ok = True
            event_log.info('[EVENT] %s enviado — status %s', event_type, resp.status_code)
        except requests.exceptions.ConnectionError:
            event_log.warning('[EVENT] %s — no se pudo conectar a %s', event_type, url)
        except requests.exceptions.Timeout:
            event_log.warning('[EVENT] %s — timeout (>5 s)', event_type)
        except requests.exceptions.HTTPError as exc:
            event_log.warning('[EVENT] %s — HTTP error: %s', event_type, exc)
        except Exception as exc:  # pragma: no cover
            event_log.warning('[EVENT] %s — error inesperado: %s', event_type, exc)

    # Canal independiente: una falla al encolar Web Push no altera jamás el
    # resultado histórico del webhook (usado por Telegram/n8n).
    try:
        from .web_push import enqueue_web_push
        enqueue_web_push(event_type, payload)
    except Exception as exc:  # pragma: no cover - defensa de integración
        event_log.warning('[WEBPUSH] error aislado al despachar %s: %s', event_type, exc)
    return webhook_ok


# Alias de compatibilidad para código anterior que llamaba send_n8n_event
send_n8n_event = send_event


# ─────────────────────────────────────────────────────────────────────────────
# Estado de alerta de stock (anti-spam)
# ─────────────────────────────────────────────────────────────────────────────
# Clave de caché por ítem: 'stock_alert_state_{pk}' → 'cero' | 'bajo' | 'normal'
# TTL de 25 horas → sobrevive un día de producción sin restart.
_CACHE_TTL = 60 * 60 * 25


def _estado_stock(stock_total: Decimal, stock_minimo: Decimal) -> str:
    if stock_total <= 0:
        return 'cero'
    if stock_minimo > 0 and stock_total <= stock_minimo:
        return 'bajo'
    return 'normal'


def _es_pigmento(item) -> bool:
    """True si el ítem es consumible con categoría 'Pigmentos'."""
    return (
        item.tipo == 'consumible'
        and item.categoria is not None
        and item.categoria.nombre.lower() == 'pigmentos'
    )


# ─────────────────────────────────────────────────────────────────────────────
# Alertas de stock
# ─────────────────────────────────────────────────────────────────────────────

def notify_stock(item, movimiento: str = '', usuario: str = ''):
    """
    Verifica el stock del ítem y envía alerta SOLO si el estado cambió.

    - stock == 0             → stock_zero
    - 0 < stock <= mínimo   → stock_low  (o pigmentos_resumen si es Pigmento)
    - stock > mínimo         → no se envía nada (estado normal)

    Anti-spam: si el estado ya era el mismo en la caché, se omite.
    """
    from django.db.models import Sum

    stock_total  = item.stock_total()
    stock_minimo = item.stock_minimo
    estado_nuevo = _estado_stock(stock_total, stock_minimo)

    cache_key    = f'stock_alert_state_{item.pk}'
    estado_previo = cache.get(cache_key, 'normal')

    # Siempre actualizar la caché con el estado actual
    cache.set(cache_key, estado_nuevo, _CACHE_TTL)

    # Si el estado no cambió, no hay nada que notificar
    if estado_nuevo == estado_previo:
        return

    # Estado normal: el ítem salió del rango de alerta — no se notifica
    if estado_nuevo == 'normal':
        return

    # ── Obtener ubicación principal (texto informativo) ──
    stock_ub = item.stock_set.select_related('ubicacion').order_by('-cantidad_actual').first()
    ubicacion_nombre = stock_ub.ubicacion.nombre if stock_ub else 'Sin ubicación'

    base_payload = {
        'item_id':          item.pk,
        'item':             item.nombre,
        'codigo':           item.codigo,
        'tipo':             item.tipo,
        'categoria':        item.categoria.nombre if item.categoria else '',
        'stock_actual':     float(stock_total),
        'stock_minimo':     float(stock_minimo),
        'unidad':           item.unidad_medida,
        'ubicacion':        ubicacion_nombre,
        'movimiento':       movimiento,
        'usuario':          usuario,
        'estado_alerta_stock': estado_nuevo,
    }

    # ── Pigmentos: resumen agrupado en lugar de alerta individual ──
    if _es_pigmento(item):
        if estado_nuevo in ('bajo', 'cero'):
            event_log.info(
                '[EVENT] pigmentos_resumen disparado por item=%s stock=%s',
                item.nombre, stock_total,
            )
            payload = generar_resumen_pigmentos()
            send_event('pigmentos_resumen', payload)
        return

    # ── Ítems normales ──
    if estado_nuevo == 'cero':
        event_log.info('[EVENT] stock_zero item=%s stock=%s', item.nombre, stock_total)
        send_event('stock_zero', base_payload)

    elif estado_nuevo == 'bajo':
        event_log.info('[EVENT] stock_low item=%s stock=%s', item.nombre, stock_total)
        send_event('stock_low', base_payload)


# ─────────────────────────────────────────────────────────────────────────────
# Resumen agrupado de Pigmentos
# ─────────────────────────────────────────────────────────────────────────────

def generar_resumen_pigmentos() -> dict:
    """
    Genera el payload completo del evento pigmentos_resumen.

    Consulta todos los ítems consumibles de la categoría 'Pigmentos',
    calcula su stock y devuelve:
      - bajos: lista de pigmentos en estado bajo o cero
      - resumen: lista completa con estado de cada uno
    """
    from apps.core.models import Item
    from django.db.models import Sum, Value
    from django.db.models.functions import Coalesce
    from django.db.models import DecimalField

    pigmentos = (
        Item.objects
        .filter(tipo='consumible', categoria__nombre__iexact='Pigmentos', activo=True)
        .annotate(
            stock_calc=Coalesce(
                Sum('stock__cantidad_actual'),
                Value(Decimal('0')),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            )
        )
        .select_related('categoria')
        .order_by('orden', 'nombre')
    )

    ahora    = timezone.localtime(timezone.now())
    bajos    = []
    resumen  = []

    for p in pigmentos:
        stock    = p.stock_calc
        minimo   = p.stock_minimo
        estado   = _estado_stock(stock, minimo)
        emoji    = _emoji_pigmento(p.nombre)

        fila = {
            'emoji':         emoji,
            'nombre':        p.nombre,
            'codigo':        p.codigo,
            'stock_actual':  float(stock),
            'stock_minimo':  float(minimo),
            'unidad':        p.unidad_medida,
            'estado':        estado,   # 'normal' | 'bajo' | 'cero'
        }

        resumen.append(fila)

        if estado in ('bajo', 'cero'):
            bajos.append(fila)

    return {
        'titulo': 'Resumen de pigmentos',
        'fecha':  ahora.strftime('%d/%m/%Y'),
        'hora':   ahora.strftime('%H:%M'),
        'total':  len(resumen),
        'total_bajos': len(bajos),
        'bajos':  bajos,
        'resumen': resumen,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Eventos de seguridad
# ─────────────────────────────────────────────────────────────────────────────

def send_security_event(event_type: str, *, title: str, user: str = '',
                        ip: str = '', path: str = '',
                        user_agent: str = '', message: str = ''):
    """
    Envía un evento de seguridad al webhook y lo registra en el logger 'security'.

    Parámetros con nombre obligatorio para evitar mezclar posicionales.
    """
    security_log.warning(
        '[SECURITY] %s user=%s ip=%s path=%s',
        event_type, user or 'anon', ip or 'unknown', path or '-',
    )

    payload = {
        'title':      title,
        'user':       user,
        'ip':         ip,
        'path':       path,
        'user_agent': user_agent,
        'message':    message,
    }
    send_event(event_type, payload)
