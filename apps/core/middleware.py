"""Confianza explícita de cabeceras añadidas por el proxy reverso."""
from ipaddress import ip_address, ip_network

from django.conf import settings


PROXY_HEADERS = (
    'HTTP_CF_CONNECTING_IP',
    'HTTP_X_FORWARDED_FOR',
    'HTTP_X_FORWARDED_HOST',
    'HTTP_X_FORWARDED_PROTO',
)


def is_trusted_proxy(remote_addr):
    try:
        address = ip_address(remote_addr or '')
    except ValueError:
        return False
    for cidr in settings.TRUSTED_PROXY_CIDRS:
        try:
            if address in ip_network(cidr, strict=False):
                return True
        except ValueError:
            continue
    return False


class TrustedProxyHeadersMiddleware:
    """Descarta cabeceras de proxy cuando la conexión no viene de uno confiable."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not is_trusted_proxy(request.META.get('REMOTE_ADDR')):
            for header in PROXY_HEADERS:
                request.META.pop(header, None)
        return self.get_response(request)
