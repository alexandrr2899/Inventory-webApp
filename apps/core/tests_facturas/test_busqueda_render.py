from django.contrib.auth.models import Permission, User
from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(FACTURAS_MODULE_ENABLED=True, ALLOWED_HOSTS=['testserver', 'localhost'])
class BuscadorRenderTests(TestCase):
    def _login(self, con_facturas):
        u = User.objects.create_user('u', password='x')
        if con_facturas:
            u.user_permissions.add(Permission.objects.get(codename='ver_facturas'))
        self.client.force_login(u)

    def test_boton_presente_con_permiso(self):
        self._login(con_facturas=True)
        resp = self.client.get(reverse('dashboard'))
        self.assertContains(resp, 'id="btnBuscarGlobal"')
        self.assertContains(resp, 'id="buscadorOverlay"')

    def test_boton_ausente_sin_permiso(self):
        self._login(con_facturas=False)
        resp = self.client.get(reverse('dashboard'))
        self.assertNotContains(resp, 'id="btnBuscarGlobal"')
