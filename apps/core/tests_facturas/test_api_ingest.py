import os
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.core.models import Cliente, DocumentoFactura, TarifaCliente

_SAMPLES = os.path.normpath(os.path.join(
    os.path.dirname(__file__), '..', '..', '..', 'docs', 'facturas', 'samples'))
_FACTURA = os.path.join(_SAMPLES, 'Fact 9543 Inversiones Zaga.pdf')

TOKEN = 'secreto-de-prueba-123'


def _factura_upload():
    with open(_FACTURA, 'rb') as fh:
        return SimpleUploadedFile('Fact 9543 Inversiones Zaga.pdf', fh.read(),
                                  content_type='application/pdf')


@override_settings(FACTURAS_MODULE_ENABLED=True, FACTURAS_INGEST_TOKEN=TOKEN,
                   ALLOWED_HOSTS=['testserver', 'localhost'], MEDIA_ROOT=tempfile.mkdtemp())
class IngestTokenTests(TestCase):
    def setUp(self):
        self.url = reverse('factura_api_ingest')
        Cliente.objects.create(nombre='Inversiones Zaga')

    def test_token_invalido_401(self):
        resp = self.client.post(self.url, {'archivo': _factura_upload()}, HTTP_X_API_KEY='malo')
        self.assertEqual(resp.status_code, 401)

    def test_sin_archivo_400(self):
        resp = self.client.post(self.url, {}, HTTP_X_API_KEY=TOKEN)
        self.assertEqual(resp.status_code, 400)

    def test_cliente_no_encontrado_422(self):
        archivo = SimpleUploadedFile('Fact 1 Cliente Inexistente.pdf', b'%PDF-1.4 dummy',
                                     content_type='application/pdf')
        resp = self.client.post(self.url, {'archivo': archivo}, HTTP_X_API_KEY=TOKEN)
        self.assertEqual(resp.status_code, 422)
        self.assertFalse(resp.json()['ok'])

    def test_ingesta_ok_crea_documento(self):
        if not os.path.exists(_FACTURA):
            self.skipTest('PDF de muestra ausente')
        resp = self.client.post(self.url, {'archivo': _factura_upload()}, HTTP_X_API_KEY=TOKEN)
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['cliente'], 'Inversiones Zaga')
        self.assertEqual(data['numero'], '9543')
        self.assertEqual(DocumentoFactura.objects.count(), 1)

    def test_dedup_no_crea_dos_veces(self):
        if not os.path.exists(_FACTURA):
            self.skipTest('PDF de muestra ausente')
        r1 = self.client.post(self.url, {'archivo': _factura_upload()}, HTTP_X_API_KEY=TOKEN)
        self.assertEqual(r1.status_code, 201)
        r2 = self.client.post(self.url, {'archivo': _factura_upload()}, HTTP_X_API_KEY=TOKEN)
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r2.json().get('duplicado'))
        self.assertEqual(DocumentoFactura.objects.count(), 1)


@override_settings(FACTURAS_MODULE_ENABLED=True, FACTURAS_INGEST_TOKEN='',
                   ALLOWED_HOSTS=['testserver', 'localhost'])
class IngestDeshabilitadoTests(TestCase):
    def test_sin_token_configurado_503(self):
        resp = self.client.post(reverse('factura_api_ingest'),
                                {'archivo': SimpleUploadedFile('x.pdf', b'x')},
                                HTTP_X_API_KEY='lo-que-sea')
        self.assertEqual(resp.status_code, 503)
