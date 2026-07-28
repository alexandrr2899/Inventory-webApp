from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User, Permission
from django.test import TestCase
from django.urls import reverse

from apps.core.models import (
    Cliente, DocumentoFactura, MetodoPago, Pago, AplicacionPago,
)


class MetodoPagoMovimientosTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u', password='x')
        self.user.user_permissions.add(
            Permission.objects.get(codename='gestionar_metodos_pago'))
        self.client.force_login(self.user)

        self.cli = Cliente.objects.create(nombre='Cli')
        self.efectivo = MetodoPago.objects.create(nombre='Efectivo', tipo='efectivo')
        self.transfer = MetodoPago.objects.create(nombre='Transferencia', tipo='transferencia')
        self.doc = DocumentoFactura.objects.create(
            cliente=self.cli, tipo_documento='factura',
            fecha_documento=date(2026, 7, 10), monto_total=Decimal('500.00'))

    def _pago(self, metodo, monto, fecha):
        return Pago.objects.create(
            cliente=self.cli, fecha_pago=fecha, metodo_pago=metodo, monto=Decimal(monto))

    def _url(self, metodo, **params):
        url = reverse('metodo_pago_movimientos', args=[metodo.pk])
        if params:
            url += '?' + '&'.join(f'{k}={v}' for k, v in params.items())
        return url

    def test_sin_permiso_prohibido(self):
        User.objects.create_user('u2', password='x')
        self.client.logout()
        self.client.force_login(User.objects.get(username='u2'))
        resp = self.client.get(self._url(self.efectivo))
        self.assertEqual(resp.status_code, 403)

    def test_solo_muestra_abonos_del_metodo(self):
        p_ef = self._pago(self.efectivo, '100.00', date(2026, 7, 15))
        p_tr = self._pago(self.transfer, '200.00', date(2026, 7, 15))
        resp = self.client.get(
            self._url(self.efectivo, desde='2026-07-01', hasta='2026-07-31'))
        self.assertEqual(resp.status_code, 200)
        pagos = list(resp.context['pagos'])
        self.assertIn(p_ef, pagos)
        self.assertNotIn(p_tr, pagos)

    def test_filtra_por_rango_de_fechas(self):
        dentro = self._pago(self.efectivo, '100.00', date(2026, 7, 15))
        fuera = self._pago(self.efectivo, '999.00', date(2026, 6, 20))
        resp = self.client.get(
            self._url(self.efectivo, desde='2026-07-01', hasta='2026-07-31'))
        pagos = list(resp.context['pagos'])
        self.assertIn(dentro, pagos)
        self.assertNotIn(fuera, pagos)

    def test_total_recibido_es_suma_del_rango(self):
        self._pago(self.efectivo, '100.00', date(2026, 7, 15))
        self._pago(self.efectivo, '50.00', date(2026, 7, 20))
        self._pago(self.efectivo, '999.00', date(2026, 6, 1))  # fuera del rango
        resp = self.client.get(
            self._url(self.efectivo, desde='2026-07-01', hasta='2026-07-31'))
        self.assertEqual(resp.context['total'], Decimal('150.00'))

    def test_rango_por_defecto_es_mes_actual(self):
        from django.utils import timezone
        hoy = timezone.localdate()
        dentro = self._pago(self.efectivo, '100.00', hoy)
        primero_mes = hoy.replace(day=1)
        resp = self.client.get(reverse('metodo_pago_movimientos', args=[self.efectivo.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['desde'], primero_mes)
        self.assertEqual(resp.context['hasta'], hoy)
        self.assertIn(dentro, list(resp.context['pagos']))

    def test_muestra_facturas_aplicadas(self):
        pago = self._pago(self.efectivo, '100.00', date(2026, 7, 15))
        AplicacionPago.objects.create(pago=pago, documento=self.doc, monto=Decimal('100.00'))
        resp = self.client.get(
            self._url(self.efectivo, desde='2026-07-01', hasta='2026-07-31'))
        self.assertContains(resp, self.doc.numero_documento or str(self.doc.pk))
