"""
Tests de las mejoras de confiabilidad y rendimiento:
sonda de salud, degradación ante caché caída, cobertura de pigmentos,
backup programado, batch de conciliación y paginación de facturas.
"""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.models import (
    BackupJob, Categoria, Cliente, Conteo, ConteoDetalle, DetalleMovimiento,
    Item, MovimientoInventario, Stock, Ubicacion, WebPushScheduledEvent,
)
from apps.core.services import notifications
from apps.core.services.pigmentos import calcular_cobertura, payload_cobertura
from apps.core.views.conteos import _stocks_en_momento_batch
from apps.core.views.stock import _stock_en_momento


class HealthzTests(TestCase):
    def test_healthz_responde_ok(self):
        resp = self.client.get('/healthz')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, b'ok')

    def test_healthz_no_requiere_sesion(self):
        """El orquestador consulta la sonda sin credenciales."""
        resp = self.client.get('/healthz')
        self.assertNotIn(resp.status_code, (302, 401, 403))

    def test_healthz_responde_503_si_la_base_falla(self):
        with mock.patch('django.db.connection.cursor', side_effect=Exception('db caída')):
            resp = self.client.get('/healthz')
        self.assertEqual(resp.status_code, 503)


class NotifyStockCacheCaidaTests(TestCase):
    """
    notify_stock corre dentro de transaction.on_commit, o sea DESPUÉS de que el
    movimiento ya se guardó. Si revienta por Redis caído, el usuario ve un 500
    sobre una operación que sí se persistió y la vuelve a capturar.
    """
    def setUp(self):
        cache.clear()
        self.item = Item.objects.create(
            codigo='X1', nombre='Bolsa', tipo='producto',
            unidad_medida='fardos', stock_minimo=Decimal('10'),
        )
        ubicacion = Ubicacion.objects.create(nombre='Bodega', tipo='bodega')
        Stock.objects.create(
            item=self.item, ubicacion=ubicacion, cantidad_actual=Decimal('2'))

    def test_no_propaga_error_si_la_cache_falla(self):
        with mock.patch.object(
            notifications.cache, 'get', side_effect=Exception('redis caído')
        ), mock.patch.object(notifications, 'send_event') as send:
            notifications.notify_stock(self.item, movimiento='salida')
        send.assert_called_once()

    def test_notifica_igual_cuando_no_hay_cache(self):
        """Sin caché preferimos una alerta repetida antes que perderla."""
        with mock.patch.object(
            notifications.cache, 'set', side_effect=Exception('redis caído')
        ), mock.patch.object(notifications, 'send_event') as send:
            notifications.notify_stock(self.item)
            notifications.notify_stock(self.item)
        self.assertEqual(send.call_count, 2)


class CoberturaPigmentosTests(TestCase):
    def setUp(self):
        cache.clear()
        self.categoria = Categoria.objects.create(nombre='Pigmentos')
        self.ubicacion = Ubicacion.objects.create(nombre='Bodega', tipo='bodega')
        self.user = User.objects.create_user(username='op', password='x')

    def _crear_pigmento(self, codigo, stock):
        item = Item.objects.create(
            codigo=codigo, nombre=f'Pigmento {codigo}', tipo='consumible',
            categoria=self.categoria, unidad_medida='kg',
        )
        Stock.objects.create(
            item=item, ubicacion=self.ubicacion, cantidad_actual=Decimal(str(stock)))
        return item

    def _consumir(self, item, cantidad, dias_atras):
        mov = MovimientoInventario.objects.create(
            tipo_movimiento='ajuste', motivo='consumo', usuario=self.user,
            fecha_movimiento=timezone.now() - timedelta(days=dias_atras),
        )
        DetalleMovimiento.objects.create(
            movimiento=mov, item=item, cantidad=Decimal(str(-cantidad)),
            ubicacion_origen=self.ubicacion,
        )

    def test_calcula_dias_de_cobertura(self):
        """10 kg consumidos en 10 días = 1 kg/día; con 5 kg quedan 5 días."""
        item = self._crear_pigmento('AZ', stock=5)
        for dia in range(10):
            self._consumir(item, 1, dias_atras=dia)

        hoy = timezone.localdate()
        resultados, _ = calcular_cobertura(hoy - timedelta(days=9), hoy)

        fila = next(r for r in resultados if r['item'].pk == item.pk)
        self.assertEqual(fila['promedio_diario'], Decimal('1.00'))
        self.assertEqual(fila['dias_cobertura'], 5.0)
        self.assertEqual(fila['estado'], 'bajo')

    def test_estado_critico_bajo_tres_dias(self):
        item = self._crear_pigmento('RJ', stock=2)
        for dia in range(10):
            self._consumir(item, 1, dias_atras=dia)

        hoy = timezone.localdate()
        resultados, totales = calcular_cobertura(hoy - timedelta(days=9), hoy)

        fila = next(r for r in resultados if r['item'].pk == item.pk)
        self.assertEqual(fila['estado'], 'critico')
        self.assertEqual(totales['total_criticos'], 1)

    def test_payload_omite_pigmentos_sin_consumo(self):
        """Sin consumo no hay proyección posible: avisarlo sería ruido diario."""
        self._crear_pigmento('SC', stock=100)
        hoy = timezone.localdate()
        resultados, _ = calcular_cobertura(hoy - timedelta(days=9), hoy)
        payload = payload_cobertura(resultados, hoy - timedelta(days=9), hoy, 14)
        self.assertEqual(payload['pigmentos'], [])

    def test_payload_ordena_por_urgencia(self):
        urgente = self._crear_pigmento('UR', stock=1)
        holgado = self._crear_pigmento('HO', stock=6)
        for dia in range(10):
            self._consumir(urgente, 1, dias_atras=dia)
            self._consumir(holgado, 1, dias_atras=dia)

        hoy = timezone.localdate()
        resultados, _ = calcular_cobertura(hoy - timedelta(days=9), hoy)
        payload = payload_cobertura(resultados, hoy - timedelta(days=9), hoy, 14)

        self.assertEqual(payload['pigmentos'][0]['codigo'], 'UR')
        self.assertEqual(payload['total_criticos'], 1)


