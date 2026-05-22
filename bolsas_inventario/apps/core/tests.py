from decimal import Decimal
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import tempfile

from django.contrib.auth.models import Group, Permission, User
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import (
    BackupJob, Categoria, Cliente, Conteo, ConteoDetalle, DetalleMovimiento,
    Item, MovimientoInventario, Stock, Ubicacion,
)
from .views import _calcular_tramos, _payload_produccion_dia


@override_settings(ALLOWED_HOSTS=['testserver', 'localhost'])
class VistasOperativasTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username='operador', password='pass12345')
        self.supervisor_group = Group.objects.create(name='Supervisor')
        for codename in ('ver_inventario', 'ver_reportes'):
            self.user.user_permissions.add(Permission.objects.get(codename=codename))

        categoria = Categoria.objects.create(nombre='Camiseta')
        self.item = Item.objects.create(
            codigo='CG',
            nombre='Bolsa Camiseta Grande',
            tipo='producto',
            categoria=categoria,
            unidad_medida='fardos',
            stock_minimo=Decimal('10'),
        )
        ubicacion = Ubicacion.objects.create(nombre='Bodega', tipo='bodega')
        Stock.objects.create(item=self.item, ubicacion=ubicacion, cantidad_actual=Decimal('5'))

    def test_dashboard_autenticado_responde(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)

    def test_inventario_responde_con_permiso(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('inventario_lista'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Bolsa Camiseta Grande')

    def test_movimientos_responde_con_paginacion(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('movimiento_lista'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('page_obj', response.context)

    def test_reporte_stock_bajo_responde(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('reporte_stock_bajo'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Bolsa Camiseta Grande')

    def test_alertas_responde_y_muestra_stock_bajo(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('alertas_centro'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Bolsa Camiseta Grande')

    def test_alertas_sin_permiso_devuelve_403(self):
        user = User.objects.create_user(username='sin_permiso', password='pass12345')
        self.client.force_login(user)
        response = self.client.get(reverse('alertas_centro'))
        self.assertEqual(response.status_code, 403)

    def test_notificaciones_panel_requiere_supervisor_o_admin(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('notificaciones_panel'))
        self.assertEqual(response.status_code, 403)

        self.user.groups.add(self.supervisor_group)
        response = self.client.get(reverse('notificaciones_panel'))
        self.assertEqual(response.status_code, 200)

    def test_notificacion_manual_stock_bajo_sin_webhook_no_falla(self):
        self.user.groups.add(self.supervisor_group)
        self.client.force_login(self.user)
        response = self.client.post(reverse('notificaciones_panel'), {'tipo': 'stock_bajo'})
        self.assertRedirects(response, reverse('notificaciones_panel'))

    def test_payload_produccion_dia_incluye_salidas_completas_del_dia(self):
        cliente = Cliente.objects.create(nombre='Renato')
        ubicacion = Stock.objects.get(item=self.item).ubicacion
        mov = MovimientoInventario.objects.create(
            tipo_movimiento='salida',
            fecha_movimiento=timezone.now(),
            usuario=self.user,
            cliente=cliente,
            motivo='Salida del día',
        )
        DetalleMovimiento.objects.create(
            movimiento=mov,
            item=self.item,
            cantidad=Decimal('7'),
            ubicacion_origen=ubicacion,
        )

        payload = _payload_produccion_dia()

        self.assertNotIn('conteos_usados', payload)
        self.assertNotIn('faltantes', payload)
        self.assertEqual(payload['inventario_actual'][0]['nombre'], 'Bolsa Camiseta Grande')
        self.assertEqual(payload['inventario_actual'][0]['stock_actual'], 5.0)
        self.assertEqual(payload['salidas_dia_total'], 7.0)
        self.assertEqual(len(payload['salidas_del_dia_detalle']), 1)
        salida = payload['salidas_del_dia_detalle'][0]
        self.assertEqual(salida['movimiento_id'], mov.pk)
        self.assertEqual(salida['cliente'], 'Renato')
        self.assertEqual(salida['total_movimiento'], 7.0)
        self.assertEqual(salida['items'][0]['nombre'], 'Bolsa Camiseta Grande')

    def test_backups_panel_requiere_permiso(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('backups_panel'))
        self.assertEqual(response.status_code, 403)

        self.user.user_permissions.add(Permission.objects.get(codename='gestionar_backups'))
        response = self.client.get(reverse('backups_panel'))
        self.assertEqual(response.status_code, 200)

    def test_backup_manual_registra_job_exitoso(self):
        self.user.user_permissions.add(Permission.objects.get(codename='gestionar_backups'))
        self.client.force_login(self.user)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / 'postgres'
            root.mkdir(parents=True)

            def fake_run(*args, **kwargs):
                (root / 'inventario_20260520_1200.sql.gz').write_bytes(b'backup')
                return SimpleNamespace(returncode=0, stdout='ok', stderr='')

            with patch.dict('os.environ', {'BACKUP_ROOT': str(root), 'N8N_WEBHOOK_URL': ''}):
                with patch('apps.core.views.subprocess.run', side_effect=fake_run):
                    response = self.client.post(reverse('backups_panel'))

        self.assertRedirects(response, reverse('backups_panel'))
        job = BackupJob.objects.latest('fecha_inicio')
        self.assertEqual(job.estado, 'exitoso')
        self.assertEqual(job.archivo, 'postgres/inventario_20260520_1200.sql.gz')

    def test_backup_download_rechaza_path_traversal(self):
        self.user.user_permissions.add(Permission.objects.get(codename='gestionar_backups'))
        self.client.force_login(self.user)
        response = self.client.get(reverse('backup_descargar', args=['..%2Fsecret.sql.gz']))
        self.assertEqual(response.status_code, 404)

    def test_tramo_noche_se_asigna_a_fecha_inicial(self):
        def aware(year, month, day, hour, minute):
            return timezone.make_aware(datetime(year, month, day, hour, minute))

        c_manana = Conteo.objects.create(
            fecha=date(2026, 5, 12),
            turno='manana',
            tipo_conteo='camiseta',
            fecha_hora_conteo=aware(2026, 5, 12, 8, 0),
            usuario=self.user,
        )
        c_tarde = Conteo.objects.create(
            fecha=date(2026, 5, 12),
            turno='tarde',
            tipo_conteo='camiseta',
            fecha_hora_conteo=aware(2026, 5, 12, 22, 59),
            usuario=self.user,
        )
        c_manana_sig = Conteo.objects.create(
            fecha=date(2026, 5, 13),
            turno='manana',
            tipo_conteo='camiseta',
            fecha_hora_conteo=aware(2026, 5, 13, 16, 25),
            usuario=self.user,
        )
        for conteo, cantidad in (
            (c_manana, Decimal('0')),
            (c_tarde, Decimal('5')),
            (c_manana_sig, Decimal('9')),
        ):
            ConteoDetalle.objects.create(
                conteo=conteo,
                item=self.item,
                ubicacion=Stock.objects.get(item=self.item).ubicacion,
                cantidad_contada=cantidad,
                cantidad_sistema_al_conteo=Decimal('0'),
            )

        tramos = _calcular_tramos(date(2026, 5, 12), date(2026, 5, 12))
        noche = [t for t in tramos if t['tipo'] == 'noche'][0]

        self.assertEqual(noche['fecha_asignada'], date(2026, 5, 12))
        self.assertIn('22:59', noche['label_rango'])
        self.assertIn('16:25', noche['label_rango'])

    def test_cliente_salidas_usa_fecha_movimiento_y_detalles(self):
        cliente = Cliente.objects.create(nombre='Renato', activo=True)
        mov = MovimientoInventario.objects.create(
            tipo_movimiento='salida',
            fecha_movimiento=timezone.make_aware(datetime(2026, 5, 5, 10, 30)),
            motivo='Venta',
            usuario=self.user,
            cliente=cliente,
        )
        DetalleMovimiento.objects.create(
            movimiento=mov,
            item=self.item,
            cantidad=Decimal('10'),
            ubicacion_origen=Stock.objects.get(item=self.item).ubicacion,
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse('cliente_salidas', args=[cliente.pk]), {
            'fecha_inicio': '2026-05-01',
            'fecha_fin': '2026-05-13',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Renato')
        self.assertContains(response, 'Bolsa Camiseta Grande')
        self.assertContains(response, '10')
