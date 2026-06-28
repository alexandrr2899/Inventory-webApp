from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, Permission, User
from django.test import TestCase, override_settings
from django.http import Http404
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from apps.core.models import AplicacionPago, Cliente, DocumentoFactura, MetodoPago, Pago
from apps.core.services.facturas import payment_service
from apps.core.views.common import facturas_enabled


@facturas_enabled
def _vista_dummy(request):
    from django.http import HttpResponse
    return HttpResponse('ok')


class InterruptorFacturasTests(TestCase):
    def setUp(self):
        self.rf = RequestFactory()

    @override_settings(FACTURAS_MODULE_ENABLED=False)
    def test_decorador_404_cuando_apagado(self):
        with self.assertRaises(Http404):
            _vista_dummy(self.rf.get('/'))

    @override_settings(FACTURAS_MODULE_ENABLED=True)
    def test_decorador_pasa_cuando_encendido(self):
        resp = _vista_dummy(self.rf.get('/'))
        self.assertEqual(resp.status_code, 200)


@override_settings(FACTURAS_MODULE_ENABLED=True, ALLOWED_HOSTS=['testserver', 'localhost'])
class FacturasVistasTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='admin', password='pass12345')
        perms = Permission.objects.filter(codename__in=[
            'ver_facturas', 'gestionar_facturas', 'registrar_pago_factura',
            'anular_factura', 'gestionar_tarifas',
        ])
        for p in perms:
            self.admin.user_permissions.add(p)
        self.operador = User.objects.create_user(username='oper', password='pass12345')
        self.cliente = Cliente.objects.create(nombre='Renato Díaz')

    def test_lista_requiere_permiso(self):
        self.client.force_login(self.operador)
        resp = self.client.get(reverse('facturas_lista'))
        self.assertEqual(resp.status_code, 403)

    def test_lista_admin_ok(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('facturas_lista'))
        self.assertEqual(resp.status_code, 200)

    @override_settings(FACTURAS_MODULE_ENABLED=False)
    def test_apagado_devuelve_404(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('facturas_lista'))
        self.assertEqual(resp.status_code, 404)

    def test_anular_marca_estado(self):
        self.client.force_login(self.admin)
        doc = DocumentoFactura.objects.create(
            cliente=self.cliente, tipo_documento='factura',
            fecha_documento=timezone.localdate(), monto_total=Decimal('50.00'),
        )
        resp = self.client.post(reverse('factura_anular', args=[doc.pk]))
        self.assertEqual(resp.status_code, 302)
        doc.refresh_from_db()
        self.assertEqual(doc.estado_pago, 'anulada')


@override_settings(FACTURAS_MODULE_ENABLED=True, ALLOWED_HOSTS=['testserver', 'localhost'])
class FacturasPagoTests(TestCase):
    def setUp(self):
        from apps.core.models import DocumentoFactura, MetodoPago
        self.admin = User.objects.create_user(username='admin2', password='pass12345')
        for p in Permission.objects.filter(codename__in=['ver_facturas', 'registrar_pago_factura']):
            self.admin.user_permissions.add(p)
        self.cliente = Cliente.objects.create(nombre='Cli')
        self.doc = DocumentoFactura.objects.create(
            cliente=self.cliente, tipo_documento='factura',
            fecha_documento=timezone.localdate(), monto_total=Decimal('100.00'),
        )
        self.met = MetodoPago.objects.create(nombre='Efectivo', tipo='efectivo')

    def test_registrar_pago_via_vista(self):
        self.client.force_login(self.admin)
        resp = self.client.post(reverse('factura_pago_nuevo', args=[self.doc.pk]), {
            'fecha_pago': timezone.localdate().isoformat(),
            'metodo_pago': self.met.pk, 'monto': '100.00', 'referencia': '', 'notas': '',
        })
        self.assertEqual(resp.status_code, 302)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.estado_pago, 'pagada')


class FacturasTarifasTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='admin3', password='pass12345')
        for p in Permission.objects.filter(codename__in=['ver_facturas', 'gestionar_tarifas']):
            self.admin.user_permissions.add(p)
        self.cliente = Cliente.objects.create(nombre='Cli')

    @override_settings(FACTURAS_MODULE_ENABLED=True)
    def test_crear_tarifa(self):
        from apps.core.models import TarifaCliente
        self.client.force_login(self.admin)
        resp = self.client.post(reverse('cliente_tarifas', args=[self.cliente.pk]), {
            'producto': 'camiseta', 'precio_por_libra': '32.00', 'activa': 'on',
            'fecha_inicio': timezone.localdate().isoformat(),
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(TarifaCliente.objects.filter(cliente=self.cliente, producto='camiseta').exists())


@override_settings(FACTURAS_MODULE_ENABLED=True, ALLOWED_HOSTS=['testserver', 'localhost'])
class VencidasFiltroTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='admin_v', password='pass12345')
        self.admin.user_permissions.add(Permission.objects.get(codename='ver_facturas'))
        self.cliente = Cliente.objects.create(nombre='Cli')
        hoy = timezone.localdate()
        # Vencida: vencimiento pasado, con saldo.
        self.vencida = DocumentoFactura.objects.create(
            cliente=self.cliente, tipo_documento='factura', numero_documento='VEN-1',
            fecha_documento=hoy - timedelta(days=40),
            fecha_vencimiento=hoy - timedelta(days=10), monto_total=Decimal('100.00'),
        )
        # Al día: vencimiento futuro.
        self.aldia = DocumentoFactura.objects.create(
            cliente=self.cliente, tipo_documento='factura', numero_documento='ALDIA-1',
            fecha_documento=hoy, fecha_vencimiento=hoy + timedelta(days=10),
            monto_total=Decimal('100.00'),
        )

    def test_filtro_vencidas_solo_muestra_vencidas(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('facturas_lista'), {'estado': 'vencida'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'VEN-1')
        self.assertNotContains(resp, 'ALDIA-1')


@override_settings(FACTURAS_MODULE_ENABLED=True, ALLOWED_HOSTS=['testserver', 'localhost'])
class FacturaPdfTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='admin_pdf', password='pass12345')
        self.admin.user_permissions.add(Permission.objects.get(codename='ver_facturas'))
        self.operador = User.objects.create_user(username='oper_pdf', password='pass12345')
        self.cliente = Cliente.objects.create(nombre='Cli')
        self.doc = DocumentoFactura.objects.create(
            cliente=self.cliente, tipo_documento='factura',
            fecha_documento=timezone.localdate(), monto_total=Decimal('10.00'),
        )

    def test_pdf_sin_archivo_devuelve_404(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('factura_pdf', args=[self.doc.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_pdf_requiere_permiso(self):
        self.client.force_login(self.operador)
        resp = self.client.get(reverse('factura_pdf', args=[self.doc.pk]))
        self.assertEqual(resp.status_code, 403)


@override_settings(FACTURAS_MODULE_ENABLED=True, ALLOWED_HOSTS=['testserver', 'localhost'])
class AnuladasNoEnTodasTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='admin_an', password='pass12345')
        self.admin.user_permissions.add(Permission.objects.get(codename='ver_facturas'))
        self.cliente = Cliente.objects.create(nombre='Cli')
        hoy = timezone.localdate()
        self.normal = DocumentoFactura.objects.create(
            cliente=self.cliente, tipo_documento='factura', numero_documento='NORMAL-1',
            fecha_documento=hoy, monto_total=Decimal('100.00'), estado_pago='pendiente',
        )
        self.anulada = DocumentoFactura.objects.create(
            cliente=self.cliente, tipo_documento='factura', numero_documento='ANUL-1',
            fecha_documento=hoy, monto_total=Decimal('100.00'), estado_pago='anulada',
        )

    def test_todas_no_incluye_anuladas(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('facturas_lista'))
        self.assertContains(resp, 'NORMAL-1')
        self.assertNotContains(resp, 'ANUL-1')

    def test_pestana_anuladas_si_las_muestra(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('facturas_lista'), {'estado': 'anulada'})
        self.assertContains(resp, 'ANUL-1')
        self.assertNotContains(resp, 'NORMAL-1')


@override_settings(FACTURAS_MODULE_ENABLED=True, ALLOWED_HOSTS=['testserver', 'localhost'])
class MejorasUXTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='admin_ux', password='pass12345')
        for cn in ('ver_facturas', 'gestionar_facturas'):
            self.admin.user_permissions.add(Permission.objects.get(codename=cn))
        self.cliente = Cliente.objects.create(nombre='Zaga SA')
        hoy = timezone.localdate()
        self.doc = DocumentoFactura.objects.create(
            cliente=self.cliente, tipo_documento='factura', numero_documento='F-555',
            fecha_documento=hoy, monto_total=Decimal('100.00'), estado_revision='pendiente',
        )
        self.otro = DocumentoFactura.objects.create(
            cliente=Cliente.objects.create(nombre='Otro Cli'), tipo_documento='factura',
            numero_documento='X-999', fecha_documento=hoy, monto_total=Decimal('50.00'),
            estado_revision='revisada',
        )

    def test_busqueda_por_numero(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('facturas_lista'), {'q': 'F-555'})
        self.assertContains(resp, 'F-555')
        self.assertNotContains(resp, 'X-999')

    def test_busqueda_por_cliente(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('facturas_lista'), {'q': 'Zaga'})
        self.assertContains(resp, 'F-555')
        self.assertNotContains(resp, 'X-999')

    def test_filtro_por_revisar(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('facturas_lista'), {'revision': 'pendiente'})
        self.assertContains(resp, 'F-555')
        self.assertNotContains(resp, 'X-999')

    def test_contador_por_revisar_en_contexto(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('facturas_lista'))
        self.assertEqual(resp.context['facturas_por_revisar'], 1)

    def test_contador_por_revisar_excluye_anuladas(self):
        # Una factura anulada antes de revisarla NO debe contar como "por revisar".
        DocumentoFactura.objects.create(
            cliente=self.cliente, tipo_documento='factura', numero_documento='ANU-PEND',
            fecha_documento=timezone.localdate(), monto_total=Decimal('10.00'),
            estado_revision='pendiente', estado_pago='anulada',
        )
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('facturas_lista'))
        # Sigue siendo 1 (la pendiente de setUp); la anulada no suma.
        self.assertEqual(resp.context['facturas_por_revisar'], 1)

    def test_detalle_no_usa_referer_como_retorno(self):
        self.client.force_login(self.admin)
        referer = 'http://testserver' + reverse('facturas_lista') + '?revision=pendiente'
        resp = self.client.get(reverse('factura_detalle', args=[self.doc.pk]), HTTP_REFERER=referer)
        self.assertEqual(resp.context['return_url'], reverse('facturas_lista'))

    def test_lista_pasa_next_a_detalle(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('facturas_lista'), {'revision': 'pendiente'})
        detalle_url = reverse('factura_detalle', args=[self.doc.pk])
        self.assertContains(resp, detalle_url + '?next=/facturas/%3Frevision%3Dpendiente')

    def test_guardar_y_revisar(self):
        self.client.force_login(self.admin)
        next_url = reverse('facturas_lista') + '?revision=pendiente'
        resp = self.client.post(reverse('factura_editar', args=[self.doc.pk]), {
            'cliente': self.cliente.pk, 'tipo_documento': 'factura',
            'numero_documento': 'F-555', 'fecha_documento': timezone.localdate().isoformat(),
            'producto': '', 'subtotal': '0', 'isv': '0', 'monto_total': '100.00',
            'estado_revision': 'pendiente', 'notas': '', 'accion': 'guardar_revisar',
            'next': next_url,
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], next_url)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.estado_revision, 'revisada')

    def test_marcar_revisada_normaliza_next_absoluto(self):
        self.client.force_login(self.admin)
        next_url = 'http://testserver' + reverse('facturas_lista') + '?revision=pendiente'
        resp = self.client.post(reverse('factura_revisar', args=[self.doc.pk]), {
            'next': next_url,
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], reverse('facturas_lista') + '?revision=pendiente')
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.estado_revision, 'revisada')

    def test_marcar_revisada_regresa_a_next(self):
        self.client.force_login(self.admin)
        next_url = reverse('facturas_lista') + '?revision=pendiente'
        resp = self.client.post(reverse('factura_revisar', args=[self.doc.pk]), {
            'next': next_url,
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], next_url)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.estado_revision, 'revisada')


