from django.contrib.auth.models import User, Permission
from django.test import TestCase
from django.urls import reverse

from apps.core.models import Item


class ItemQrPngTests(TestCase):
    def setUp(self):
        self.item = Item.objects.create(
            codigo='R-001', nombre='Rodamiento', tipo='repuesto', unidad_medida='u')
        self.user = User.objects.create_user('u', password='x')
        self.user.user_permissions.add(Permission.objects.get(codename='ver_inventario'))

    def test_devuelve_png(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('item_qr_png', args=[self.item.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'image/png')
        self.assertEqual(resp.content[:8], b'\x89PNG\r\n\x1a\n')

    def test_sin_permiso_403(self):
        otro = User.objects.create_user('u2', password='x')
        self.client.force_login(otro)
        resp = self.client.get(reverse('item_qr_png', args=[self.item.pk]))
        self.assertEqual(resp.status_code, 403)

    def test_item_inexistente_404(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('item_qr_png', args=[999999]))
        self.assertEqual(resp.status_code, 404)


class ItemDetalleQrTests(TestCase):
    def setUp(self):
        self.item = Item.objects.create(
            codigo='R-002', nombre='Faja', tipo='consumible', unidad_medida='u')
        self.user = User.objects.create_user('v', password='x')
        self.user.user_permissions.add(Permission.objects.get(codename='ver_inventario'))
        self.client.force_login(self.user)

    def test_ficha_incluye_img_del_qr(self):
        resp = self.client.get(reverse('item_detalle', args=[self.item.pk]))
        self.assertEqual(resp.status_code, 200)
        qr_url = reverse('item_qr_png', args=[self.item.pk])
        self.assertContains(resp, qr_url)


class ItemEtiquetasTests(TestCase):
    def setUp(self):
        self.rep = Item.objects.create(codigo='R-1', nombre='Rep', tipo='repuesto', unidad_medida='u')
        self.con = Item.objects.create(codigo='C-1', nombre='Con', tipo='consumible', unidad_medida='u')
        self.prod = Item.objects.create(codigo='P-1', nombre='Prod', tipo='producto', unidad_medida='u')
        self.inactivo = Item.objects.create(
            codigo='X-1', nombre='Inactivo', tipo='repuesto', unidad_medida='u', activo=False)
        self.user = User.objects.create_user('w', password='x')
        self.user.user_permissions.add(Permission.objects.get(codename='ver_inventario'))
        self.client.force_login(self.user)

    def test_por_defecto_solo_repuestos_y_consumibles(self):
        resp = self.client.get(reverse('item_etiquetas'))
        self.assertEqual(resp.status_code, 200)
        items = list(resp.context['items'])
        self.assertIn(self.rep, items)
        self.assertIn(self.con, items)
        self.assertNotIn(self.prod, items)
        self.assertNotIn(self.inactivo, items)

    def test_filtro_tipo_producto(self):
        resp = self.client.get(reverse('item_etiquetas'), {'tipo': 'producto'})
        items = list(resp.context['items'])
        self.assertEqual(items, [self.prod])

    def test_filtro_todos(self):
        resp = self.client.get(reverse('item_etiquetas'), {'tipo': 'todos'})
        items = list(resp.context['items'])
        self.assertEqual(set(items), {self.rep, self.con, self.prod})

    def test_sin_permiso_403(self):
        self.client.logout()
        self.client.force_login(User.objects.create_user('w2', password='x'))
        resp = self.client.get(reverse('item_etiquetas'))
        self.assertEqual(resp.status_code, 403)
