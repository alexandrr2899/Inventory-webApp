import os
import unittest
from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.core.services.facturas.pdf_extractors.factura_extractor import FacturaExtractor
from apps.core.services.facturas.pdf_extractors.envio_extractor import EnvioExtractor
from apps.core.services.facturas.pdf_extractors import base_extractor
from apps.core.services.facturas.pdf_extractors import filename_extractor


# ---------------------------------------------------------------------------
# Fixtures reales extraídos con PyMuPDF de los PDFs de muestra
# ---------------------------------------------------------------------------

REAL_FACTURA = (
    " \n2\n20x30\n1\n34.78\n1391.30\n24x37\n1\n34.78\n1391.30\n"
    "-----------\n-----------\n2,782.61\n--------\n417.39\n--------\n3,200.00\n"
    "0801-9019-164281\nInversiones Zaga\nTotal Unitario\nLb Bolsa Lisa\n"
    " TRES MIL DOSCIENTOS 00/100 \n23/06/2026\n80 \nLb Bolsa Lisa\n40\n40\n"
)

REAL_ENVIO = (
    " \nDIA\nMES\nAÑO\nCLIENTE\nSEÑOR(ES): \nTEL:\nDIRECCION: \nCANTIDAD\nFardos\n"
    "Grande\n7\nGrande Negra\n3\nMediana\n10\nTotal Lbs\n20\n126\n"
    "Certificado de Entrega\n23/06/2026\nRENATO DIAZ\nPRODUCTO\nTAMAÑO\nCANTIDAD\nLBS\n"
    "Camiseta\n350\nCamiseta\n150\nCamiseta\n500\nENTREGADO POR\nFIRMA ACEPTADO CLIENTE\n"
    "1000\nMarvin Reyes\n"
)


# ---------------------------------------------------------------------------
# HelpersTests — mantener (siguen válidos)
# ---------------------------------------------------------------------------

class HelpersTests(TestCase):
    def test_parse_decimal_con_separador_miles(self):
        self.assertEqual(base_extractor.parse_decimal('L 1,150.00'), Decimal('1150.00'))

    def test_parse_decimal_invalido(self):
        self.assertIsNone(base_extractor.parse_decimal('—'))

    def test_parse_fecha_dmy(self):
        self.assertEqual(base_extractor.parse_fecha('03/06/2026'), date(2026, 6, 3))


# ---------------------------------------------------------------------------
# FilenameExtractorTests
# ---------------------------------------------------------------------------

class FilenameExtractorTests(TestCase):
    def test_factura(self):
        d = filename_extractor.extraer_de_nombre('Fact 9543 Inversiones Zaga.pdf')
        self.assertEqual(d['tipo_documento'], 'factura')
        self.assertEqual(d['numero_documento'], '9543')
        self.assertEqual(d['cliente_nombre'], 'Inversiones Zaga')

    def test_envio(self):
        d = filename_extractor.extraer_de_nombre('RENATO DIAZ Envio camiseta 126.pdf')
        self.assertEqual(d['tipo_documento'], 'envio')
        self.assertEqual(d['numero_documento'], '126')
        self.assertEqual(d['producto'], 'camiseta')
        self.assertEqual(d['cliente_nombre'], 'RENATO DIAZ')


# ---------------------------------------------------------------------------
# FacturaRealTests — texto posicional real
# ---------------------------------------------------------------------------

class FacturaRealTests(TestCase):
    def test_montos(self):
        d = FacturaExtractor().extraer(REAL_FACTURA)
        self.assertEqual(d['fecha_documento'], date(2026, 6, 23))
        self.assertEqual(d['monto_total'], Decimal('3200.00'))
        self.assertEqual(d['subtotal'], Decimal('2782.61'))
        self.assertEqual(d['isv'], Decimal('417.39'))


# ---------------------------------------------------------------------------
# EnvioRealTests — texto posicional real
# ---------------------------------------------------------------------------

class EnvioRealTests(TestCase):
    def test_libras_y_fecha(self):
        d = EnvioExtractor().extraer(REAL_ENVIO)
        self.assertEqual(d['fecha_documento'], date(2026, 6, 23))
        self.assertEqual(d['total_libras'], Decimal('1000'))


# ---------------------------------------------------------------------------
# Integración opcional (skip si los PDFs de muestra no están presentes)
# ---------------------------------------------------------------------------

_BASE = os.path.join(
    os.path.dirname(__file__),
    '..', '..', '..', 'docs', 'facturas', 'samples',
)
_PDF_FACTURA = os.path.normpath(os.path.join(_BASE, 'Fact 9543 Inversiones Zaga.pdf'))
_PDF_ENVIO = os.path.normpath(os.path.join(_BASE, 'RENATO DIAZ Envio camiseta 126.pdf'))


class IntegracionFacturaTests(TestCase):
    @unittest.skipUnless(os.path.exists(_PDF_FACTURA), 'sample PDF ausente')
    def test_previsualizar_factura(self):
        from apps.core.services.facturas import invoice_service

        class FakeFile:
            name = _PDF_FACTURA

            def read(self):
                with open(_PDF_FACTURA, 'rb') as f:
                    return f.read()

            def tell(self):
                return 0

            def seek(self, pos):
                pass

        result = invoice_service.previsualizar('factura', FakeFile())
        datos = result['datos']
        self.assertEqual(datos.get('numero_documento'), '9543')
        self.assertEqual(datos.get('monto_total'), Decimal('3200.00'))
        self.assertEqual(datos.get('subtotal'), Decimal('2782.61'))
        self.assertEqual(datos.get('isv'), Decimal('417.39'))

    @unittest.skipUnless(os.path.exists(_PDF_ENVIO), 'sample PDF ausente')
    def test_previsualizar_envio(self):
        from apps.core.services.facturas import invoice_service

        class FakeFile:
            name = _PDF_ENVIO

            def read(self):
                with open(_PDF_ENVIO, 'rb') as f:
                    return f.read()

            def tell(self):
                return 0

            def seek(self, pos):
                pass

        result = invoice_service.previsualizar('envio', FakeFile())
        datos = result['datos']
        self.assertEqual(datos.get('numero_documento'), '126')
        self.assertEqual(datos.get('total_libras'), Decimal('1000'))
