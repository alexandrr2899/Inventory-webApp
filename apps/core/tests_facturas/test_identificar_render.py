from datetime import date

from django.contrib.auth.models import Permission, User
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.core.models import Cliente, DocumentoFactura
from apps.core.services.facturas import clientes


@override_settings(FACTURAS_MODULE_ENABLED=True, ALLOWED_HOSTS=['testserver', 'localhost'])
class ListaIdentificarRenderTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='admin_render', password='pass12345')
        for codename in ('ver_facturas', 'gestionar_facturas'):
            self.admin.user_permissions.add(Permission.objects.get(codename=codename))
        self.client.force_login(self.admin)
        self.sin_id = clientes.cliente_sin_identificar()
        self.url = reverse('facturas_lista')

    def _doc(self, cliente, sugerido=''):
        return DocumentoFactura.objects.create(
            cliente=cliente, tipo_documento='factura', numero_documento='F-1',
            fecha_documento=date(2026, 7, 3), monto_total=100, cliente_sugerido=sugerido)

    def test_muestra_el_badge_y_el_nombre_del_archivo(self):
        self._doc(self.sin_id, sugerido='ACME S DE RL')
        html = self.client.get(self.url).content.decode()

        self.assertIn('Sin identificar', html)
        self.assertIn('ACME S DE RL', html)
        self.assertIn('btn-identificar', html)

    def test_documento_normal_no_trae_el_boton(self):
        self._doc(Cliente.objects.create(nombre='Acme Honduras'))
        html = self.client.get(self.url).content.decode()

        # No buscamos solo 'btn-identificar': ese texto vive también en el JS
        # de _modal_identificar.html (querySelectorAll('.btn-identificar')),
        # que se incluye siempre en extra_js. Buscamos la clase completa del
        # <button>, que solo aparece si el botón realmente se renderiza.
        self.assertNotIn('btn btn-sm btn-outline-warning btn-identificar', html)

    def test_el_contexto_trae_el_id_del_cliente_sin_identificar(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.context['sin_identificar_id'], self.sin_id.pk)

    def test_el_modal_se_incluye_una_sola_vez(self):
        self._doc(self.sin_id, sugerido='A')
        self._doc(self.sin_id, sugerido='B')
        html = self.client.get(self.url).content.decode()

        self.assertEqual(html.count('id="modalIdentificar"'), 1)
