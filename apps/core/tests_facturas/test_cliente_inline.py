from unittest.mock import patch

from django.contrib.auth.models import Permission, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.core.models import Cliente


@override_settings(FACTURAS_MODULE_ENABLED=True, ALLOWED_HOSTS=['testserver', 'localhost'])
class ClienteInlineEndpointTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='admin_inline', password='pass12345')
        self.admin.user_permissions.add(Permission.objects.get(codename='gestionar_facturas'))
        self.operador = User.objects.create_user(username='oper_inline', password='pass12345')
        self.url = reverse('cliente_crear_inline')

    def test_crear_cliente_inline(self):
        self.client.force_login(self.admin)
        resp = self.client.post(self.url, {
            'nombre': 'Cliente Nuevo',
            'telefono': '9999-9999',
            'rtn': '',
            'direccion': '',
            'dias_credito': '0',
        })

        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertTrue(data['ok'])
        cliente = Cliente.objects.get(pk=data['cliente']['id'])
        self.assertEqual(cliente.nombre, 'Cliente Nuevo')
        self.assertTrue(cliente.activo)

    def test_requiere_permiso_gestionar_facturas(self):
        self.client.force_login(self.operador)
        resp = self.client.post(self.url, {'nombre': 'Sin Permiso'})

        self.assertEqual(resp.status_code, 403)
        self.assertFalse(Cliente.objects.filter(nombre='Sin Permiso').exists())

    def test_validacion_nombre_vacio(self):
        self.client.force_login(self.admin)
        resp = self.client.post(self.url, {'nombre': ''})

        self.assertEqual(resp.status_code, 400)
        self.assertIn('nombre', resp.json()['errors'])
        self.assertEqual(Cliente.objects.count(), 0)

    def test_duplicado_sin_forzar_no_crea(self):
        existente = Cliente.objects.create(nombre='Juan Pérez')
        self.client.force_login(self.admin)
        resp = self.client.post(self.url, {'nombre': 'juan pérez'})

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data['ok'])
        self.assertEqual(data['duplicado']['id'], existente.pk)
        self.assertEqual(data['duplicado']['nombre'], 'Juan Pérez')
        self.assertEqual(Cliente.objects.filter(nombre__iexact='juan pérez').count(), 1)

    def test_duplicado_forzado_crea(self):
        Cliente.objects.create(nombre='Juan Pérez')
        self.client.force_login(self.admin)
        resp = self.client.post(self.url, {'nombre': 'juan pérez', 'forzar': '1'})

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(Cliente.objects.filter(nombre__iexact='juan pérez').count(), 2)


@override_settings(FACTURAS_MODULE_ENABLED=True, ALLOWED_HOSTS=['testserver', 'localhost'])
class ClienteInlineRenderTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='admin_inline_render', password='pass12345')
        self.admin.user_permissions.add(Permission.objects.get(codename='gestionar_facturas'))
        Cliente.objects.create(nombre='Cliente Activo')

    def test_form_upload_incluye_boton_y_modal(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('factura_upload'))

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '+ Nuevo cliente')
        self.assertContains(resp, 'id="cliente-inline-modal"')
        self.assertContains(resp, 'js/cliente-inline.js')
        self.assertContains(resp, 'cliente-select')

    def test_lote_revisar_incluye_boton_y_modal(self):
        self.client.force_login(self.admin)
        archivo = SimpleUploadedFile('factura.pdf', b'%PDF-1.4', content_type='application/pdf')
        filas = [{
            'archivo': 'tmp/factura.pdf',
            'nombre_original': 'factura.pdf',
            'cliente_id': '',
            'cliente_sugerido': 'Cliente Nuevo',
            'tipo': 'factura',
            'numero_documento': 'F-1',
            'fecha_documento': '2026-07-02',
            'categoria_id': '',
            'total_libras': '',
            'subtotal': '',
            'isv': '',
            'monto_total': '100.00',
        }]

        with patch('apps.core.views.facturas_lote.bulk_service.procesar_archivos', return_value=('batch-1', filas)):
            resp = self.client.post(reverse('factura_lote'), {'archivos': [archivo]})

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '+ Nuevo cliente')
        self.assertContains(resp, 'id="cliente-inline-modal"')
        self.assertContains(resp, 'id="cliente-fila-0"')
        self.assertContains(resp, 'class="form-select form-select-sm cliente-select"')
        self.assertContains(resp, 'js/cliente-inline.js')
