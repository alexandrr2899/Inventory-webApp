import os
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from apps.core.models import Cliente, DocumentoFactura, TarifaCliente
from apps.core.services.facturas import bulk_service

_SAMPLES = os.path.normpath(os.path.join(
    os.path.dirname(__file__), '..', '..', '..', 'docs', 'facturas', 'samples'))
_FACTURA = os.path.join(_SAMPLES, 'Fact 9543 Inversiones Zaga.pdf')
_ENVIO = os.path.join(_SAMPLES, 'RENATO DIAZ Envio camiseta 126.pdf')


class MatchClienteTests(TestCase):
    def setUp(self):
        self.zaga = Cliente.objects.create(nombre='Inversiones Zaga')
        self.renato = Cliente.objects.create(nombre='Renato Díaz')  # con acento

    def test_match_exacto(self):
        self.assertEqual(bulk_service.match_cliente('Inversiones Zaga'), self.zaga)

    def test_match_ignora_acentos_y_mayusculas(self):
        # El nombre del archivo viene como 'RENATO DIAZ' (sin acento, mayúsculas).
        self.assertEqual(bulk_service.match_cliente('RENATO DIAZ'), self.renato)

    def test_sin_match_devuelve_none(self):
        self.assertIsNone(bulk_service.match_cliente('Cliente Inexistente'))

    def test_solo_exacto_rechaza_substring(self):
        # 'Renato' es substring de 'Renato Díaz' pero no es match exacto.
        self.assertIsNotNone(bulk_service.match_cliente('Renato'))           # fuzzy: sí
        self.assertIsNone(bulk_service.match_cliente('Renato', solo_exacto=True))  # exacto: no
        self.assertEqual(bulk_service.match_cliente('RENATO DIAZ', solo_exacto=True), self.renato)



def _archivos_reales():
    archivos = []
    for ruta in (_FACTURA, _ENVIO):
        with open(ruta, 'rb') as fh:
            archivos.append(SimpleUploadedFile(os.path.basename(ruta), fh.read(),
                                               content_type='application/pdf'))
    return archivos


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class LoteEndToEndTests(TestCase):
    def setUp(self):
        self.zaga = Cliente.objects.create(nombre='Inversiones Zaga')
        self.renato = Cliente.objects.create(nombre='Renato Díaz')
        TarifaCliente.objects.create(cliente=self.renato, producto='camiseta',
                                     precio_por_libra=__import__('decimal').Decimal('30.00'),
                                     activa=True)

    def test_procesar_empareja_y_detecta(self):
        if not (os.path.exists(_FACTURA) and os.path.exists(_ENVIO)):
            self.skipTest('PDFs de muestra ausentes')
        batch_id, filas = bulk_service.procesar_archivos(_archivos_reales())
        self.assertEqual(len(filas), 2)
        por_nombre = {f['nombre_original']: f for f in filas}
        fac = por_nombre['Fact 9543 Inversiones Zaga.pdf']
        env = por_nombre['RENATO DIAZ Envio camiseta 126.pdf']
        self.assertEqual(fac['tipo'], 'factura')
        self.assertEqual(str(fac['cliente_id']), str(self.zaga.pk))
        self.assertEqual(fac['numero_documento'], '9543')
        self.assertEqual(env['tipo'], 'envio')
        self.assertEqual(str(env['cliente_id']), str(self.renato.pk))
        self.assertEqual(env['producto'], 'camiseta')

    def test_crear_desde_lote_crea_documentos(self):
        if not (os.path.exists(_FACTURA) and os.path.exists(_ENVIO)):
            self.skipTest('PDFs de muestra ausentes')
        batch_id, filas = bulk_service.procesar_archivos(_archivos_reales())
        creados, errores = bulk_service.crear_desde_lote(batch_id, filas)
        self.assertEqual(creados, 2)
        self.assertEqual(errores, [])
        self.assertEqual(DocumentoFactura.objects.count(), 2)
        env = DocumentoFactura.objects.get(tipo_documento='envio')
        # La tarifa de Renato (30/lb) se aplicó sobre 1000 libras.
        self.assertEqual(env.precio_por_libra, __import__('decimal').Decimal('30.00'))
        self.assertEqual(env.monto_total, __import__('decimal').Decimal('30000.00'))

    def test_fila_sin_cliente_se_reporta_como_error(self):
        batch_id, filas = bulk_service.procesar_archivos(_archivos_reales())
        for f in filas:
            f['cliente_id'] = ''  # simular que el usuario no asignó cliente
        creados, errores = bulk_service.crear_desde_lote(batch_id, filas)
        self.assertEqual(creados, 0)
        self.assertEqual(len(errores), 2)
