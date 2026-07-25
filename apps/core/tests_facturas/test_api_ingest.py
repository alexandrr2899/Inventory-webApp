import os
import tempfile

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.core.models import Cliente, ClienteAlias, DocumentoFactura, TarifaCliente

_SAMPLES = os.path.normpath(os.path.join(
    os.path.dirname(__file__), '..', '..', '..', 'docs', 'facturas', 'samples'))
_FACTURA = os.path.join(_SAMPLES, 'Fact 9543 Inversiones Zaga.pdf')

TOKEN = 'secreto-de-prueba-123'


def _factura_upload(nombre='Fact 9543 Inversiones Zaga.pdf'):
    with open(_FACTURA, 'rb') as fh:
        return SimpleUploadedFile(nombre, fh.read(),
                                  content_type='application/pdf')


@override_settings(FACTURAS_MODULE_ENABLED=True, FACTURAS_INGEST_TOKEN=TOKEN,
                   ALLOWED_HOSTS=['testserver', 'localhost'], MEDIA_ROOT=tempfile.mkdtemp())
class IngestTokenTests(TestCase):
    def setUp(self):
        cache.clear()  # aislar el contador de rate-limit entre tests
        self.url = reverse('factura_api_ingest')
        Cliente.objects.create(nombre='Inversiones Zaga')

    def test_token_invalido_401(self):
        resp = self.client.post(self.url, {'archivo': _factura_upload()}, HTTP_X_API_KEY='malo')
        self.assertEqual(resp.status_code, 401)

    def test_sin_archivo_400(self):
        resp = self.client.post(self.url, {}, HTTP_X_API_KEY=TOKEN)
        self.assertEqual(resp.status_code, 400)

    def test_rechaza_archivo_no_pdf_400(self):
        # Extensión válida pero contenido que no es PDF → 400.
        falso = SimpleUploadedFile('factura.pdf', b'esto no es un pdf',
                                   content_type='application/pdf')
        resp = self.client.post(self.url, {'archivo': falso}, HTTP_X_API_KEY=TOKEN)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(DocumentoFactura.objects.count(), 0)

    def test_rechaza_extension_no_pdf_400(self):
        falso = SimpleUploadedFile('factura.txt', b'%PDF-1.4 pero .txt',
                                   content_type='text/plain')
        resp = self.client.post(self.url, {'archivo': falso}, HTTP_X_API_KEY=TOKEN)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(DocumentoFactura.objects.count(), 0)

    def test_cliente_no_encontrado_crea_sin_identificar_para_revision(self):
        if not os.path.exists(_FACTURA):
            self.skipTest('PDF de muestra ausente')
        archivo = _factura_upload('Fact 9543 Cliente Inexistente.pdf')
        resp = self.client.post(self.url, {'archivo': archivo}, HTTP_X_API_KEY=TOKEN)
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertTrue(data['requiere_revision'])
        self.assertEqual(data['cliente'], 'Sin identificar')
        self.assertEqual(data['cliente_sugerido'], 'Cliente Inexistente')
        doc = DocumentoFactura.objects.get()
        self.assertEqual(doc.cliente.nombre, 'Sin identificar')
        self.assertIn('Cliente Inexistente', doc.notas)
        self.assertEqual(Cliente.objects.filter(nombre='Sin identificar').count(), 1)

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

    def test_alias_empareja_en_la_ingesta_sin_pasar_por_sin_identificar(self):
        if not os.path.exists(_FACTURA):
            self.skipTest('PDF de muestra ausente')
        zaga = Cliente.objects.get(nombre='Inversiones Zaga')
        ClienteAlias.objects.create(cliente=zaga, alias='Comercial Zaga')

        archivo = _factura_upload('Fact 9543 Comercial Zaga.pdf')
        resp = self.client.post(self.url, {'archivo': archivo}, HTTP_X_API_KEY=TOKEN)

        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertFalse(data['requiere_revision'])
        self.assertEqual(data['cliente'], 'Inversiones Zaga')
        self.assertEqual(DocumentoFactura.objects.get().cliente, zaga)
        self.assertFalse(
            Cliente.objects.filter(nombre='Sin identificar').exists())

    def test_dedup_no_crea_dos_veces(self):
        if not os.path.exists(_FACTURA):
            self.skipTest('PDF de muestra ausente')
        r1 = self.client.post(self.url, {'archivo': _factura_upload()}, HTTP_X_API_KEY=TOKEN)
        self.assertEqual(r1.status_code, 201)
        r2 = self.client.post(self.url, {'archivo': _factura_upload()}, HTTP_X_API_KEY=TOKEN)
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r2.json().get('duplicado'))
        self.assertEqual(DocumentoFactura.objects.count(), 1)


@override_settings(FACTURAS_MODULE_ENABLED=True, FACTURAS_INGEST_TOKEN=TOKEN,
                   ALLOWED_HOSTS=['testserver', 'localhost'], MEDIA_ROOT=tempfile.mkdtemp())
class IngestRateLimitTests(TestCase):
    def setUp(self):
        cache.clear()
        self.url = reverse('factura_api_ingest')

    def test_bloquea_tras_muchos_fallos_de_token(self):
        for _ in range(10):
            r = self.client.post(self.url, {}, HTTP_X_API_KEY='malo')
            self.assertEqual(r.status_code, 401)
        # El siguiente intento queda bloqueado, aun con token válido
        # (el bloqueo se evalúa antes de validar el token).
        r = self.client.post(
            self.url, {'archivo': SimpleUploadedFile('x.pdf', b'%PDF-1.4')},
            HTTP_X_API_KEY=TOKEN)
        self.assertEqual(r.status_code, 429)

    def test_token_valido_no_dispara_rate_limit(self):
        # Muchas peticiones con token válido nunca se bloquean (siguen dando 400
        # por falta de archivo, no 429).
        for _ in range(15):
            r = self.client.post(self.url, {}, HTTP_X_API_KEY=TOKEN)
            self.assertEqual(r.status_code, 400)


@override_settings(FACTURAS_MODULE_ENABLED=True, FACTURAS_INGEST_TOKEN='',
                   ALLOWED_HOSTS=['testserver', 'localhost'])
class IngestDeshabilitadoTests(TestCase):
    def test_sin_token_configurado_503(self):
        resp = self.client.post(reverse('factura_api_ingest'),
                                {'archivo': SimpleUploadedFile('x.pdf', b'x')},
                                HTTP_X_API_KEY='lo-que-sea')
        self.assertEqual(resp.status_code, 503)
