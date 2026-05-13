from decimal import Decimal
from datetime import date, datetime

from django.contrib.auth.models import Permission, User
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Categoria, Conteo, ConteoDetalle, Item, Stock, Ubicacion
from .views import _calcular_tramos


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

    def test_tramo_noche_se_asigna_a_fecha_inicial(self):
        def aware(year, month, day, hour, minute):
            return timezone.make_aware(datetime(year, month, day, hour, minute))

        c_manana = Conteo.objects.create(
            fecha=date(2026, 5, 12),
            turno='manana',
            tipo_conteo='camiseta',
            fecha_hora_conteo=aware(2026, 5, 12, 8, 0),
            usuario=self.user,
        )
        c_tarde = Conteo.objects.create(
            fecha=date(2026, 5, 12),
            turno='tarde',
            tipo_conteo='camiseta',
            fecha_hora_conteo=aware(2026, 5, 12, 22, 59),
            usuario=self.user,
        )
        c_manana_sig = Conteo.objects.create(
            fecha=date(2026, 5, 13),
            turno='manana',
            tipo_conteo='camiseta',
            fecha_hora_conteo=aware(2026, 5, 13, 16, 25),
            usuario=self.user,
        )
        for conteo, cantidad in (
            (c_manana, Decimal('0')),
            (c_tarde, Decimal('5')),
            (c_manana_sig, Decimal('9')),
        ):
            ConteoDetalle.objects.create(
                conteo=conteo,
                item=self.item,
                ubicacion=Stock.objects.get(item=self.item).ubicacion,
                cantidad_contada=cantidad,
                cantidad_sistema_al_conteo=Decimal('0'),
            )

        tramos = _calcular_tramos(date(2026, 5, 12), date(2026, 5, 12))
        noche = [t for t in tramos if t['tipo'] == 'noche'][0]

        self.assertEqual(noche['fecha_asignada'], date(2026, 5, 12))
