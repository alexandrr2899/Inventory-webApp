import json

from django.contrib.auth.models import Permission, User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from apps.core.forms import ItemForm, UbicacionForm
from apps.core.models import Item, Ubicacion


class UbicacionJerarquicaTests(TestCase):
    def setUp(self):
        self.planta = Ubicacion.objects.create(nombre='Planta 1', tipo='planta')
        self.oficina = Ubicacion.objects.create(
            nombre='Oficina 1', tipo='oficina', padre=self.planta,
        )
        self.estante = Ubicacion.objects.create(
            nombre='Estante 1', tipo='estante', padre=self.oficina,
        )

    def test_construye_ruta_completa(self):
        self.assertEqual(
            self.estante.ruta_completa,
            'Planta 1 → Oficina 1 → Estante 1',
        )

    def test_impide_asignar_un_descendiente_como_padre(self):
        self.planta.padre = self.estante

        with self.assertRaises(ValidationError):
            self.planta.full_clean()

    def test_formulario_impide_ciclo_profundo(self):
        form = UbicacionForm(
            data={
                'nombre': self.planta.nombre,
                'tipo': self.planta.tipo,
                'padre': self.estante.pk,
                'descripcion': '',
            },
            instance=self.planta,
        )

        self.assertFalse(form.is_valid())
        self.assertIn('padre', form.errors)


class UbicacionPredeterminadaItemTests(TestCase):
    def setUp(self):
        self.planta = Ubicacion.objects.create(nombre='Planta 2', tipo='planta')
        self.item = Item.objects.create(
            codigo='CON-01', nombre='Consumible', tipo='consumible',
            unidad_medida='u',
        )

    def test_se_asigna_desde_el_formulario_del_item(self):
        form = ItemForm(data={
            'codigo': self.item.codigo,
            'nombre': self.item.nombre,
            'descripcion': '',
            'tipo': self.item.tipo,
            'categoria': '',
            'ubicacion_predeterminada': self.planta.pk,
            'unidad_medida': self.item.unidad_medida,
            'stock_minimo': '0',
            'activo': 'on',
        }, instance=self.item)

        self.assertTrue(form.is_valid(), form.errors)
        item = form.save()
        self.assertEqual(item.ubicacion_predeterminada, self.planta)

    def test_conteo_expone_ubicacion_asignada_para_el_qr(self):
        self.item.ubicacion_predeterminada = self.planta
        self.item.save(update_fields=['ubicacion_predeterminada'])
        user = User.objects.create_user('conteo-ubicacion', password='x')
        user.user_permissions.add(Permission.objects.get(codename='registrar_conteo'))
        self.client.force_login(user)

        response = self.client.get(reverse('conteo_nuevo'))

        self.assertEqual(response.status_code, 200)
        items = json.loads(response.context['all_items_json'])
        item_data = next(row for row in items if row['pk'] == self.item.pk)
        self.assertEqual(item_data['default_ub'], self.planta.pk)
        self.assertTrue(item_data['ubicacion_asignada'])
        ubicaciones = json.loads(response.context['ubicaciones_json'])
        self.assertIn(
            {'pk': self.planta.pk, 'nombre': 'Planta 2', 'tipo': 'Planta'},
            ubicaciones,
        )
