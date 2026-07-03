from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


class SidebarToggleRenderTests(TestCase):
    def test_boton_desktop_presente_para_autenticado(self):
        user = User.objects.create_user('sb', password='x')
        self.client.force_login(user)
        resp = self.client.get(reverse('dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="sidebarToggle"')
