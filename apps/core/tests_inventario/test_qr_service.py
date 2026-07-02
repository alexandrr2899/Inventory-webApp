from django.test import SimpleTestCase

from apps.core.services import qr


class QrServiceTests(SimpleTestCase):
    def test_devuelve_png_no_vacio(self):
        data = 'https://ejemplo.com/inventario/1/'
        out = qr.qr_png_bytes(data)
        self.assertIsInstance(out, bytes)
        self.assertGreater(len(out), 0)
        # Cabecera PNG.
        self.assertEqual(out[:8], b'\x89PNG\r\n\x1a\n')

    def test_datos_distintos_dan_pngs_distintos(self):
        a = qr.qr_png_bytes('https://ejemplo.com/inventario/1/')
        b = qr.qr_png_bytes('https://ejemplo.com/inventario/2/')
        self.assertNotEqual(a, b)
