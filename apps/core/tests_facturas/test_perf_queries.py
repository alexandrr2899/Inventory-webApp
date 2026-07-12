"""Regresión de rendimiento: las vistas de facturas no deben tener N+1 al
crecer el número de documentos (el conteo de consultas debe mantenerse constante).
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Permission, User
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Cliente, DocumentoFactura, MetodoPago
from apps.core.services.facturas import payment_service, estado_cuenta_service


@override_settings(FACTURAS_MODULE_ENABLED=True, ALLOWED_HOSTS=['testserver', 'localhost'])
class SinN1Tests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u', password='x')
        self.user.user_permissions.add(Permission.objects.get(codename='ver_facturas'))
        self.client.force_login(self.user)
        self.cli = Cliente.objects.create(nombre='Cli')
        self.met = MetodoPago.objects.create(nombre='Efectivo', tipo='efectivo')

    def _doc_con_pago(self, numero, monto='1000.00', pagar='400.00'):
        doc = DocumentoFactura.objects.create(
            cliente=self.cli, tipo_documento='factura', numero_documento=numero,
            fecha_documento=timezone.localdate(), total_libras=Decimal('100'),
            precio_por_libra=Decimal('10'), monto_total=Decimal(monto))
        payment_service.registrar_abono(
            self.cli, fecha_pago=timezone.localdate(), metodo_pago=self.met,
            monto=Decimal(pagar), aplicaciones=[(doc, Decimal(pagar))])
        return doc

    def _contar_consultas(self, url, params=None):
        with CaptureQueriesContext(connection) as ctx:
            resp = self.client.get(url, params or {})
        self.assertEqual(resp.status_code, 200)
        return len(ctx.captured_queries)

    def test_facturas_lista_no_escala_con_filas(self):
        for i in range(2):
            self._doc_con_pago(f'A{i}')
        n_2 = self._contar_consultas(reverse('facturas_lista'))
        for i in range(5):
            self._doc_con_pago(f'B{i}')
        n_7 = self._contar_consultas(reverse('facturas_lista'))
        self.assertEqual(
            n_2, n_7,
            f'La lista de facturas tiene N+1: {n_2} consultas con 2 docs vs {n_7} con 7.')

    def test_estado_cuenta_pdf_no_escala_con_filas(self):
        url = reverse('cliente_estado_cuenta', args=[self.cli.pk])
        for i in range(2):
            self._doc_con_pago(f'A{i}')
        n_2 = self._contar_consultas(url, {'format': 'pdf'})
        for i in range(5):
            self._doc_con_pago(f'B{i}')
        n_7 = self._contar_consultas(url, {'format': 'pdf'})
        self.assertEqual(
            n_2, n_7,
            f'El estado de cuenta tiene N+1: {n_2} consultas con 2 docs vs {n_7} con 7.')

    def test_servicio_build_conteo_constante(self):
        """El servicio build no debe consultar por fila (annotate + prefetch)."""
        hoy = timezone.localdate()
        for i in range(2):
            self._doc_con_pago(f'A{i}')
        with CaptureQueriesContext(connection) as ctx2:
            datos = estado_cuenta_service.build(self.cli, hoy - timedelta(days=1), hoy)
            _ = [f['pago'] for f in datos['filas']]  # fuerza lectura de monto_pagado
            _ = [f['fecha_cancelacion'] for f in datos['filas']]
        n_2 = len(ctx2.captured_queries)
        for i in range(5):
            self._doc_con_pago(f'B{i}')
        with CaptureQueriesContext(connection) as ctx7:
            datos = estado_cuenta_service.build(self.cli, hoy - timedelta(days=1), hoy)
            _ = [f['pago'] for f in datos['filas']]
            _ = [f['fecha_cancelacion'] for f in datos['filas']]
        n_7 = len(ctx7.captured_queries)
        self.assertEqual(n_2, n_7, f'build() tiene N+1: {n_2} vs {n_7} consultas.')
