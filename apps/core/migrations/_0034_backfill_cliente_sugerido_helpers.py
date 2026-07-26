"""Helper del backfill 0034, en su propio módulo para poder testearlo."""
import re

_PATRON = re.compile(r'^Cliente sugerido por archivo:\s*(.+)$', re.MULTILINE)

# Lo que escribía la ingesta cuando el nombre del archivo no dejaba deducir nada.
_SIN_NOMBRE = '(sin nombre detectado)'


def extraer_sugerido(notas):
    """Saca el nombre sugerido de las `notas` que escribía la ingesta. '' si no hay."""
    match = _PATRON.search(notas or '')
    if not match:
        return ''
    nombre = match.group(1).strip()
    return '' if nombre == _SIN_NOMBRE else nombre
