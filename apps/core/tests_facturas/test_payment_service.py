from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.core.models import Cliente, DocumentoFactura, PagoFactura
from apps.core.services.facturas import payment_service


class PaymentServiceTests(TestCase):
    def setUp(self):
        self.cliente = Cliente.objects.create(nombre='Cli')
        self.hoy = timezone.localdate()
        self.doc = DocumentoFactura.objects.create(
            cliente=self.cliente, tipo_documento='factura',
            fecha_documento=self.hoy,
            fecha_vencimiento=self.hoy + timedelta(days=10),
            monto_total=Decimal('100.00'),
        )

    def test_registrar_pago_actualiza_estado_a_pendiente_si_parcial(self):
        payment_service.registrar_pago(
            self.doc, fecha_pago=self.hoy, metodo_pago='efectivo',
            monto=Decimal('40.00'),
        )
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.monto_pagado, Decimal('40.00'))
        self.assertEqual(self.doc.estado_pago, 'pendiente')

    def test_pago_total_marca_pagada(self):
        payment_service.registrar_pago(
            self.doc, fecha_pago=self.hoy, metodo_pago='efectivo',
            monto=Decimal('100.00'),
        )
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.estado_pago, 'pagada')

    def test_multiples_pagos_suman_hasta_pagar(self):
        payment_service.registrar_pago(
            self.doc, fecha_pago=self.hoy, metodo_pago='efectivo',
            monto=Decimal('60.00'),
        )
        payment_service.registrar_pago(
            self.doc, fecha_pago=self.hoy, metodo_pago='transferencia',
            monto=Decimal('40.00'),
        )
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.monto_pagado, Decimal('100.00'))
        self.assertEqual(self.doc.estado_pago, 'pagada')

    def test_borrar_pago_recalcula_estado(self):
        p = payment_service.registrar_pago(
            self.doc, fecha_pago=self.hoy, metodo_pago='efectivo',
            monto=Decimal('100.00'),
        )
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.estado_pago, 'pagada')
        p.delete()
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.estado_pago, 'pendiente')
