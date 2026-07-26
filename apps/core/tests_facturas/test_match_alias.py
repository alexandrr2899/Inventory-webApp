from django.test import TestCase

from apps.core.models import Cliente, ClienteAlias
from apps.core.services.facturas import bulk_service


class MatchClienteAliasTests(TestCase):
    def setUp(self):
        self.acme = Cliente.objects.create(nombre='Acme Honduras')

    def test_el_alias_empareja(self):
        ClienteAlias.objects.create(cliente=self.acme, alias='ACME S DE RL')
        self.assertEqual(bulk_service.match_cliente('acme s de rl'), self.acme)

    def test_el_alias_empareja_tambien_con_solo_exacto(self):
        # Es el caso que importa: la ingesta automática usa solo_exacto=True.
        ClienteAlias.objects.create(cliente=self.acme, alias='ACME S DE RL')
        self.assertEqual(
            bulk_service.match_cliente('ACME S DE RL', solo_exacto=True), self.acme)

    def test_el_nombre_real_le_gana_al_alias(self):
        # Se crea el alias directo (crear_alias lo rechazaría) para probar la
        # precedencia: un alias nunca puede tapar a un cliente existente.
        otro = Cliente.objects.create(nombre='Distribuidora Sur')
        ClienteAlias.objects.create(cliente=self.acme, alias='Distribuidora Sur')
        self.assertEqual(bulk_service.match_cliente('Distribuidora Sur'), otro)

    def test_el_alias_le_gana_al_contiene(self):
        # Sin el alias, el paso 'contiene' elegiría a "Acme".
        Cliente.objects.create(nombre='Acme')
        ClienteAlias.objects.create(cliente=self.acme, alias='ACME SRL')
        self.assertEqual(bulk_service.match_cliente('ACME SRL'), self.acme)

    def test_sin_alias_ni_nombre_devuelve_none_con_solo_exacto(self):
        self.assertIsNone(bulk_service.match_cliente('Nadie', solo_exacto=True))
