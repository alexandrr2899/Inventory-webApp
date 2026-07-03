from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.core.models import Cliente, DocumentoFactura, TarifaCliente, CategoriaProducto
from apps.core.services.facturas import invoice_service


class DetectarTipoTests(TestCase):
    def test_envio(self):
        self.assertEqual(invoice_service.detectar_tipo('Walter Aguilera Envio Camiseta 98.pdf'), 'envio')

    def test_factura(self):
        self.assertEqual(invoice_service.detectar_tipo('Fact 9541 ASOVEMEZB-- Milton.pdf'), 'factura')

    def test_desconocido_default_factura(self):
        self.assertEqual(invoice_service.detectar_tipo('algo_raro.pdf'), 'factura')


class VencimientoCreditoTests(TestCase):
    def test_vencimiento_se_calcula_con_dias_credito(self):
        cliente = Cliente.objects.create(nombre='Crédito 15', dias_credito=15)
        doc = invoice_service.crear_documento(
            cliente=cliente, tipo_documento='factura',
            datos={'fecha_documento': date(2026, 6, 1), 'monto_total': Decimal('100.00')},
        )
        self.assertEqual(doc.fecha_vencimiento, date(2026, 6, 16))

    def test_contado_no_pone_vencimiento(self):
        cliente = Cliente.objects.create(nombre='Contado', dias_credito=0)
        doc = invoice_service.crear_documento(
            cliente=cliente, tipo_documento='factura',
            datos={'fecha_documento': date(2026, 6, 1), 'monto_total': Decimal('100.00')},
        )
        self.assertIsNone(doc.fecha_vencimiento)

    def test_vencimiento_explicito_no_se_sobrescribe(self):
        cliente = Cliente.objects.create(nombre='Crédito 30', dias_credito=30)
        doc = invoice_service.crear_documento(
            cliente=cliente, tipo_documento='factura',
            datos={'fecha_documento': date(2026, 6, 1),
                   'fecha_vencimiento': date(2026, 6, 5), 'monto_total': Decimal('100.00')},
        )
        self.assertEqual(doc.fecha_vencimiento, date(2026, 6, 5))


class InvoiceServiceTests(TestCase):
    def setUp(self):
        self.cliente = Cliente.objects.create(nombre='Renato Díaz')
        CategoriaProducto.objects.all().delete()
        self.camiseta = CategoriaProducto.objects.create(nombre='Camiseta', palabra_clave='camiseta')
        self.otro = CategoriaProducto.objects.create(nombre='Otro', es_predeterminada=True)

    def test_crear_factura_desde_datos(self):
        doc = invoice_service.crear_documento(
            cliente=self.cliente, tipo_documento='factura',
            datos={
                'numero_documento': 'F-1', 'fecha_documento': date(2026, 6, 1),
                'subtotal': Decimal('100.00'), 'isv': Decimal('15.00'),
                'monto_total': Decimal('115.00'),
            },
            texto_extraido='...',
        )
        self.assertEqual(doc.tipo_documento, 'factura')
        self.assertEqual(doc.monto_total, Decimal('115.00'))
        self.assertEqual(doc.estado_revision, 'pendiente')
        self.assertEqual(doc.estado_pago, 'pendiente')

    def test_crear_envio_aplica_tarifa_y_calcula_monto(self):
        TarifaCliente.objects.create(
            cliente=self.cliente, categoria=self.camiseta,
            precio_por_libra=Decimal('32.00'), activa=True,
            fecha_inicio=date(2026, 1, 1),
        )
        doc = invoice_service.crear_documento(
            cliente=self.cliente, tipo_documento='envio', categoria=self.camiseta,
            datos={'numero_documento': 'E-1', 'total_libras': Decimal('10.00')},
        )
        self.assertEqual(doc.categoria, self.camiseta)
        self.assertEqual(doc.precio_por_libra, Decimal('32.00'))
        self.assertEqual(doc.monto_total, Decimal('320.00'))

    def test_envio_sin_tarifa_deja_monto_cero(self):
        doc = invoice_service.crear_documento(
            cliente=self.cliente, tipo_documento='envio', categoria=self.otro,
            datos={'total_libras': Decimal('10.00')},
        )
        self.assertIsNone(doc.precio_por_libra)
        self.assertEqual(doc.monto_total, Decimal('0'))


class PrevisualizarCategoriaTests(TestCase):
    def setUp(self):
        CategoriaProducto.objects.all().delete()
        self.camiseta = CategoriaProducto.objects.create(
            nombre='Camiseta', palabra_clave='camiseta', orden=0)
        self.lisa = CategoriaProducto.objects.create(
            nombre='Lisa', palabra_clave='lisa, blanca', es_predeterminada=True, orden=1)

    def _run_previsualizar(self, tipo, nombre_archivo, texto_pdf):
        archivo = SimpleUploadedFile(nombre_archivo, b'%PDF', content_type='application/pdf')
        with patch('apps.core.services.facturas.invoice_service.pdf_service') as mock_pdf, \
             patch('apps.core.services.facturas.invoice_service.filename_extractor') as mock_fe:
            mock_pdf.extraer_texto.return_value = texto_pdf
            mock_pdf.get_extractor.return_value.extraer.return_value = {}
            mock_fe.extraer_de_nombre.return_value = {}
            return invoice_service.previsualizar(tipo, archivo)

    def test_factura_keyword_en_contenido_asigna_categoria(self):
        result = self._run_previsualizar(
            'factura', 'Fact 9546 Tekniplasticos.pdf', 'Lb Bolsa Camiseta\n2000.00')
        self.assertEqual(result['datos']['categoria_id'], self.camiseta.pk)

    def test_factura_sin_coincidencia_no_incluye_categoria_id(self):
        result = self._run_previsualizar(
            'factura', 'Fact 9544 Inversiones San Juan.pdf', 'Rollo de Poliducto x 100yd')
        self.assertNotIn('categoria_id', result['datos'])

    def test_envio_sin_coincidencia_usa_predeterminada(self):
        result = self._run_previsualizar(
            'envio', 'Envio 123 Cliente.pdf', 'texto sin keywords')
        self.assertEqual(result['datos']['categoria_id'], self.lisa.pk)

    def test_envio_keyword_en_contenido_asigna_categoria(self):
        result = self._run_previsualizar(
            'envio', 'Envio 123 Cliente.pdf', 'Lb Bolsa Camiseta\n500 Lb')
        self.assertEqual(result['datos']['categoria_id'], self.camiseta.pk)