@override_settings(FACTURAS_MODULE_ENABLED=True, ALLOWED_HOSTS=['testserver', 'localhost'])
class BorrarPagoPreservaSaldoTests(TestCase):
    """Verifica que factura_pago_borrar preserve el saldo a favor del cliente."""

    def setUp(self):
        self.admin = User.objects.create_user(username='admin_borrar', password='pass12345')
        for p in Permission.objects.filter(codename__in=['ver_facturas', 'registrar_pago_factura']):
            self.admin.user_permissions.add(p)
        self.cliente = Cliente.objects.create(nombre='Cli Saldo')
        self.met = MetodoPago.objects.create(nombre='Efectivo', tipo='efectivo')
        hoy = timezone.localdate()
        self.doc = DocumentoFactura.objects.create(
            cliente=self.cliente, tipo_documento='factura',
            fecha_documento=hoy, monto_total=Decimal('100.00'),
        )

    def test_borrar_pago_completo_elimina_pago(self):
        """Pago 1:1 con la factura — al borrar la aplicación, el Pago también desaparece."""
        self.client.force_login(self.admin)
        payment_service.registrar_abono(
            self.cliente,
            fecha_pago=timezone.localdate(), metodo_pago=self.met,
            monto=Decimal('100.00'),
            aplicaciones=[(self.doc, Decimal('100.00'))],
        )
        apl = AplicacionPago.objects.get(documento=self.doc)
        pago_pk = apl.pago_id

        resp = self.client.post(reverse('factura_pago_borrar', args=[apl.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(AplicacionPago.objects.filter(pk=apl.pk).exists())
        self.assertFalse(Pago.objects.filter(pk=pago_pk).exists())
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.monto_pagado, Decimal('0.00'))

    def test_borrar_aplicacion_preserva_pago_con_saldo_a_favor(self):
        """Abono de 150 con 100 aplicados → borrar la aplicación conserva el Pago (50 quedan como saldo)."""
        self.client.force_login(self.admin)
        payment_service.registrar_abono(
            self.cliente,
            fecha_pago=timezone.localdate(), metodo_pago=self.met,
            monto=Decimal('150.00'),
            aplicaciones=[(self.doc, Decimal('100.00'))],
        )
        apl = AplicacionPago.objects.get(documento=self.doc)
        pago_pk = apl.pago_id

        resp = self.client.post(reverse('factura_pago_borrar', args=[apl.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(AplicacionPago.objects.filter(pk=apl.pk).exists())
        self.assertTrue(Pago.objects.filter(pk=pago_pk).exists())
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.monto_pagado, Decimal('0.00'))
        self.cliente.refresh_from_db()
        self.assertEqual(self.cliente.saldo_a_favor, Decimal('150.00'))
