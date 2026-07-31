import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from celery.exceptions import Retry
from django.contrib.auth.models import Group, Permission, User
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import (
    Categoria, Cliente, Conteo, DocumentoFactura, Item, MetodoPago, Stock,
    Ubicacion, WebPushPreference, WebPushScheduledEvent, WebPushSubscription,
)
from .services.notifications import send_event
from .services.web_push import (
    enqueue_web_push, event_notification, user_can_receive_category,
)
from .tasks import (
    deliver_web_push, flush_count_web_push, notify_overdue_invoices,
)


PUSH_SETTINGS = override_settings(
    VAPID_PUBLIC_KEY='publica',
    VAPID_PRIVATE_KEY='privada',
    VAPID_SUBJECT='mailto:test@example.com',
)


@PUSH_SETTINGS
class WebPushEndpointTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username='admin-push', email='a@example.com', password='x')
        self.client.force_login(self.user)

    def test_suscribe_actualiza_endpoint_y_crea_preferencias(self):
        payload = {
            'endpoint': 'https://push.example/sub/1',
            'keys': {'p256dh': 'p256dh-key', 'auth': 'auth-key'},
        }
        response = self.client.post(
            reverse('web_push_subscribe'),
            data=json.dumps(payload), content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        subscription = WebPushSubscription.objects.get()
        self.assertEqual(subscription.user, self.user)
        self.assertTrue(WebPushPreference.objects.get(user=self.user).inventario)

    def test_rechaza_suscripcion_incompleta(self):
        response = self.client.post(
            reverse('web_push_subscribe'),
            data=json.dumps({'endpoint': 'https://push.example/sub/1'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)

    def test_guarda_preferencias_booleanas(self):
        response = self.client.post(
            reverse('web_push_preferences'),
            data=json.dumps({'inventario': False, 'facturas': True}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        preference = WebPushPreference.objects.get(user=self.user)
        self.assertFalse(preference.inventario)
        self.assertTrue(preference.facturas)

    def test_desuscribe_solo_endpoint_del_usuario(self):
        subscription = WebPushSubscription.objects.create(
            user=self.user, endpoint='https://push.example/sub/1',
            p256dh='p', auth='a',
        )
        response = self.client.post(
            reverse('web_push_unsubscribe'),
            data=json.dumps({'endpoint': subscription.endpoint}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(WebPushSubscription.objects.exists())


class PushPermissionTests(TestCase):
    def setUp(self):
        self.supervisor = User.objects.create_user('supervisor')
        group = Group.objects.create(name='Supervisor')
        self.supervisor.groups.add(group)

    def test_supervisor_no_recibe_facturas_sin_permiso(self):
        self.assertFalse(user_can_receive_category(self.supervisor, 'facturas'))
        self.assertTrue(user_can_receive_category(self.supervisor, 'inventario'))

    def test_supervisor_recibe_facturas_al_tener_permiso(self):
        permission = Permission.objects.get(
            content_type__app_label='core', codename='ver_facturas')
        self.supervisor.user_permissions.add(permission)
        for cache_name in ('_perm_cache', '_user_perm_cache', '_group_perm_cache'):
            if hasattr(self.supervisor, cache_name):
                delattr(self.supervisor, cache_name)
        self.assertTrue(user_can_receive_category(self.supervisor, 'facturas'))


@PUSH_SETTINGS
class DeliveryTaskTests(TestCase):
    def setUp(self):
        user = User.objects.create_superuser('push-delivery', 'd@example.com', 'x')
        self.subscription = WebPushSubscription.objects.create(
            user=user, endpoint='https://push.example/sub/delivery',
            p256dh='p256dh', auth='auth',
        )
        self.notification = {
            'title': 'Prueba', 'body': 'Contenido', 'url': '/',
            'category': 'operaciones',
        }

    @patch('pywebpush.webpush')
    def test_entrega_correcta_actualiza_estado(self, webpush_mock):
        self.assertTrue(deliver_web_push(self.subscription.pk, self.notification))
        self.subscription.refresh_from_db()
        self.assertIsNotNone(self.subscription.last_success_at)
        self.assertEqual(self.subscription.last_error, '')
        webpush_mock.assert_called_once()

    @patch('pywebpush.webpush')
    def test_endpoint_expirado_se_elimina(self, webpush_mock):
        from pywebpush import WebPushException
        response = type('Response', (), {'status_code': 410})()
        webpush_mock.side_effect = WebPushException('gone', response=response)
        self.assertFalse(deliver_web_push(self.subscription.pk, self.notification))
        self.assertFalse(WebPushSubscription.objects.filter(
            pk=self.subscription.pk).exists())

    @patch('pywebpush.webpush')
    def test_error_transitorio_programa_reintento(self, webpush_mock):
        from pywebpush import WebPushException
        response = type('Response', (), {'status_code': 503})()
        webpush_mock.side_effect = WebPushException('temporal', response=response)
        with patch.object(deliver_web_push, 'retry', side_effect=Retry()) as retry_mock:
            with self.assertRaises(Retry):
                deliver_web_push(self.subscription.pk, self.notification)
        retry_mock.assert_called_once()
        self.subscription.refresh_from_db()
        self.assertIn('temporal', self.subscription.last_error)


class EventCompatibilityTests(TestCase):
    @override_settings(
        N8N_WEBHOOK_URL='https://n8n.example/hook',
        VAPID_PUBLIC_KEY='publica',
        VAPID_PRIVATE_KEY='privada',
        VAPID_SUBJECT='mailto:test@example.com',
    )
    @patch('apps.core.services.web_push.enqueue_web_push', side_effect=RuntimeError('push caído'))
    @patch('apps.core.services.notifications.requests.post')
    def test_falla_push_no_cambia_resultado_telegram(self, post, _enqueue):
        post.return_value.raise_for_status.return_value = None
        post.return_value.status_code = 200
        self.assertTrue(send_event('stock_low', {'item': 'Bolsa'}))
        post.assert_called_once()

    def test_pago_tiene_contenido_y_destino(self):
        notification = event_notification('pago_factura_creado', {
            'pago_id': 8, 'documento_id': 12, 'cliente': 'ACME',
            'monto': '500.00', 'metodo_pago': 'Transferencia',
        })
        self.assertEqual(notification['category'], 'facturas')
        self.assertIn('ACME', notification['body'])
        self.assertEqual(notification['url'], reverse('factura_detalle', args=[12]))

    def test_resumen_vencidas_incluye_documentos_clientes_y_saldo(self):
        notification = event_notification('resumen_facturas_vencidas', {
            'fecha': '2026-07-31', 'cantidad': 3, 'clientes': 2,
            'saldo_total': '1250.50',
        })
        self.assertEqual(
            notification['body'],
            '3 documentos de 2 clientes · saldo L 1,250.50',
        )
        self.assertEqual(
            notification['url'], f'{reverse("facturas_lista")}?estado=vencida')

    def test_conteo_creado_tiene_resumen_y_destino(self):
        notification = event_notification('conteo_creado', {
            'conteo_id': 15, 'tipo_conteo': 'Camiseta', 'turno': 'Mañana',
            'items_contados': 8, 'usuario': 'Ana',
        })
        self.assertEqual(notification['title'], 'Conteo registrado · Camiseta')
        self.assertEqual(notification['body'], '8 ítems · Mañana · Ana')
        self.assertEqual(notification['url'], reverse('conteo_conciliar', args=[15]))


@PUSH_SETTINGS
class CountPushAggregationTests(TestCase):
    def setUp(self):
        cache.clear()

    @patch('apps.core.tasks.flush_count_web_push.apply_async')
    def test_agrupa_ajustes_del_mismo_conteo_en_una_tarea(self, apply_async):
        base = {
            'conteo_id': 7, 'tipo_conteo': 'Camiseta',
            'turno': 'Mañana', 'usuario': 'operador',
        }
        self.assertTrue(enqueue_web_push(
            'count_difference', {**base, 'ajustes_aplicados': 1}))
        self.assertTrue(enqueue_web_push(
            'count_difference', {**base, 'ajustes_aplicados': 3}))

        apply_async.assert_called_once_with(args=[7], countdown=30)
        with patch('apps.core.tasks.fanout_web_push', return_value=1) as fanout:
            self.assertEqual(flush_count_web_push(7), 1)
        fanout.assert_called_once_with('count_difference', {
            **base, 'ajustes_aplicados': 4,
        })

    @patch('apps.core.tasks.fanout_web_push.delay')
    def test_reporte_automatico_no_duplica_el_push_del_conteo(self, delay):
        self.assertTrue(enqueue_web_push('inventario_camiseta_actual', {
            'origen': 'conciliacion_automatica', 'conteo_id': 7,
        }))
        delay.assert_not_called()

    @patch('apps.core.tasks.fanout_web_push.delay')
    def test_alerta_stock_de_ajuste_no_duplica_el_push_del_conteo(self, delay):
        self.assertTrue(enqueue_web_push('stock_low', {
            'item': 'Bolsa Camiseta', 'movimiento': 'ajuste',
        }))
        delay.assert_not_called()


class CountViewEventTests(TestCase):
    def setUp(self):
        categoria = Categoria.objects.create(nombre='Camiseta')
        self.item = Item.objects.create(
            codigo='B-1', nombre='Bolsa Camiseta', tipo='producto',
            categoria=categoria, unidad_medida='fardos',
        )
        self.ubicacion = Ubicacion.objects.create(
            nombre='Bodega', tipo='bodega')
        Stock.objects.create(
            item=self.item, ubicacion=self.ubicacion,
            cantidad_actual=Decimal('10'),
        )
        self.user = User.objects.create_user('contador')
        self.user.user_permissions.add(Permission.objects.get(
            content_type__app_label='core', codename='registrar_conteo'))
        self.client.force_login(self.user)

    @patch('apps.core.views.conteos.send_event')
    def test_conteo_nuevo_emite_un_solo_resumen(self, send_event_mock):
        now = timezone.localtime().strftime('%Y-%m-%dT%H:%M')
        response = self.client.post(reverse('conteo_nuevo'), {
            'fecha': timezone.localdate().isoformat(),
            'turno': 'manana',
            'tipo_conteo': 'camiseta',
            'fecha_hora_conteo': now,
            'observaciones': '',
            'item[]': [str(self.item.pk)],
            'ubicacion[]': [str(self.ubicacion.pk)],
            'cantidad_contada[]': ['12'],
        })

        self.assertEqual(response.status_code, 302)
        conteo = Conteo.objects.get()
        send_event_mock.assert_called_once_with('conteo_creado', {
            'conteo_id': conteo.pk,
            'tipo_conteo': 'Camiseta',
            'turno': 'Mañana',
            'items_contados': 1,
            'usuario': 'contador',
        })


class PaymentEventTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username='cobrador-push', email='c@example.com', password='x')
        self.client.force_login(self.user)
        self.customer = Cliente.objects.create(nombre='Cliente pago')
        self.method = MetodoPago.objects.create(
            nombre='Transferencia', tipo='transferencia')
        self.document = DocumentoFactura.objects.create(
            cliente=self.customer, tipo_documento='factura',
            numero_documento='F-PUSH', fecha_documento=timezone.localdate(),
            monto_total=Decimal('500.00'),
        )

    @patch('apps.core.views.common.send_event')
    def test_pago_factura_emite_evento_despues_del_commit(self, send_event_mock):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse('factura_pago_nuevo', args=[self.document.pk]), {
                    'fecha_pago': timezone.localdate().isoformat(),
                    'metodo_pago': self.method.pk,
                    'monto': '100.00',
                    'referencia': 'REF-1',
                })
        self.assertEqual(response.status_code, 302)
        send_event_mock.assert_called_once()
        event_type, payload = send_event_mock.call_args.args
        self.assertEqual(event_type, 'pago_factura_creado')
        self.assertEqual(payload['documento_id'], self.document.pk)

    @patch('apps.core.views.common.send_event')
    def test_pago_invalido_no_emite_evento(self, send_event_mock):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse('factura_pago_nuevo', args=[self.document.pk]), {
                    'fecha_pago': timezone.localdate().isoformat(),
                    'metodo_pago': self.method.pk,
                    'monto': '-1.00',
                })
        self.assertEqual(response.status_code, 200)
        send_event_mock.assert_not_called()


@PUSH_SETTINGS
class OverdueTaskTests(TestCase):
    def setUp(self):
        self.client_model = Cliente.objects.create(nombre='Cliente vencido')
        self.today = timezone.localdate()
        self.overdue = DocumentoFactura.objects.create(
            cliente=self.client_model, tipo_documento='factura',
            numero_documento='F-1',
            fecha_documento=self.today - timedelta(days=40),
            fecha_vencimiento=self.today - timedelta(days=10),
            monto_total=Decimal('100.00'), estado_pago='pendiente',
        )
        DocumentoFactura.objects.create(
            cliente=self.client_model, tipo_documento='factura',
            numero_documento='F-2',
            fecha_documento=self.today,
            fecha_vencimiento=self.today + timedelta(days=10),
            monto_total=Decimal('200.00'), estado_pago='pendiente',
        )

    @patch('apps.core.tasks.fanout_web_push.delay')
    def test_envia_solo_un_resumen_diario_y_lo_deduplica(self, delay):
        segundo_cliente = Cliente.objects.create(nombre='Otro cliente vencido')
        DocumentoFactura.objects.create(
            cliente=segundo_cliente, tipo_documento='factura',
            numero_documento='F-3',
            fecha_documento=self.today - timedelta(days=30),
            fecha_vencimiento=self.today - timedelta(days=5),
            monto_total=Decimal('250.00'), estado_pago='pendiente',
        )
        first = notify_overdue_invoices()
        second = notify_overdue_invoices()
        self.assertEqual(first['individuales'], 0)
        self.assertTrue(first['resumen'])
        self.assertEqual(second['individuales'], 0)
        self.assertFalse(second['resumen'])
        delay.assert_called_once_with('resumen_facturas_vencidas', {
            'fecha': self.today.isoformat(),
            'cantidad': 2,
            'clientes': 2,
            'saldo_total': '350.00',
        })
        self.assertFalse(WebPushScheduledEvent.objects.filter(
            event_type='factura_vencida').exists())

    @patch('apps.core.tasks.fanout_web_push.delay')
    def test_no_notifica_si_no_hay_documentos_vencidos(self, delay):
        self.overdue.estado_pago = 'pagada'
        self.overdue.save(update_fields=['estado_pago'])

        result = notify_overdue_invoices()

        self.assertEqual(result, {'individuales': 0, 'resumen': False})
        delay.assert_not_called()
        self.assertFalse(WebPushScheduledEvent.objects.exists())
