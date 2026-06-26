from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase

from apps.core.models import Cliente, DocumentoFactura, TarifaCliente
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
            cliente=self.cliente, producto='camiseta',
            precio_por_libra=Decimal('32.00'), activa=True,
            fecha_inicio=date(2026, 1, 1),
        )
        doc = invoice_service.crear_documento(
            cliente=self.cliente, tipo_documento='envio', producto='camiseta',
            datos={'numero_documento': 'E-1', 'total_libras': Decimal('10.00')},
        )
        self.assertEqual(doc.precio_por_libra, Decimal('32.00'))
        self.assertEqual(doc.monto_total, Decimal('320.00'))

    def test_envio_sin_tarifa_deja_monto_cero(self):
        doc = invoice_service.crear_documento(
            cliente=self.cliente, tipo_documento='envio', producto='otro',
            datos={'total_libras': Decimal('10.00')},
        )
        self.assertIsNone(doc.precio_por_libra)
        self.assertEqual(doc.monto_total, Decimal('0'))
