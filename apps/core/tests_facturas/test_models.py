from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.core.models import (
    Cliente, DocumentoFactura, TarifaCliente, MetodoPago, Pago, AplicacionPago,
    CategoriaProducto,
)


class EstaVencidaTests(TestCase):
    def setUp(self):
        self.cliente = Cliente.objects.create(nombre='Cli')
        self.hoy = timezone.localdate()
        self.met = MetodoPago.objects.create(nombre='Efectivo', tipo='efectivo')

    def _doc(self, venc, total='100.00', estado='pendiente'):
        return DocumentoFactura.objects.create(
            cliente=self.cliente, tipo_documento='factura',
            fecha_documento=self.hoy, fecha_vencimiento=venc,
            monto_total=Decimal(total), estado_pago=estado,
        )

    def test_vencida_si_pasada_con_saldo(self):
        self.assertTrue(self._doc(self.hoy - timedelta(days=1)).esta_vencida)

    def test_no_vencida_si_futura(self):
        self.assertFalse(self._doc(self.hoy + timedelta(days=5)).esta_vencida)

    def test_no_vencida_si_anulada(self):
        self.assertFalse(self._doc(self.hoy - timedelta(days=1), estado='anulada').esta_vencida)

    def test_no_vencida_si_pagada(self):
        doc = self._doc(self.hoy - timedelta(days=1))
        pago = Pago.objects.create(cliente=self.cliente, fecha_pago=self.hoy,
                                   metodo_pago=self.met, monto=Decimal('100.00'))
        AplicacionPago.objects.create(pago=pago, documento=doc, monto=Decimal('100.00'))
        doc.refresh_from_db()
        self.assertFalse(doc.esta_vencida)

    def test_no_vencida_sin_fecha_vencimiento(self):
        self.assertFalse(self._doc(None).esta_vencida)


class DocumentoFacturaPropsTests(TestCase):
    def setUp(self):
        self.cliente = Cliente.objects.create(nombre='Renato Díaz')
        self.met = MetodoPago.objects.create(nombre='Efectivo', tipo='efectivo')
        self.doc = DocumentoFactura.objects.create(
            cliente=self.cliente,
            tipo_documento='factura',
            numero_documento='F-001',
            fecha_documento=date(2026, 6, 1),
            fecha_vencimiento=date(2026, 6, 30),
            producto='otro',
            subtotal=Decimal('100.00'),
            isv=Decimal('15.00'),
            monto_total=Decimal('115.00'),
        )

    def test_sin_pagos_saldo_igual_total(self):
        self.assertEqual(self.doc.monto_pagado, Decimal('0.00'))
        self.assertEqual(self.doc.saldo_pendiente, Decimal('115.00'))
        self.assertFalse(self.doc.es_pago_parcial)

    def test_pagos_suman_y_saldo_baja(self):
        pago1 = Pago.objects.create(cliente=self.cliente, fecha_pago=date(2026, 6, 5),
                                    metodo_pago=self.met, monto=Decimal('40.00'))
        AplicacionPago.objects.create(pago=pago1, documento=self.doc, monto=Decimal('40.00'))
        pago2 = Pago.objects.create(cliente=self.cliente, fecha_pago=date(2026, 6, 6),
                                    metodo_pago=self.met, monto=Decimal('25.00'))
        AplicacionPago.objects.create(pago=pago2, documento=self.doc, monto=Decimal('25.00'))
        self.assertEqual(self.doc.monto_pagado, Decimal('65.00'))
        self.assertEqual(self.doc.saldo_pendiente, Decimal('50.00'))
        self.assertTrue(self.doc.es_pago_parcial)

    def test_vence_hoy_y_en_7_dias(self):
        hoy = timezone.localdate()
        self.doc.fecha_vencimiento = hoy
        self.assertTrue(self.doc.vence_hoy)
        self.doc.fecha_vencimiento = hoy + timedelta(days=5)
        self.assertTrue(self.doc.vence_en_7_dias)
        self.assertFalse(self.doc.vence_hoy)


class TarifaClienteTests(TestCase):
    def setUp(self):
        self.cliente = Cliente.objects.create(nombre='Renato Díaz')
        CategoriaProducto.objects.all().delete()
        self.camiseta = CategoriaProducto.objects.create(nombre='Camiseta', palabra_clave='camiseta')
        self.lisa = CategoriaProducto.objects.create(nombre='Lisa', palabra_clave='lisa')
        self.otro = CategoriaProducto.objects.create(nombre='Otro')

    def test_activa_para_devuelve_la_vigente(self):
        TarifaCliente.objects.create(
            cliente=self.cliente, categoria=self.camiseta,
            precio_por_libra=Decimal('32.00'), activa=True,
            fecha_inicio=date(2026, 1, 1),
        )
        TarifaCliente.objects.create(
            cliente=self.cliente, categoria=self.lisa,
            precio_por_libra=Decimal('29.50'), activa=True,
            fecha_inicio=date(2026, 1, 1),
        )
        t = TarifaCliente.activa_para(self.cliente, self.camiseta)
        self.assertIsNotNone(t)
        self.assertEqual(t.precio_por_libra, Decimal('32.00'))

    def test_activa_para_sin_tarifa_devuelve_none(self):
        self.assertIsNone(TarifaCliente.activa_para(self.cliente, self.otro))

    def test_inactiva_no_se_devuelve(self):
        TarifaCliente.objects.create(
            cliente=self.cliente, categoria=self.camiseta,
            precio_por_libra=Decimal('10.00'), activa=False,
            fecha_inicio=date(2026, 1, 1),
        )
        self.assertIsNone(TarifaCliente.activa_para(self.cliente, self.camiseta))
