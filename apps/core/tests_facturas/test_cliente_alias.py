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