class NotifyPigmentCoverageTaskTests(TestCase):
    def setUp(self):
        cache.clear()
        self.categoria = Categoria.objects.create(nombre='Pigmentos')
        self.ubicacion = Ubicacion.objects.create(nombre='Bodega', tipo='bodega')
        self.user = User.objects.create_user(username='op', password='x')

    def _pigmento_en_riesgo(self):
        item = Item.objects.create(
            codigo='AZ', nombre='Pigmento Azul', tipo='consumible',
            categoria=self.categoria, unidad_medida='kg',
        )
        Stock.objects.create(
            item=item, ubicacion=self.ubicacion, cantidad_actual=Decimal('2'))
        for dia in range(10):
            mov = MovimientoInventario.objects.create(
                tipo_movimiento='ajuste', motivo='consumo', usuario=self.user,
                fecha_movimiento=timezone.now() - timedelta(days=dia),
            )
            DetalleMovimiento.objects.create(
                movimiento=mov, item=item, cantidad=Decimal('-1'),
                ubicacion_origen=self.ubicacion,
            )
        return item

    def test_envia_evento_cuando_hay_pigmentos_en_riesgo(self):
        from apps.core.tasks import notify_pigment_coverage
        self._pigmento_en_riesgo()

        with mock.patch(
            'apps.core.services.notifications.send_event'
        ) as send:
            resultado = notify_pigment_coverage()

        self.assertTrue(resultado['enviado'])
        send.assert_called_once()
        self.assertEqual(send.call_args[0][0], 'pigmentos_cobertura')

    def test_no_envia_dos_veces_el_mismo_dia(self):
        from apps.core.tasks import notify_pigment_coverage
        self._pigmento_en_riesgo()

        with mock.patch('apps.core.services.notifications.send_event') as send:
            primero = notify_pigment_coverage()
            segundo = notify_pigment_coverage()

        self.assertTrue(primero['enviado'])
        self.assertFalse(segundo['enviado'])
        self.assertEqual(send.call_count, 1)

    def test_sin_riesgo_no_consume_la_clave_diaria(self):
        """Si el stock cae más tarde ese mismo día, la alerta todavía debe salir."""
        from apps.core.tasks import notify_pigment_coverage

        with mock.patch('apps.core.services.notifications.send_event'):
            resultado = notify_pigment_coverage()

        self.assertFalse(resultado['enviado'])
        self.assertFalse(WebPushScheduledEvent.objects.exists())


