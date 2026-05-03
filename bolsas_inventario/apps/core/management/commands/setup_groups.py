from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission


GRUPOS = {
    'Administrador': [
        'ver_inventario', 'crear_item', 'editar_item',
        'registrar_entrada', 'registrar_salida', 'registrar_conteo',
        'aplicar_conciliacion', 'importar_excel', 'ver_reportes',
        'registrar_produccion',
        # Gestión de movimientos (solo admin)
        'editar_movimiento', 'anular_movimiento', 'eliminar_movimiento',
    ],
    'Supervisor': [
        'ver_inventario', 'registrar_entrada', 'registrar_salida',
        'registrar_conteo', 'aplicar_conciliacion', 'ver_reportes',
        'registrar_produccion',
    ],
    'Operador': [
        'ver_inventario', 'registrar_conteo', 'registrar_produccion',
    ],
}


class Command(BaseCommand):
    help = 'Crea/actualiza los grupos de usuario con sus permisos'

    def handle(self, *args, **options):
        self.stdout.write('Configurando grupos...')

        for nombre, codenames in GRUPOS.items():
            grupo, created = Group.objects.get_or_create(name=nombre)
            perms = Permission.objects.filter(
                codename__in=codenames,
                content_type__app_label='core',
            )
            grupo.permissions.set(perms)
            verb = 'Creado' if created else 'Actualizado'
            self.stdout.write(
                self.style.SUCCESS(f'  {verb}: {nombre} ({perms.count()} permisos)')
            )

        self.stdout.write(self.style.SUCCESS('Grupos configurados correctamente.'))
