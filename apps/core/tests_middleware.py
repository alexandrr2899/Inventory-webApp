from django.test import RequestFactory, SimpleTestCase

from apps.core.middleware import TrustedProxyHeadersMiddleware


class TrustedProxyHeadersMiddlewareTests(SimpleTestCase):
    def _request(self, remote_addr):
        request = RequestFactory().get(
            '/', REMOTE_ADDR=remote_addr,
            HTTP_CF_CONNECTING_IP='203.0.113.8',
            HTTP_X_FORWARDED_PROTO='https',
            HTTP_X_FORWARDED_HOST='inventario.example',
        )
        middleware = TrustedProxyHeadersMiddleware(lambda req: req)
        return middleware(request)

    def test_descarta_cabeceras_desde_cliente_directo(self):
        request = self._request('10.0.0.25')
        self.assertNotIn('HTTP_CF_CONNECTING_IP', request.META)
        self.assertNotIn('HTTP_X_FORWARDED_PROTO', request.META)
        self.assertNotIn('HTTP_X_FORWARDED_HOST', request.META)

    def test_conserva_cabeceras_desde_red_docker(self):
        request = self._request('172.25.0.1')
        self.assertEqual(request.META['HTTP_CF_CONNECTING_IP'], '203.0.113.8')
        self.assertEqual(request.META['HTTP_X_FORWARDED_PROTO'], 'https')
