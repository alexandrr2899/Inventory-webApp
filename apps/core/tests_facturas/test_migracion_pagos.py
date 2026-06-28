from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.core.models import (
    Cliente, DocumentoFactura, PagoFactura, Pago, AplicacionPago, MetodoPago,
)
from apps.core.services.facturas import migracion


class MigracionPagosTests(TestCase):
    def setUp(self):
        self.cli = Cliente.objects.create(nombre='Cli')
        self.hoy = timezone.localdate()
        self.doc = DocumentoFactura.objects.create(
            cliente=self.cli, tipo_documento='factura', fecha_documento=self.hoy,
            monto_total=Decimal('100.00'),
        )
        PagoFactura.objects.create(
            documento=self.doc, fecha_pago=self.hoy, metodo_pago='transferencia',
            monto=Decimal('60.00'), referencia='REF1',
        )

    def test_convierte_pagofactura_en_pago_y_aplicacion(self):
        migracion.migrar_pagos_a_abonos(
            PagoFactura, Pago, AplicacionPago, MetodoPago,
        )
        self.assertEqual(Pago.objects.count(), 1)
        self.assertEqual(AplicacionPago.objects.count(), 1)
        pago = Pago.objects.get()
        self.assertEqual(pago.cliente, self.cli)
        self.assertEqual(pago.monto, Decimal('60.00'))
        self.assertEqual(pago.referencia, 'REF1')
        self.assertEqual(pago.metodo_pago.tipo, 'transferencia')
        apl = AplicacionPago.objects.get()
        self.assertEqual(apl.documento, self.doc)
        self.assertEqual(apl.monto, Decimal('60.00'))

    def test_reusa_metodo_existente_por_tipo(self):
        PagoFactura.objects.create(
            documento=self.doc, fecha_pago=self.hoy, metodo_pago='transferencia',
            monto=Decimal('40.00'),
        )
        migracion.migrar_pagos_a_abonos(PagoFactura, Pago, AplicacionPago, MetodoPago)
        # Dos pagos 'transferencia' → un solo MetodoPago
        self.assertEqual(MetodoPago.objects.filter(tipo='transferencia').count(), 1)
        self.assertEqual(Pago.objects.count(), 2)
