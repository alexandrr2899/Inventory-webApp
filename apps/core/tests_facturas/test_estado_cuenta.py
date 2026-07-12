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
from apps.core.forms import DocumentoEditarForm, CategoriaProductoForm


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


class EstadoCuentaServiceTests(TestCase):
    def setUp(self):
        from apps.core.services.facturas import estado_cuenta_service
        self.svc = estado_cuenta_service
        self.hoy = timezone.localdate()
        self.cli = Cliente.objects.create(nombre='Renato')
        self.cat = CategoriaProducto.objects.create(nombre='Camiseta', color='#FFA500')
        self.met = MetodoPago.objects.create(nombre='Efectivo', tipo='efectivo')
        self.f1 = DocumentoFactura.objects.create(
            cliente=self.cli, tipo_documento='factura', categoria=self.cat,
            numero_documento='125', fecha_documento=self.hoy - timedelta(days=5),
            total_libras=Decimal('2500'), precio_por_libra=Decimal('36.00'),
            monto_total=Decimal('90000.00'), subcliente='Johan')
        self.e1 = DocumentoFactura.objects.create(
            cliente=self.cli, tipo_documento='envio',
            numero_documento='870', fecha_documento=self.hoy - timedelta(days=3),
            total_libras=Decimal('2400'), precio_por_libra=Decimal('37.50'),
            monto_total=Decimal('90000.00'))

    def test_incluye_rango_y_excluye_anuladas(self):
        anulada = DocumentoFactura.objects.create(
            cliente=self.cli, tipo_documento='factura', numero_documento='X',
            fecha_documento=self.hoy, monto_total=Decimal('50.00'), estado_pago='anulada')
        fuera = DocumentoFactura.objects.create(
            cliente=self.cli, tipo_documento='factura', numero_documento='Y',
            fecha_documento=self.hoy - timedelta(days=40), monto_total=Decimal('50.00'))
        datos = self.svc.build(self.cli, self.hoy - timedelta(days=10), self.hoy)
        etiquetas = [f['etiqueta'] for f in datos['filas']]
        self.assertIn('125', etiquetas)
        self.assertIn('Envio 870', etiquetas)   # los envíos llevan prefijo
        self.assertNotIn('X', etiquetas)         # anulada excluida
        self.assertNotIn('Y', etiquetas)         # fuera de rango

    def test_fila_lleva_subcliente_y_color(self):
        datos = self.svc.build(self.cli, self.hoy - timedelta(days=10), self.hoy)
        fila125 = next(f for f in datos['filas'] if f['etiqueta'] == '125')
        self.assertEqual(fila125['subcliente'], 'Johan')
        self.assertEqual(fila125['producto'], 'Camiseta')
        self.assertEqual(fila125['color'], '#FFA500')

    def test_fecha_cancelacion_solo_si_saldo_cero(self):
        # f1 sin pago -> None; e1 pagada completa -> fecha del abono
        payment_service.registrar_abono(
            self.cli, fecha_pago=self.hoy, metodo_pago=self.met,
            monto=Decimal('90000.00'), aplicaciones=[(self.e1, Decimal('90000.00'))])
        datos = self.svc.build(self.cli, self.hoy - timedelta(days=10), self.hoy)
        fila_f1 = next(f for f in datos['filas'] if f['etiqueta'] == '125')
        fila_e1 = next(f for f in datos['filas'] if f['etiqueta'] == 'Envio 870')
        self.assertIsNone(fila_f1['fecha_cancelacion'])
        self.assertEqual(fila_e1['fecha_cancelacion'], self.hoy)

    def test_totales_y_saldo(self):
        payment_service.registrar_abono(
            self.cli, fecha_pago=self.hoy, metodo_pago=self.met,
            monto=Decimal('40000.00'), aplicaciones=[(self.f1, Decimal('40000.00'))])
        datos = self.svc.build(self.cli, self.hoy - timedelta(days=10), self.hoy)
        t = datos['totales']
        self.assertEqual(t['libras'], Decimal('4900'))          # 2500 + 2400
        self.assertEqual(t['valor'], Decimal('180000.00'))      # 90000 + 90000
        self.assertEqual(t['pago'], Decimal('40000.00'))
        self.assertEqual(t['saldo'], Decimal('140000.00'))      # valor - pago