class StockEnMomentoBatchTests(TestCase):
    """El batch de conciliación debe dar exactamente lo mismo que el cálculo
    fila por fila que reemplaza."""

    def setUp(self):
        cache.clear()
        self.categoria = Categoria.objects.create(nombre='Camiseta')
        self.ubicacion = Ubicacion.objects.create(nombre='Bodega', tipo='bodega')
        self.otra = Ubicacion.objects.create(nombre='Producción', tipo='produccion')
        self.user = User.objects.create_user(username='op', password='x')
        self.cliente = Cliente.objects.create(nombre='Renato')

        self.items = []
        for i in range(4):
            item = Item.objects.create(
                codigo=f'IT{i}', nombre=f'Item {i}', tipo='producto',
                categoria=self.categoria, unidad_medida='fardos',
            )
            Stock.objects.create(
                item=item, ubicacion=self.ubicacion,
                cantidad_actual=Decimal('50'),
            )
            self.items.append(item)

        self.momento = timezone.now()

        # Movimientos posteriores al conteo (deben revertirse del teórico) y
        # anteriores (no deben tocarlo).
        for item in self.items[:2]:
            posterior = MovimientoInventario.objects.create(
                tipo_movimiento='salida', tipo_salida='producto_terminado',
                motivo='post', usuario=self.user, cliente=self.cliente,
                fecha_movimiento=self.momento + timedelta(hours=2),
            )
            DetalleMovimiento.objects.create(
                movimiento=posterior, item=item, cantidad=Decimal('7'),
                ubicacion_origen=self.ubicacion, cliente=self.cliente,
            )
            anterior = MovimientoInventario.objects.create(
                tipo_movimiento='entrada', motivo='pre', usuario=self.user,
                fecha_movimiento=self.momento - timedelta(hours=2),
            )
            DetalleMovimiento.objects.create(
                movimiento=anterior, item=item, cantidad=Decimal('3'),
                ubicacion_destino=self.ubicacion,
            )

        self.conteo = Conteo.objects.create(
            fecha=self.momento.date(), turno='manana', tipo_conteo='camiseta',
            usuario=self.user, fecha_hora_conteo=self.momento,
        )
        self.detalles = [
            ConteoDetalle.objects.create(
                conteo=self.conteo, item=item, ubicacion=self.ubicacion,
                cantidad_contada=Decimal('50'),
            )
            for item in self.items
        ]

    def test_batch_coincide_con_calculo_individual(self):
        batch = _stocks_en_momento_batch(self.detalles, self.momento)
        for detalle in self.detalles:
            esperado = _stock_en_momento(
                detalle.item, detalle.ubicacion, self.momento)
            self.assertEqual(
                batch[(detalle.item_id, detalle.ubicacion_id)], esperado,
                f'difiere para {detalle.item.codigo}',
            )

    def test_batch_usa_un_numero_fijo_de_consultas(self):
        """2 consultas sin importar cuántos ítems tenga el conteo."""
        with self.assertNumQueries(2):
            _stocks_en_momento_batch(self.detalles, self.momento)

    def test_batch_vacio_no_consulta(self):
        with self.assertNumQueries(0):
            self.assertEqual(_stocks_en_momento_batch([], self.momento), {})


class BackupServiceTests(TestCase):
    def test_backup_fallido_registra_job_sin_levantar_excepcion(self):
        """El backup programado no debe tumbar al worker si el script falla."""
        from apps.core.services import backups

        with mock.patch.object(
            backups.subprocess, 'run', side_effect=OSError('sin permisos')
        ), mock.patch('apps.core.services.notifications.send_event') as send:
            resultado = backups.ejecutar_backup(usuario=None, origen='programado')

        send.assert_called_once()
        self.assertEqual(send.call_args[0][0], 'backup_fallido')

        self.assertFalse(resultado['ok'])
        job = BackupJob.objects.latest('fecha_inicio')
        self.assertEqual(job.estado, 'fallido')
        self.assertIsNotNone(job.fecha_fin)
        self.assertIsNone(job.usuario)

    def test_verificar_integridad_detecta_archivo_corrupto(self):
        import gzip
        import tarfile
        import tempfile
        from pathlib import Path

        from apps.core.services import backups

        with tempfile.TemporaryDirectory() as tmp:
            bueno = Path(tmp) / 'bueno.sql.gz'
            with gzip.open(bueno, 'wb') as fh:
                fh.write(b'CREATE TABLE x();')
            ok, _ = backups.verificar_integridad(bueno)
            self.assertTrue(ok)

            malo = Path(tmp) / 'malo.sql.gz'
            malo.write_bytes(b'esto no es gzip')
            ok, detalle = backups.verificar_integridad(malo)
            self.assertFalse(ok)
            self.assertTrue(detalle)

            sql = Path(tmp) / 'database.sql.gz'
            with gzip.open(sql, 'wb') as fh:
                fh.write(b'CREATE TABLE x();')
            media = Path(tmp) / 'media'
            media.mkdir()
            (media / 'factura.pdf').write_bytes(b'%PDF-1.4')
            completo = Path(tmp) / 'inventario_20260811_1200.tar.gz'
            with tarfile.open(completo, 'w:gz') as tar:
                tar.add(sql, arcname='database.sql.gz')
                tar.add(media, arcname='media')
            ok, detalle = backups.verificar_integridad(completo)
            self.assertTrue(ok, detalle)

            incompleto = Path(tmp) / 'inventario_20260811_1201.tar.gz'
            with tarfile.open(incompleto, 'w:gz') as tar:
                tar.add(media, arcname='media')
            ok, detalle = backups.verificar_integridad(incompleto)
            self.assertFalse(ok)
            self.assertIn('database.sql.gz', detalle)


class FacturasListaPaginacionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_superuser(
            username='admin', password='x', email='a@b.c')
        self.client.force_login(self.user)
        self.cliente = Cliente.objects.create(nombre='Renato')

    def _crear_documentos(self, cantidad, monto='100.00'):
        from apps.core.models import DocumentoFactura
        hoy = timezone.localdate()
        return [
            DocumentoFactura.objects.create(
                cliente=self.cliente, tipo_documento='factura',
                numero_documento=f'F{i:04d}', fecha_documento=hoy,
                fecha_vencimiento=hoy + timedelta(days=30),
                monto_total=Decimal(monto), estado_pago='pendiente',
            )
            for i in range(cantidad)
        ]

    def test_lista_pagina_y_no_trae_todo(self):
        self._crear_documentos(120)
        resp = self.client.get(reverse('facturas_lista'))
        self.assertEqual(resp.status_code, 200)
        page_obj = resp.context['page_obj']
        self.assertEqual(page_obj.paginator.count, 120)
        self.assertEqual(len(page_obj.object_list), 100)
        self.assertTrue(page_obj.has_next())

    def test_resumen_cubre_todos_los_documentos_no_solo_la_pagina(self):
        """El resumen se agrega en la BD: debe reflejar los 120, no los 100."""
        self._crear_documentos(120)
        resp = self.client.get(reverse('facturas_lista'))
        resumen = resp.context['resumen']
        self.assertEqual(resumen['total_documentos'], 120)
        self.assertEqual(resumen['total_facturado'], Decimal('12000.00'))
        self.assertEqual(resumen['total_pendiente'], Decimal('12000.00'))

    def test_resumen_descuenta_pagos_aplicados(self):
        from apps.core.models import AplicacionPago, MetodoPago, Pago

        documentos = self._crear_documentos(3)
        metodo = MetodoPago.objects.create(nombre='Efectivo')
        pago = Pago.objects.create(
            cliente=self.cliente, metodo_pago=metodo,
            monto=Decimal('50.00'), fecha_pago=timezone.localdate(),
        )
        AplicacionPago.objects.create(
            pago=pago, documento=documentos[0], monto=Decimal('50.00'))

        resp = self.client.get(reverse('facturas_lista'))
        resumen = resp.context['resumen']
        self.assertEqual(resumen['total_facturado'], Decimal('300.00'))
        self.assertEqual(resumen['total_cobrado'], Decimal('50.00'))
        self.assertEqual(resumen['total_pendiente'], Decimal('250.00'))

    def test_resumen_no_multiplica_por_pagos_parciales(self):
        """
        Regresión: sumar sobre el queryset anotado con anotar_pagado mete un
        JOIN a aplicaciones y duplicaría monto_total por cada pago aplicado.
        """
        from apps.core.models import AplicacionPago, MetodoPago, Pago

        documentos = self._crear_documentos(1)
        metodo = MetodoPago.objects.create(nombre='Efectivo')
        for _ in range(3):
            pago = Pago.objects.create(
                cliente=self.cliente, metodo_pago=metodo,
                monto=Decimal('10.00'), fecha_pago=timezone.localdate(),
            )
            AplicacionPago.objects.create(
                pago=pago, documento=documentos[0], monto=Decimal('10.00'))

        resp = self.client.get(reverse('facturas_lista'))
        resumen = resp.context['resumen']
        self.assertEqual(resumen['total_facturado'], Decimal('100.00'))
        self.assertEqual(resumen['total_cobrado'], Decimal('30.00'))

    def test_total_vencido_solo_cuenta_lo_atrasado(self):
        from apps.core.models import DocumentoFactura

        hoy = timezone.localdate()
        DocumentoFactura.objects.create(
            cliente=self.cliente, tipo_documento='factura',
            numero_documento='V1', fecha_documento=hoy - timedelta(days=60),
            fecha_vencimiento=hoy - timedelta(days=10),
            monto_total=Decimal('500.00'), estado_pago='pendiente',
        )
        DocumentoFactura.objects.create(
            cliente=self.cliente, tipo_documento='factura',
            numero_documento='V2', fecha_documento=hoy,
            fecha_vencimiento=hoy + timedelta(days=10),
            monto_total=Decimal('300.00'), estado_pago='pendiente',
        )

        resp = self.client.get(reverse('facturas_lista'))
        self.assertEqual(resp.context['resumen']['total_vencido'], Decimal('500.00'))
