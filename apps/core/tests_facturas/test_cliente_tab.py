from datetime import date
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