@override_settings(FACTURAS_MODULE_ENABLED=True, ALLOWED_HOSTS=['testserver', 'localhost'])
class EstadoCuentaViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u', password='x')
        self.user.user_permissions.add(Permission.objects.get(codename='ver_facturas'))
        self.cli = Cliente.objects.create(nombre='Renato Diaz')
        DocumentoFactura.objects.create(
            cliente=self.cli, tipo_documento='factura', numero_documento='125',
            fecha_documento=timezone.localdate(), total_libras=Decimal('2500'),
            precio_por_libra=Decimal('36.00'), monto_total=Decimal('90000.00'))

    def test_html_ok(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('cliente_estado_cuenta', args=[self.cli.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Estado de Cuenta')
        self.assertContains(resp, 'Renato Diaz')
        self.assertContains(resp, '125')

    def test_pdf_ok(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('cliente_estado_cuenta', args=[self.cli.pk]), {'format': 'pdf'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')
        self.assertTrue(resp.content.startswith(b'%PDF'))

    def test_sin_permiso_403(self):
        otro = User.objects.create_user('sinperm', password='x')
        self.client.force_login(otro)
        resp = self.client.get(reverse('cliente_estado_cuenta', args=[self.cli.pk]))
        self.assertEqual(resp.status_code, 403)

    def test_no_filtra_comentario_de_plantilla(self):
        """Los comentarios {# #} de la plantilla no deben aparecer en el HTML ni en el PDF."""
        self.client.force_login(self.user)
        html = self.client.get(reverse('cliente_estado_cuenta', args=[self.cli.pk]))
        self.assertNotContains(html, '{#')
        self.assertNotContains(html, 'Rótulos con colspan')
        import fitz  # PyMuPDF
        pdf = self.client.get(reverse('cliente_estado_cuenta', args=[self.cli.pk]), {'format': 'pdf'})
        texto = fitz.open(stream=pdf.content, filetype='pdf')[0].get_text()
        self.assertNotIn('{#', texto)
        self.assertNotIn('Rótulos con colspan', texto)

    def test_pdf_columnas_no_colapsan_y_saldo_en_una_linea(self):
        """Guarda contra la regresión de columnas colapsadas / rótulo partido en el PDF."""
        import fitz  # PyMuPDF
        self.client.force_login(self.user)
        resp = self.client.get(reverse('cliente_estado_cuenta', args=[self.cli.pk]), {'format': 'pdf'})
        page = fitz.open(stream=resp.content, filetype='pdf')[0]
        texto = page.get_text()
        for encabezado in ['Subcliente', 'Producto', 'Fact', 'Fecha', 'Lbs', 'Precio', 'Valor', 'Pago', 'Canc']:
            self.assertIn(encabezado, texto, f'Falta el encabezado {encabezado} en el PDF')
        # Posición de cada palabra: (x0, y0, x1, y1, palabra, ...)
        x0, y0 = {}, {}
        for w in page.get_text('words'):
            x0.setdefault(w[4], w[0])
            y0.setdefault(w[4], round(w[1]))
        # Valor y Pago son columnas de 92pt: si el PDF colapsa, se enciman (antes ~9pt).
        self.assertGreater(x0['Pago'] - x0['Valor'], 50,
                           'Columnas Valor/Pago encimadas: el PDF colapsó')
        # "Saldo Total" debe quedar en una sola línea.
        self.assertEqual(y0['Saldo'], y0['Total'], '"Saldo Total" quedó partido en dos líneas')


class CapturaCamposFormTests(TestCase):
    def test_documento_editar_form_guarda_subcliente(self):
        cli = Cliente.objects.create(nombre='Cli')
        doc = DocumentoFactura.objects.create(
            cliente=cli, tipo_documento='factura', monto_total=Decimal('100.00'))
        form = DocumentoEditarForm({
            'cliente': cli.pk, 'tipo_documento': 'factura', 'numero_documento': 'F-1',
            'estado_revision': 'pendiente', 'subtotal': '0', 'isv': '0',
            'monto_total': '100', 'subcliente': 'Johan',
        }, instance=doc)
        self.assertTrue(form.is_valid(), form.errors)
        guardado = form.save()
        self.assertEqual(guardado.subcliente, 'Johan')

    def test_categoria_form_guarda_color(self):
        form = CategoriaProductoForm({'nombre': 'Camiseta', 'orden': '0', 'color': '#FFA500'})
        self.assertTrue(form.is_valid(), form.errors)
        cat = form.save()
        self.assertEqual(cat.color, '#FFA500')
