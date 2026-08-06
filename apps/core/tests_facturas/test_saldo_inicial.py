"""Saldo inicial: la deuda que el cliente ya traía antes de llevar sus facturas aquí."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Permission, User
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Cliente, DocumentoFactura, MetodoPago
from apps.core.services.facturas import estado_cuenta_service, invoice_service, payment_service


class SaldoInicialServiceTests(TestCase):
    def setUp(self):
        self.hoy = timezone.localdate()
        self.cli = Cliente.objects.create(nombre='Viejo cliente', dias_credito=30)
        self.met = MetodoPago.objects.create(nombre='Efectivo', tipo='efectivo')

    def _apertura(self, monto='500.00', dias_atras=1):
        return invoice_service.registrar_saldo_inicial(
            self.cli, monto=Decimal(monto), fecha=self.hoy - timedelta(days=dias_atras))

    def test_suma_en_lo_adeudado(self):
        self._apertura()
        self.assertEqual(self.cli.total_adeudado, Decimal('500.00'))

    def test_vence_el_dia_del_corte_aunque_haya_credito(self):
        """Es deuda que ya venía corriendo: los 30 días de crédito no la aplazan."""
        doc = self._apertura(dias_atras=1)
        self.assertEqual(doc.fecha_vencimiento, self.hoy - timedelta(days=1))
        self.assertEqual(doc.estado_pago, 'vencida')

    def test_el_abono_la_cobra_antes_que_las_facturas_nuevas(self):
        apertura = self._apertura('500.00', dias_atras=10)
        nueva = DocumentoFactura.objects.create(
            cliente=self.cli, tipo_documento='factura',
            fecha_documento=self.hoy, monto_total=Decimal('300.00'))
        payment_service.registrar_abono(
            self.cli, fecha_pago=self.hoy, metodo_pago=self.met, monto=Decimal('600.00'))
        apertura.refresh_from_db(); nueva.refresh_from_db()
        self.assertEqual(apertura.monto_pagado, Decimal('500.00'))
        self.assertEqual(apertura.estado_pago, 'pagada')
        self.assertEqual(nueva.monto_pagado, Decimal('100.00'))

    def test_no_cuenta_como_venta_en_los_reportes(self):
        """Los reportes agregan por tipo con whitelist: la apertura no debe aparecer."""
        self._apertura('500.00', dias_atras=0)
        from apps.core.views.reportes import _totales_facturacion
        totales = _totales_facturacion(self.hoy, self.hoy)
        self.assertEqual(set(totales), {'factura', 'envio'})
        self.assertEqual(totales['factura']['total'], Decimal('0'))

    def test_sale_en_el_estado_de_cuenta(self):
        self._apertura('500.00', dias_atras=2)
        datos = estado_cuenta_service.build(
            self.cli, self.hoy - timedelta(days=5), self.hoy)
        etiquetas = [fila['etiqueta'] for fila in datos['filas']]
        self.assertIn('Saldo inicial', etiquetas)

    def test_solo_uno_por_cliente(self):
        self._apertura()
        with self.assertRaises(ValidationError):
            self._apertura()

    def test_usa_el_saldo_a_favor_que_ya_tenia(self):
        payment_service.registrar_abono(
            self.cli, fecha_pago=self.hoy, metodo_pago=self.met, monto=Decimal('200.00'))
        self.assertEqual(self.cli.saldo_a_favor, Decimal('200.00'))
        doc = self._apertura('500.00')
        doc.refresh_from_db()
        self.assertEqual(doc.monto_pagado, Decimal('200.00'))
        self.assertEqual(self.cli.total_adeudado, Decimal('300.00'))


@override_settings(FACTURAS_MODULE_ENABLED=True)
class SaldoInicialViewTests(TestCase):
    def setUp(self):
        self.hoy = timezone.localdate()
        self.user = User.objects.create_user('gestor', password='x')
        self.user.user_permissions.add(
            Permission.objects.get(codename='gestionar_facturas'),
            Permission.objects.get(codename='ver_facturas'))
        self.client.force_login(self.user)
        self.cli = Cliente.objects.create(nombre='Cli')
        self.url = reverse('cliente_saldo_inicial', args=[self.cli.pk])

    def test_registra_el_saldo(self):
        resp = self.client.post(self.url, {
            'monto': '750.00', 'fecha': self.hoy.isoformat(), 'notas': 'corte julio'})
        self.assertEqual(resp.status_code, 302)
        doc = DocumentoFactura.objects.get(cliente=self.cli, tipo_documento='apertura')
        self.assertEqual(doc.monto_total, Decimal('750.00'))
        self.assertEqual(doc.estado_revision, 'revisada')

    def test_segundo_intento_muestra_error(self):
        self.client.post(self.url, {'monto': '750.00', 'fecha': self.hoy.isoformat()})
        resp = self.client.post(self.url, {'monto': '100.00', 'fecha': self.hoy.isoformat()})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'ya tiene un saldo inicial')
        self.assertEqual(DocumentoFactura.objects.filter(tipo_documento='apertura').count(), 1)

    def test_monto_negativo_rechazado(self):
        resp = self.client.post(self.url, {'monto': '-5.00', 'fecha': self.hoy.isoformat()})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(DocumentoFactura.objects.exists())

    def test_sin_permiso_403(self):
        otro = User.objects.create_user('mirador', password='x')
        otro.user_permissions.add(Permission.objects.get(codename='ver_facturas'))
        self.client.force_login(otro)
        self.assertEqual(self.client.get(self.url).status_code, 403)
