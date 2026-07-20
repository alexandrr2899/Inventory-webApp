from decimal import Decimal

from django.contrib.auth.models import Permission, User
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.core.models import (
    Cliente, DocumentoFactura, MetodoPago, Pago, AplicacionPago,
)


@override_settings(FACTURAS_MODULE_ENABLED=True, ALLOWED_HOSTS=['testserver', 'localhost'])
class BuscarGlobalTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u', password='x')
        for cod in ('ver_facturas', 'registrar_pago_factura'):
            self.user.user_permissions.add(Permission.objects.get(codename=cod))
        self.client.force_login(self.user)
        self.url = reverse('buscar_global')
        self.met = MetodoPago.objects.create(nombre='Efectivo', tipo='efectivo')
        self.cli = Cliente.objects.create(nombre='Renato Díaz')
        self.doc = DocumentoFactura.objects.create(
            cliente=self.cli, tipo_documento='factura', numero_documento='9543',
            fecha_documento=timezone.localdate(), monto_total=Decimal('1000'))

    def test_q_corta_devuelve_vacio(self):
        data = self.client.get(self.url, {'q': 'a'}).json()
        self.assertEqual(data, {'clientes': [], 'facturas': []})

    def test_encuentra_cliente_por_nombre_con_saldo(self):
        data = self.client.get(self.url, {'q': 'Rena'}).json()
        self.assertEqual(len(data['clientes']), 1)
        c = data['clientes'][0]
        self.assertEqual(c['nombre'], 'Renato Díaz')
        self.assertEqual(Decimal(c['saldo']), Decimal('1000'))
        self.assertTrue(c['puede_abonar'])

    def test_saldo_descuenta_pagos(self):
        pago = Pago.objects.create(cliente=self.cli, fecha_pago=timezone.localdate(),
                                   metodo_pago=self.met, monto=Decimal('400'))
        AplicacionPago.objects.create(pago=pago, documento=self.doc, monto=Decimal('400'))
        data = self.client.get(self.url, {'q': 'Rena'}).json()
        self.assertEqual(Decimal(data['clientes'][0]['saldo']), Decimal('600'))

    def test_encuentra_factura_por_numero_y_excluye_anulada(self):
        data = self.client.get(self.url, {'q': '9543'}).json()
        self.assertEqual(len(data['facturas']), 1)
        self.assertEqual(data['facturas'][0]['numero'], '9543')
        self.doc.estado_pago = 'anulada'; self.doc.save(update_fields=['estado_pago'])
        data = self.client.get(self.url, {'q': '9543'}).json()
        self.assertEqual(data['facturas'], [])

    def test_403_sin_permiso(self):
        otro = User.objects.create_user('o', password='x')
        self.client.force_login(otro)
        self.assertEqual(self.client.get(self.url, {'q': 'Rena'}).status_code, 403)

    @override_settings(FACTURAS_MODULE_ENABLED=False)
    def test_404_modulo_apagado(self):
        self.assertEqual(self.client.get(self.url, {'q': 'Rena'}).status_code, 404)

    def test_sin_n_mas_1_en_clientes(self):
        def crear(n):
            AplicacionPago.objects.all().delete()
            Pago.objects.all().delete()
            DocumentoFactura.objects.all().delete()
            Cliente.objects.all().delete()
            for i in range(n):
                c = Cliente.objects.create(nombre=f'Clix {i}')
                DocumentoFactura.objects.create(
                    cliente=c, tipo_documento='factura', numero_documento=f'X{i}',
                    fecha_documento=timezone.localdate(), monto_total=Decimal('100'))
        crear(3)
        with CaptureQueriesContext(connection) as ctx3:
            self.client.get(self.url, {'q': 'Clix'})
        crear(6)
        with CaptureQueriesContext(connection) as ctx6:
            self.client.get(self.url, {'q': 'Clix'})
        self.assertEqual(len(ctx3.captured_queries), len(ctx6.captured_queries))
