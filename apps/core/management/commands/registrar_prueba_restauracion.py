from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.core.models import SystemHeartbeat


class Command(BaseCommand):
    help = 'Registra que una restauración fue probada y validada por el operador'

    def add_arguments(self, parser):
        parser.add_argument(
            '--notas', default='',
            help='Entorno, archivo restaurado o resultado de la prueba.',
        )

    def handle(self, *args, **options):
        SystemHeartbeat.objects.update_or_create(
            name='restore_test',
            defaults={
                'last_seen_at': timezone.now(),
                'details': {'notes': options['notas'][:500]},
            },
        )
        self.stdout.write(self.style.SUCCESS(
            'Prueba de restauración registrada para el panel de salud.'))
