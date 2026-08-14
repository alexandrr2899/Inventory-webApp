from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.models import (
    AplicacionPago,
    Categoria,
    Cliente,
    ClienteAlias,
    DocumentoFactura,
    Item,
    MetodoPago,
    Pago,
    Stock,
    Ubicacion,
)


@override_settings(JAIME_API_TOKEN='token-seguro-de-prueba')
class JaimeApiTests(TestCase):
    token = 'token-seguro-de-prueba'

    @classmethod
    def setUpTestData(cls):
        cls.hoy = timezone.localdate()
        cls.cliente = Cliente.objects.create(
            nombre='Cliente Textiles ABC',
            telefono='9999-0000',
            rtn='08011999123456',
        )
        ClienteAlias.objects.create(cliente=cls.cliente, alias='Comercial ABC')
        cls.otro_cliente = Cliente.objects.create(nombre='Otro cliente')

        cls.vencida = DocumentoFactura.objects.create(
            cliente=cls.cliente,
            tipo_documento='factura',
            numero_documento='FAC-001',
            fecha_documento=cls.hoy - timedelta(days=40),
            fecha_vencimiento=cls.hoy - timedelta(days=10),
            monto_total=Decimal('1000.00'),
            estado_pago='pendiente',
        )
        cls.pendiente = DocumentoFactura.objects.create(
            cliente=cls.cliente,
            tipo_documento='envio',
            numero_documento='ENV-002',
            fecha_documento=cls.hoy,
            fecha_vencimiento=cls.hoy + timedelta(days=15),
            monto_total=Decimal('500.00'),
            estado_pago='pendiente',
        )
        cls.pagada = DocumentoFactura.objects.create(
            cliente=cls.cliente,
            tipo_documento='factura',
            numero_documento='FAC-003',
            fecha_documento=cls.hoy - timedelta(days=5),
            fecha_vencimiento=cls.hoy + timedelta(days=5),
            monto_total=Decimal('200.00'),
            estado_pago='pagada',
        )
        DocumentoFactura.objects.create(
            cliente=cls.cliente,
            tipo_documento='factura',
            numero_documento='FAC-ANULADA',
            fecha_documento=cls.hoy,
            fecha_vencimiento=cls.hoy - timedelta(days=1),
            monto_total=Decimal('300.00'),
            estado_pago='anulada',
        )

        metodo = MetodoPago.objects.create(nombre='Transferencia', tipo='transferencia')
        pago_parcial = Pago.objects.create(
            cliente=cls.cliente,
            fecha_pago=cls.hoy,
            metodo_pago=metodo,
            monto=Decimal('400.00'),
        )
        AplicacionPago.objects.create(
            pago=pago_parcial,
            documento=cls.vencida,
            monto=Decimal('400.00'),
        )
        pago_completo = Pago.objects.create(
            cliente=cls.cliente,
            fecha_pago=cls.hoy,
            metodo_pago=metodo,
            monto=Decimal('200.00'),
        )
        AplicacionPago.objects.create(
            pago=pago_completo,
            documento=cls.pagada,
            monto=Decimal('200.00'),
        )

        categoria = Categoria.objects.create(nombre='Camisetas')
        cls.item = Item.objects.create(
            codigo='CAM-NEGRA',
            nombre='Camiseta negra',
            descripcion='Camiseta de algodón color negro',
            tipo='producto',
            categoria=categoria,
            unidad_medida='unidades',
        )
        bodega = Ubicacion.objects.create(nombre='Bodega', tipo='bodega')
        oficina = Ubicacion.objects.create(nombre='Oficina', tipo='oficina')
        Stock.objects.create(item=cls.item, ubicacion=bodega, cantidad_actual=Decimal('12'))
        Stock.objects.create(item=cls.item, ubicacion=oficina, cantidad_actual=Decimal('8'))

    def _get(self, url, params=None, token=None):
        token = self.token if token is None else token
        return self.client.get(
            url,
            params or {},
            HTTP_AUTHORIZATION=f'Bearer {token}',
        )

    def _crear_35_facturas(self):
        cliente = Cliente.objects.create(nombre='Cliente con 35 facturas')
        documentos = [
            DocumentoFactura(
                cliente=cliente,
                tipo_documento='factura',
                numero_documento=f'LOTE-{numero:02d}',
                fecha_documento=self.hoy - timedelta(days=60 - numero),
                fecha_vencimiento=self.hoy - timedelta(days=36 - numero),
                monto_total=Decimal(numero),
                estado_pago='pendiente',
            )
            for numero in range(1, 36)
        ]
        DocumentoFactura.objects.bulk_create(documentos)
        return cliente, 630.0

    def test_peticion_sin_token_retorna_401(self):
        response = self.client.get(reverse('jaime_api:buscar_clientes'), {'q': 'ABC'})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {'ok': False, 'error': 'unauthorized'})

    def test_token_incorrecto_retorna_401(self):
        response = self._get(reverse('jaime_api:buscar_clientes'), {'q': 'ABC'}, 'incorrecto')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['error'], 'unauthorized')

    @override_settings(JAIME_API_TOKEN='')
    def test_token_no_configurado_deshabilita_api(self):
        response = self.client.get(
            reverse('jaime_api:buscar_clientes'),
            {'q': 'ABC'},
            HTTP_AUTHORIZATION='Bearer cualquier-token',
        )
        self.assertEqual(response.status_code, 401)

    def test_token_correcto_da_acceso(self):
        response = self._get(reverse('jaime_api:buscar_clientes'), {'q': 'ABC'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])

    def test_post_retorna_405(self):
        response = self.client.post(
            reverse('jaime_api:buscar_clientes'),
            {'q': 'ABC'},
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response['Allow'], 'GET')
        self.assertEqual(response.json()['error'], 'method_not_allowed')

    def test_busqueda_cliente_por_nombre_y_alias(self):
        for query in ('Textiles', 'Comercial ABC'):
            with self.subTest(query=query):
                response = self._get(
                    reverse('jaime_api:buscar_clientes'), {'q': query}
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['data'][0]['id'], self.cliente.pk)
                self.assertNotIn('direccion', response.json()['data'][0])

    def test_cliente_inexistente_retorna_404(self):
        response = self._get(reverse('jaime_api:saldo_cliente', args=[999999]))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()['error'], 'cliente_no_encontrado')

    def test_calculo_saldo_reutiliza_aplicaciones(self):
        response = self._get(reverse('jaime_api:saldo_cliente', args=[self.cliente.pk]))
        self.assertEqual(response.status_code, 200)
        data = response.json()['data']
        self.assertEqual(data['saldo_pendiente'], 1100.0)
        self.assertEqual(data['cantidad_facturas_pendientes'], 2)
        self.assertEqual(data['cantidad_facturas_vencidas'], 1)
        self.assertEqual(data['saldo_vencido'], 600.0)
        self.assertIsInstance(data['saldo_pendiente'], (int, float))

    def test_facturas_pendientes(self):
        response = self._get(
            reverse('jaime_api:facturas_pendientes'),
            {'cliente_id': self.cliente.pk},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()['data']
        self.assertEqual(data['resumen'], {
            'cantidad': 2,
            'registros_devuelto': 2,
            'total_pendiente': 1100.0,
        })
        self.assertEqual(
            {factura['numero'] for factura in data['facturas']},
            {'FAC-001', 'ENV-002'},
        )
        vencida = next(f for f in data['facturas'] if f['numero'] == 'FAC-001')
        self.assertEqual(vencida['pagado'], 400.0)
        self.assertEqual(vencida['saldo'], 600.0)
        self.assertTrue(vencida['vencida'])

    def test_facturas_vencidas_usan_fecha_local_y_saldo(self):
        response = self._get(reverse('jaime_api:facturas_vencidas'))
        self.assertEqual(response.status_code, 200)
        data = response.json()['data']
        self.assertEqual(data['resumen'], {
            'cantidad': 1,
            'registros_devuelto': 1,
            'total_vencido': 600.0,
        })
        self.assertEqual(data['facturas'][0]['numero'], 'FAC-001')
        self.assertEqual(data['facturas'][0]['dias_vencida'], 10)

    def test_35_vencidas_sin_limite_resume_todas_y_devuelve_20(self):
        cliente, total = self._crear_35_facturas()
        response = self._get(
            reverse('jaime_api:facturas_vencidas'), {'cliente_id': cliente.pk}
        )
        data = response.json()['data']
        self.assertEqual(len(data['facturas']), 20)
        self.assertEqual(data['resumen'], {
            'cantidad': 35,
            'registros_devuelto': 20,
            'total_vencido': total,
        })

    def test_35_vencidas_limite_1_mantiene_resumen_total(self):
        cliente, total = self._crear_35_facturas()
        response = self._get(reverse('jaime_api:facturas_vencidas'), {
            'cliente_id': cliente.pk, 'limite': 1,
        })
        data = response.json()['data']
        self.assertEqual(len(data['facturas']), 1)
        self.assertEqual(data['resumen'], {
            'cantidad': 35,
            'registros_devuelto': 1,
            'total_vencido': total,
        })

    def test_35_vencidas_limite_100_devuelve_todas(self):
        cliente, total = self._crear_35_facturas()
        response = self._get(reverse('jaime_api:facturas_vencidas'), {
            'cliente_id': cliente.pk, 'limite': 100,
        })
        data = response.json()['data']
        self.assertEqual(len(data['facturas']), 35)
        self.assertEqual(data['resumen'], {
            'cantidad': 35,
            'registros_devuelto': 35,
            'total_vencido': total,
        })

    def test_35_pendientes_sin_limite_resume_todas_y_devuelve_20(self):
        cliente, total = self._crear_35_facturas()
        response = self._get(
            reverse('jaime_api:facturas_pendientes'), {'cliente_id': cliente.pk}
        )
        data = response.json()['data']
        self.assertEqual(len(data['facturas']), 20)
        self.assertEqual(data['resumen'], {
            'cantidad': 35,
            'registros_devuelto': 20,
            'total_pendiente': total,
        })

    def test_35_pendientes_limite_1_mantiene_resumen_total(self):
        cliente, total = self._crear_35_facturas()
        response = self._get(reverse('jaime_api:facturas_pendientes'), {
            'cliente_id': cliente.pk, 'limite': 1,
        })
        data = response.json()['data']
        self.assertEqual(len(data['facturas']), 1)
        self.assertEqual(data['resumen'], {
            'cantidad': 35,
            'registros_devuelto': 1,
            'total_pendiente': total,
        })

    def test_35_pendientes_limite_100_devuelve_todas(self):
        cliente, total = self._crear_35_facturas()
        response = self._get(reverse('jaime_api:facturas_pendientes'), {
            'cliente_id': cliente.pk, 'limite': 100,
        })
        data = response.json()['data']
        self.assertEqual(len(data['facturas']), 35)
        self.assertEqual(data['resumen'], {
            'cantidad': 35,
            'registros_devuelto': 35,
            'total_pendiente': total,
        })

    def test_consulta_inventario_suma_stock_por_ubicacion(self):
        response = self._get(
            reverse('jaime_api:consultar_inventario'), {'q': 'camiseta negra'}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()['data']
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['codigo'], 'CAM-NEGRA')
        self.assertEqual(data[0]['existencia'], 20.0)
        self.assertEqual(data[0]['unidad'], 'unidades')
        self.assertEqual(data[0]['categoria'], 'Camisetas')
