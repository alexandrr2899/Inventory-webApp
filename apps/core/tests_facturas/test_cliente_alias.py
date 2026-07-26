from django.db.utils import IntegrityError
from django.test import TestCase

from apps.core.models import Cliente, ClienteAlias
from apps.core.services.facturas import clientes


class ClienteAliasModelTests(TestCase):
    def setUp(self):
        self.cliente = Cliente.objects.create(nombre='Acme Honduras')

    def test_alias_norm_se_calcula_al_guardar(self):
        alias = ClienteAlias.objects.create(cliente=self.cliente, alias='  ACME  S de RL  ')
        self.assertEqual(alias.alias_norm, 'acme s de rl')

    def test_alias_norm_ignora_acentos(self):
        alias = ClienteAlias.objects.create(cliente=self.cliente, alias='Almacén Céntrico')
        self.assertEqual(alias.alias_norm, 'almacen centrico')

    def test_alias_norm_es_unico_en_toda_la_tabla(self):
        # Un mismo alias no puede apuntar a dos clientes: el emparejado dejaría
        # de ser determinista.
        otro = Cliente.objects.create(nombre='Acme Sur')
        ClienteAlias.objects.create(cliente=self.cliente, alias='ACME SRL')
        with self.assertRaises(IntegrityError):
            ClienteAlias.objects.create(cliente=otro, alias='acme  srl')

    def test_borrar_cliente_borra_sus_alias(self):
        ClienteAlias.objects.create(cliente=self.cliente, alias='ACME SRL')
        self.cliente.delete()
        self.assertEqual(ClienteAlias.objects.count(), 0)


class ClienteSinIdentificarTests(TestCase):
    def test_devuelve_siempre_el_mismo_y_no_duplica(self):
        primero = clientes.cliente_sin_identificar()
        segundo = clientes.cliente_sin_identificar()
        self.assertEqual(primero.pk, segundo.pk)
        self.assertEqual(
            Cliente.objects.filter(nombre=clientes.NOMBRE_SIN_IDENTIFICAR).count(), 1)

    def test_reactiva_el_cliente_si_estaba_inactivo(self):
        Cliente.objects.create(nombre=clientes.NOMBRE_SIN_IDENTIFICAR, activo=False)
        self.assertTrue(clientes.cliente_sin_identificar().activo)


class CrearAliasTests(TestCase):
    def setUp(self):
        self.acme = Cliente.objects.create(nombre='Acme Honduras')

    def test_crea_el_alias_y_no_devuelve_error(self):
        alias, error = clientes.crear_alias(self.acme, '  ACME S DE RL  ')
        self.assertIsNone(error)
        self.assertEqual(alias.alias, 'ACME S DE RL')
        self.assertEqual(alias.cliente, self.acme)

    def test_texto_vacio_no_hace_nada(self):
        alias, error = clientes.crear_alias(self.acme, '   ')
        self.assertIsNone(alias)
        self.assertIsNone(error)
        self.assertEqual(ClienteAlias.objects.count(), 0)

    def test_alias_igual_al_nombre_del_propio_cliente_se_ignora_en_silencio(self):
        # Sería redundante: el paso 1 del matcher ya lo empareja por nombre.
        alias, error = clientes.crear_alias(self.acme, 'acme honduras')
        self.assertIsNone(alias)
        self.assertIsNone(error)
        self.assertEqual(ClienteAlias.objects.count(), 0)

    def test_alias_repetido_del_mismo_cliente_es_idempotente(self):
        primero, _ = clientes.crear_alias(self.acme, 'ACME SRL')
        segundo, error = clientes.crear_alias(self.acme, 'acme srl')
        self.assertIsNone(error)
        self.assertEqual(primero.pk, segundo.pk)
        self.assertEqual(ClienteAlias.objects.count(), 1)

    def test_alias_de_otro_cliente_devuelve_error_y_no_crea(self):
        otro = Cliente.objects.create(nombre='Acme Sur')
        clientes.crear_alias(otro, 'ACME SRL')
        alias, error = clientes.crear_alias(self.acme, 'ACME SRL')
        self.assertIsNone(alias)
        self.assertIn('Acme Sur', error)
        self.assertEqual(ClienteAlias.objects.count(), 1)

    def test_alias_que_choca_con_el_nombre_de_otro_cliente_devuelve_error(self):
        Cliente.objects.create(nombre='Distribuidora Sur')
        alias, error = clientes.crear_alias(self.acme, 'distribuidora sur')
        self.assertIsNone(alias)
        self.assertIn('Distribuidora Sur', error)
        self.assertEqual(ClienteAlias.objects.count(), 0)


