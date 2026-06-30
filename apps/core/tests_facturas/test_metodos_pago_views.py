from django.contrib.auth.models import User, Permission
from django.test import TestCase
from django.urls import reverse

from apps.core.models import MetodoPago


class MetodosPagoViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u', password='x')
        self.user.user_permissions.add(
            Permission.objects.get(codename='gestionar_metodos_pago'))
        self.client.force_login(self.user)

    def test_crear_metodo(self):
        resp = self.client.post(reverse('metodo_pago_crear'), {
            'nombre': 'Transferencia BAC', 'tipo': 'transferencia', 'orden': 0})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(MetodoPago.objects.filter(nombre='Transferencia BAC').exists())

    def test_toggle_activo(self):
        m = MetodoPago.objects.create(nombre='Efectivo', tipo='efectivo')
        self.client.post(reverse('metodo_pago_toggle_activo', args=[m.pk]))
        m.refresh_from_db()
        self.assertFalse(m.activo)

    def test_sin_permiso_prohibido(self):
        User.objects.create_user('u2', password='x')
        self.client.logout(); self.client.force_login(User.objects.get(username='u2'))
        resp = self.client.get(reverse('metodo_pago_lista'))
        self.assertEqual(resp.status_code, 403)
