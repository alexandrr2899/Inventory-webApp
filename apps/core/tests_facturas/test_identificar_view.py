from datetime import date
from unittest import mock

from django.contrib.auth.models import Permission, User
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.core.models import Cliente, ClienteAlias, DocumentoFactura
from apps.core.services.facturas import clientes


@override_settings(FACTURAS_MODULE_ENABLED=True, ALLOWED_HOSTS=['testserver', 'localhost'])
class FacturaIdentificarTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='admin_ident', password='pass12345')
        self.admin.user_permissions.add(
            Permission.objects.get(codename='gestionar_facturas'))
        self.operador = User.objects.create_user(username='oper_ident', password='pass12345')

        self.sin_id = clientes.cliente_sin_identificar()
        self.acme = Cliente.objects.create(nombre='Acme Honduras', dias_credito=30)
        self.doc = DocumentoFactura.objects.create(
            cliente=self.sin_id, tipo_documento='factura', numero_documento='F-0142',
            fecha_documento=date(2026, 7, 3), monto_total=1000,
            cliente_sugerido='ACME S DE RL',
        )
        self.url = reverse('factura_identificar', args=[self.doc.pk])

    def _post(self, **extra):
        datos = {'cliente': self.acme.pk}
        datos.update(extra)
        return self.client.post(self.url, datos)

    def test_asigna_el_cliente(self):
        self.client.force_login(self.admin)
        resp = self._post()

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['ok'])
        self.assertEqual(resp.json()['cliente_nombre'], 'Acme Honduras')
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.cliente, self.acme)

    def test_calcula_el_vencimiento_con_los_dias_del_cliente_real(self):
        """«Sin identificar» no recibe vencimiento; se calcula al identificar."""
        self.assertIsNone(self.doc.fecha_vencimiento)
        self.client.force_login(self.admin)
        self._post()
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.fecha_vencimiento, date(2026, 8, 2))  # +30 días

    def test_cliente_de_contado_vence_el_dia_del_documento(self):
        contado = Cliente.objects.create(nombre='Contado ident', dias_credito=0)
        self.client.force_login(self.admin)
        self._post(cliente=contado.pk)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.fecha_vencimiento, date(2026, 7, 3))

    def test_guarda_el_alias_cuando_se_pide(self):
        self.client.force_login(self.admin)
        self._post(guardar_alias='1')

        alias = ClienteAlias.objects.get()
        self.assertEqual(alias.alias, 'ACME S DE RL')
        self.assertEqual(alias.cliente, self.acme)

    def test_no_guarda_el_alias_si_el_checkbox_viene_desmarcado(self):
        self.client.force_login(self.admin)
        self._post()
        self.assertEqual(ClienteAlias.objects.count(), 0)

    def test_no_marca_revisado_por_defecto(self):
        self.client.force_login(self.admin)
        resp = self._post()

        self.assertFalse(resp.json()['revisada'])
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.estado_revision, 'pendiente')

    def test_marca_revisado_cuando_se_pide(self):
        self.client.force_login(self.admin)
        resp = self._post(marcar_revisado='1')

        self.assertTrue(resp.json()['revisada'])
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.estado_revision, 'revisada')

    def test_calcula_el_vencimiento_con_los_dias_de_credito_del_cliente_real(self):
        # El documento llegó bajo "Sin identificar" (0 días), así que no tenía
        # vencimiento; al asignar el cliente real hay que calcularlo.
        self.client.force_login(self.admin)
        self._post()

        self.doc.refresh_from_db()
        self.assertEqual(self.doc.fecha_vencimiento, date(2026, 8, 2))

    def test_no_pisa_un_vencimiento_que_ya_existia(self):
        self.doc.fecha_vencimiento = date(2026, 7, 10)
        self.doc.save(update_fields=['fecha_vencimiento'])
        self.client.force_login(self.admin)
        self._post()

        self.doc.refresh_from_db()
        self.assertEqual(self.doc.fecha_vencimiento, date(2026, 7, 10))

    def test_alias_de_otro_cliente_avisa_pero_identifica_igual(self):
        otro = Cliente.objects.create(nombre='Acme Sur')
        ClienteAlias.objects.create(cliente=otro, alias='ACME S DE RL')
        self.client.force_login(self.admin)
        resp = self._post(guardar_alias='1')

        self.assertTrue(resp.json()['ok'])
        self.assertIn('Acme Sur', resp.json()['aviso'])
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.cliente, self.acme)
        self.assertEqual(ClienteAlias.objects.count(), 1)

    def test_falla_inesperada_del_alias_igual_identifica(self):
        # Regla de robustez: una excepción inesperada al crear el alias degrada a
        # un aviso; la identificación (la acción principal) nunca se pierde.
        self.client.force_login(self.admin)
        with mock.patch(
                'apps.core.services.facturas.clientes.crear_alias',
                side_effect=RuntimeError('boom')):
            resp = self._post(guardar_alias='1')

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['ok'])
        self.assertIn('no se pudo guardar el alias', resp.json()['aviso'].lower())
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.cliente, self.acme)

    def test_documento_ya_identificado_devuelve_409(self):
        self.doc.cliente = self.acme
        self.doc.save(update_fields=['cliente'])
        self.client.force_login(self.admin)
        resp = self._post()

        self.assertEqual(resp.status_code, 409)
        self.assertFalse(resp.json()['ok'])
        self.assertIn('Acme Honduras', resp.json()['errors']['__all__'][0])

    def test_rechaza_asignar_el_cliente_sin_identificar(self):
        self.client.force_login(self.admin)
        resp = self.client.post(self.url, {'cliente': self.sin_id.pk})

        self.assertEqual(resp.status_code, 400)
        self.assertIn('cliente', resp.json()['errors'])

    def test_rechaza_cliente_vacio(self):
        self.client.force_login(self.admin)
        resp = self.client.post(self.url, {})

        self.assertEqual(resp.status_code, 400)
        self.assertIn('cliente', resp.json()['errors'])

    def test_rechaza_cliente_no_numerico(self):
        self.client.force_login(self.admin)
        resp = self.client.post(self.url, {'cliente': 'abc'})

        self.assertEqual(resp.status_code, 400)
        self.assertIn('cliente', resp.json()['errors'])

    def test_requiere_permiso_gestionar_facturas(self):
        self.client.force_login(self.operador)
        resp = self._post()

        self.assertEqual(resp.status_code, 403)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.cliente, self.sin_id)

    def test_rechaza_get(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.url).status_code, 405)
