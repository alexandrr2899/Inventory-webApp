from django.test import TestCase

from apps.core.models import MetodoPago


class MetodoPagoTests(TestCase):
    def test_str_es_el_nombre(self):
        m = MetodoPago.objects.create(nombre='Transferencia BAC', tipo='transferencia')
        self.assertEqual(str(m), 'Transferencia BAC')

    def test_defaults(self):
        m = MetodoPago.objects.create(nombre='Efectivo', tipo='efectivo')
        self.assertTrue(m.activo)
        self.assertEqual(m.orden, 0)

    def test_orden_por_orden_luego_nombre(self):
        MetodoPago.objects.create(nombre='B', tipo='otro', orden=1)
        MetodoPago.objects.create(nombre='A', tipo='otro', orden=1)
        MetodoPago.objects.create(nombre='Z', tipo='otro', orden=0)
        nombres = list(MetodoPago.objects.values_list('nombre', flat=True))
        self.assertEqual(nombres, ['Z', 'A', 'B'])
