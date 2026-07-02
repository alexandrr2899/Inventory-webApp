from django.test import TestCase

from apps.core.models import CategoriaProducto
from apps.core.services.facturas import invoice_service


class ClasificarCategoriaTests(TestCase):
    def setUp(self):
        # La migración de siembra crea categorías; limpiamos para controlar el escenario.
        CategoriaProducto.objects.all().delete()
        self.camiseta = CategoriaProducto.objects.create(
            nombre='Camiseta', palabra_clave='camiseta', orden=0)
        self.lisa = CategoriaProducto.objects.create(
            nombre='Lisa', palabra_clave='lisa', es_predeterminada=True, orden=1)

    def test_palabra_clave_coincide(self):
        c = invoice_service.clasificar_categoria('RENATO DIAZ Envio camiseta 126.pdf')
        self.assertEqual(c, self.camiseta)

    def test_sin_coincidencia_usa_predeterminada(self):
        c = invoice_service.clasificar_categoria('Antonio Sanchez 126.pdf')
        self.assertEqual(c, self.lisa)

    def test_categoria_nueva_con_su_palabra_clave(self):
        polo = CategoriaProducto.objects.create(nombre='Polo', palabra_clave='polo', orden=2)
        c = invoice_service.clasificar_categoria('Marvin Polo 77.pdf')
        self.assertEqual(c, polo)

    def test_inactiva_se_ignora(self):
        self.camiseta.activa = False
        self.camiseta.save(update_fields=['activa'])
        c = invoice_service.clasificar_categoria('X Envio camiseta 9.pdf')
        self.assertEqual(c, self.lisa)  # cae a la predeterminada
