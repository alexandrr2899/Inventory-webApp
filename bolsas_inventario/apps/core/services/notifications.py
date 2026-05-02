import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def send_n8n_event(event_type: str, payload: dict) -> bool:
    """
    Envía un evento al webhook de n8n.
    Silencioso: los errores se loguean pero no interrumpen el flujo.
    """
    url = getattr(settings, 'N8N_WEBHOOK_URL', None)
    if not url:
        return False

    body = {
        'event_type': event_type,
        'source': 'inventory_app',
        'payload': payload,
    }
    try:
        resp = requests.post(url, json=body, timeout=5)
        resp.raise_for_status()
        return True
    except requests.exceptions.ConnectionError:
        logger.warning('n8n webhook: no se pudo conectar a %s', url)
    except requests.exceptions.Timeout:
        logger.warning('n8n webhook: timeout (%s)', event_type)
    except Exception as exc:
        logger.warning('n8n webhook error (%s): %s', event_type, exc)
    return False


def notify_stock(item):
    """Verifica el stock del ítem y envía alerta si corresponde."""
    stock = item.stock_total()
    payload = {
        'item': item.nombre,
        'codigo': item.codigo,
        'tipo': item.tipo,
        'stock_actual': str(stock),
        'stock_minimo': str(item.stock_minimo),
    }
    if stock <= 0:
        send_n8n_event('stock_zero', payload)
    elif item.stock_minimo > 0 and stock <= item.stock_minimo:
        send_n8n_event('stock_low', payload)
