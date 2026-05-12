from decimal import Decimal

from django.contrib.auth.models import Permission, User
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Categoria, Item, Stock, Ubicacion


@override_settings(ALLOWED_HOSTS=['testserver', 'localhost'])
class VistasOperativasTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username='operador', password='pass12345')
        for codename in ('ver_inventario', 'ver_reportes'):
            self.user.user_permissions.add(Permission.objects.get(codename=codename))

        categoria = Categoria.objects.create(nombre='Camiseta')
        self.item = Item.objects.create(
            codigo='CG',
            nombre='Bolsa Camiseta Grande',
            tipo='producto',
            categoria=categoria,
            unidad_medida='fardos',
            stock_minimo=Decimal('10'),
        )
        ubicacion = Ubicacion.objects.create(nombre='Bodega', tipo='bodega')
        Stock.objects.create(item=self.item, ubicacion=ubicacion, cantidad_actual=Decimal('5'))

    def test_dashboard_autenticado_responde(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)

    def test_inventario_responde_con_permiso(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('inventario_lista'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Bolsa Camiseta Grande')

    def test_movimientos_responde_con_paginacion(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('movimiento_lista'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('page_obj', response.context)

    def test_reporte_stock_bajo_responde(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('reporte_stock_bajo'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Bolsa Camiseta Grande')

    def test_alertas_responde_y_muestra_stock_bajo(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('alertas_centro'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Bolsa Camiseta Grande')

    def test_alertas_sin_permiso_devuelve_403(self):
        user = User.objects.create_user(username='sin_permiso', password='pass12345')
        self.client.force_login(user)
        response = self.client.get(reverse('alertas_centro'))
        self.assertEqual(response.status_code, 403)
