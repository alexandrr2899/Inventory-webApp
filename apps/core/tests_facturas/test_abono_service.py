from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.core.models import Cliente, DocumentoFactura, MetodoPago, AplicacionPago
from apps.core.services.facturas import payment_service


class AbonoServiceTests(TestCase):
    def setUp(self):
        self.cli = Cliente.objects.create(nombre='Cli')
        self.met = MetodoPago.objects.create(nombre='Efectivo', tipo='efectivo')
        self.hoy = timezone.localdate()
        # Dos facturas: la más vieja primero
        self.f1 = DocumentoFactura.objects.create(
            cliente=self.cli, tipo_documento='factura',
            fecha_documento=self.hoy - timedelta(days=10), monto_total=Decimal('100.00'),
        )
        self.f2 = DocumentoFactura.objects.create(
            cliente=self.cli, tipo_documento='factura',
            fecha_documento=self.hoy - timedelta(days=5), monto_total=Decimal('100.00'),
        )

    def _abono(self, monto, aplicaciones=None):
        return payment_service.registrar_abono(
            self.cli, fecha_pago=self.hoy, metodo_pago=self.met,
            monto=Decimal(monto), aplicaciones=aplicaciones,
        )

    def test_auto_reparto_por_antiguedad_llena_f1_y_pasa_a_f2(self):
        self._abono('150.00')
        self.f1.refresh_from_db(); self.f2.refresh_from_db()
        self.assertEqual(self.f1.monto_pagado, Decimal('100.00'))
        self.assertEqual(self.f1.estado_pago, 'pagada')
        self.assertEqual(self.f2.monto_pagado, Decimal('50.00'))
        self.assertEqual(self.f2.estado_pago, 'pendiente')

    def test_excedente_queda_como_saldo_a_favor(self):
        self._abono('250.00')
        self.assertEqual(self.cli.saldo_a_favor, Decimal('50.00'))

    def test_reparto_editado_respeta_montos_dados(self):
        self._abono('80.00', aplicaciones=[(self.f2, Decimal('80.00'))])
        self.f1.refresh_from_db(); self.f2.refresh_from_db()
        self.assertEqual(self.f1.monto_pagado, Decimal('0.00'))
        self.assertEqual(self.f2.monto_pagado, Decimal('80.00'))

    def test_proponer_reparto_no_persiste(self):
        reparto = payment_service.proponer_reparto(self.cli, Decimal('120.00'))
        self.assertEqual([(d.pk, m) for d, m in reparto],
                         [(self.f1.pk, Decimal('100.00')), (self.f2.pk, Decimal('20.00'))])
        self.assertEqual(AplicacionPago.objects.count(), 0)

    def test_aplicar_saldo_a_favor_a_factura_nueva(self):
        self._abono('250.00')  # 50 de crédito
        nueva = DocumentoFactura.objects.create(
            cliente=self.cli, tipo_documento='factura',
            fecha_documento=self.hoy, monto_total=Decimal('30.00'),
        )
        aplicado = payment_service.aplicar_saldo_a_favor(nueva)
        nueva.refresh_from_db()
        self.assertEqual(aplicado, Decimal('30.00'))
        self.assertEqual(nueva.estado_pago, 'pagada')

    def test_liberar_aplicaciones_devuelve_a_saldo_a_favor(self):
        self._abono('100.00')  # cubre f1
        self.f1.refresh_from_db()
        self.assertEqual(self.f1.estado_pago, 'pagada')
        payment_service.liberar_aplicaciones(self.f1)
        self.f1.refresh_from_db()
        self.assertEqual(self.f1.monto_pagado, Decimal('0.00'))
        self.assertEqual(self.cli.saldo_a_favor, Decimal('100.00'))
