from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.core.models import Cliente, DocumentoFactura, MetodoPago, Pago, AplicacionPago
from apps.core.services.facturas import status_service


class StatusServiceTests(TestCase):
    def setUp(self):
        self.cliente = Cliente.objects.create(nombre='Cli')
        self.hoy = timezone.localdate()

    def _doc(self, total, venc):
        return DocumentoFactura.objects.create(
            cliente=self.cliente, tipo_documento='factura',
            fecha_documento=self.hoy, fecha_vencimiento=venc,
            monto_total=Decimal(total),
        )

    def test_pendiente_si_no_vencida_y_con_saldo(self):
        doc = self._doc('100.00', self.hoy + timedelta(days=10))
        self.assertEqual(status_service.calcular_estado_pago(doc), 'pendiente')

    def test_vencida_si_pasada_la_fecha_y_con_saldo(self):
        doc = self._doc('100.00', self.hoy - timedelta(days=1))
        self.assertEqual(status_service.calcular_estado_pago(doc), 'vencida')

    def test_pagada_si_saldo_cero(self):
        doc = self._doc('100.00', self.hoy - timedelta(days=1))
        met = MetodoPago.objects.create(nombre='Efectivo', tipo='efectivo')
        pago = Pago.objects.create(cliente=self.cliente, fecha_pago=self.hoy,
                                   metodo_pago=met, monto=Decimal('100.00'))
        AplicacionPago.objects.create(pago=pago, documento=doc, monto=Decimal('100.00'))
        self.assertEqual(status_service.calcular_estado_pago(doc), 'pagada')

    def test_anulada_no_se_sobrescribe(self):
        doc = self._doc('100.00', self.hoy - timedelta(days=1))
        doc.estado_pago = 'anulada'
        self.assertEqual(status_service.calcular_estado_pago(doc), 'anulada')

    def test_actualizar_persiste(self):
        doc = self._doc('100.00', self.hoy + timedelta(days=10))
        status_service.actualizar_estado_pago(doc)
        doc.refresh_from_db()
        self.assertEqual(doc.estado_pago, 'pendiente')

    def test_actualizar_no_persiste_si_guardar_false(self):
        doc = self._doc('100.00', self.hoy - timedelta(days=1))  # vencida en DB tras crear
        # estado en DB es 'pendiente' (default al crear); en memoria lo dejamos así
        doc.refresh_from_db()
        estado_dom = status_service.actualizar_estado_pago(doc, guardar=False)
        self.assertEqual(estado_dom, 'vencida')   # cálculo correcto devuelto
        recargado = type(doc).objects.get(pk=doc.pk)
        self.assertEqual(recargado.estado_pago, 'pendiente')  # NO se persistió

    def test_monto_cero_no_es_pagada(self):
        # Un documento sin monto (p. ej. sin montos extraídos) no debe quedar "pagada".
        doc = DocumentoFactura.objects.create(
            cliente=self.cliente, tipo_documento='factura',
            fecha_documento=self.hoy, monto_total=Decimal('0'),
        )
        self.assertEqual(status_service.calcular_estado_pago(doc), 'pendiente')
