"""clientes.py — El cliente "Sin identificar" y los alias de cliente.

Centraliza dos cosas que estaban dispersas: el helper del cliente ficticio (vivía
dentro de una vista de la API, y ahora lo necesitan tres lugares) y el alta de
alias, que tiene reglas propias y no debe replicarse en cada llamador.
"""
from apps.core.models import Cliente, ClienteAlias
from apps.core.textnorm import norm  # noqa: F401  (reexportado para los llamadores)

NOMBRE_SIN_IDENTIFICAR = 'Sin identificar'


def cliente_sin_identificar():
    """El cliente ficticio al que van los documentos que la ingesta no pudo emparejar.

    Se reactiva si alguien lo desactivó: sin él, la ingesta automática no tendría
    dónde dejar los documentos y fallaría en vez de encolarlos para revisión.
    """
    cliente, _creado = Cliente.objects.get_or_create(
        nombre=NOMBRE_SIN_IDENTIFICAR, defaults={'activo': True})
    if not cliente.activo:
        cliente.activo = True
        cliente.save(update_fields=['activo'])
    return cliente
