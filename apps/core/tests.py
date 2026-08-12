from decimal import Decimal
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import tempfile

from django.contrib.auth.models import Group, Permission, User
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import (
    BackupJob, Categoria, CategoriaProducto, Cliente, Conteo, ConteoDetalle,
    DetalleMovimiento, DocumentoFactura, Item, Maquina, MovimientoInventario,
    Stock, Ubicacion,
)
from .views import (
    _aplicar_efecto_detalle,
    _calcular_produccion,
    _calcular_produccion_rango,
    _calcular_tramos,
    _payload_produccion_dia,
    _stock_en_momento,
)


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

    def test_navegacion_simplifica_reportes_sin_eliminar_rutas(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('dashboard'))
        html = response.content.decode()

        self.assertEqual(html.count(f'href="{reverse("reporte_produccion")}"'), 0)
        self.assertEqual(html.count(f'href="{reverse("reporte_produccion_avanzado")}"'), 2)
        self.assertNotIn('Producción rango', html)
        self.assertEqual(reverse('reporte_stock_bajo'), '/reportes/stock-bajo/')
        self.assertEqual(reverse('reporte_produccion'), '/reportes/produccion/')
        self.assertEqual(reverse('alertas_centro'), '/alertas/')

    def test_dashboard_ultimos_movimientos_muestra_cliente_de_salida(self):
        cliente = Cliente.objects.create(nombre='Renato')
        ubicacion = Stock.objects.get(item=self.item).ubicacion
        mov = MovimientoInventario.objects.create(
            tipo_movimiento='salida',
            fecha_movimiento=timezone.now(),
            usuario=self.user,
            cliente=cliente,
            motivo='Entrega programada',
        )
        DetalleMovimiento.objects.create(
            movimiento=mov,
            item=self.item,
            cantidad=Decimal('3'),
            ubicacion_origen=ubicacion,
            cliente=cliente,
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Renato')
        self.assertContains(response, 'Entrega programada')

    def test_dashboard_muestra_ajuste_positivo_de_producto_como_produccion(self):
        ubicacion = Stock.objects.get(item=self.item).ubicacion
        mov = MovimientoInventario.objects.create(
            tipo_movimiento='ajuste',
            fecha_movimiento=timezone.now(),
            usuario=self.user,
            motivo='Ajuste por conteo',
        )
        DetalleMovimiento.objects.create(
            movimiento=mov,
            item=self.item,
            cantidad=Decimal('10'),
            ubicacion_destino=ubicacion,
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        idx = html.index('Ajuste por conteo')
        movimiento_html = html[idx - 600:idx]
        self.assertIn('Producción', movimiento_html)
        self.assertNotIn('>Ajuste', movimiento_html)

    def test_dashboard_muestra_ajuste_negativo_de_producto_como_ajuste(self):
        ubicacion = Stock.objects.get(item=self.item).ubicacion
        mov = MovimientoInventario.objects.create(
            tipo_movimiento='ajuste',
            fecha_movimiento=timezone.now(),
            usuario=self.user,
            motivo='Ajuste por merma',
        )
        DetalleMovimiento.objects.create(
            movimiento=mov,
            item=self.item,
            cantidad=Decimal('-4'),
            ubicacion_destino=ubicacion,
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        idx = html.index('Ajuste por merma')
        movimiento_html = html[idx - 600:idx]
        self.assertIn('Ajuste', movimiento_html)
        self.assertNotIn('Producción', movimiento_html)

    @override_settings(FACTURAS_MODULE_ENABLED=True)
    @patch('apps.core.views.dashboard._calcular_tramos')
    def test_dashboard_resume_mes_actual_y_facturacion_por_tipo(self, calcular_tramos):
        calcular_tramos.return_value = [
            {'produccion': Decimal('120')},
            {'produccion': Decimal('80')},
        ]
        self.user.user_permissions.add(Permission.objects.get(codename='ver_facturas'))
        cliente = Cliente.objects.create(nombre='Cliente mensual')
        ubicacion = Stock.objects.get(item=self.item).ubicacion
        salida = MovimientoInventario.objects.create(
            tipo_movimiento='salida',
            fecha_movimiento=timezone.now(),
            usuario=self.user,
        )
        DetalleMovimiento.objects.create(
            movimiento=salida,
            item=self.item,
            cantidad=Decimal('35'),
            ubicacion_origen=ubicacion,
        )
        DocumentoFactura.objects.create(
            cliente=cliente,
            tipo_documento='factura',
            fecha_documento=timezone.localdate(),
            monto_total=Decimal('1500'),
        )
        DocumentoFactura.objects.create(
            cliente=cliente,
            tipo_documento='envio',
            fecha_documento=timezone.localdate(),
            monto_total=Decimal('725'),
        )
        DocumentoFactura.objects.create(
            cliente=cliente,
            tipo_documento='factura',
            fecha_documento=timezone.localdate(),
            monto_total=Decimal('999'),
            estado_pago='anulada',
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['resumen_mes']['produccion'], Decimal('200'))
        self.assertEqual(response.context['resumen_mes']['salidas'], Decimal('35'))
        facturacion = response.context['resumen_mes']['facturacion']
        self.assertEqual(facturacion['factura']['total'], Decimal('1500'))
        self.assertEqual(facturacion['envio']['total'], Decimal('725'))
        self.assertContains(response, 'Facturado · Facturas')
        self.assertContains(response, 'Facturado · Envíos')

    @override_settings(FACTURAS_MODULE_ENABLED=True)
    @patch('apps.core.views.reportes._calcular_tramos')
    def test_reporte_rendimiento_compara_mismo_corte_y_excluye_anuladas(
            self, calcular_tramos):
        hoy = timezone.localdate()
        inicio_actual = hoy.replace(day=1)
        fin_mes_anterior = inicio_actual - timedelta(days=1)
        inicio_anterior = fin_mes_anterior.replace(day=1)
        fin_anterior = min(
            fin_mes_anterior,
            inicio_anterior + timedelta(days=hoy.day - 1),
        )

        def tramos_por_periodo(inicio, fin):
            total = Decimal('300') if inicio == inicio_actual else Decimal('200')
            return [{'produccion': total}]

        calcular_tramos.side_effect = tramos_por_periodo
        self.user.user_permissions.add(Permission.objects.get(codename='ver_facturas'))
        cliente = Cliente.objects.create(nombre='Cliente comparativo')

        DocumentoFactura.objects.create(
            cliente=cliente,
            tipo_documento='factura',
            fecha_documento=hoy,
            monto_total=Decimal('1500'),
        )
        DocumentoFactura.objects.create(
            cliente=cliente,
            tipo_documento='factura',
            fecha_documento=fin_anterior,
            monto_total=Decimal('1000'),
        )
        DocumentoFactura.objects.create(
            cliente=cliente,
            tipo_documento='factura',
            fecha_documento=hoy,
            monto_total=Decimal('900'),
            estado_pago='anulada',
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse('reporte_rendimiento_mensual'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['fin_actual'], hoy)
        self.assertEqual(response.context['fin_anterior'], fin_anterior)
        self.assertEqual(response.context['produccion']['variacion'], Decimal('50.0'))
        factura = response.context['facturacion']['factura']
        self.assertEqual(factura['actual'], Decimal('1500'))
        self.assertEqual(factura['anterior'], Decimal('1000'))
        self.assertEqual(factura['variacion'], Decimal('50.0'))
        self.assertContains(response, 'Rendimiento por período')
        self.assertContains(response, 'Período anterior')

    @override_settings(FACTURAS_MODULE_ENABLED=True)
    @patch('apps.core.views.reportes._calcular_tramos', return_value=[])
    def test_reporte_rendimiento_oculta_facturacion_sin_permiso(self, calcular_tramos):
        self.client.force_login(self.user)

        response = self.client.get(reverse('reporte_rendimiento_mensual'))

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['facturacion'])
        self.assertContains(response, 'requiere que el módulo esté habilitado')

    @override_settings(FACTURAS_MODULE_ENABLED=True)
    @patch('apps.core.views.reportes._calcular_tramos', return_value=[])
    def test_reporte_rendimiento_desglosa_facturas_y_envios_por_categoria(
            self, calcular_tramos):
        hoy = timezone.localdate()
        inicio_actual = hoy.replace(day=1)
        fin_mes_anterior = inicio_actual - timedelta(days=1)
        inicio_mes_anterior = fin_mes_anterior.replace(day=1)
        fecha_comparable_anterior = inicio_mes_anterior + timedelta(days=hoy.day - 1)
        categoria = CategoriaProducto.objects.create(nombre='Bolsa Camiseta')
        cliente = Cliente.objects.create(nombre='Cliente por categoría')
        self.user.user_permissions.add(Permission.objects.get(codename='ver_facturas'))

        DocumentoFactura.objects.create(
            cliente=cliente,
            tipo_documento='factura',
            categoria=categoria,
            fecha_documento=hoy,
            monto_total=Decimal('1200'),
        )
        DocumentoFactura.objects.create(
            cliente=cliente,
            tipo_documento='envio',
            categoria=categoria,
            fecha_documento=hoy,
            monto_total=Decimal('300'),
        )
        DocumentoFactura.objects.create(
            cliente=cliente,
            tipo_documento='factura',
            categoria=categoria,
            fecha_documento=fecha_comparable_anterior,
            monto_total=Decimal('800'),
        )
        DocumentoFactura.objects.create(
            cliente=cliente,
            tipo_documento='envio',
            fecha_documento=hoy,
            monto_total=Decimal('125'),
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse('reporte_rendimiento_mensual'))

        self.assertEqual(response.status_code, 200)
        filas = response.context['facturacion_por_categoria']
        self.assertEqual(
            [(f['tipo_documento'], f['categoria']) for f in filas],
            [
                ('factura', 'Bolsa Camiseta'),
                ('envio', 'Bolsa Camiseta'),
                ('envio', 'Sin categoría'),
            ],
        )
        factura_camiseta = filas[0]
        self.assertEqual(factura_camiseta['actual'], Decimal('1200'))
        self.assertEqual(factura_camiseta['anterior'], Decimal('800'))
        self.assertEqual(factura_camiseta['documentos_actual'], 1)
        self.assertEqual(factura_camiseta['variacion'], Decimal('50.0'))
        self.assertContains(response, 'Facturación por tipo y categoría')
        self.assertContains(response, 'Bolsa Camiseta')
        self.assertContains(response, 'Sin categoría')

    @override_settings(FACTURAS_MODULE_ENABLED=True)
    @patch('apps.core.views.reportes.timezone.localdate', return_value=date(2026, 8, 4))
    @patch('apps.core.views.reportes._calcular_tramos', return_value=[])
    def test_reporte_rendimiento_no_marca_nueva_categoria_con_actividad_previa(
            self, calcular_tramos, localdate):
        categoria = CategoriaProducto.objects.create(nombre='Lisa')
        cliente = Cliente.objects.create(nombre='Cliente base comparable')
        self.user.user_permissions.add(Permission.objects.get(codename='ver_facturas'))
        DocumentoFactura.objects.create(
            cliente=cliente,
            tipo_documento='factura',
            categoria=categoria,
            fecha_documento=date(2026, 7, 20),
            monto_total=Decimal('5000'),
        )
        DocumentoFactura.objects.create(
            cliente=cliente,
            tipo_documento='factura',
            categoria=categoria,
            fecha_documento=date(2026, 8, 2),
            monto_total=Decimal('1200'),
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse('reporte_rendimiento_mensual'))

        self.assertEqual(response.status_code, 200)
        lisa = response.context['facturacion_por_categoria'][0]
        self.assertEqual(lisa['actual'], Decimal('1200'))
        self.assertEqual(lisa['anterior'], Decimal('0'))
        self.assertEqual(lisa['tendencia'], 'sin_base')
        self.assertContains(response, 'Sin base comparable')

    @patch('apps.core.views.reportes._calcular_tramos', return_value=[])
    def test_reporte_rendimiento_permite_comparar_trimestres(self, calcular_tramos):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse('reporte_rendimiento_mensual'),
            {'periodo': 'trimestre', 'anio': '2026', 'trimestre': '2'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['tipo_periodo'], 'trimestre')
        self.assertEqual(response.context['inicio_actual'], date(2026, 4, 1))
        self.assertEqual(response.context['fin_actual'], date(2026, 6, 30))
        self.assertEqual(response.context['inicio_anterior'], date(2026, 1, 1))
        self.assertEqual(response.context['fin_anterior'], date(2026, 3, 31))
        self.assertEqual(response.context['periodo_actual_titulo'], 'T2 2026')
        self.assertContains(response, 'T2 · Abr–Jun')
        self.assertContains(response, 'Período actual')

    @override_settings(FACTURAS_MODULE_ENABLED=True)
    @patch('apps.core.views.reportes._calcular_tramos', return_value=[])
    def test_reporte_rendimiento_compara_meses_historicos_completos(
            self, calcular_tramos):
        self.user.user_permissions.add(Permission.objects.get(codename='ver_facturas'))
        cliente = Cliente.objects.create(nombre='Cliente cierre mensual')
        DocumentoFactura.objects.create(
            cliente=cliente,
            tipo_documento='factura',
            fecha_documento=date(2026, 3, 31),
            monto_total=Decimal('700'),
        )
        DocumentoFactura.objects.create(
            cliente=cliente,
            tipo_documento='factura',
            fecha_documento=date(2026, 4, 30),
            monto_total=Decimal('500'),
        )

        self.client.force_login(self.user)
        response = self.client.get(
            reverse('reporte_rendimiento_mensual'),
            {'periodo': 'mes', 'mes': '2026-04'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['inicio_actual'], date(2026, 4, 1))
        self.assertEqual(response.context['fin_actual'], date(2026, 4, 30))
        self.assertEqual(response.context['inicio_anterior'], date(2026, 3, 1))
        self.assertEqual(response.context['fin_anterior'], date(2026, 3, 31))
        factura = response.context['facturacion']['factura']
        self.assertEqual(factura['actual'], Decimal('500'))
        self.assertEqual(factura['anterior'], Decimal('700'))

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
                (root / 'inventario_20260520_1200.tar.gz').write_bytes(b'backup')
                return SimpleNamespace(returncode=0, stdout='ok', stderr='')

            with patch.dict('os.environ', {'BACKUP_ROOT': str(root), 'N8N_WEBHOOK_URL': ''}):
                with patch('apps.core.views.admin_ops.subprocess.run', side_effect=fake_run):
                    response = self.client.post(reverse('backups_panel'))

        self.assertRedirects(response, reverse('backups_panel'))
        job = BackupJob.objects.latest('fecha_inicio')
        self.assertEqual(job.estado, 'exitoso')
        self.assertEqual(job.archivo, 'postgres/inventario_20260520_1200.tar.gz')

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

    def test_salida_en_mismo_minuto_del_conteo_final_pertenece_al_turno_dia(self):
        """Un datetime-local no guarda segundos: el cierre debe incluir su minuto."""
        def aware(year, month, day, hour, minute):
            return timezone.make_aware(datetime(year, month, day, hour, minute))

        ubicacion = Stock.objects.get(item=self.item).ubicacion
        fecha_operativa = date(2026, 7, 27)
        conteo_manana = Conteo.objects.create(
            fecha=fecha_operativa,
            turno='manana',
            tipo_conteo='camiseta',
            fecha_hora_conteo=aware(2026, 7, 27, 10, 40),
            usuario=self.user,
        )
        conteo_tarde = Conteo.objects.create(
            fecha=fecha_operativa,
            turno='tarde',
            tipo_conteo='camiseta',
            fecha_hora_conteo=aware(2026, 7, 27, 17, 1),
            usuario=self.user,
        )
        conteo_manana_sig = Conteo.objects.create(
            fecha=date(2026, 7, 28),
            turno='manana',
            tipo_conteo='camiseta',
            fecha_hora_conteo=aware(2026, 7, 28, 10, 40),
            usuario=self.user,
        )
        for conteo, cantidad in (
            (conteo_manana, Decimal('476')),
            (conteo_tarde, Decimal('311')),
            (conteo_manana_sig, Decimal('311')),
        ):
            ConteoDetalle.objects.create(
                conteo=conteo,
                item=self.item,
                ubicacion=ubicacion,
                cantidad_contada=cantidad,
                cantidad_sistema_al_conteo=Decimal('0'),
            )

        movimientos = []
        for hora, minuto, cantidad in (
            (15, 41, Decimal('95')),
            (17, 1, Decimal('90')),
        ):
            movimiento = MovimientoInventario.objects.create(
                tipo_movimiento='salida',
                tipo_salida='producto_terminado',
                fecha_movimiento=aware(2026, 7, 27, hora, minuto),
                usuario=self.user,
            )
            DetalleMovimiento.objects.create(
                movimiento=movimiento,
                item=self.item,
                cantidad=cantidad,
                ubicacion_origen=ubicacion,
            )
            movimientos.append(movimiento)

        produccion = _calcular_produccion(fecha_operativa)
        rango = _calcular_produccion_rango(fecha_operativa, fecha_operativa)[fecha_operativa]
        tramos = _calcular_tramos(fecha_operativa, fecha_operativa)
        tramo_dia = next(t for t in tramos if t['tipo'] == 'dia')
        tramo_noche = next(t for t in tramos if t['tipo'] == 'noche')
        self.client.force_login(self.user)
        reporte = self.client.get(
            reverse('reporte_produccion'),
            {'fecha': fecha_operativa.isoformat()},
        )

        self.assertEqual(produccion['salidas_dia'], Decimal('185'))
        self.assertEqual(produccion['produccion_dia'], Decimal('20'))
        self.assertEqual(produccion['salidas_noche'], Decimal('0'))
        self.assertEqual(rango['prod_dia'], Decimal('20'))
        self.assertEqual(rango['prod_noche'], Decimal('0'))
        self.assertEqual(tramo_dia['salidas'], Decimal('185'))
        self.assertEqual(tramo_noche['salidas'], Decimal('0'))
        self.assertCountEqual(
            reporte.context['salidas_detalle_dia'].values_list('movimiento_id', flat=True),
            [movimiento.pk for movimiento in movimientos],
        )
        self.assertFalse(reporte.context['salidas_detalle_noche'].exists())

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


@override_settings(ALLOWED_HOSTS=['testserver', 'localhost'])
class SalidaPendienteConciliacionTests(TestCase):
    """
    Verifica que las salidas con stock insuficiente:
      • Descuentan stock normalmente (queda negativo).
      • Se marcan como pendiente_conciliacion=True.
      • NO se excluyen de stock teórico ni de conteos.
      • Generan ajuste positivo correcto en conciliación.
    """
    def setUp(self):
        cache.clear()
        categoria = Categoria.objects.create(nombre='Camiseta')
        self.item = Item.objects.create(
            codigo='BCG', nombre='Bolsa Camiseta Grande', tipo='producto',
            categoria=categoria, unidad_medida='fardos', stock_minimo=Decimal('10'),
        )
        self.ubicacion = Ubicacion.objects.create(nombre='Bodega PT', tipo='bodega')
        self.cliente = Cliente.objects.create(nombre='Renato')
        # Stock inicial 21
        Stock.objects.create(
            item=self.item, ubicacion=self.ubicacion,
            cantidad_actual=Decimal('21'),
        )
        self.user = User.objects.create_user(username='op', password='x')

    def _crear_salida(self, cantidad, pendiente, fecha=None):
        mov = MovimientoInventario.objects.create(
            tipo_movimiento='salida', tipo_salida='producto_terminado',
            motivo='test', usuario=self.user, cliente=self.cliente,
            fecha_movimiento=fecha or timezone.now(),
        )
        det = DetalleMovimiento.objects.create(
            movimiento=mov, item=self.item, cantidad=Decimal(str(cantidad)),
            ubicacion_origen=self.ubicacion, cliente=self.cliente,
            pendiente_conciliacion=pendiente,
        )
        _aplicar_efecto_detalle(det)
        return mov, det

    def test_salida_pendiente_descuenta_stock_normalmente(self):
        """Stock 21 - salida 25 = -4, con pendiente_conciliacion=True."""
        mov, det = self._crear_salida(25, pendiente=True)
        stock = Stock.objects.get(item=self.item, ubicacion=self.ubicacion)
        self.assertEqual(stock.cantidad_actual, Decimal('-4'))
        self.assertTrue(det.pendiente_conciliacion)

    def test_stock_en_momento_incluye_salidas_pendientes(self):
        """_stock_en_momento usa cantidad_actual real → ve el stock negativo."""
        ahora = timezone.now()
        self._crear_salida(25, pendiente=True, fecha=ahora - timezone.timedelta(hours=1))
        stock_teorico = _stock_en_momento(self.item, self.ubicacion, ahora)
        self.assertEqual(stock_teorico, Decimal('-4'))

    def test_stock_en_momento_incluye_salida_del_mismo_minuto(self):
        """Regresión: salida y conteo en el mismo minuto.

        El widget del conteo trunca la hora al minuto (14:23:00) mientras que la
        salida guarda fecha_movimiento con segundos (14:23:47). La salida NO debe
        revertirse: si no, el conteo se ve 'como si la salida no se aplicara'.
        """
        base = timezone.make_aware(datetime(2026, 5, 12, 14, 23, 0))
        # Salida de 5 en el segundo 47 del MISMO minuto que el conteo → stock 16.
        self._crear_salida(5, pendiente=False,
                           fecha=base + timezone.timedelta(seconds=47))
        # Conteo truncado al minuto, como lo envía el input datetime-local.
        stock_teorico = _stock_en_momento(self.item, self.ubicacion, base)
        self.assertEqual(stock_teorico, Decimal('16'))  # 21 - 5, salida incluida

    def test_conteo_nuevo_muestra_stock_negativo_si_pendiente(self):
        """Conteo nuevo debe leer Stock.cantidad_actual incluyendo el -4."""
        self._crear_salida(25, pendiente=True)
        # Otorgar permisos al usuario
        self.user.user_permissions.add(
            Permission.objects.get(codename='registrar_conteo'),
            Permission.objects.get(codename='ver_inventario'),
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse('conteo_nuevo'))
        self.assertEqual(response.status_code, 200)
        # El JSON con stocks_by_ub debe contener -4
        self.assertContains(response, '-4')

    def test_permite_varios_conteos_de_repuestos_el_mismo_turno(self):
        """"Otros" representa conteos parciales de repuestos y es repetible."""
        self.user.user_permissions.add(
            Permission.objects.get(codename='registrar_conteo')
        )
        self.client.force_login(self.user)
        payload = {
            'fecha': date.today().isoformat(),
            'turno': 'manana',
            'tipo_conteo': 'otros',
            'fecha_hora_conteo': timezone.localtime().strftime('%Y-%m-%dT%H:%M'),
            'item[]': [str(self.item.pk)],
            'ubicacion[]': [str(self.ubicacion.pk)],
            'cantidad_contada[]': ['21'],
        }

        primero = self.client.post(reverse('conteo_nuevo'), payload)
        segundo = self.client.post(reverse('conteo_nuevo'), payload)

        self.assertEqual(primero.status_code, 302)
        self.assertEqual(segundo.status_code, 302)
        self.assertEqual(
            Conteo.objects.filter(
                fecha=date.today(), turno='manana', tipo_conteo='otros',
                anulado=False,
            ).count(),
            2,
        )

    def test_conteo_fijo_sigue_siendo_unico_por_turno(self):
        datos = {
            'fecha': date.today(),
            'turno': 'manana',
            'tipo_conteo': 'camiseta',
            'usuario': self.user,
            'fecha_hora_conteo': timezone.now(),
        }
        Conteo.objects.create(**datos)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Conteo.objects.create(**datos)

    def test_conteo_rechaza_cantidad_decimal(self):
        self.user.user_permissions.add(Permission.objects.get(codename='registrar_conteo'))
        self.client.force_login(self.user)
        response = self.client.post(reverse('conteo_nuevo'), {
            'fecha': date.today().isoformat(),
            'turno': 'manana',
            'tipo_conteo': 'camiseta',
            'fecha_hora_conteo': timezone.localtime().strftime('%Y-%m-%dT%H:%M'),
            'item[]': [str(self.item.pk)],
            'ubicacion[]': [str(self.ubicacion.pk)],
            'cantidad_contada[]': ['5.5'],
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Las cantidades del conteo deben ser números enteros.')
        self.assertEqual(Conteo.objects.count(), 0)

    def test_editar_conteo_precarga_cantidad_sin_decimales(self):
        conteo = Conteo.objects.create(
            fecha=date.today(), turno='manana', tipo_conteo='camiseta',
            usuario=self.user, fecha_hora_conteo=timezone.now(),
        )
        ConteoDetalle.objects.create(
            conteo=conteo, item=self.item, ubicacion=self.ubicacion,
            cantidad_contada=Decimal('5.00'),
            cantidad_sistema_al_conteo=Decimal('21.00'),
        )
        self.user.user_permissions.add(Permission.objects.get(codename='editar_conteo'))
        self.client.force_login(self.user)
        response = self.client.get(reverse('conteo_editar', args=[conteo.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '"cant": "5"')

    def test_conciliacion_genera_ajuste_positivo_correcto(self):
        """
        Stock sistema -4, contado 21 → diferencia = 21 - (-4) = +25.
        Conciliación debe crear ajuste positivo +25.
        """
        from .views import _stock_en_momento as _sem
        ahora = timezone.now()
        self._crear_salida(25, pendiente=True, fecha=ahora - timezone.timedelta(hours=2))

        # Crear conteo
        conteo = Conteo.objects.create(
            fecha=date.today(), turno='manana', tipo_conteo='camiseta',
            usuario=self.user, fecha_hora_conteo=ahora,
        )
        ConteoDetalle.objects.create(
            conteo=conteo, item=self.item, ubicacion=self.ubicacion,
            cantidad_contada=Decimal('21'),
            cantidad_sistema_al_conteo=Decimal('-4'),
        )

        stock_teorico = _sem(self.item, self.ubicacion, ahora)
        diferencia = Decimal('21') - stock_teorico  # 21 - (-4) = 25
        self.assertEqual(stock_teorico, Decimal('-4'))
        self.assertEqual(diferencia, Decimal('25'))

    def test_get_conciliar_no_persiste_diferencia_final(self):
        ahora = timezone.now()
        conteo = Conteo.objects.create(
            fecha=date.today(), turno='manana', tipo_conteo='camiseta',
            usuario=self.user, fecha_hora_conteo=ahora,
        )
        detalle = ConteoDetalle.objects.create(
            conteo=conteo, item=self.item, ubicacion=self.ubicacion,
            cantidad_contada=Decimal('10'),
            cantidad_sistema_al_conteo=Decimal('21'),
        )
        self.user.user_permissions.add(Permission.objects.get(codename='aplicar_conciliacion'))
        self.client.force_login(self.user)
        response = self.client.get(reverse('conteo_conciliar', args=[conteo.pk]))
        self.assertEqual(response.status_code, 200)
        detalle.refresh_from_db()
        self.assertIsNone(detalle.diferencia_final)

    def test_conciliacion_aplica_ajuste_y_restaura_stock(self):
        """
        Flujo completo: stock -4 → conciliación con conteo 21 →
        ajuste +25 aplicado → stock final 21.
        """
        ahora = timezone.now()
        self._crear_salida(25, pendiente=True, fecha=ahora - timezone.timedelta(hours=2))
        self.assertEqual(
            Stock.objects.get(item=self.item, ubicacion=self.ubicacion).cantidad_actual,
            Decimal('-4'),
        )

        conteo = Conteo.objects.create(
            fecha=date.today(), turno='manana', tipo_conteo='camiseta',
            usuario=self.user, fecha_hora_conteo=ahora,
        )
        ConteoDetalle.objects.create(
            conteo=conteo, item=self.item, ubicacion=self.ubicacion,
            cantidad_contada=Decimal('21'),
            cantidad_sistema_al_conteo=Decimal('-4'),
            diferencia_final=Decimal('25'),
        )

        for codename in ('aplicar_conciliacion', 'registrar_conteo'):
            self.user.user_permissions.add(Permission.objects.get(codename=codename))
        self.client.force_login(self.user)
        resp = self.client.post(reverse('conteo_ajustar_todos', args=[conteo.pk]))
        self.assertIn(resp.status_code, (302, 200))

        stock = Stock.objects.get(item=self.item, ubicacion=self.ubicacion)
        self.assertEqual(stock.cantidad_actual, Decimal('21'))

    def test_anular_salida_pendiente_revierte_una_sola_vez(self):
        """Caso 3: anular salida -25 → stock vuelve a 21, sin doble reversión."""
        mov, _ = self._crear_salida(25, pendiente=True)
        self.assertEqual(
            Stock.objects.get(item=self.item, ubicacion=self.ubicacion).cantidad_actual,
            Decimal('-4'),
        )

        self.user.user_permissions.add(Permission.objects.get(codename='anular_movimiento'))
        self.client.force_login(self.user)
        resp = self.client.post(
            reverse('movimiento_anular', args=[mov.pk]),
            {'motivo_anulacion': 'prueba reversión'},
        )
        self.assertIn(resp.status_code, (302, 200))

        stock = Stock.objects.get(item=self.item, ubicacion=self.ubicacion)
        self.assertEqual(stock.cantidad_actual, Decimal('21'))
        mov.refresh_from_db()
        self.assertTrue(mov.anulado)

        # Segundo intento de anular no debe volver a revertir (sigue en 21)
        self.client.post(
            reverse('movimiento_anular', args=[mov.pk]),
            {'motivo_anulacion': 'segundo intento'},
        )
        stock.refresh_from_db()
        self.assertEqual(stock.cantidad_actual, Decimal('21'))

    def test_salida_repuesto_sin_stock_se_bloquea(self):
        """Caso 4: salida de repuesto sin stock suficiente NO se permite."""
        repuesto = Item.objects.create(
            codigo='REP1', nombre='Cuchilla', tipo='repuesto',
            unidad_medida='unidad', stock_minimo=Decimal('1'),
        )
        Stock.objects.create(item=repuesto, ubicacion=self.ubicacion, cantidad_actual=Decimal('2'))
        maquina = Maquina.objects.create(codigo='M1', nombre='Extrusora', area='Producción')

        self.user.user_permissions.add(Permission.objects.get(codename='registrar_salida'))
        self.client.force_login(self.user)
        resp = self.client.post(reverse('movimiento_salida'), {
            'tipo_salida': 'repuestos',
            'motivo': 'test',
            'item[]': [str(repuesto.pk)],
            'cantidad[]': ['10'],            # > stock (2)
            'ubicacion_origen[]': [str(self.ubicacion.pk)],
            'maquina[]': [str(maquina.pk)],
        })
        # No se crea movimiento de repuesto y el stock no cambia
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(
            MovimientoInventario.objects.filter(tipo_salida='repuestos').exists()
        )
        self.assertEqual(
            Stock.objects.get(item=repuesto, ubicacion=self.ubicacion).cantidad_actual,
            Decimal('2'),
        )


@override_settings(ALLOWED_HOSTS=['testserver', 'localhost'])
class InventarioCamisetaPostConciliacionTests(TestCase):
    """
    Verifica el reenvío automático del inventario camiseta (event_type
    'inventario_camiseta_actual') UNA sola vez, cuando el conteo transiciona
    a 'conciliado' — sin importar si fue por aplicar ajustes (que cierra la
    conciliación automáticamente) o por el botón 'Cerrar conciliación'.
    """
    def setUp(self):
        cache.clear()
        cat = Categoria.objects.create(nombre='Camiseta')
        self.item = Item.objects.create(
            codigo='BCG', nombre='Bolsa Camiseta Grande', tipo='producto',
            categoria=cat, unidad_medida='fardos', stock_minimo=Decimal('10'),
        )
        self.ub = Ubicacion.objects.create(nombre='Bodega PT', tipo='bodega')
        Stock.objects.create(item=self.item, ubicacion=self.ub, cantidad_actual=Decimal('5'))
        self.user = User.objects.create_user(username='conc', password='x')
        self.user.user_permissions.add(
            Permission.objects.get(codename='aplicar_conciliacion')
        )

    def _conteo_con_diferencia(self, tipo='camiseta'):
        """Conteo camiseta con una diferencia pendiente de ajustar (+25)."""
        conteo = Conteo.objects.create(
            fecha=date.today(), turno='manana', tipo_conteo=tipo,
            usuario=self.user, fecha_hora_conteo=timezone.now(),
        )
        ConteoDetalle.objects.create(
            conteo=conteo, item=self.item, ubicacion=self.ub,
            cantidad_contada=Decimal('30'),
            cantidad_sistema_al_conteo=Decimal('5'),
            diferencia_final=Decimal('25'),
        )
        return conteo

    def test_aplicar_todos_envia_inventario_una_vez(self):
        """Aplicar todos los ajustes cierra la conciliación → envía 1 vez."""
        conteo = self._conteo_con_diferencia('camiseta')
        self.client.force_login(self.user)
        with patch('apps.core.views.payloads.send_event', return_value=True) as mock_send:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.post(reverse('conteo_ajustar_todos', args=[conteo.pk]))
            self.assertIn(resp.status_code, (302, 200))
        envios = [c for c in mock_send.call_args_list
                  if c.args[0] == 'inventario_camiseta_actual']
        self.assertEqual(len(envios), 1)
        conteo.refresh_from_db()
        self.assertEqual(conteo.estado, 'conciliado')
        # Stock final correcto: 5 + 25 = 30
        self.assertEqual(
            Stock.objects.get(item=self.item, ubicacion=self.ub).cantidad_actual,
            Decimal('30'),
        )

    def test_cerrar_conciliacion_manual_turno_tarde_envia_produccion(self):
        """Cerrar conciliación de camiseta turno tarde → envía producción 1 vez."""
        conteo = Conteo.objects.create(
            fecha=date.today(), turno='tarde', tipo_conteo='camiseta',
            usuario=self.user, fecha_hora_conteo=timezone.now(),
        )
        ConteoDetalle.objects.create(
            conteo=conteo, item=self.item, ubicacion=self.ub,
            cantidad_contada=Decimal('5'),
            cantidad_sistema_al_conteo=Decimal('5'),
            diferencia_final=Decimal('0'), ajuste_aplicado=True,
        )
        self.client.force_login(self.user)
        with patch('apps.core.views.payloads.send_event', return_value=True) as mock_send:
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(reverse('conteo_marcar_conciliado', args=[conteo.pk]))
        tipos = [c.args[0] for c in mock_send.call_args_list]
        # Turno tarde manda producción, NO inventario camiseta.
        self.assertEqual(tipos.count('reporte_produccion_dia'), 1)
        self.assertNotIn('inventario_camiseta_actual', tipos)

    def test_conciliacion_turno_manana_envia_inventario_camiseta(self):
        """Conciliar camiseta turno mañana → envía inventario camiseta 1 vez."""
        conteo = Conteo.objects.create(
            fecha=date.today(), turno='manana', tipo_conteo='camiseta',
            usuario=self.user, fecha_hora_conteo=timezone.now(),
        )
        ConteoDetalle.objects.create(
            conteo=conteo, item=self.item, ubicacion=self.ub,
            cantidad_contada=Decimal('5'),
            cantidad_sistema_al_conteo=Decimal('5'),
            diferencia_final=Decimal('0'), ajuste_aplicado=True,
        )
        self.client.force_login(self.user)
        with patch('apps.core.views.payloads.send_event', return_value=True) as mock_send:
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(reverse('conteo_marcar_conciliado', args=[conteo.pk]))
        tipos = [c.args[0] for c in mock_send.call_args_list]
        self.assertEqual(tipos.count('inventario_camiseta_actual'), 1)
        self.assertNotIn('reporte_produccion_dia', tipos)

    def test_no_doble_envio_si_ya_conciliado(self):
        """Cerrar un conteo ya conciliado NO debe reenviar."""
        conteo = self._conteo_con_diferencia('camiseta')
        self.client.force_login(self.user)
        # 1) Aplicar todos → conciliado, envía 1
        with patch('apps.core.views.payloads.send_event', return_value=True):
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(reverse('conteo_ajustar_todos', args=[conteo.pk]))
        # 2) Cerrar conciliación sobre conteo ya conciliado → no reenvía
        with patch('apps.core.views.payloads.send_event', return_value=True) as mock2:
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(reverse('conteo_marcar_conciliado', args=[conteo.pk]))
        envios = [c for c in mock2.call_args_list
                  if c.args[0] == 'inventario_camiseta_actual']
        self.assertEqual(len(envios), 0)

    def test_no_envia_para_conteo_no_camiseta(self):
        conteo = self._conteo_con_diferencia('pigmentos')
        self.client.force_login(self.user)
        with patch('apps.core.views.payloads.send_event', return_value=True) as mock_send:
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(reverse('conteo_ajustar_todos', args=[conteo.pk]))
        tipos = [c.args[0] for c in mock_send.call_args_list]
        self.assertNotIn('inventario_camiseta_actual', tipos)

    def test_fallo_webhook_no_rompe_conciliacion(self):
        """Si send_event lanza excepción, la conciliación igual se completa."""
        conteo = self._conteo_con_diferencia('camiseta')
        self.client.force_login(self.user)

        def _side_effect(event_type, payload):
            if event_type == 'inventario_camiseta_actual':
                raise RuntimeError('n8n caído')
            return True

        with patch('apps.core.views.payloads.send_event', side_effect=_side_effect):
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.post(reverse('conteo_ajustar_todos', args=[conteo.pk]))
            self.assertIn(resp.status_code, (302, 200))
        conteo.refresh_from_db()
        self.assertEqual(conteo.estado, 'conciliado')
        self.assertEqual(
            Stock.objects.get(item=self.item, ubicacion=self.ub).cantidad_actual,
            Decimal('30'),
        )


@override_settings(ALLOWED_HOSTS=['testserver', 'localhost'])
class AuditarStockPendientesCommandTests(TestCase):
    """Verifica el comando de detección de drift de stock (solo-lectura)."""
    def setUp(self):
        cache.clear()
        self.item = Item.objects.create(
            codigo='X', nombre='Producto X', tipo='producto',
            unidad_medida='u', stock_minimo=Decimal('0'),
        )
        self.ub = Ubicacion.objects.create(nombre='B', tipo='bodega')
        self.user = User.objects.create_user(username='u', password='x')

    def test_detecta_y_corrige_drift(self):
        from io import StringIO
        from django.core.management import call_command

        # Stock dice 50 pero no hay movimientos → esperado 0 → drift -50
        Stock.objects.create(item=self.item, ubicacion=self.ub, cantidad_actual=Decimal('50'))

        out = StringIO()
        call_command('auditar_stock_pendientes', stdout=out)
        salida = out.getvalue()
        self.assertIn('Drift de stock', salida)
        self.assertIn('Producto X', salida)

        # Con --fix --confirm corrige a 0
        out2 = StringIO()
        call_command('auditar_stock_pendientes', '--fix', '--confirm', stdout=out2)
        self.assertEqual(
            Stock.objects.get(item=self.item, ubicacion=self.ub).cantidad_actual,
            Decimal('0'),
        )


@override_settings(ALLOWED_HOSTS=['testserver', 'localhost'])
class InventarioConfigModelTests(TestCase):
    def test_singleton_y_permiso_existen(self):
        from apps.core.models import InventarioConfig
        from django.contrib.auth.models import Permission

        config, creado = InventarioConfig.objects.get_or_create(pk=1)
        self.assertTrue(creado)
        self.assertEqual(config.orden_tabs, [])
        self.assertTrue(
            Permission.objects.filter(codename='ordenar_tabs_inventario').exists()
        )


@override_settings(ALLOWED_HOSTS=['testserver', 'localhost'])
class GetOrdenTabsTests(TestCase):
    def test_orden_canonico_sin_config(self):
        from apps.core.views import get_orden_tabs
        claves = [t['clave'] for t in get_orden_tabs()]
        self.assertEqual(
            claves, ['todos', 'producto', 'repuesto', 'consumible', 'bajo_stock']
        )

    def test_reconcilia_guardado_con_canonico(self):
        from apps.core.models import InventarioConfig
        from apps.core.views import get_orden_tabs
        InventarioConfig.objects.create(
            pk=1, orden_tabs=['bajo_stock', 'desconocida', 'producto']
        )
        claves = [t['clave'] for t in get_orden_tabs()]
        self.assertEqual(claves[:2], ['bajo_stock', 'producto'])
        self.assertEqual(len(claves), 5)
        self.assertEqual(
            set(claves), {'todos', 'producto', 'repuesto', 'consumible', 'bajo_stock'}
        )
        # Las tabs ausentes se agregan al final en orden canónico
        self.assertEqual(claves[2:], ['todos', 'repuesto', 'consumible'])

    def test_ignora_duplicados_guardados(self):
        from apps.core.models import InventarioConfig
        from apps.core.views import get_orden_tabs
        InventarioConfig.objects.create(pk=1, orden_tabs=['todos', 'todos', 'producto'])
        claves = [t['clave'] for t in get_orden_tabs()]
        self.assertEqual(len(claves), 5)
        self.assertEqual(claves.count('todos'), 1)


@override_settings(ALLOWED_HOSTS=['testserver', 'localhost'])
class GuardarOrdenTabsTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import Permission
        self.editor = User.objects.create_user('editor', password='x')
        self.editor.user_permissions.add(
            Permission.objects.get(codename='ordenar_tabs_inventario')
        )
        self.viewer = User.objects.create_user('viewer', password='x')

    def _post(self, user, orden):
        import json as _json
        self.client.force_login(user)
        return self.client.post(
            reverse('inventario_tabs_orden'),
            data=_json.dumps({'orden': orden}),
            content_type='application/json',
        )

    def test_guarda_permutacion_valida_con_permiso(self):
        from apps.core.models import InventarioConfig
        orden = ['bajo_stock', 'producto', 'todos', 'consumible', 'repuesto']
        resp = self._post(self.editor, orden)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(InventarioConfig.objects.get(pk=1).orden_tabs, orden)

    def test_sin_permiso_403(self):
        resp = self._post(self.viewer,
                          ['todos', 'producto', 'repuesto', 'consumible', 'bajo_stock'])
        self.assertEqual(resp.status_code, 403)

    def test_permutacion_invalida_400(self):
        resp = self._post(self.editor, ['todos', 'producto', 'repuesto', 'consumible'])
        self.assertEqual(resp.status_code, 400)

    def test_clave_desconocida_400(self):
        resp = self._post(self.editor,
                          ['todos', 'producto', 'repuesto', 'consumible', 'XXX'])
        self.assertEqual(resp.status_code, 400)


@override_settings(ALLOWED_HOSTS=['testserver', 'localhost'])
class InventarioListaOrdenTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user('op2', password='x')
        self.user.user_permissions.add(Permission.objects.get(codename='ver_inventario'))
        self.ub = Ubicacion.objects.create(nombre='Bodega', tipo='bodega')
        for codigo, nombre, tipo in (
            ('A', 'Alfa', 'producto'),
            ('B', 'Beta', 'repuesto'),
            ('C', 'Gamma', 'consumible'),
        ):
            Item.objects.create(codigo=codigo, nombre=nombre, tipo=tipo,
                                unidad_medida='u', stock_minimo=Decimal('0'))

    def test_contexto_incluye_tabs_y_permiso(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('inventario_lista'))
        self.assertEqual(resp.status_code, 200)
        claves = [t['clave'] for t in resp.context['tabs_ordenadas']]
        self.assertEqual(len(claves), 5)
        self.assertFalse(resp.context['puede_ordenar_tabs'])

    def test_orden_por_tipo_desc(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('inventario_lista'),
                               {'orden_col': 'tipo', 'orden_dir': 'desc'})
        tipos = [d['item'].tipo for d in resp.context['items_data']]
        self.assertEqual(tipos, sorted(tipos, reverse=True))

    def test_orden_col_invalida_cae_a_default(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('inventario_lista'),
                               {'orden_col': 'inexistente', 'orden_dir': 'asc'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['orden_col'], '')


@override_settings(ALLOWED_HOSTS=['testserver', 'localhost'])
class InventarioListaRenderTabsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.perm_ver = Permission.objects.get(codename='ver_inventario')
        self.perm_ord = Permission.objects.get(codename='ordenar_tabs_inventario')

    def test_boton_ordenar_oculto_sin_permiso(self):
        u = User.objects.create_user('v1', password='x')
        u.user_permissions.add(self.perm_ver)
        self.client.force_login(u)
        resp = self.client.get(reverse('inventario_lista'))
        self.assertNotContains(resp, 'modalOrdenTabs')

    def test_boton_ordenar_visible_con_permiso(self):
        u = User.objects.create_user('v2', password='x')
        u.user_permissions.add(self.perm_ver, self.perm_ord)
        self.client.force_login(u)
        resp = self.client.get(reverse('inventario_lista'))
        self.assertContains(resp, 'modalOrdenTabs')
        self.assertContains(resp, 'sortable-tabs')

    def test_tabs_se_renderizan_en_orden_guardado(self):
        from apps.core.models import InventarioConfig
        InventarioConfig.objects.create(
            pk=1, orden_tabs=['bajo_stock', 'todos', 'producto', 'repuesto', 'consumible'])
        u = User.objects.create_user('v3', password='x')
        u.user_permissions.add(self.perm_ver)
        self.client.force_login(u)
        resp = self.client.get(reverse('inventario_lista'))
        html = resp.content.decode()
        self.assertLess(html.index('data-tab="bajo_stock"'), html.index('data-tab="producto"'))
        # La PRIMERA tab del orden queda preseleccionada (active + estado JS).
        self.assertIn("let tabActual = 'bajo_stock'", html)
        primer_btn = html.index('data-tab="bajo_stock"')
        self.assertIn('active', html[primer_btn - 80:primer_btn])
