from django.test import TestCase

from apps.core.models import CategoriaProducto


class CategoriaProductoTests(TestCase):
    def test_str_y_defaults(self):
        c = CategoriaProducto.objects.create(nombre='Camiseta', palabra_clave='camiseta')
        self.assertEqual(str(c), 'Camiseta')
        self.assertTrue(c.activa)
        self.assertFalse(c.es_predeterminada)
        self.assertEqual(c.orden, 0)

    def test_una_sola_predeterminada(self):
        a = CategoriaProducto.objects.create(nombre='Lisa', es_predeterminada=True)
        b = CategoriaProducto.objects.create(nombre='Camiseta', es_predeterminada=True)
        a.refresh_from_db()
        self.assertFalse(a.es_predeterminada)
        self.assertTrue(b.es_predeterminada)
        self.assertEqual(CategoriaProducto.predeterminada(), b)

    def test_predeterminada_none_si_ninguna(self):
        CategoriaProducto.objects.all().delete()
        CategoriaProducto.objects.create(nombre='Otro')
        self.assertIsNone(CategoriaProducto.predeterminada())