class SincronizarAliasesTests(TestCase):
    def setUp(self):
        self.acme = Cliente.objects.create(nombre='Acme Honduras')

    def test_crea_los_alias_de_las_lineas(self):
        errores = clientes.sincronizar_aliases(self.acme, 'ACME SRL\nAcme HN')
        self.assertEqual(errores, [])
        self.assertEqual(
            sorted(self.acme.aliases.values_list('alias', flat=True)), ['ACME SRL', 'Acme HN'])

    def test_borra_los_que_se_quitaron_y_conserva_los_que_no_cambiaron(self):
        clientes.sincronizar_aliases(self.acme, 'ACME SRL\nAcme HN')
        conservado = self.acme.aliases.get(alias='ACME SRL')
        clientes.sincronizar_aliases(self.acme, 'ACME SRL')
        self.assertEqual(list(self.acme.aliases.values_list('alias', flat=True)), ['ACME SRL'])
        # El que no cambió no se borra y se vuelve a crear: conserva su pk.
        self.assertEqual(self.acme.aliases.get().pk, conservado.pk)

    def test_descarta_lineas_vacias_y_repetidas(self):
        errores = clientes.sincronizar_aliases(self.acme, 'ACME SRL\n\n  \nacme  srl\n')
        self.assertEqual(errores, [])
        self.assertEqual(self.acme.aliases.count(), 1)

    def test_junta_todos_los_errores_de_una_vez(self):
        otro = Cliente.objects.create(nombre='Acme Sur')
        clientes.crear_alias(otro, 'ACME SRL')
        Cliente.objects.create(nombre='Distribuidora Sur')
        errores = clientes.sincronizar_aliases(self.acme, 'ACME SRL\nDistribuidora Sur\nAcme HN')
        self.assertEqual(len(errores), 2)
        self.assertEqual(list(self.acme.aliases.values_list('alias', flat=True)), ['Acme HN'])

    def test_texto_vacio_borra_todos_los_alias(self):
        clientes.sincronizar_aliases(self.acme, 'ACME SRL')
        clientes.sincronizar_aliases(self.acme, '')
        self.assertEqual(self.acme.aliases.count(), 0)

    def test_linea_igual_al_propio_nombre_se_ignora_junto_a_una_valida(self):
        # El caso (c) de crear_alias (redundante con el propio nombre) también
        # tiene que comportarse bien mezclado dentro de una sincronización, no
        # solo llamado directo.
        errores = clientes.sincronizar_aliases(self.acme, 'Acme Honduras\nACME SRL')
        self.assertEqual(errores, [])
        self.assertEqual(list(self.acme.aliases.values_list('alias', flat=True)), ['ACME SRL'])

    def test_atomic_no_borra_alias_validos_preexistentes_si_hay_errores_parciales(self):
        # Mismo escenario que test_junta_todos_los_errores_de_una_vez, pero acá
        # verificamos el otro lado: el atomic no debe hacer que un error de
        # línea (que no lanza excepción) revierta lo que sí se sincronizó bien.
        clientes.sincronizar_aliases(self.acme, 'Acme HN')
        preexistente = self.acme.aliases.get(alias='Acme HN')

        otro = Cliente.objects.create(nombre='Acme Sur')
        clientes.crear_alias(otro, 'ACME SRL')
        Cliente.objects.create(nombre='Distribuidora Sur')

        errores = clientes.sincronizar_aliases(
            self.acme, 'Acme HN\nACME SRL\nDistribuidora Sur')
        self.assertEqual(len(errores), 2)
        self.assertEqual(list(self.acme.aliases.values_list('alias', flat=True)), ['Acme HN'])
        # El alias válido preexistente sobrevivió intacto (misma pk).
        self.assertEqual(self.acme.aliases.get().pk, preexistente.pk)
