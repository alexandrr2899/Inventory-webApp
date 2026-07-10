from datetime import timedelta
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
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

    def test_sobrepago_por_factura_va_a_saldo_a_favor(self):
        """Un excedente explícito sobre una factura fija se auto-reparte a la
        siguiente factura pendiente (no fijada), en vez de ir directo a crédito."""
        # f1 tiene saldo_pendiente=100; pedimos aplicar 150 → se aplican 100 a f1
        # (topado) y los 50 restantes se auto-reparten a f2 (pendiente, no fijada).
        pago = self._abono('150.00', aplicaciones=[(self.f1, Decimal('150.00'))])
        self.f1.refresh_from_db(); self.f2.refresh_from_db()
        self.assertEqual(self.f1.monto_pagado, Decimal('100.00'))
        self.assertEqual(self.f1.estado_pago, 'pagada')
        self.assertEqual(self.f2.monto_pagado, Decimal('50.00'))
        self.assertEqual(self.cli.saldo_a_favor, Decimal('0.00'))

    def test_reparto_fija_explicitas_y_autoreparte_el_resto(self):
        # f1=100 explícito; el resto (100) se auto-reparte a f2 (pendiente, no fijada).
        self._abono('200.00', aplicaciones=[(self.f1, Decimal('100.00'))])
        self.f1.refresh_from_db(); self.f2.refresh_from_db()
        self.assertEqual(self.f1.monto_pagado, Decimal('100.00'))
        self.assertEqual(self.f2.monto_pagado, Decimal('100.00'))
        self.assertEqual(self.cli.saldo_a_favor, Decimal('0.00'))

    def test_explicito_cero_no_recibe_remanente(self):
        # f1=0 explícito (fija en 0); el pago va todo a f2.
        self._abono('100.00', aplicaciones=[(self.f1, Decimal('0')), (self.f2, Decimal('100.00'))])
        self.f1.refresh_from_db(); self.f2.refresh_from_db()
        self.assertEqual(self.f1.monto_pagado, Decimal('0.00'))
        self.assertEqual(self.f2.monto_pagado, Decimal('100.00'))

    def test_reparto_editado_no_excede_monto_del_abono(self):
        """La suma de aplicaciones no puede superar el monto del abono."""
        # Abono de 100; se piden 80+80=160 → se aplican 80 a f1 y 20 a f2 (total 100)
        pago = self._abono('100.00', aplicaciones=[
            (self.f1, Decimal('80.00')),
            (self.f2, Decimal('80.00')),
        ])
        self.f1.refresh_from_db()
        self.f2.refresh_from_db()
        self.assertEqual(self.f1.monto_pagado, Decimal('80.00'))
        self.assertEqual(self.f2.monto_pagado, Decimal('20.00'))
        self.assertEqual(self.cli.saldo_a_favor, Decimal('0.00'))
        self.assertGreaterEqual(pago.saldo_sin_aplicar, Decimal('0.00'))

    def test_aplicacion_no_excede_saldo_factura(self):
        """Una aplicación pedida por encima del saldo se topa al saldo real."""
        # f1 tiene saldo=100; abono=100; se pide aplicar 200 → solo se aplican 100
        pago = self._abono('100.00', aplicaciones=[(self.f1, Decimal('200.00'))])
        self.f1.refresh_from_db()
        self.assertEqual(self.f1.monto_pagado, Decimal('100.00'))
        self.assertEqual(self.cli.saldo_a_favor, Decimal('0.00'))
        self.assertEqual(pago.saldo_sin_aplicar, Decimal('0.00'))
        self.assertGreaterEqual(pago.saldo_sin_aplicar, Decimal('0.00'))

    def test_editar_sube_monto_y_rehace_reparto(self):
        pago = self._abono('100.00')  # auto: cubre f1
        self.f1.refresh_from_db()
        self.assertEqual(self.f1.estado_pago, 'pagada')
        payment_service.editar_abono(
            pago, fecha_pago=self.hoy, metodo_pago=self.met,
            monto=Decimal('200.00'), aplicaciones=None)
        self.f1.refresh_from_db(); self.f2.refresh_from_db()
        self.assertEqual(self.f1.monto_pagado, Decimal('100.00'))
        self.assertEqual(self.f2.monto_pagado, Decimal('100.00'))

    def test_editar_baja_monto_libera_saldo(self):
        pago = self._abono('200.00')  # auto: cubre f1 y f2
        self.f2.refresh_from_db()
        self.assertEqual(self.f2.estado_pago, 'pagada')
        payment_service.editar_abono(
            pago, fecha_pago=self.hoy, metodo_pago=self.met,
            monto=Decimal('50.00'), aplicaciones=None)
        self.f1.refresh_from_db(); self.f2.refresh_from_db()
        self.assertEqual(self.f1.monto_pagado, Decimal('50.00'))
        self.assertEqual(self.f2.monto_pagado, Decimal('0.00'))
        self.assertEqual(self.f2.estado_pago, 'pendiente')

    def test_editar_con_reparto_explicito(self):
        pago = self._abono('100.00')  # auto: cubre f1
        payment_service.editar_abono(
            pago, fecha_pago=self.hoy, metodo_pago=self.met,
            monto=Decimal('100.00'), aplicaciones=[(self.f2, Decimal('100.00'))])
        self.f1.refresh_from_db(); self.f2.refresh_from_db()
        self.assertEqual(self.f1.monto_pagado, Decimal('0.00'))
        self.assertEqual(self.f2.monto_pagado, Decimal('100.00'))

    def test_editar_conserva_comprobante_si_no_se_envia_uno(self):
        comp = SimpleUploadedFile('c.pdf', b'x', content_type='application/pdf')
        pago = payment_service.registrar_abono(
            self.cli, fecha_pago=self.hoy, metodo_pago=self.met,
            monto=Decimal('100.00'), comprobante=comp)
        nombre = pago.comprobante.name
        self.assertTrue(nombre)
        payment_service.editar_abono(
            pago, fecha_pago=self.hoy, metodo_pago=self.met,
            monto=Decimal('120.00'), comprobante=None)
        pago.refresh_from_db()
        self.assertEqual(pago.comprobante.name, nombre)
