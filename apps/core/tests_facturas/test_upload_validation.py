"""Validación de archivos subidos (extensión, tamaño, magic bytes)."""
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.core.models import Cliente, MetodoPago
from apps.core.forms import (
    DocumentoUploadForm, PagoFacturaForm, AbonoClienteForm, ImportarItemsForm,
)


class UploadValidationTests(TestCase):
    def setUp(self):
        self.cli = Cliente.objects.create(nombre='Cli')
        self.met = MetodoPago.objects.create(nombre='Efectivo', tipo='efectivo')

    # ── Factura PDF ────────────────────────────────────────────────────────────
    def test_documento_acepta_pdf_valido(self):
        form = DocumentoUploadForm(
            {'cliente': self.cli.pk},
            {'archivo_pdf': SimpleUploadedFile('f.pdf', b'%PDF-1.4 hola',
                                               content_type='application/pdf')})
        self.assertTrue(form.is_valid(), form.errors)

    def test_documento_rechaza_extension_invalida(self):
        form = DocumentoUploadForm(
            {'cliente': self.cli.pk},
            {'archivo_pdf': SimpleUploadedFile('malo.exe', b'%PDF-1.4')})
        self.assertFalse(form.is_valid())
        self.assertIn('archivo_pdf', form.errors)

    def test_documento_rechaza_pdf_falso(self):
        # Extensión .pdf pero sin la cabecera %PDF.
        form = DocumentoUploadForm(
            {'cliente': self.cli.pk},
            {'archivo_pdf': SimpleUploadedFile('x.pdf', b'esto no es un pdf')})
        self.assertFalse(form.is_valid())
        self.assertIn('archivo_pdf', form.errors)

    def test_documento_rechaza_demasiado_grande(self):
        grande = SimpleUploadedFile('x.pdf', b'%PDF-1.4')
        grande.size = 26 * 1024 * 1024  # supera el límite de 25 MB
        form = DocumentoUploadForm({'cliente': self.cli.pk}, {'archivo_pdf': grande})
        self.assertFalse(form.is_valid())
        self.assertIn('archivo_pdf', form.errors)

    # ── Comprobante de pago (pdf o imagen) ──────────────────────────────────────
    def test_comprobante_acepta_imagen(self):
        form = PagoFacturaForm(
            {'fecha_pago': '2026-01-01', 'metodo_pago': self.met.pk, 'monto': '10.00'},
            {'comprobante': SimpleUploadedFile('recibo.jpg', b'\xff\xd8\xff',
                                               content_type='image/jpeg')})
        self.assertTrue(form.is_valid(), form.errors)

    def test_comprobante_rechaza_ejecutable(self):
        form = AbonoClienteForm(
            {'fecha_pago': '2026-01-01', 'metodo_pago': self.met.pk, 'monto': '10.00'},
            {'comprobante': SimpleUploadedFile('recibo.exe', b'MZ')})
        self.assertFalse(form.is_valid())
        self.assertIn('comprobante', form.errors)

    # ── Import Excel ────────────────────────────────────────────────────────────
    def test_excel_rechaza_extension_invalida(self):
        form = ImportarItemsForm({}, {'archivo': SimpleUploadedFile('x.txt', b'hola')})
        self.assertFalse(form.is_valid())
        self.assertIn('archivo', form.errors)
