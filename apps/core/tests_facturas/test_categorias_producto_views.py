from django.contrib.auth.models import User, Permission
from django.test import TestCase
from django.urls import reverse

from apps.core.models import CategoriaProducto


class CategoriasProductoViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u', password='x')
        self.user.user_permissions.add(
            Permission.objects.get(codename='gestionar_categorias_producto'))
        self.client.force_login(self.user)

    def test_crear(self):
        resp = self.client.post(reverse('categoria_producto_crear'), {
            'nombre': 'Polo', 'palabra_clave': 'polo', 'orden': 0})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(CategoriaProducto.objects.filter(nombre='Polo').exists())

    def test_toggle(self):
        c = CategoriaProducto.objects.create(nombre='Lisa')
        self.client.post(reverse('categoria_producto_toggle_activo', args=[c.pk]))
        c.refresh_from_db()
        self.assertFalse(c.activa)

    def test_sin_permiso_403(self):
        self.client.logout()
        self.client.force_login(User.objects.create_user('u2', password='x'))
        resp = self.client.get(reverse('categoria_producto_lista'))
        self.assertEqual(resp.status_code, 403)
