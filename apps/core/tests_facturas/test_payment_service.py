from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.core.models import Cliente, DocumentoFactura, MetodoPago
from apps.core.services.facturas import payment_service


class PaymentServiceTests(TestCase):
    def setUp(self):
        self.cliente = Cliente.objects.create(nombre='Cli')
        self.met = MetodoPago.objects.create(nombre='Efectivo', tipo='efectivo')
        self.hoy = timezone.localdate()
        self.doc = DocumentoFactura.objects.create(
            cliente=self.cliente, tipo_documento='factura', fecha_documento=self.hoy,
            fecha_vencimiento=self.hoy + timedelta(days=10), monto_total=Decimal('100.00'),
        )

    def _abono(self, monto):
        return payment_service.registrar_abono(
            self.cliente, fecha_pago=self.hoy, metodo_pago=self.met,
            monto=Decimal(monto), aplicaciones=[(self.doc, Decimal(monto))],
        )

    def test_pago_parcial_queda_pendiente(self):
        self._abono('40.00')
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.monto_pagado, Decimal('40.00'))
        self.assertEqual(self.doc.estado_pago, 'pendiente')

    def test_pago_total_marca_pagada(self):
        self._abono('100.00')
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.estado_pago, 'pagada')

    def test_borrar_aplicacion_recalcula_estado(self):
        self._abono('100.00')
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.estado_pago, 'pagada')
        self.doc.aplicaciones.all().delete()
        self.doc.refresh_from_db()
        self.assertNotEqual(self.doc.estado_pago, 'pagada')
