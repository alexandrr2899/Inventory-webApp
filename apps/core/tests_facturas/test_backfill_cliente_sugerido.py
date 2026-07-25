from django.test import TestCase

from apps.core.migrations import _0034_backfill_cliente_sugerido_helpers as _backfill_helpers


class BackfillClienteSugeridoTests(TestCase):
    def test_extrae_el_nombre_de_las_notas(self):
        notas = ('Cliente no encontrado en ingesta automática.\n'
                 'Cliente sugerido por archivo: Comercial Zaga\n'
                 'Archivo original: Fact 9543 Comercial Zaga.pdf')
        self.assertEqual(_backfill_helpers.extraer_sugerido(notas), 'Comercial Zaga')

    def test_devuelve_vacio_si_las_notas_no_tienen_el_patron(self):
        self.assertEqual(_backfill_helpers.extraer_sugerido('Nota escrita a mano'), '')

    def test_devuelve_vacio_si_el_nombre_no_se_detecto(self):
        notas = 'Cliente sugerido por archivo: (sin nombre detectado)\n'
        self.assertEqual(_backfill_helpers.extraer_sugerido(notas), '')
