from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User, Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Cliente, DocumentoFactura, MetodoPago, Pago
from apps.core.services.facturas import payment_service


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

    def _pago(self, monto, aplicaciones=None):
        return payment_service.registrar_abono(
            self.cli, fecha_pago=self.hoy, metodo_pago=self.met,
            monto=Decimal(monto), aplicaciones=aplicaciones)

    def test_editar_get_precarga_formulario(self):
        pago = self._pago('100.00')
        resp = self.client.get(reverse('cliente_abono_editar', args=[pago.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Editar abono')
        # La factura ya saldada por este pago aparece en el reparto para redistribuir.
        self.assertContains(resp, f'aplicar_{self.f1.pk}')

    def test_editar_post_actualiza_monto(self):
        pago = self._pago('100.00')  # cubre f1
        resp = self.client.post(reverse('cliente_abono_editar', args=[pago.pk]), {
            'fecha_pago': self.hoy.isoformat(), 'metodo_pago': self.met.pk,
            'monto': '200.00'})
        self.assertEqual(resp.status_code, 302)
        self.f1.refresh_from_db(); self.f2.refresh_from_db()
        self.assertEqual(self.f1.monto_pagado, Decimal('100.00'))
        self.assertEqual(self.f2.monto_pagado, Decimal('100.00'))

    def test_borrar_elimina_pago_y_recalcula(self):
        pago = self._pago('100.00')  # cubre f1
        self.f1.refresh_from_db()
        self.assertEqual(self.f1.estado_pago, 'pagada')
        resp = self.client.post(reverse('cliente_abono_borrar', args=[pago.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Pago.objects.filter(pk=pago.pk).exists())
        self.f1.refresh_from_db()
        self.assertEqual(self.f1.monto_pagado, Decimal('0.00'))
        self.assertEqual(self.f1.estado_pago, 'pendiente')

    def test_editar_sin_permiso_403(self):
        otro = User.objects.create_user('sinperm', password='x')
        otro.user_permissions.add(Permission.objects.get(codename='ver_facturas'))
        self.client.force_login(otro)
        pago = self._pago('100.00')
        resp = self.client.get(reverse('cliente_abono_editar', args=[pago.pk]))
        self.assertEqual(resp.status_code, 403)

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
