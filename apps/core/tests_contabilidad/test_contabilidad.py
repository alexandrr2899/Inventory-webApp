import os
import tempfile
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import Group, Permission, User
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db.models.deletion import ProtectedError
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.core.forms import GastoForm
from apps.core.models import (
    CategoriaGasto, Cliente, DocumentoFactura, Gasto, MetodoPago,
)
from apps.core.services.contabilidad import resumen_financiero
from apps.core.views.reportes import _comparar_periodos


class ContabilidadBase(TestCase):
    def setUp(self):
        self.categoria = CategoriaGasto.objects.create(nombre='Pruebas', orden=1)
        self.metodo = MetodoPago.objects.create(nombre='Transferencia', tipo='transferencia')
        self.usuario = User.objects.create_user('contador', password='x')
        self.usuario.user_permissions.add(*Permission.objects.filter(codename__in=[
            'ver_contabilidad', 'administrar_gastos',
            'administrar_categorias_gasto', 'ver_reportes', 'ver_facturas',
        ]))

    def gasto(self, **kwargs):
        datos = {
            'fecha': date(2026, 9, 10), 'categoria': self.categoria,
            'descripcion': 'Materia prima', 'monto': Decimal('250.00'),
            'metodo_pago': self.metodo, 'registrado_por': self.usuario,
        }
        datos.update(kwargs)
        return Gasto.objects.create(**datos)


