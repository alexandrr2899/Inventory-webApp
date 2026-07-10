from decimal import Decimal

from django.contrib.auth.models import Permission, User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Cliente, DocumentoFactura


@override_settings(FACTURAS_MODULE_ENABLED=True, ALLOWED_HOSTS=['testserver', 'localhost'])
class ClienteTabTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='admin', password='pass12345')
        self.admin.user_permissions.add(Permission.objects.get(codename='ver_facturas'))
        self.cliente = Cliente.objects.create(nombre='Renato Díaz')
        DocumentoFactura.objects.create(
            cliente=self.cliente, tipo_documento='factura',
            numero_documento='F-1', fecha_documento=timezone.localdate(),
            monto_total=Decimal('100.00'),
        )
        DocumentoFactura.objects.create(
            cliente=self.cliente, tipo_documento='envio',
            numero_documento='E-1', fecha_documento=timezone.localdate(),
            monto_total=Decimal('50.00'),
        )

    def test_fragmento_muestra_documentos(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('cliente_facturas_fragment', args=[self.cliente.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'F-1')
        self.assertContains(resp, 'E-1')

    def test_filtra_solo_envios(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('cliente_facturas_fragment', args=[self.cliente.pk]), {'tipo': 'envio'})
        self.assertContains(resp, 'E-1')
        self.assertNotContains(resp, 'F-1')

    def test_fragmento_muestra_saldo_a_favor(self):
        from apps.core.models import MetodoPago
        from apps.core.services.facturas import payment_service
        met = MetodoPago.objects.create(nombre='Efectivo', tipo='efectivo')
        # setUp crea documentos por L 150.00 total; un abono de 200 deja 50 como saldo a favor.
        payment_service.registrar_abono(
            self.cliente, fecha_pago=timezone.localdate(), metodo_pago=met, monto=Decimal('200.00'))
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('cliente_facturas_fragment', args=[self.cliente.pk]))
        # Asevera el valor renderizado (L {{ cliente.saldo_a_favor }} sin filtro moneda)
        self.assertContains(resp, 'L 50.00')

    def test_detalle_muestra_aplicacion_y_pago_rapido(self):
        from decimal import Decimal
        from apps.core.models import MetodoPago
        self.admin.user_permissions.add(Permission.objects.get(codename='registrar_pago_factura'))
        met = MetodoPago.objects.create(nombre='Transferencia', tipo='transferencia')
        doc = DocumentoFactura.objects.filter(cliente=self.cliente, tipo_documento='factura').first()
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse('factura_pago_nuevo', args=[doc.pk]),
            {'metodo_pago': met.pk, 'monto': '50.00', 'fecha_pago': str(timezone.localdate())},
        )
        self.assertEqual(resp.status_code, 302)
        doc.refresh_from_db()
        self.assertEqual(doc.monto_pagado, Decimal('50.00'))
        resp = self.client.get(reverse('factura_detalle', args=[doc.pk]))
        self.assertContains(resp, 'Transferencia')

    def test_tabla_abonos_muestra_acciones_con_permiso(self):
        from apps.core.models import MetodoPago
        from apps.core.services.facturas import payment_service
        self.admin.user_permissions.add(Permission.objects.get(codename='registrar_pago_factura'))
        met = MetodoPago.objects.create(nombre='Efectivo', tipo='efectivo')
        pago = payment_service.registrar_abono(
            self.cliente, fecha_pago=timezone.localdate(), metodo_pago=met, monto=Decimal('50.00'))
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('cliente_facturas_fragment', args=[self.cliente.pk]))
        self.assertContains(resp, reverse('cliente_abono_editar', args=[pago.pk]))
        self.assertContains(resp, reverse('cliente_abono_borrar', args=[pago.pk]))

    def test_tabla_abonos_oculta_acciones_sin_permiso(self):
        from apps.core.models import MetodoPago
        from apps.core.services.facturas import payment_service
        met = MetodoPago.objects.create(nombre='Efectivo', tipo='efectivo')
        pago = payment_service.registrar_abono(
            self.cliente, fecha_pago=timezone.localdate(), metodo_pago=met, monto=Decimal('50.00'))
        self.client.force_login(self.admin)  # solo tiene ver_facturas
        resp = self.client.get(reverse('cliente_facturas_fragment', args=[self.cliente.pk]))
        self.assertNotContains(resp, reverse('cliente_abono_borrar', args=[pago.pk]))
