from django.test import TestCase, override_settings
from django.http import Http404
from django.test import RequestFactory

from apps.core.views.common import facturas_enabled


@facturas_enabled
def _vista_dummy(request):
    from django.http import HttpResponse
    return HttpResponse('ok')


class InterruptorFacturasTests(TestCase):
    def setUp(self):
        self.rf = RequestFactory()

    @override_settings(FACTURAS_MODULE_ENABLED=False)
    def test_decorador_404_cuando_apagado(self):
        with self.assertRaises(Http404):
            _vista_dummy(self.rf.get('/'))

    @override_settings(FACTURAS_MODULE_ENABLED=True)
    def test_decorador_pasa_cuando_encendido(self):
        resp = _vista_dummy(self.rf.get('/'))
        self.assertEqual(resp.status_code, 200)
