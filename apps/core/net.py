"""Utilidades de red compartidas."""


def get_client_ip(request):
    """IP real del cliente, NO falsificable detrás de Cloudflare.

    Cloudflare (incluido Cloudflare Tunnel) sobrescribe siempre la cabecera
    ``CF-Connecting-IP`` con la IP real del visitante; el cliente no puede
    forjarla porque el edge la reemplaza antes de llegar al origen.

    A propósito NO se usa ``X-Forwarded-For``: su primer valor lo controla el
    cliente (puede anteponer IPs arbitrarias) y con él se podía evadir el
    rate-limit de ingesta o falsear los logs de seguridad. Sin Cloudflare
    (local / tests / acceso directo) se cae a ``REMOTE_ADDR``, que es lo único
    no falsificable en ese contexto.
    """
    if request is None:
        return 'unknown'
    cf = request.META.get('HTTP_CF_CONNECTING_IP')
    if cf:
        return cf.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', 'unknown')