class GastoModeloFormularioTests(ContabilidadBase):
    def test_monto_debe_ser_mayor_que_cero(self):
        gasto = Gasto(
            fecha=date(2026, 9, 10), categoria=self.categoria,
            descripcion='Inválido', monto=Decimal('0'), metodo_pago=self.metodo,
        )
        with self.assertRaises(ValidationError):
            gasto.full_clean()

    def test_formulario_acepta_campos_opcionales_vacios(self):
        form = GastoForm({
            'fecha': '2026-09-10', 'categoria': self.categoria.pk,
            'descripcion': 'Energía', 'monto': '100.50',
            'metodo_pago': self.metodo.pk, 'proveedor': '',
            'referencia': '', 'notas': '',
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_formulario_valida_firma_real_del_comprobante(self):
        datos = {
            'fecha': '2026-09-10', 'categoria': self.categoria.pk,
            'descripcion': 'Energía', 'monto': '100.50',
            'metodo_pago': self.metodo.pk,
        }
        valido = GastoForm(datos, {'comprobante': SimpleUploadedFile('recibo.pdf', b'%PDF-1.4')})
        falso = GastoForm(datos, {'comprobante': SimpleUploadedFile('recibo.png', b'no es png')})
        self.assertTrue(valido.is_valid(), valido.errors)
        self.assertFalse(falso.is_valid())

    def test_categoria_usada_esta_protegida(self):
        self.gasto()
        with self.assertRaises(ProtectedError):
            self.categoria.delete()

    def test_usuario_creador_se_preserva_mientras_existe_el_gasto(self):
        self.gasto()
        with self.assertRaises(ProtectedError):
            self.usuario.delete()

    def test_comprobante_rechaza_archivo_mayor_de_10_mb(self):
        archivo = SimpleUploadedFile('recibo.pdf', b'%PDF-1.4')
        archivo.size = 10 * 1024 * 1024 + 1
        form = GastoForm({
            'fecha': '2026-09-10', 'categoria': self.categoria.pk,
            'descripcion': 'Energía', 'monto': '100.50',
            'metodo_pago': self.metodo.pk,
        }, {'comprobante': archivo})
        self.assertFalse(form.is_valid())
        self.assertIn('comprobante', form.errors)


class CalculosFinancierosTests(ContabilidadBase):
    def setUp(self):
        super().setUp()
        cliente = Cliente.objects.create(nombre='Cliente')
        comunes = {'cliente': cliente, 'fecha_documento': date(2026, 9, 10)}
        DocumentoFactura.objects.create(
            **comunes, tipo_documento='factura', monto_total=Decimal('1000.00'),
        )
        DocumentoFactura.objects.create(
            **comunes, tipo_documento='envio', monto_total=Decimal('400.00'),
        )
        DocumentoFactura.objects.create(
            **comunes, tipo_documento='apertura', monto_total=Decimal('9000.00'),
        )
        DocumentoFactura.objects.create(
            **comunes, tipo_documento='factura', monto_total=Decimal('7000.00'),
            estado_pago='anulada',
        )
        DocumentoFactura.objects.create(
            cliente=cliente, fecha_documento=date(2026, 8, 31),
            tipo_documento='factura', monto_total=Decimal('8000.00'),
        )
        self.gasto(monto=Decimal('500.00'))

    def test_excluye_anulados_aperturas_y_fuera_del_periodo(self):
        resumen = resumen_financiero(date(2026, 9, 1), date(2026, 9, 30))
        self.assertEqual(resumen['ingresos_facturas'], Decimal('1000.00'))
        self.assertEqual(resumen['ingresos_envios'], Decimal('400.00'))
        self.assertEqual(resumen['ingreso_total'], Decimal('1400.00'))
        self.assertEqual(resumen['gastos_totales'], Decimal('500.00'))
        self.assertEqual(resumen['utilidad'], Decimal('900.00'))
        self.assertEqual(resumen['margen'], Decimal('64.29'))

    def test_cero_ingresos_y_utilidad_negativa(self):
        self.gasto(fecha=date(2026, 7, 1), monto=Decimal('25.00'))
        resumen = resumen_financiero(date(2026, 7, 1), date(2026, 7, 31))
        self.assertEqual(resumen['ingreso_total'], 0)
        self.assertEqual(resumen['utilidad'], Decimal('-25.00'))
        self.assertEqual(resumen['margen'], 0)

    def test_comparacion_de_utilidad_negativa_tiene_signo_y_tendencia_correctos(self):
        mejora = _comparar_periodos(Decimal('-500'), Decimal('-1000'))
        perdida_nueva = _comparar_periodos(Decimal('-500'), Decimal('0'))
        self.assertEqual(mejora['tendencia'], 'sube')
        self.assertEqual(mejora['variacion'], Decimal('50.0'))
        self.assertEqual(perdida_nueva['tendencia'], 'baja_sin_base')
        self.assertIsNone(perdida_nueva['variacion'])

    def test_comparacion_de_gastos_marca_aumento_como_desfavorable(self):
        aumento = _comparar_periodos(
            Decimal('120'), Decimal('100'), menor_es_mejor=True,
        )
        reduccion = _comparar_periodos(
            Decimal('80'), Decimal('100'), menor_es_mejor=True,
        )
        self.assertEqual(aumento['tendencia'], 'sube_mal')
        self.assertEqual(aumento['variacion'], Decimal('20.0'))
        self.assertEqual(reduccion['tendencia'], 'baja_bien')
        self.assertEqual(reduccion['variacion'], Decimal('-20.0'))

    @override_settings(FACTURAS_MODULE_ENABLED=True)
    def test_rendimiento_usa_las_mismas_cifras(self):
        self.client.force_login(self.usuario)
        respuesta = self.client.get(reverse('reporte_rendimiento_mensual'), {
            'periodo': 'mes', 'mes': '2026-09',
        })
        self.assertEqual(respuesta.status_code, 200)
        esperado = resumen_financiero(
            respuesta.context['inicio_actual'], respuesta.context['fin_actual'],
        )
        self.assertEqual(respuesta.context['finanzas']['ingreso_total']['actual'], esperado['ingreso_total'])
        self.assertEqual(respuesta.context['finanzas']['gastos']['actual'], esperado['gastos_totales'])
        self.assertEqual(respuesta.context['finanzas']['utilidad']['actual'], esperado['utilidad'])


class ContabilidadVistasTests(ContabilidadBase):
    def setUp(self):
        super().setUp()
        self.media = tempfile.TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.media.name)
        self.override.enable()

    def tearDown(self):
        self.override.disable()
        self.media.cleanup()
        super().tearDown()

    def test_sin_permiso_no_accede_a_panel_archivo_ni_exportaciones(self):
        gasto = self.gasto()
        gasto.comprobante.save('recibo.jpg', ContentFile(b'\xff\xd8\xffcontenido'), save=True)
        intruso = User.objects.create_user('intruso', password='x')
        self.client.force_login(intruso)
        urls = [
            reverse('contabilidad_panel'), reverse('gasto_comprobante', args=[gasto.pk]),
            reverse('contabilidad_exportar_csv'), reverse('contabilidad_exportar_pdf'),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_crear_asigna_usuario_y_editar_conserva_opcionales(self):
        self.client.force_login(self.usuario)
        datos = {
            'fecha': '2026-09-11', 'categoria': self.categoria.pk,
            'descripcion': 'Alquiler', 'monto': '300.00',
            'metodo_pago': self.metodo.pk, 'proveedor': '', 'referencia': '', 'notas': '',
        }
        respuesta = self.client.post(reverse('gasto_crear'), datos)
        gasto = Gasto.objects.get(descripcion='Alquiler')
        self.assertRedirects(respuesta, reverse('gasto_detalle', args=[gasto.pk]))
        self.assertEqual(gasto.registrado_por, self.usuario)
        datos['descripcion'] = 'Alquiler editado'
        self.client.post(reverse('gasto_editar', args=[gasto.pk]), datos)
        gasto.refresh_from_db()
        self.assertEqual(gasto.descripcion, 'Alquiler editado')

    def test_comprobante_protegido_y_limpieza_al_reemplazar_y_eliminar(self):
        gasto = self.gasto()
        gasto.comprobante.save('viejo.jpg', ContentFile(b'\xff\xd8\xffviejo'), save=True)
        nombre_viejo = gasto.comprobante.path
        self.client.force_login(self.usuario)
        respuesta = self.client.get(reverse('gasto_comprobante', args=[gasto.pk]))
        self.assertEqual(b''.join(respuesta.streaming_content), b'\xff\xd8\xffviejo')
        datos = {
            'fecha': '2026-09-10', 'categoria': self.categoria.pk,
            'descripcion': gasto.descripcion, 'monto': gasto.monto,
            'metodo_pago': self.metodo.pk,
        }
        datos['comprobante'] = SimpleUploadedFile(
            'nuevo.png', b'\x89PNG\r\n\x1a\ncontenido', content_type='image/png',
        )
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('gasto_editar', args=[gasto.pk]), datos)
        gasto.refresh_from_db()
        self.assertFalse(os.path.exists(nombre_viejo))
        nombre_nuevo = gasto.comprobante.path
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('gasto_eliminar', args=[gasto.pk]))
        self.assertFalse(os.path.exists(nombre_nuevo))

    def test_filtros_csv_paginacion_y_pdf(self):
        for indice in range(26):
            self.gasto(descripcion=f'Compra {indice}', proveedor='Proveedor A')
        self.gasto(fecha=date(2026, 8, 31), descripcion='Fuera')
        self.client.force_login(self.usuario)
        filtros = {'desde': '2026-09-01', 'hasta': '2026-09-30', 'proveedor': 'Proveedor A'}
        panel = self.client.get(reverse('contabilidad_panel'), filtros)
        self.assertEqual(panel.context['page_obj'].paginator.count, 26)
        self.assertTrue(panel.context['page_obj'].has_next())
        csv_response = self.client.get(reverse('contabilidad_exportar_csv'), filtros)
        contenido = csv_response.content.decode('utf-8-sig')
        self.assertEqual(csv_response.status_code, 200)
        self.assertIn('Compra 25', contenido)
        self.assertNotIn('Fuera', contenido)
        pdf = self.client.get(reverse('contabilidad_exportar_pdf'), filtros)
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf['Content-Type'], 'application/pdf')
        self.assertTrue(pdf.content.startswith(b'%PDF'))

    def test_kpis_del_panel_no_se_distorsionan_con_filtros_de_gastos(self):
        self.gasto(monto=Decimal('100.00'), proveedor='Incluido')
        self.gasto(monto=Decimal('300.00'), proveedor='Excluido')
        self.client.force_login(self.usuario)
        respuesta = self.client.get(reverse('contabilidad_panel'), {
            'desde': '2026-09-01', 'hasta': '2026-09-30',
            'proveedor': 'Incluido',
        })
        self.assertEqual(respuesta.context['resumen']['gastos_totales'], Decimal('400.00'))
        self.assertEqual(respuesta.context['gastos_filtrados_total'], Decimal('100.00'))
        self.assertTrue(respuesta.context['hay_filtros_gasto'])

    def test_categoria_lista_usa_conteo_agregado(self):
        self.gasto()
        self.gasto(monto=Decimal('10.00'))
        self.client.force_login(self.usuario)
        respuesta = self.client.get(reverse('categoria_gasto_lista'))
        categoria = next(c for c in respuesta.context['categorias'] if c.pk == self.categoria.pk)
        self.assertEqual(categoria.cantidad_gastos, 2)
        self.assertNotIn('_prefetched_objects_cache', categoria.__dict__)

    def test_paginacion_conserva_filtros_codificados(self):
        for indice in range(26):
            self.gasto(descripcion=f'A&B {indice}')
        self.client.force_login(self.usuario)
        respuesta = self.client.get(reverse('contabilidad_panel'), {
            'desde': '2026-09-01', 'hasta': '2026-09-30', 'q': 'A&B',
        })
        self.assertContains(respuesta, 'q=A%26B&amp;page=2')

    def test_csv_protege_todas_las_columnas_textuales(self):
        categoria = CategoriaGasto.objects.create(nombre='=CATEGORIA')
        metodo = MetodoPago.objects.create(nombre='+METODO')
        self.gasto(categoria=categoria, metodo_pago=metodo)
        self.client.force_login(self.usuario)
        respuesta = self.client.get(reverse('contabilidad_exportar_csv'), {
            'desde': '2026-09-01', 'hasta': '2026-09-30',
        })
        contenido = respuesta.content.decode('utf-8-sig')
        self.assertIn("'=CATEGORIA", contenido)
        self.assertIn("'+METODO", contenido)

    def test_quitar_comprobante_limpia_el_archivo(self):
        gasto = self.gasto()
        gasto.comprobante.save('quitar.jpg', ContentFile(b'\xff\xd8\xffcontenido'), save=True)
        ruta = gasto.comprobante.path
        self.client.force_login(self.usuario)
        datos = {
            'fecha': '2026-09-10', 'categoria': self.categoria.pk,
            'descripcion': gasto.descripcion, 'monto': gasto.monto,
            'metodo_pago': self.metodo.pk, 'comprobante-clear': 'on',
        }
        with self.captureOnCommitCallbacks(execute=True):
            respuesta = self.client.post(reverse('gasto_editar', args=[gasto.pk]), datos)
        self.assertEqual(respuesta.status_code, 302)
        gasto.refresh_from_db()
        self.assertFalse(gasto.comprobante)
        self.assertFalse(os.path.exists(ruta))

    @override_settings(CONTABILIDAD_PDF_MAX_REGISTROS=1)
    def test_pdf_rechaza_volumen_excesivo_sin_truncar(self):
        self.gasto()
        self.gasto(monto=Decimal('10.00'))
        self.client.force_login(self.usuario)
        respuesta = self.client.get(reverse('contabilidad_exportar_pdf'), {
            'desde': '2026-09-01', 'hasta': '2026-09-30',
        })
        self.assertEqual(respuesta.status_code, 400)
        self.assertContains(respuesta, 'no superar 1 registros', status_code=400)


class SetupGroupsContabilidadTests(TestCase):
    def test_permisos_contables_solo_se_asignan_al_administrador(self):
        call_command('setup_groups', verbosity=0)
        codenames = {
            'ver_contabilidad', 'administrar_gastos',
            'administrar_categorias_gasto', 'gestionar_metodos_pago',
        }
        admin = Group.objects.get(name='Administrador')
        self.assertTrue(codenames.issubset(
            set(admin.permissions.values_list('codename', flat=True))
        ))
        for nombre in ('Supervisor', 'Operador'):
            permisos = set(
                Group.objects.get(name=nombre).permissions.values_list('codename', flat=True)
            )
            self.assertTrue(codenames.isdisjoint(permisos))
