from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Permission, User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.models import (
    Cliente, DocumentoFactura, CategoriaProducto, MetodoPago,
)
from apps.core.services.facturas import payment_service


class ModeloCamposNuevosTests(TestCase):
    def test_documento_acepta_subcliente_y_categoria_color(self):
        cat = CategoriaProducto.objects.create(nombre='Camiseta', color='#FFA500')
        cli = Cliente.objects.create(nombre='Cli')
        doc = DocumentoFactura.objects.create(
            cliente=cli, tipo_documento='factura', categoria=cat,
            fecha_documento=timezone.localdate(), monto_total=Decimal('100.00'),
            subcliente='Johan')
        doc.refresh_from_db(); cat.refresh_from_db()
        self.assertEqual(doc.subcliente, 'Johan')
        self.assertEqual(cat.color, '#FFA500')

    def test_defaults_vacios(self):
        cat = CategoriaProducto.objects.create(nombre='Lisa')
        cli = Cliente.objects.create(nombre='Cli2')
        doc = DocumentoFactura.objects.create(
            cliente=cli, tipo_documento='factura', monto_total=Decimal('1.00'))
        self.assertEqual(doc.subcliente, '')
        self.assertEqual(cat.color, '')
