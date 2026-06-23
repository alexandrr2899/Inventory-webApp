from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, Permission, User
from django.test import TestCase, override_settings
from django.http import Http404
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Cliente, DocumentoFactura
from apps.core.views.common import facturas_enabled


@facturas_enabled
def _vista_dummy(request):
    from django.http import HttpResponse
    return HttpResponse('ok')


class InterruptorFacturasTests(TestCase):
    def setUp(self):
        self.rf = RequestFactory()

    @override_settings(FACTURAS_MODULE_ENABLED=False)
    def test_decorador_404_cuando_apagado(self):
        with self.assertRaises(Http404):
            _vista_dummy(self.rf.get('/'))

    @override_settings(FACTURAS_MODULE_ENABLED=True)
    def test_decorador_pasa_cuando_encendido(self):
        resp = _vista_dummy(self.rf.get('/'))
        self.assertEqual(resp.status_code, 200)


@override_settings(FACTURAS_MODULE_ENABLED=True, ALLOWED_HOSTS=['testserver', 'localhost'])
class FacturasVistasTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='admin', password='pass12345')
        perms = Permission.objects.filter(codename__in=[
            'ver_facturas', 'gestionar_facturas', 'registrar_pago_factura',
            'anular_factura', 'gestionar_tarifas',
        ])
        for p in perms:
            self.admin.user_permissions.add(p)
        self.operador = User.objects.create_user(username='oper', password='pass12345')
        self.cliente = Cliente.objects.create(nombre='Renato Díaz')

    def test_dashboard_requiere_permiso(self):
        self.client.force_login(self.operador)
        resp = self.client.get(reverse('facturas_dashboard'))
        self.assertEqual(resp.status_code, 403)

    def test_dashboard_admin_ok(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('facturas_dashboard'))
        self.assertEqual(resp.status_code, 200)

    @override_settings(FACTURAS_MODULE_ENABLED=False)
    def test_apagado_devuelve_404(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('facturas_dashboard'))
        self.assertEqual(resp.status_code, 404)

    def test_anular_marca_estado(self):
        self.client.force_login(self.admin)
        doc = DocumentoFactura.objects.create(
            cliente=self.cliente, tipo_documento='factura',
            fecha_documento=timezone.localdate(), monto_total=Decimal('50.00'),
        )
        resp = self.client.post(reverse('factura_anular', args=[doc.pk]))
        self.assertEqual(resp.status_code, 302)
        doc.refresh_from_db()
        self.assertEqual(doc.estado_pago, 'anulada')


@override_settings(FACTURAS_MODULE_ENABLED=True, ALLOWED_HOSTS=['testserver', 'localhost'])
class FacturasPagoTests(TestCase):
    def setUp(self):
        from apps.core.models import DocumentoFactura
        self.admin = User.objects.create_user(username='admin2', password='pass12345')
        for p in Permission.objects.filter(codename__in=['ver_facturas', 'registrar_pago_factura']):
            self.admin.user_permissions.add(p)
        self.cliente = Cliente.objects.create(nombre='Cli')
        self.doc = DocumentoFactura.objects.create(
            cliente=self.cliente, tipo_documento='factura',
            fecha_documento=timezone.localdate(), monto_total=Decimal('100.00'),
        )

    def test_registrar_pago_via_vista(self):
        self.client.force_login(self.admin)
        resp = self.client.post(reverse('factura_pago_nuevo', args=[self.doc.pk]), {
            'fecha_pago': timezone.localdate().isoformat(),
            'metodo_pago': 'efectivo', 'monto': '100.00', 'referencia': '', 'notas': '',
        })
        self.assertEqual(resp.status_code, 302)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.estado_pago, 'pagada')
