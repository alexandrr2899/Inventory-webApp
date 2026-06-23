from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.core.models import Cliente, DocumentoFactura, TarifaCliente
from apps.core.services.facturas import invoice_service


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
