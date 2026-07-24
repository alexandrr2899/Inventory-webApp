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


def crear_alias(cliente, texto):
    """Registra `texto` como alias de `cliente`.

    Devuelve `(alias, error)`. `alias` es None cuando no se creó nada; `error` es
    None cuando no hubo problema — incluido el caso redundante, que se ignora a
    propósito en silencio porque no es un error del usuario, solo un no-op.
    """
    texto = (texto or '').strip()
    objetivo = norm(texto)
    if not objetivo:
        return None, None
    if objetivo == norm(cliente.nombre):
        # Redundante: el paso 1 del matcher ya empareja por nombre.
        return None, None

    existente = ClienteAlias.objects.filter(
        alias_norm=objetivo).select_related('cliente').first()
    if existente:
        if existente.cliente_id == cliente.pk:
            return existente, None
        return None, (f'«{texto}» ya está registrado como alias de '
                      f'{existente.cliente.nombre}; no se guardó.')

    # Un alias igual al nombre de otro cliente nunca se alcanzaría (el paso 1 del
    # matcher gana siempre); guardarlo solo generaría confusión.
    choque = next((c for c in Cliente.objects.all() if norm(c.nombre) == objetivo), None)
    if choque:
        return None, (f'«{texto}» es el nombre del cliente {choque.nombre}; '
                      'un alias así nunca se usaría.')

    return ClienteAlias.objects.create(cliente=cliente, alias=texto), None


def sincronizar_aliases(cliente, texto_multilinea):
    """Deja los alias de `cliente` iguales a las líneas de `texto_multilinea`.

    Devuelve la lista de errores (vacía si todo salió bien). Se juntan todos y se
    devuelven de una vez, en lugar de cortar en el primero: quien edita el
    textarea quiere ver de una todo lo que tiene que arreglar.
    """
    lineas, vistos = [], set()
    for linea in (texto_multilinea or '').splitlines():
        linea = linea.strip()
        clave = norm(linea)
        if not clave or clave in vistos:
            continue
        vistos.add(clave)
        lineas.append(linea)

    cliente.aliases.exclude(alias_norm__in=vistos).delete()

    errores = []
    for linea in lineas:
        _alias, error = crear_alias(cliente, linea)
        if error:
            errores.append(error)
    return errores
