import tempfile
from decimal import Decimal

from django.contrib.auth.models import Permission, User
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.core.models import Cliente, MetodoPago, Pago


class PagoComprobanteTests(TestCase):
    def setUp(self):
        self.media = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(MEDIA_ROOT=self.media.name)
        self.settings_override.enable()
        self.cliente = Cliente.objects.create(nombre='Cliente')
        self.metodo = MetodoPago.objects.create(nombre='Transferencia', tipo='transferencia')
        self.pago = Pago.objects.create(
            cliente=self.cliente, metodo_pago=self.metodo, monto=Decimal('100.00'),
        )
        self.pago.comprobante.save(
            'recibo.jpg', ContentFile(b'\xff\xd8\xffcontenido'), save=True,
        )
        self.usuario = User.objects.create_user('visor-comprobante', password='x')
        self.usuario.user_permissions.add(Permission.objects.get(codename='ver_facturas'))
        self.url = reverse('pago_comprobante', args=[self.pago.pk])

    def tearDown(self):
        self.settings_override.disable()
        self.media.cleanup()
        super().tearDown()

    def test_sirve_imagen_desde_el_volumen_media(self):
        self.client.force_login(self.usuario)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/jpeg')
        self.assertEqual(b''.join(response.streaming_content), b'\xff\xd8\xffcontenido')

    def test_requiere_un_permiso_relacionado_con_pagos(self):
        usuario = User.objects.create_user('sin-permiso-comprobante', password='x')
        self.client.force_login(usuario)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    def test_sin_archivo_devuelve_404(self):
        self.pago.comprobante.delete(save=True)
        self.client.force_login(self.usuario)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 404)
