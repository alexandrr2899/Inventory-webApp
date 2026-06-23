from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.core.services.facturas.pdf_extractors.factura_extractor import FacturaExtractor
from apps.core.services.facturas.pdf_extractors.envio_extractor import EnvioExtractor
from apps.core.services.facturas.pdf_extractors import base_extractor


TEXTO_FACTURA = """
EMPRESA TEXTIL S. DE R.L.
Factura No. F-2026-0042
Fecha: 03/06/2026
Cliente: Renato Díaz
Subtotal: L 1,000.00
ISV (15%): L 150.00
Total: L 1,150.00
"""

TEXTO_ENVIO = """
COMPROBANTE DE ENVÍO
Envío No. E-2026-0117
Fecha: 04/06/2026
Cliente: Renato Díaz
Producto: Camiseta
Total Libras: 85.50
"""


class HelpersTests(TestCase):
    def test_parse_decimal_con_separador_miles(self):
        self.assertEqual(base_extractor.parse_decimal('L 1,150.00'), Decimal('1150.00'))

    def test_parse_decimal_invalido(self):
        self.assertIsNone(base_extractor.parse_decimal('—'))

    def test_parse_fecha_dmy(self):
        self.assertEqual(base_extractor.parse_fecha('03/06/2026'), date(2026, 6, 3))


class FacturaExtractorTests(TestCase):
    def test_extrae_campos_clave(self):
        datos = FacturaExtractor().extraer(TEXTO_FACTURA)
        self.assertEqual(datos['numero_documento'], 'F-2026-0042')
        self.assertEqual(datos['fecha_documento'], date(2026, 6, 3))
        self.assertEqual(datos['subtotal'], Decimal('1000.00'))
        self.assertEqual(datos['isv'], Decimal('150.00'))
        self.assertEqual(datos['monto_total'], Decimal('1150.00'))


class EnvioExtractorTests(TestCase):
    def test_extrae_total_libras_y_numero(self):
        datos = EnvioExtractor().extraer(TEXTO_ENVIO)
        self.assertEqual(datos['numero_documento'], 'E-2026-0117')
        self.assertEqual(datos['fecha_documento'], date(2026, 6, 4))
        self.assertEqual(datos['total_libras'], Decimal('85.50'))
