from django.test import TestCase

from apps.core.forms import ClienteForm
from apps.core.models import Cliente, ClienteAlias


class ClienteFormAliasesTests(TestCase):
    def _datos(self, **extra):
        datos = {'nombre': 'Acme Honduras', 'telefono': '', 'rtn': '',
                 'direccion': '', 'dias_credito': 0, 'activo': True}
        datos.update(extra)
        return datos

    def test_crea_los_alias_al_guardar(self):
        form = ClienteForm(self._datos(aliases='ACME SRL\nAcme HN'))
        self.assertTrue(form.is_valid(), form.errors)
        cliente = form.save()

        self.assertEqual(
            sorted(cliente.aliases.values_list('alias', flat=True)), ['ACME SRL', 'Acme HN'])

    def test_precarga_los_alias_existentes(self):
        cliente = Cliente.objects.create(nombre='Acme Honduras')
        ClienteAlias.objects.create(cliente=cliente, alias='ACME SRL')
        ClienteAlias.objects.create(cliente=cliente, alias='Acme HN')

        form = ClienteForm(instance=cliente)
        self.assertEqual(form.initial['aliases'], 'ACME SRL\nAcme HN')

    def test_quitar_una_linea_borra_ese_alias(self):
        cliente = Cliente.objects.create(nombre='Acme Honduras')
        ClienteAlias.objects.create(cliente=cliente, alias='ACME SRL')
        ClienteAlias.objects.create(cliente=cliente, alias='Acme HN')

        form = ClienteForm(self._datos(aliases='ACME SRL'), instance=cliente)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()

        self.assertEqual(list(cliente.aliases.values_list('alias', flat=True)), ['ACME SRL'])

    def test_alias_de_otro_cliente_invalida_el_formulario(self):
        otro = Cliente.objects.create(nombre='Acme Sur')
        ClienteAlias.objects.create(cliente=otro, alias='ACME SRL')

        form = ClienteForm(self._datos(aliases='ACME SRL'))
        self.assertFalse(form.is_valid())
        self.assertIn('Acme Sur', str(form.errors['aliases']))
        self.assertEqual(Cliente.objects.filter(nombre='Acme Honduras').count(), 0)

    def test_sin_alias_es_valido(self):
        form = ClienteForm(self._datos())
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().aliases.count(), 0)
