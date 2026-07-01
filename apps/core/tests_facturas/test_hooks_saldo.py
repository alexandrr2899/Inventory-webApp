from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User, Permission
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Cliente, DocumentoFactura, MetodoPago
from apps.core.services.facturas import payment_service


@override_settings(FACTURAS_MODULE_ENABLED=True, ALLOWED_HOSTS=['testserver', 'localhost'])
class HooksSaldoTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u', password='x')
        self.user.user_permissions.add(
            Permission.objects.get(codename='anular_factura'),
            Permission.objects.get(codename='ver_facturas'),
            Permission.objects.get(codename='gestionar_facturas'),
        )
        self.client.force_login(self.user)
        self.cli = Cliente.objects.create(nombre='Cli')
        self.met = MetodoPago.objects.create(nombre='Efectivo', tipo='efectivo')
        self.hoy = timezone.localdate()

    def test_anular_factura_libera_aplicaciones_a_saldo_a_favor(self):
        doc = DocumentoFactura.objects.create(
            cliente=self.cli, tipo_documento='factura', fecha_documento=self.hoy,
            monto_total=Decimal('100.00'))
        payment_service.registrar_abono(
            self.cli, fecha_pago=self.hoy, metodo_pago=self.met,
            monto=Decimal('100.00'), aplicaciones=[(doc, Decimal('100.00'))])
        self.client.post(reverse('factura_anular', args=[doc.pk]))
        doc.refresh_from_db()
        self.assertEqual(doc.estado_pago, 'anulada')
        self.assertEqual(doc.monto_pagado, Decimal('0.00'))
        self.cli.refresh_from_db()
        self.assertEqual(self.cli.saldo_a_favor, Decimal('100.00'))

    def test_factura_editar_aplica_saldo_a_favor(self):
        """Al editar una factura con monto_total > 0, el saldo a favor del cliente se aplica."""
        # Crear factura 1 con monto 100 y un pago de 250 => 150 queda como saldo a favor
        f1 = DocumentoFactura.objects.create(
            cliente=self.cli, tipo_documento='factura', fecha_documento=self.hoy,
            monto_total=Decimal('100.00'))
        payment_service.registrar_abono(
            self.cli, fecha_pago=self.hoy, metodo_pago=self.met,
            monto=Decimal('250.00'), aplicaciones=[(f1, Decimal('100.00'))])
        # Confirmar 150 de saldo a favor
        self.assertEqual(self.cli.saldo_a_favor, Decimal('150.00'))

        # Crear factura nueva con monto_total=0 (pendiente de revisión)
        f2 = DocumentoFactura.objects.create(
            cliente=self.cli, tipo_documento='factura', fecha_documento=self.hoy,
            monto_total=Decimal('0.00'))
        self.assertEqual(f2.monto_pagado, Decimal('0.00'))

        # POST a factura_editar con monto_total=60
        url = reverse('factura_editar', args=[f2.pk])
        resp = self.client.post(url, {
            'cliente': self.cli.pk,
            'tipo_documento': 'factura',
            'numero_documento': 'F-0002',
            'fecha_documento': self.hoy.isoformat(),
            'fecha_vencimiento': '',
            'producto': '',
            'total_libras': '',
            'precio_por_libra': '',
            'subtotal': '0',
            'isv': '0',
            'monto_total': '60.00',
            'estado_revision': 'pendiente',
            'notas': '',
        })
        # Should redirect (302) on success
        self.assertEqual(resp.status_code, 302, 'La edicion deberia redirigir (form valido)')

        f2.refresh_from_db()
        self.assertEqual(f2.monto_pagado, Decimal('60.00'),
                         'El saldo a favor deberia haberse aplicado automaticamente')
        self.assertEqual(f2.estado_pago, 'pagada',
                         'La factura deberia quedar pagada por el saldo a favor')
        self.cli.refresh_from_db()
        self.assertEqual(self.cli.saldo_a_favor, Decimal('90.00'),
                         'El saldo restante deberia ser 150 - 60 = 90')
