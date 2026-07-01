from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User, Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Cliente, DocumentoFactura, MetodoPago


class AbonoViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u', password='x')
        self.user.user_permissions.add(
            Permission.objects.get(codename='registrar_pago_factura'),
            Permission.objects.get(codename='ver_facturas'))
        self.client.force_login(self.user)
        self.cli = Cliente.objects.create(nombre='Cli')
        self.met = MetodoPago.objects.create(nombre='Efectivo', tipo='efectivo', activo=True)
        self.hoy = timezone.localdate()
        self.f1 = DocumentoFactura.objects.create(
            cliente=self.cli, tipo_documento='factura',
            fecha_documento=self.hoy - timedelta(days=5), monto_total=Decimal('100.00'))
        self.f2 = DocumentoFactura.objects.create(
            cliente=self.cli, tipo_documento='factura',
            fecha_documento=self.hoy, monto_total=Decimal('100.00'))

    def test_abono_auto_reparte_por_antiguedad(self):
        resp = self.client.post(reverse('cliente_abono_nuevo', args=[self.cli.pk]), {
            'fecha_pago': self.hoy.isoformat(), 'metodo_pago': self.met.pk,
            'monto': '150.00',
            # sin montos por factura -> auto reparto
        })
        self.assertEqual(resp.status_code, 302)
        self.f1.refresh_from_db(); self.f2.refresh_from_db()
        self.assertEqual(self.f1.monto_pagado, Decimal('100.00'))
        self.assertEqual(self.f2.monto_pagado, Decimal('50.00'))

    def test_abono_con_reparto_editado(self):
        resp = self.client.post(reverse('cliente_abono_nuevo', args=[self.cli.pk]), {
            'fecha_pago': self.hoy.isoformat(), 'metodo_pago': self.met.pk,
            'monto': '100.00',
            f'aplicar_{self.f1.pk}': '0',
            f'aplicar_{self.f2.pk}': '100.00',
        })
        self.assertEqual(resp.status_code, 302)
        self.f1.refresh_from_db(); self.f2.refresh_from_db()
        self.assertEqual(self.f1.monto_pagado, Decimal('0.00'))
        self.assertEqual(self.f2.monto_pagado, Decimal('100.00'))

    def test_abono_con_valor_invalido_no_revienta(self):
        resp = self.client.post(reverse('cliente_abono_nuevo', args=[self.cli.pk]), {
            'fecha_pago': self.hoy.isoformat(), 'metodo_pago': self.met.pk,
            'monto': '150.00',
            f'aplicar_{self.f1.pk}': 'abc',
        })
        self.assertEqual(resp.status_code, 302)
        self.f1.refresh_from_db(); self.f2.refresh_from_db()
        # La fila inválida se ignora y no cuenta como edición, así que se aplica
        # el auto-reparto por antigüedad: f1 (más antigua) recibe 100, f2 recibe 50.
        self.assertEqual(self.f1.monto_pagado, Decimal('100.00'))
        self.assertEqual(self.f2.monto_pagado, Decimal('50.00'))
