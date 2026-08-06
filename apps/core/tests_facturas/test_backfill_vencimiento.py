"""Backfill de fecha_vencimiento (migración 0036).

Se ejecuta la función de la migración contra el registro real de modelos: es la única
forma de comprobar que los documentos ya cargados sin vencimiento quedan con fecha y
con el estado recalculado.
"""
from datetime import timedelta
from decimal import Decimal
from importlib import import_module

from django.apps import apps as registro_apps
from django.test import TestCase
from django.utils import timezone

from apps.core.models import Cliente, DocumentoFactura
from apps.core.services.facturas import clientes

# El módulo empieza con dígitos, así que no se puede importar con `from ... import`.
backfill = import_module('apps.core.migrations.0036_backfill_fecha_vencimiento').backfill


class BackfillVencimientoTests(TestCase):
    def setUp(self):
        self.hoy = timezone.localdate()
        self.contado = Cliente.objects.create(nombre='Contado viejo', dias_credito=0)
        self.credito = Cliente.objects.create(nombre='Crédito 30 viejo', dias_credito=30)

    def _doc(self, cliente, dias_atras, **extra):
        return DocumentoFactura.objects.create(
            cliente=cliente, tipo_documento='factura',
            fecha_documento=self.hoy - timedelta(days=dias_atras),
            monto_total=Decimal('100.00'), **extra)

    def test_contado_viejo_queda_vencido(self):
        doc = self._doc(self.contado, 3)
        self.assertIsNone(doc.fecha_vencimiento)
        backfill(registro_apps, None)
        doc.refresh_from_db()
        self.assertEqual(doc.fecha_vencimiento, self.hoy - timedelta(days=3))
        self.assertEqual(doc.estado_pago, 'vencida')

    def test_contado_de_hoy_sigue_pendiente(self):
        doc = self._doc(self.contado, 0)
        backfill(registro_apps, None)
        doc.refresh_from_db()
        self.assertEqual(doc.fecha_vencimiento, self.hoy)
        self.assertEqual(doc.estado_pago, 'pendiente')

    def test_usa_los_dias_de_credito_del_cliente(self):
        doc = self._doc(self.credito, 10)
        backfill(registro_apps, None)
        doc.refresh_from_db()
        self.assertEqual(doc.fecha_vencimiento, self.hoy + timedelta(days=20))
        self.assertEqual(doc.estado_pago, 'pendiente')

    def test_no_pisa_un_vencimiento_existente(self):
        doc = self._doc(self.contado, 3, fecha_vencimiento=self.hoy + timedelta(days=5))
        backfill(registro_apps, None)
        doc.refresh_from_db()
        self.assertEqual(doc.fecha_vencimiento, self.hoy + timedelta(days=5))

    def test_sin_identificar_se_deja_intacto(self):
        doc = self._doc(clientes.cliente_sin_identificar(), 3)
        backfill(registro_apps, None)
        doc.refresh_from_db()
        self.assertIsNone(doc.fecha_vencimiento)

    def test_anulada_no_cambia_de_estado(self):
        doc = self._doc(self.contado, 3, estado_pago='anulada')
        backfill(registro_apps, None)
        doc.refresh_from_db()
        self.assertEqual(doc.fecha_vencimiento, self.hoy - timedelta(days=3))
        self.assertEqual(doc.estado_pago, 'anulada')
