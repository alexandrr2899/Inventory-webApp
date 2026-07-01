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
        CategoriaProducto.objects.all().delete()

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

    def test_documento_sin_producto_queda_sin_categoria(self):
        doc = DocumentoFactura.objects.create(
            cliente=self.cli, tipo_documento='factura', producto='')
        categorias.sembrar_y_migrar(CategoriaProducto, DocumentoFactura, TarifaCliente)
        doc.refresh_from_db()
        self.assertIsNone(doc.categoria)

    def test_tarifa_sin_match_va_a_otro(self):
        tar = TarifaCliente.objects.create(
            cliente=self.cli, producto='', precio_por_libra=5)
        categorias.sembrar_y_migrar(CategoriaProducto, DocumentoFactura, TarifaCliente)
        tar.refresh_from_db()
        self.assertEqual(tar.categoria.nombre, 'Otro')
