from django.test import TestCase

from apps.core.models import (
    Cliente, DocumentoFactura, TarifaCliente, CategoriaProducto,
)
from apps.core.services.facturas import categorias


class MigracionCategoriasTests(TestCase):
    def setUp(self):
        self.cli = Cliente.objects.create(nombre='Cli')
        self.doc = DocumentoFactura.objects.create(
            cliente=self.cli, tipo_documento='envio', producto='camiseta')
        self.tar = TarifaCliente.objects.create(
            cliente=self.cli, producto='lisa', precio_por_libra=10)

    def test_siembra_tres_categorias_con_predeterminada_lisa(self):
        categorias.sembrar_y_migrar(CategoriaProducto, DocumentoFactura, TarifaCliente)
        nombres = set(CategoriaProducto.objects.values_list('nombre', flat=True))
        self.assertEqual(nombres, {'Camiseta', 'Lisa', 'Otro'})
        self.assertEqual(CategoriaProducto.predeterminada().nombre, 'Lisa')

    def test_mapea_strings_a_fk(self):
        categorias.sembrar_y_migrar(CategoriaProducto, DocumentoFactura, TarifaCliente)
        self.doc.refresh_from_db(); self.tar.refresh_from_db()
        self.assertEqual(self.doc.categoria.nombre, 'Camiseta')
        self.assertEqual(self.tar.categoria.nombre, 'Lisa')
