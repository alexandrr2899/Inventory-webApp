from django.contrib.auth.models import User, Permission
from django.test import TestCase
from django.urls import reverse


class QrScannerNavbarRenderTests(TestCase):
    def test_boton_visible_con_ver_inventario(self):
        user = User.objects.create_user('scan1', password='x')
        user.user_permissions.add(Permission.objects.get(codename='ver_inventario'))
        self.client.force_login(user)
        resp = self.client.get(reverse('dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="btnQrScan"')
        self.assertContains(resp, 'id="qrScannerModal"')

    def test_boton_oculto_sin_ver_inventario(self):
        user = User.objects.create_user('scan2', password='x')
        self.client.force_login(user)
        resp = self.client.get(reverse('dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'id="btnQrScan"')

    def test_conteo_otros_incluye_escaner_qr(self):
        user = User.objects.create_user('scan-conteo', password='x')
        user.user_permissions.add(Permission.objects.get(codename='registrar_conteo'))
        self.client.force_login(user)

        resp = self.client.get(reverse('conteo_nuevo'))

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="btn-escanear-otros"')
        self.assertContains(resp, "QRScanner.open({ mode: 'continuous'")
        self.assertContains(resp, 'agregarFilaOtros({ item_id: String(id) })')
