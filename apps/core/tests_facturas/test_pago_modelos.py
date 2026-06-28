from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.core.models import (
    Cliente, DocumentoFactura, MetodoPago, Pago, AplicacionPago,
)


class PagoModeloTests(TestCase):
    def setUp(self):
        self.cli = Cliente.objects.create(nombre='Cli')
        self.met = MetodoPago.objects.create(nombre='Efectivo', tipo='efectivo')
        self.hoy = timezone.localdate()
        self.doc = DocumentoFactura.objects.create(
            cliente=self.cli, tipo_documento='factura', fecha_documento=self.hoy,
            monto_total=Decimal('100.00'),
        )

    def _pago(self, monto):
        return Pago.objects.create(
            cliente=self.cli, fecha_pago=self.hoy, metodo_pago=self.met, monto=monto,
        )

    def test_monto_aplicado_y_saldo_sin_aplicar(self):
        pago = self._pago(Decimal('100.00'))
        AplicacionPago.objects.create(pago=pago, documento=self.doc, monto=Decimal('40.00'))
        self.assertEqual(pago.monto_aplicado, Decimal('40.00'))
        self.assertEqual(pago.saldo_sin_aplicar, Decimal('60.00'))

    def test_saldo_a_favor_del_cliente(self):
        pago = self._pago(Decimal('100.00'))
        AplicacionPago.objects.create(pago=pago, documento=self.doc, monto=Decimal('30.00'))
        self.assertEqual(self.cli.saldo_a_favor, Decimal('70.00'))

    def test_total_adeudado_del_cliente(self):
        # doc de 100 sin pagos: adeudado = 100
        self.assertEqual(self.cli.total_adeudado, Decimal('100.00'))
        pago = self._pago(Decimal('40.00'))
        AplicacionPago.objects.create(pago=pago, documento=self.doc, monto=Decimal('40.00'))
        self.assertEqual(self.cli.total_adeudado, Decimal('60.00'))
