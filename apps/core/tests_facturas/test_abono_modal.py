from decimal import Decimal

from django.contrib.auth.models import Permission, User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Cliente, DocumentoFactura, MetodoPago, Pago

AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}


@override_settings(FACTURAS_MODULE_ENABLED=True, ALLOWED_HOSTS=['testserver', 'localhost'])
class AbonoModalTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u', password='x')
        for cod in ('ver_facturas', 'gestionar_facturas', 'registrar_pago_factura'):
            self.user.user_permissions.add(Permission.objects.get(codename=cod))
        self.client.force_login(self.user)
        self.met = MetodoPago.objects.create(nombre='Efectivo', tipo='efectivo')
        self.cli = Cliente.objects.create(nombre='Renato')
        self.doc = DocumentoFactura.objects.create(
            cliente=self.cli, tipo_documento='factura', numero_documento='9543',
            fecha_documento=timezone.localdate(), monto_total=Decimal('1000'))
        self.url = reverse('cliente_abono_nuevo', args=[self.cli.pk])

    def test_get_ajax_devuelve_fragmento(self):
        resp = self.client.get(self.url, **AJAX)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'data-abono-form')
        self.assertContains(resp, 'name="foto_comprobante"')
        self.assertContains(resp, 'capture="environment"')
        self.assertNotContains(resp, '<nav')  # no es la página completa

    def test_post_ajax_registra_y_devuelve_json(self):
        resp = self.client.post(self.url, {
            'fecha_pago': timezone.localdate().isoformat(),
            'metodo_pago': self.met.pk, 'monto': '400',
        }, **AJAX)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['ok'])
        self.assertEqual(Pago.objects.filter(cliente=self.cli).count(), 1)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.saldo_pendiente, Decimal('600'))

    def test_post_ajax_invalido_devuelve_errores(self):
        resp = self.client.post(self.url, {'monto': ''}, **AJAX)
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.json()['ok'])
        self.assertIn('monto', resp.json()['errors'])

    def test_post_normal_sigue_redirigiendo(self):
        resp = self.client.post(self.url, {
            'fecha_pago': timezone.localdate().isoformat(),
            'metodo_pago': self.met.pk, 'monto': '400',
        })
        self.assertEqual(resp.status_code, 302)

    def test_tab_cliente_boton_abre_modal(self):
        resp = self.client.get(reverse('cliente_facturas_fragment', args=[self.cli.pk]))
        self.assertContains(resp, 'data-abrir-abono')

    def test_base_incluye_contenedor_modal(self):
        resp = self.client.get(reverse('dashboard'))
        self.assertContains(resp, 'id="abonoModal"')
