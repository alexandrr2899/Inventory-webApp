from cryptography.hazmat.primitives import serialization
from django.core.management.base import BaseCommand
from py_vapid import Vapid
from py_vapid.utils import b64urlencode


class Command(BaseCommand):
    help = 'Genera un par VAPID para configurar Web Push (no lo guarda en disco)'

    def handle(self, *args, **options):
        vapid = Vapid()
        vapid.generate_keys()
        private_value = vapid.private_key.private_numbers().private_value
        private_raw = private_value.to_bytes(32, 'big')
        public_raw = vapid.public_key.public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.UncompressedPoint,
        )
        self.stdout.write('Guardá estos valores como secretos; no los regenerés en cada despliegue:')
        self.stdout.write(f'VAPID_PRIVATE_KEY={b64urlencode(private_raw)}')
        self.stdout.write(f'VAPID_PUBLIC_KEY={b64urlencode(public_raw)}')
        self.stdout.write('VAPID_SUBJECT=mailto:admin@tempaques.com')
