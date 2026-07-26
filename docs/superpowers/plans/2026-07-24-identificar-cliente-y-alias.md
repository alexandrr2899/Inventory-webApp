# Identificar cliente sin salir de la lista + alias de cliente — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolver desde la pestaña "Por revisar" los documentos que la ingesta automática dejó en "Sin identificar", creando el cliente si hace falta sin cambiar de página, y enseñarle al emparejado alias por cliente para que ese nombre no vuelva a preguntarse.

**Architecture:** Un modelo `ClienteAlias` con `alias_norm` único global alimenta un paso intermedio en `match_cliente()` (nombre exacto → alias exacto → "contiene"). Como el paso de alias es igualdad exacta, la ingesta automática lo usa y deja de mandar documentos a "Sin identificar". En la UI, un modal AJAX por fila reutiliza el modal de cliente inline que ya existe.

**Tech Stack:** Django 4.x, SQLite/Postgres vía Docker, Bootstrap 5, JS vanilla (sin build step), `unittest` de Django.

**Spec:** [`docs/superpowers/specs/2026-07-24-identificar-cliente-y-alias-design.md`](../specs/2026-07-24-identificar-cliente-y-alias-design.md)

## Global Constraints

- **Todo corre en Docker.** No hay `python` local y `entrypoint.sh` ignora sus argumentos. El comando de tests/manage.py es siempre:
  `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py <cmd>`
- **Los tests llevan `--noinput`**, si no fallan con `EOFError` cuando quedó una BD de test previa.
- **`django-axes` rompe el login por formulario en tests** → usar `self.client.force_login(user)`, nunca `self.client.login(...)`.
- **Los tests del módulo facturas necesitan** `@override_settings(FACTURAS_MODULE_ENABLED=True, ALLOWED_HOSTS=['testserver', 'localhost'])`.
- **Idioma:** todo el código, comentarios, docstrings, mensajes de UI y nombres de test van en español, como el resto del repo.
- **Comentarios:** el repo comenta el *porqué* de las decisiones no obvias, no el *qué*. Mantener esa densidad.
- **Vistas:** los módulos de `apps/core/views/` empiezan con `from .common import *` y toman de ahí Django, modelos y helpers.
- **Migraciones:** la última es `0031_pago_pago_monto_positivo`. Las nuevas se generan con `makemigrations core`, nunca a mano.

## Desvíos respecto del spec

Dos ajustes técnicos que aparecieron al bajar el diseño a código:

1. **`norm()` va en `apps/core/textnorm.py`, no en `services/facturas/clientes.py`.** El spec la ponía en el módulo de servicios, pero `ClienteAlias.save()` la necesita y `models.py` no puede importar de `services/` (que importa `models`) sin un ciclo. Un módulo hoja sin dependencias de Django lo resuelve, siguiendo el precedente de `apps/core/net.py`. `clientes.py` y `bulk_service.py` la importan de ahí.
2. **Al identificar se recalcula `fecha_vencimiento` si está vacía** (Task 5). El spec no lo contemplaba: `invoice_service.crear_documento` calcula el vencimiento con `cliente.dias_credito` (`invoice_service.py:104`), y "Sin identificar" tiene 0 días, así que los documentos de la ingesta llegan sin vencimiento. Al asignar el cliente real hay que calcularlo, con el mismo guardia que usa `invoice_service`: **solo si está vacío**, para no pisar nunca una fecha que trajo el PDF o puso una persona.

## Estructura de archivos

**Archivos nuevos**

| Archivo | Responsabilidad |
|---|---|
| `apps/core/textnorm.py` | `norm()`. Módulo hoja, sin imports de Django, para que lo puedan usar modelos y servicios. |
| `apps/core/services/facturas/clientes.py` | El cliente "Sin identificar" y el alta/sincronización de alias. Toda la lógica de alias vive acá; las vistas y forms solo la llaman. |
| `templates/facturas/_modal_identificar.html` | El modal + su JS, autocontenido, incluido desde `lista.html`. |
| `apps/core/migrations/_0034_backfill_cliente_sugerido_helpers.py` | El parseo de `notas` del backfill, en su propio módulo para poder testearlo. |
| `apps/core/tests_facturas/test_cliente_alias.py` | Modelo `ClienteAlias` y los servicios de alias. |
| `apps/core/tests_facturas/test_match_alias.py` | Precedencia del emparejado. |
| `apps/core/tests_facturas/test_backfill_cliente_sugerido.py` | El parseo del backfill. |
| `apps/core/tests_facturas/test_identificar_view.py` | El endpoint. |
| `apps/core/tests_facturas/test_identificar_render.py` | Badge, botón y modal en la lista. |
| `apps/core/tests_facturas/test_cliente_form_aliases.py` | El textarea del formulario de cliente. |

**Archivos modificados**

| Archivo | Cambio |
|---|---|
| `apps/core/models.py` | Modelo `ClienteAlias`; campo `DocumentoFactura.cliente_sugerido`. |
| `apps/core/services/facturas/bulk_service.py` | `_norm` delega en `textnorm.norm`; `match_cliente` gana el paso de alias. |
| `apps/core/views/facturas_api.py` | Usa `clientes.cliente_sin_identificar()`; llena `cliente_sugerido`. |
| `apps/core/views/facturas.py` | `facturas_lista` pasa `sin_identificar_id` al contexto. |
| `apps/core/views/facturas_cliente.py` | Vista `factura_identificar`. |
| `apps/core/views/__init__.py` | Exporta `factura_identificar`. |
| `apps/core/urls.py` | Ruta `factura_identificar`. |
| `apps/core/forms.py` | `ClienteForm` gana el campo `aliases`. |
| `templates/facturas/lista.html` | Badge + botón + include del modal. |
| `templates/clientes/form.html` | El textarea. |
| `apps/core/tests_facturas/test_api_ingest.py` | Alias empareja en la ingesta; `cliente_sugerido` se llena. |
| `apps/core/tests_facturas/test_perf_queries.py` | La lista no suma consultas por fila sin identificar. |

---

### Task 1: Modelo `ClienteAlias` y módulo de clientes

**Files:**
- Create: `apps/core/textnorm.py`
- Create: `apps/core/services/facturas/clientes.py`
- Create: `apps/core/tests_facturas/test_cliente_alias.py`
- Modify: `apps/core/models.py` (después de la clase `Cliente`, que termina en la línea ~200)
- Modify: `apps/core/services/facturas/bulk_service.py:52-57`
- Modify: `apps/core/views/facturas_api.py:44-52` y `:93`

**Interfaces:**
- Produces:
  - `apps.core.textnorm.norm(s: str) -> str`
  - `apps.core.models.ClienteAlias` con campos `cliente`, `alias`, `alias_norm`, `created_at` y `related_name='aliases'`
  - `apps.core.services.facturas.clientes.NOMBRE_SIN_IDENTIFICAR: str`
  - `apps.core.services.facturas.clientes.cliente_sin_identificar() -> Cliente`

- [ ] **Step 1: Escribir los tests que fallan**

Crear `apps/core/tests_facturas/test_cliente_alias.py`:

```python
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
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

```bash
docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_facturas.test_cliente_alias --noinput -v 2
```

Esperado: FAIL con `ImportError: cannot import name 'ClienteAlias'`.

- [ ] **Step 3: Crear `apps/core/textnorm.py`**

```python
"""textnorm — Normalización de texto para comparar nombres.

Módulo hoja a propósito: no importa nada de Django ni del proyecto, así lo pueden
usar tanto `models.py` como los servicios sin ciclos de importación.
"""
import unicodedata


def norm(s):
    """Normaliza para comparar: minúsculas, sin acentos, espacios colapsados."""
    s = unicodedata.normalize('NFKD', s or '')
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return ' '.join(s.lower().split())
```

- [ ] **Step 4: Agregar `ClienteAlias` a `apps/core/models.py`**

Al inicio del archivo, junto a los otros imports del proyecto:

```python
from .textnorm import norm
```

Justo después de la clase `Cliente` (antes de la siguiente clase del archivo):

```python
class ClienteAlias(models.Model):
    """Otro nombre con el que un cliente aparece en los PDFs.

    `alias_norm` es único en TODA la tabla, no por cliente: un alias no puede
    apuntar a dos clientes, porque entonces el emparejado del nombre del archivo
    dejaría de ser determinista.
    """
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name='aliases')
    alias = models.CharField(max_length=200)
    alias_norm = models.CharField(max_length=200, db_index=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Alias de cliente'
        verbose_name_plural = 'Alias de cliente'
        ordering = ['alias']
        constraints = [
            models.UniqueConstraint(fields=['alias_norm'], name='cliente_alias_norm_unico'),
        ]

    def __str__(self):
        return f'{self.alias} → {self.cliente.nombre}'

    def save(self, *args, **kwargs):
        self.alias = (self.alias or '').strip()
        self.alias_norm = norm(self.alias)
        super().save(*args, **kwargs)
```

- [ ] **Step 5: Crear `apps/core/services/facturas/clientes.py`**

```python
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
```

- [ ] **Step 6: Hacer que `bulk_service` use `textnorm`**

En `apps/core/services/facturas/bulk_service.py`, reemplazar la definición de `_norm` (líneas 52-57) por el import. Quitar también `import unicodedata` de la cabecera si ya no se usa en el archivo.

```python
from apps.core.textnorm import norm as _norm
```

- [ ] **Step 7: Hacer que la ingesta use el helper compartido**

En `apps/core/views/facturas_api.py`: borrar la función `_cliente_sin_identificar()` (líneas 44-52), agregar `clientes` al import de servicios y usarla en la línea 93.

```python
from ..services.facturas import bulk_service, clientes, invoice_service
```

```python
    if requiere_revision:
        cliente = clientes.cliente_sin_identificar()
```

- [ ] **Step 8: Generar la migración**

```bash
docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py makemigrations core
```

Esperado: `0032_clientealias.py` con `CreateModel` y la `UniqueConstraint`.

- [ ] **Step 9: Correr los tests y verificar que pasan**

```bash
docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_facturas --noinput -v 2
```

Esperado: PASS, incluidos los tests de `test_api_ingest.py` que ya existían (la ingesta no cambió de comportamiento, solo de dónde saca el helper).

- [ ] **Step 10: Commit**

```bash
git add apps/core/textnorm.py apps/core/services/facturas/clientes.py apps/core/models.py apps/core/migrations/0032_clientealias.py apps/core/services/facturas/bulk_service.py apps/core/views/facturas_api.py apps/core/tests_facturas/test_cliente_alias.py
git commit -m "feat(clientes): modelo ClienteAlias y servicio de clientes"
```

---

### Task 2: Alta y sincronización de alias

**Files:**
- Modify: `apps/core/services/facturas/clientes.py`
- Modify: `apps/core/tests_facturas/test_cliente_alias.py`

**Interfaces:**
- Consumes: `ClienteAlias`, `norm()`, `NOMBRE_SIN_IDENTIFICAR` (Task 1)
- Produces:
  - `crear_alias(cliente: Cliente, texto: str) -> tuple[ClienteAlias | None, str | None]` — `(alias, error)`. `alias` es `None` cuando no se creó nada; `error` es `None` cuando no hubo problema, **incluido el caso redundante**, que se ignora en silencio.
  - `sincronizar_aliases(cliente: Cliente, texto_multilinea: str) -> list[str]` — lista de mensajes de error, vacía si todo bien.

- [ ] **Step 1: Escribir los tests que fallan**

Agregar al final de `apps/core/tests_facturas/test_cliente_alias.py`:

```python
class CrearAliasTests(TestCase):
    def setUp(self):
        self.acme = Cliente.objects.create(nombre='Acme Honduras')

    def test_crea_el_alias_y_no_devuelve_error(self):
        alias, error = clientes.crear_alias(self.acme, '  ACME S DE RL  ')
        self.assertIsNone(error)
        self.assertEqual(alias.alias, 'ACME S DE RL')
        self.assertEqual(alias.cliente, self.acme)

    def test_texto_vacio_no_hace_nada(self):
        alias, error = clientes.crear_alias(self.acme, '   ')
        self.assertIsNone(alias)
        self.assertIsNone(error)
        self.assertEqual(ClienteAlias.objects.count(), 0)

    def test_alias_igual_al_nombre_del_propio_cliente_se_ignora_en_silencio(self):
        # Sería redundante: el paso 1 del matcher ya lo empareja por nombre.
        alias, error = clientes.crear_alias(self.acme, 'acme honduras')
        self.assertIsNone(alias)
        self.assertIsNone(error)
        self.assertEqual(ClienteAlias.objects.count(), 0)

    def test_alias_repetido_del_mismo_cliente_es_idempotente(self):
        primero, _ = clientes.crear_alias(self.acme, 'ACME SRL')
        segundo, error = clientes.crear_alias(self.acme, 'acme srl')
        self.assertIsNone(error)
        self.assertEqual(primero.pk, segundo.pk)
        self.assertEqual(ClienteAlias.objects.count(), 1)

    def test_alias_de_otro_cliente_devuelve_error_y_no_crea(self):
        otro = Cliente.objects.create(nombre='Acme Sur')
        clientes.crear_alias(otro, 'ACME SRL')
        alias, error = clientes.crear_alias(self.acme, 'ACME SRL')
        self.assertIsNone(alias)
        self.assertIn('Acme Sur', error)
        self.assertEqual(ClienteAlias.objects.count(), 1)

    def test_alias_que_choca_con_el_nombre_de_otro_cliente_devuelve_error(self):
        Cliente.objects.create(nombre='Distribuidora Sur')
        alias, error = clientes.crear_alias(self.acme, 'distribuidora sur')
        self.assertIsNone(alias)
        self.assertIn('Distribuidora Sur', error)
        self.assertEqual(ClienteAlias.objects.count(), 0)


class SincronizarAliasesTests(TestCase):
    def setUp(self):
        self.acme = Cliente.objects.create(nombre='Acme Honduras')

    def test_crea_los_alias_de_las_lineas(self):
        errores = clientes.sincronizar_aliases(self.acme, 'ACME SRL\nAcme HN')
        self.assertEqual(errores, [])
        self.assertEqual(
            sorted(self.acme.aliases.values_list('alias', flat=True)), ['ACME SRL', 'Acme HN'])

    def test_borra_los_que_se_quitaron_y_conserva_los_que_no_cambiaron(self):
        clientes.sincronizar_aliases(self.acme, 'ACME SRL\nAcme HN')
        conservado = self.acme.aliases.get(alias='ACME SRL')
        clientes.sincronizar_aliases(self.acme, 'ACME SRL')
        self.assertEqual(list(self.acme.aliases.values_list('alias', flat=True)), ['ACME SRL'])
        # El que no cambió no se borra y se vuelve a crear: conserva su pk.
        self.assertEqual(self.acme.aliases.get().pk, conservado.pk)

    def test_descarta_lineas_vacias_y_repetidas(self):
        errores = clientes.sincronizar_aliases(self.acme, 'ACME SRL\n\n  \nacme  srl\n')
        self.assertEqual(errores, [])
        self.assertEqual(self.acme.aliases.count(), 1)

    def test_junta_todos_los_errores_de_una_vez(self):
        otro = Cliente.objects.create(nombre='Acme Sur')
        clientes.crear_alias(otro, 'ACME SRL')
        Cliente.objects.create(nombre='Distribuidora Sur')
        errores = clientes.sincronizar_aliases(self.acme, 'ACME SRL\nDistribuidora Sur\nAcme HN')
        self.assertEqual(len(errores), 2)
        self.assertEqual(list(self.acme.aliases.values_list('alias', flat=True)), ['Acme HN'])

    def test_texto_vacio_borra_todos_los_alias(self):
        clientes.sincronizar_aliases(self.acme, 'ACME SRL')
        clientes.sincronizar_aliases(self.acme, '')
        self.assertEqual(self.acme.aliases.count(), 0)
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

```bash
docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_facturas.test_cliente_alias --noinput -v 2
```

Esperado: FAIL con `AttributeError: module ... has no attribute 'crear_alias'`.

- [ ] **Step 3: Implementar las dos funciones**

Agregar al final de `apps/core/services/facturas/clientes.py`:

```python
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
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

```bash
docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_facturas.test_cliente_alias --noinput -v 2
```

Esperado: PASS (16 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/core/services/facturas/clientes.py apps/core/tests_facturas/test_cliente_alias.py
git commit -m "feat(clientes): alta y sincronización de alias con validaciones"
```

---

### Task 3: El emparejado usa los alias

**Files:**
- Modify: `apps/core/services/facturas/bulk_service.py:60-82`
- Create: `apps/core/tests_facturas/test_match_alias.py`
- Modify: `apps/core/tests_facturas/test_api_ingest.py`

**Interfaces:**
- Consumes: `ClienteAlias` (Task 1)
- Produces: `match_cliente(nombre, solo_exacto=False)` con el paso de alias intercalado. Sin cambios de firma.

- [ ] **Step 1: Escribir los tests que fallan**

Crear `apps/core/tests_facturas/test_match_alias.py`:

```python
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
```

Agregar a `apps/core/tests_facturas/test_api_ingest.py`, dentro de la clase `IngestTokenTests` (que ya crea `Cliente.objects.create(nombre='Inversiones Zaga')` en `setUp`):

```python
    def test_alias_empareja_en_la_ingesta_sin_pasar_por_sin_identificar(self):
        if not os.path.exists(_FACTURA):
            self.skipTest('PDF de muestra ausente')
        zaga = Cliente.objects.get(nombre='Inversiones Zaga')
        ClienteAlias.objects.create(cliente=zaga, alias='Comercial Zaga')

        archivo = _factura_upload('Fact 9543 Comercial Zaga.pdf')
        resp = self.client.post(self.url, {'archivo': archivo}, HTTP_X_API_KEY=TOKEN)

        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertFalse(data['requiere_revision'])
        self.assertEqual(data['cliente'], 'Inversiones Zaga')
        self.assertEqual(DocumentoFactura.objects.get().cliente, zaga)
        self.assertFalse(
            Cliente.objects.filter(nombre='Sin identificar').exists())
```

Actualizar el import del archivo:

```python
from apps.core.models import Cliente, ClienteAlias, DocumentoFactura, TarifaCliente
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

```bash
docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_facturas.test_match_alias apps.core.tests_facturas.test_api_ingest --noinput -v 2
```

Esperado: FAIL en `test_el_alias_empareja` (devuelve `None`) y en el test de ingesta (`requiere_revision` es `True`).

- [ ] **Step 3: Intercalar el paso de alias en `match_cliente`**

Reemplazar `match_cliente` en `apps/core/services/facturas/bulk_service.py` por:

```python
def match_cliente(nombre, solo_exacto=False):
    """Empareja un nombre (del archivo) a un Cliente existente; None si no hay match.

    Orden: 1) nombre exacto normalizado, 2) alias exacto normalizado,
    3) 'contiene' en cualquier dirección (solo si no `solo_exacto`).

    El alias va después del nombre real para que nunca pueda tapar a un cliente
    existente, y antes del 'contiene' porque un alias es una afirmación explícita
    del usuario mientras que el 'contiene' es una corazonada. Como el paso 2 es
    igualdad exacta, es tan confiable como el 1: por eso la ingesta automática
    (`solo_exacto=True`, sin revisión humana que corrija un mal match) también
    empareja por alias.
    """
    objetivo = _norm(nombre)
    if not objetivo:
        return None
    clientes_todos = list(Cliente.objects.all())
    # 1) Igualdad exacta normalizada del nombre.
    for c in clientes_todos:
        if _norm(c.nombre) == objetivo:
            return c
    # 2) Alias exacto. Una consulta indexada, no todos los alias en memoria.
    alias = ClienteAlias.objects.filter(
        alias_norm=objetivo).select_related('cliente').first()
    if alias:
        return alias.cliente
    if solo_exacto:
        return None
    # 3) 'Contiene' en cualquier dirección; preferir el nombre de cliente más largo.
    matches = [c for c in clientes_todos
               if _norm(c.nombre) and (_norm(c.nombre) in objetivo or objetivo in _norm(c.nombre))]
    if matches:
        return max(matches, key=lambda c: len(c.nombre))
    return None
```

Actualizar el import de modelos en la cabecera del archivo:

```python
from apps.core.models import Cliente, CategoriaProducto, ClienteAlias
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

```bash
docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_facturas --noinput -v 2
```

Esperado: PASS, incluidos los tests de lote que ya usaban `match_cliente`.

- [ ] **Step 5: Commit**

```bash
git add apps/core/services/facturas/bulk_service.py apps/core/tests_facturas/test_match_alias.py apps/core/tests_facturas/test_api_ingest.py
git commit -m "feat(facturas): match_cliente empareja por alias"
```

---

### Task 4: Campo `cliente_sugerido` con backfill

**Files:**
- Modify: `apps/core/models.py` (clase `DocumentoFactura`, junto a `notas` y `subcliente`, línea ~628)
- Modify: `apps/core/views/facturas_api.py:118-124`
- Create: `apps/core/migrations/0033_documentofactura_cliente_sugerido.py` (generada)
- Create: `apps/core/migrations/0034_backfill_cliente_sugerido.py` (a mano, de datos)
- Create: `apps/core/migrations/_0034_backfill_cliente_sugerido_helpers.py`
- Create: `apps/core/tests_facturas/test_backfill_cliente_sugerido.py`
- Modify: `apps/core/tests_facturas/test_api_ingest.py`

**Interfaces:**
- Produces: `DocumentoFactura.cliente_sugerido: str` — el nombre que venía en el archivo cuando la ingesta no pudo emparejar; `''` en los demás casos.

- [ ] **Step 1: Escribir los tests que fallan**

Agregar a `IngestTokenTests` en `apps/core/tests_facturas/test_api_ingest.py`:

```python
    def test_guarda_el_nombre_sugerido_en_su_propio_campo(self):
        if not os.path.exists(_FACTURA):
            self.skipTest('PDF de muestra ausente')
        archivo = _factura_upload('Fact 9543 Cliente Inexistente.pdf')
        resp = self.client.post(self.url, {'archivo': archivo}, HTTP_X_API_KEY=TOKEN)

        self.assertEqual(resp.status_code, 201)
        doc = DocumentoFactura.objects.get()
        self.assertEqual(doc.cliente_sugerido, 'Cliente Inexistente')
        # `notas` sigue existiendo tal cual, para humanos.
        self.assertIn('Cliente Inexistente', doc.notas)

    def test_documento_emparejado_no_lleva_cliente_sugerido(self):
        if not os.path.exists(_FACTURA):
            self.skipTest('PDF de muestra ausente')
        resp = self.client.post(self.url, {'archivo': _factura_upload()},
                                HTTP_X_API_KEY=TOKEN)

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(DocumentoFactura.objects.get().cliente_sugerido, '')
```

Crear `apps/core/tests_facturas/test_backfill_cliente_sugerido.py`:

```python
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
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

```bash
docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_facturas.test_api_ingest apps.core.tests_facturas.test_backfill_cliente_sugerido --noinput -v 2
```

Esperado: FAIL con `AttributeError: 'DocumentoFactura' object has no attribute 'cliente_sugerido'` y `ImportError` del helper del backfill.

- [ ] **Step 3: Agregar el campo al modelo**

En `apps/core/models.py`, clase `DocumentoFactura`, justo después de `subcliente`:

```python
    cliente_sugerido = models.CharField(
        max_length=200, blank=True,
        help_text='Nombre del cliente que venía en el archivo cuando la ingesta '
                  'automática no pudo emparejarlo.')
```

- [ ] **Step 4: Generar la migración de esquema**

```bash
docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py makemigrations core
```

Esperado: `0033_documentofactura_cliente_sugerido.py`.

- [ ] **Step 5: Escribir el helper y la migración de datos**

Crear `apps/core/migrations/_0034_backfill_cliente_sugerido_helpers.py` (el guion bajo lo mantiene fuera del autodescubrimiento de migraciones, y así el parseo se puede testear sin correr la migración):

```python
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
```

Crear `apps/core/migrations/0034_backfill_cliente_sugerido.py`:

```python
"""Llena `cliente_sugerido` de los documentos que la ingesta dejó sin identificar.

El nombre estaba enterrado como prosa dentro de `notas`. Se copia al campo nuevo y
`notas` se deja intacta: sigue siendo la nota para humanos.
"""
from django.db import migrations

from ._0034_backfill_cliente_sugerido_helpers import extraer_sugerido


def backfill(apps, schema_editor):
    DocumentoFactura = apps.get_model('core', 'DocumentoFactura')
    pendientes = []
    for doc in DocumentoFactura.objects.exclude(notas='').only('id', 'notas'):
        sugerido = extraer_sugerido(doc.notas)
        if sugerido:
            doc.cliente_sugerido = sugerido[:200]
            pendientes.append(doc)
    DocumentoFactura.objects.bulk_update(pendientes, ['cliente_sugerido'], batch_size=200)


def revertir(apps, schema_editor):
    DocumentoFactura = apps.get_model('core', 'DocumentoFactura')
    DocumentoFactura.objects.update(cliente_sugerido='')


class Migration(migrations.Migration):
    dependencies = [('core', '0033_documentofactura_cliente_sugerido')]
    operations = [migrations.RunPython(backfill, revertir)]
```

- [ ] **Step 6: Hacer que la ingesta llene el campo**

En `apps/core/views/facturas_api.py`, reemplazar el bloque `if requiere_revision:` posterior a `crear_documento` (líneas 118-124):

```python
    if requiere_revision:
        doc.cliente_sugerido = (nombre_cli or '')[:200]
        doc.notas = (
            'Cliente no encontrado en ingesta automática.\n'
            f'Cliente sugerido por archivo: {nombre_cli or "(sin nombre detectado)"}\n'
            f'Archivo original: {archivo.name}'
        )
        doc.save(update_fields=['cliente_sugerido', 'notas'])
```

- [ ] **Step 7: Correr los tests y verificar que pasan**

```bash
docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_facturas --noinput -v 2
```

Esperado: PASS.

- [ ] **Step 8: Verificar que no quedan migraciones sin generar**

```bash
docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py makemigrations --check --dry-run
```

Esperado: `No changes detected`.

- [ ] **Step 9: Commit**

```bash
git add apps/core/models.py apps/core/migrations/0033_documentofactura_cliente_sugerido.py apps/core/migrations/0034_backfill_cliente_sugerido.py apps/core/migrations/_0034_backfill_cliente_sugerido_helpers.py apps/core/views/facturas_api.py apps/core/tests_facturas/test_api_ingest.py apps/core/tests_facturas/test_backfill_cliente_sugerido.py
git commit -m "feat(facturas): campo cliente_sugerido con backfill desde notas"
```

---

### Task 5: Endpoint `factura_identificar`

**Files:**
- Modify: `apps/core/views/facturas_cliente.py` (al final)
- Modify: `apps/core/views/__init__.py`
- Modify: `apps/core/urls.py:99` (junto a las otras rutas de facturas)
- Create: `apps/core/tests_facturas/test_identificar_view.py`

**Interfaces:**
- Consumes: `clientes.cliente_sin_identificar()`, `clientes.crear_alias()` (Tasks 1-2); `DocumentoFactura.cliente_sugerido` (Task 4)
- Produces: URL name `factura_identificar` en `facturas/documentos/<int:pk>/identificar/`. POST con `cliente` (id), `guardar_alias` (`'1'` o ausente), `marcar_revisado` (`'1'` o ausente). Responde `{ok, cliente_nombre, revisada, aviso}` o `{ok: false, errors}`.

- [ ] **Step 1: Escribir los tests que fallan**

Crear `apps/core/tests_facturas/test_identificar_view.py`:

```python
from datetime import date

from django.contrib.auth.models import Permission, User
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.core.models import Cliente, ClienteAlias, DocumentoFactura
from apps.core.services.facturas import clientes


@override_settings(FACTURAS_MODULE_ENABLED=True, ALLOWED_HOSTS=['testserver', 'localhost'])
class FacturaIdentificarTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='admin_ident', password='pass12345')
        self.admin.user_permissions.add(
            Permission.objects.get(codename='gestionar_facturas'))
        self.operador = User.objects.create_user(username='oper_ident', password='pass12345')

        self.sin_id = clientes.cliente_sin_identificar()
        self.acme = Cliente.objects.create(nombre='Acme Honduras', dias_credito=30)
        self.doc = DocumentoFactura.objects.create(
            cliente=self.sin_id, tipo_documento='factura', numero_documento='F-0142',
            fecha_documento=date(2026, 7, 3), monto_total=1000,
            cliente_sugerido='ACME S DE RL',
        )
        self.url = reverse('factura_identificar', args=[self.doc.pk])

    def _post(self, **extra):
        datos = {'cliente': self.acme.pk}
        datos.update(extra)
        return self.client.post(self.url, datos)

    def test_asigna_el_cliente(self):
        self.client.force_login(self.admin)
        resp = self._post()

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['ok'])
        self.assertEqual(resp.json()['cliente_nombre'], 'Acme Honduras')
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.cliente, self.acme)

    def test_guarda_el_alias_cuando_se_pide(self):
        self.client.force_login(self.admin)
        self._post(guardar_alias='1')

        alias = ClienteAlias.objects.get()
        self.assertEqual(alias.alias, 'ACME S DE RL')
        self.assertEqual(alias.cliente, self.acme)

    def test_no_guarda_el_alias_si_el_checkbox_viene_desmarcado(self):
        self.client.force_login(self.admin)
        self._post()
        self.assertEqual(ClienteAlias.objects.count(), 0)

    def test_no_marca_revisado_por_defecto(self):
        self.client.force_login(self.admin)
        resp = self._post()

        self.assertFalse(resp.json()['revisada'])
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.estado_revision, 'pendiente')

    def test_marca_revisado_cuando_se_pide(self):
        self.client.force_login(self.admin)
        resp = self._post(marcar_revisado='1')

        self.assertTrue(resp.json()['revisada'])
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.estado_revision, 'revisada')

    def test_calcula_el_vencimiento_con_los_dias_de_credito_del_cliente_real(self):
        # El documento llegó bajo "Sin identificar" (0 días), así que no tenía
        # vencimiento; al asignar el cliente real hay que calcularlo.
        self.client.force_login(self.admin)
        self._post()

        self.doc.refresh_from_db()
        self.assertEqual(self.doc.fecha_vencimiento, date(2026, 8, 2))

    def test_no_pisa_un_vencimiento_que_ya_existia(self):
        self.doc.fecha_vencimiento = date(2026, 7, 10)
        self.doc.save(update_fields=['fecha_vencimiento'])
        self.client.force_login(self.admin)
        self._post()

        self.doc.refresh_from_db()
        self.assertEqual(self.doc.fecha_vencimiento, date(2026, 7, 10))

    def test_alias_de_otro_cliente_avisa_pero_identifica_igual(self):
        otro = Cliente.objects.create(nombre='Acme Sur')
        ClienteAlias.objects.create(cliente=otro, alias='ACME S DE RL')
        self.client.force_login(self.admin)
        resp = self._post(guardar_alias='1')

        self.assertTrue(resp.json()['ok'])
        self.assertIn('Acme Sur', resp.json()['aviso'])
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.cliente, self.acme)
        self.assertEqual(ClienteAlias.objects.count(), 1)

    def test_documento_ya_identificado_devuelve_409(self):
        self.doc.cliente = self.acme
        self.doc.save(update_fields=['cliente'])
        self.client.force_login(self.admin)
        resp = self._post()

        self.assertEqual(resp.status_code, 409)
        self.assertFalse(resp.json()['ok'])
        self.assertIn('Acme Honduras', resp.json()['errors']['__all__'][0])

    def test_rechaza_asignar_el_cliente_sin_identificar(self):
        self.client.force_login(self.admin)
        resp = self.client.post(self.url, {'cliente': self.sin_id.pk})

        self.assertEqual(resp.status_code, 400)
        self.assertIn('cliente', resp.json()['errors'])

    def test_rechaza_cliente_vacio(self):
        self.client.force_login(self.admin)
        resp = self.client.post(self.url, {})

        self.assertEqual(resp.status_code, 400)
        self.assertIn('cliente', resp.json()['errors'])

    def test_requiere_permiso_gestionar_facturas(self):
        self.client.force_login(self.operador)
        resp = self._post()

        self.assertEqual(resp.status_code, 403)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.cliente, self.sin_id)

    def test_rechaza_get(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.url).status_code, 405)
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

```bash
docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_facturas.test_identificar_view --noinput -v 2
```

Esperado: FAIL con `NoReverseMatch: Reverse for 'factura_identificar' not found`.

- [ ] **Step 3: Escribir la vista**

Agregar al final de `apps/core/views/facturas_cliente.py`:

```python
@login_required
@permission_required(_perm('gestionar_facturas'), raise_exception=True)
@facturas_enabled
@require_POST
def factura_identificar(request, pk):
    """Asigna el cliente real a un documento que la ingesta dejó sin identificar.

    Identificar el documento es la acción principal; guardar el alias es un efecto
    secundario. Si el alias falla, el documento se identifica igual y el aviso
    viaja en la respuesta: nunca se pierde la acción que importaba por culpa de la
    que no.
    """
    doc = get_object_or_404(DocumentoFactura.objects.select_related('cliente'), pk=pk)
    sin_identificar = clientes.cliente_sin_identificar()
    if doc.cliente_id != sin_identificar.pk:
        return JsonResponse({
            'ok': False,
            'errors': {'__all__': [f'Ya fue identificado como {doc.cliente.nombre}.']},
        }, status=409)

    cliente = Cliente.objects.filter(pk=request.POST.get('cliente') or 0).first()
    if cliente is None:
        return JsonResponse(
            {'ok': False, 'errors': {'cliente': ['Elegí un cliente.']}}, status=400)
    if cliente.pk == sin_identificar.pk:
        return JsonResponse({
            'ok': False,
            'errors': {'cliente': ['Elegí un cliente real, no «Sin identificar».']},
        }, status=400)

    aviso = ''
    if request.POST.get('guardar_alias') == '1' and doc.cliente_sugerido:
        _alias, error = clientes.crear_alias(cliente, doc.cliente_sugerido)
        aviso = error or ''

    doc.cliente = cliente
    campos = ['cliente', 'updated_at']
    # El documento entró bajo "Sin identificar" (0 días de crédito), así que suele
    # llegar sin vencimiento. Se calcula con el mismo guardia que usa
    # invoice_service: solo si está vacío, para no pisar una fecha del PDF ni una
    # que puso una persona.
    if not doc.fecha_vencimiento and doc.fecha_documento and cliente.dias_credito:
        doc.fecha_vencimiento = doc.fecha_documento + timedelta(days=cliente.dias_credito)
        campos.append('fecha_vencimiento')

    revisada = request.POST.get('marcar_revisado') == '1'
    if revisada:
        doc.estado_revision = 'revisada'
        campos.append('estado_revision')
    doc.save(update_fields=campos)

    # El documento cambió de cliente: puede corresponderle saldo a favor del real,
    # y su estado de pago depende del vencimiento que acabamos de calcular.
    payment_service.aplicar_saldo_a_favor(doc)
    status_service.actualizar_estado_pago(doc)

    return JsonResponse({
        'ok': True,
        'cliente_nombre': cliente.nombre,
        'revisada': revisada,
        'aviso': aviso,
    })
```

Actualizar los imports de la cabecera del archivo:

```python
from ..services.facturas import clientes, payment_service, status_service
```

`timedelta` y `Cliente` ya llegan por `from .common import *`.

- [ ] **Step 4: Exportar la vista y registrar la ruta**

En `apps/core/views/__init__.py`, agregar `factura_identificar` a la línea que importa de `facturas_cliente`.

En `apps/core/urls.py`, después de la línea 96 (`factura_anular`):

```python
    path('facturas/documentos/<int:pk>/identificar/', views.factura_identificar, name='factura_identificar'),
```

- [ ] **Step 5: Correr los tests y verificar que pasan**

```bash
docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_facturas.test_identificar_view --noinput -v 2
```

Esperado: PASS (14 tests).

- [ ] **Step 6: Commit**

```bash
git add apps/core/views/facturas_cliente.py apps/core/views/__init__.py apps/core/urls.py apps/core/tests_facturas/test_identificar_view.py
git commit -m "feat(facturas): endpoint para identificar el cliente de un documento"
```

---

### Task 6: Badge en la lista y modal de identificación

**Files:**
- Modify: `apps/core/views/facturas.py:88-108` (contexto de `facturas_lista`)
- Modify: `templates/facturas/lista.html` (celda de cliente, celda de acciones, `extra_js`)
- Create: `templates/facturas/_modal_identificar.html`
- Create: `apps/core/tests_facturas/test_identificar_render.py`
- Modify: `apps/core/tests_facturas/test_perf_queries.py`

**Interfaces:**
- Consumes: URL `factura_identificar` (Task 5); `DocumentoFactura.cliente_sugerido` (Task 4); `clientes.cliente_sin_identificar()` (Task 1); el modal inline existente vía `data-cliente-inline data-target="identificar-cliente"`
- Produces: contexto `sin_identificar_id` en `facturas_lista`

- [ ] **Step 1: Escribir los tests que fallan**

Crear `apps/core/tests_facturas/test_identificar_render.py`:

```python
from datetime import date

from django.contrib.auth.models import Permission, User
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.core.models import Cliente, DocumentoFactura
from apps.core.services.facturas import clientes


@override_settings(FACTURAS_MODULE_ENABLED=True, ALLOWED_HOSTS=['testserver', 'localhost'])
class ListaIdentificarRenderTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='admin_render', password='pass12345')
        for codename in ('ver_facturas', 'gestionar_facturas'):
            self.admin.user_permissions.add(Permission.objects.get(codename=codename))
        self.client.force_login(self.admin)
        self.sin_id = clientes.cliente_sin_identificar()
        self.url = reverse('facturas_lista')

    def _doc(self, cliente, sugerido=''):
        return DocumentoFactura.objects.create(
            cliente=cliente, tipo_documento='factura', numero_documento='F-1',
            fecha_documento=date(2026, 7, 3), monto_total=100, cliente_sugerido=sugerido)

    def test_muestra_el_badge_y_el_nombre_del_archivo(self):
        self._doc(self.sin_id, sugerido='ACME S DE RL')
        html = self.client.get(self.url).content.decode()

        self.assertIn('Sin identificar', html)
        self.assertIn('ACME S DE RL', html)
        self.assertIn('btn-identificar', html)

    def test_documento_normal_no_trae_el_boton(self):
        self._doc(Cliente.objects.create(nombre='Acme Honduras'))
        html = self.client.get(self.url).content.decode()

        self.assertNotIn('btn-identificar', html)

    def test_el_contexto_trae_el_id_del_cliente_sin_identificar(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.context['sin_identificar_id'], self.sin_id.pk)

    def test_el_modal_se_incluye_una_sola_vez(self):
        self._doc(self.sin_id, sugerido='A')
        self._doc(self.sin_id, sugerido='B')
        html = self.client.get(self.url).content.decode()

        self.assertEqual(html.count('id="modalIdentificar"'), 1)
```

Agregar a la clase `SinN1Tests` de `apps/core/tests_facturas/test_perf_queries.py`, siguiendo el patrón del archivo (comparar el conteo con 2 documentos contra el conteo con 7, usando el helper `_contar_consultas` que ya existe):

```python
    def test_facturas_lista_con_sin_identificar_no_escala_con_filas(self):
        # El badge y el botón de identificar se resuelven contra un id que la vista
        # calcula una sola vez; si alguien lo vuelve una propiedad del modelo, este
        # test lo cacha.
        self.user.user_permissions.add(
            Permission.objects.get(codename='gestionar_facturas'))
        sin_id = clientes.cliente_sin_identificar()

        def _doc_sin_identificar(numero):
            DocumentoFactura.objects.create(
                cliente=sin_id, tipo_documento='factura', numero_documento=numero,
                fecha_documento=timezone.localdate(), monto_total=Decimal('100'),
                cliente_sugerido=f'Cliente {numero}')

        for i in range(2):
            _doc_sin_identificar(f'S{i}')
        n_2 = self._contar_consultas(reverse('facturas_lista'))
        for i in range(5):
            _doc_sin_identificar(f'T{i}')
        n_7 = self._contar_consultas(reverse('facturas_lista'))
        self.assertEqual(
            n_2, n_7,
            f'La lista con documentos sin identificar tiene N+1: {n_2} consultas '
            f'con 2 docs vs {n_7} con 7.')
```

Actualizar el import de servicios del archivo:

```python
from apps.core.services.facturas import payment_service, estado_cuenta_service, clientes
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

```bash
docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_facturas.test_identificar_render --noinput -v 2
```

Esperado: FAIL — `'btn-identificar' not found in html` y `KeyError: 'sin_identificar_id'`.

- [ ] **Step 3: Pasar `sin_identificar_id` al contexto**

En `apps/core/views/facturas.py`, dentro de `facturas_lista`, agregar al diccionario `ctx`:

```python
        # Se resuelve una sola vez acá y el template compara por id. Una propiedad
        # del modelo dispararía una consulta por fila.
        'sin_identificar_id': clientes.cliente_sin_identificar().pk,
```

Y al import de servicios de la cabecera:

```python
from ..services.facturas import clientes, invoice_service, status_service, payment_service
```

- [ ] **Step 4: Modificar las celdas en `templates/facturas/lista.html`**

Reemplazar la celda de cliente:

```html
          <td class="fw-semibold">{{ doc.cliente.nombre }}</td>
```

por:

```html
          <td class="fw-semibold">
            {% if doc.cliente_id == sin_identificar_id %}
            <span class="badge bg-warning-subtle text-warning-emphasis">
              <i class="bi bi-question-circle me-1"></i>Sin identificar
            </span>
            {% if doc.cliente_sugerido %}
            <div class="small text-muted fw-normal">Del archivo: "{{ doc.cliente_sugerido }}"</div>
            {% endif %}
            {% else %}
            {{ doc.cliente.nombre }}
            {% endif %}
          </td>
```

Dentro del `div` de acciones, antes del botón de pago:

```html
              {% if perms.core.gestionar_facturas and doc.cliente_id == sin_identificar_id %}
              <button type="button" class="btn btn-sm btn-outline-warning btn-identificar" title="Identificar cliente"
                      data-url="{% url 'factura_identificar' doc.pk %}"
                      data-sugerido="{{ doc.cliente_sugerido }}"
                      data-info="{{ doc.get_tipo_documento_display }} {{ doc.numero_documento }} · {{ doc.monto_total|moneda }} · {{ doc.fecha_documento|date:'d/m/Y' }}"
                      data-pdf="{% if doc.archivo_pdf %}{% url 'factura_pdf' doc.pk %}{% endif %}">
                <i class="bi bi-person-plus"></i>
              </button>
              {% endif %}
```

En el bloque `extra_js`, junto al include del modal de pago:

```html
{% include "facturas/_modal_identificar.html" %}
{% include "facturas/_cliente_modal.html" %}
<script src="{% static 'js/cliente-inline.js' %}"></script>
```

Verificar que `{% load static %}` esté en la cabecera del template; si no, agregarlo.

- [ ] **Step 5: Crear `templates/facturas/_modal_identificar.html`**

```html
{# Modal reutilizable de identificación. Los botones .btn-identificar lo abren con data-*. #}
<div class="modal fade" id="modalIdentificar" tabindex="-1" aria-hidden="true">
  <div class="modal-dialog modal-dialog-centered">
    <form id="form-identificar">
      <div class="modal-content">
        <div class="modal-header">
          <h5 class="modal-title"><i class="bi bi-person-plus me-2"></i>Identificar cliente</h5>
          <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Cerrar"></button>
        </div>
        <div class="modal-body">
          <div id="identificar-aviso" class="alert alert-danger d-none" role="alert"></div>

          <div id="identificar-sugerido-box" class="alert alert-light border py-2 d-none">
            <div class="text-muted small">El archivo decía</div>
            <div class="fw-semibold" id="identificar-sugerido">—</div>
          </div>
          <div class="text-muted small mb-1" id="identificar-doc-info">—</div>
          <a href="#" class="btn btn-sm btn-outline-secondary mb-3 d-none" id="identificar-pdf" target="_blank">
            <i class="bi bi-file-earmark-pdf-fill text-danger me-1"></i>Ver PDF
          </a>

          <label class="form-label" for="identificar-cliente">Cliente *</label>
          <div class="input-group mb-3">
            <select id="identificar-cliente" name="cliente" class="form-select" required>
              <option value="">— elegí un cliente —</option>
              {% for c in clientes %}
              {% if c.pk != sin_identificar_id %}
              <option value="{{ c.pk }}">{{ c.nombre }}</option>
              {% endif %}
              {% endfor %}
            </select>
            <button type="button" class="btn btn-outline-primary"
                    data-cliente-inline data-target="identificar-cliente">
              <i class="bi bi-plus-lg me-1"></i>Nuevo
            </button>
          </div>

          <div class="form-check" id="identificar-alias-box">
            <input class="form-check-input" type="checkbox" id="identificar-alias" checked>
            <label class="form-check-label" for="identificar-alias">
              Recordar <span class="fw-semibold" id="identificar-alias-nombre"></span> como alias
            </label>
          </div>
          <div class="form-check">
            <input class="form-check-input" type="checkbox" id="identificar-revisado">
            <label class="form-check-label" for="identificar-revisado">
              Marcar el documento como revisado
            </label>
          </div>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Cancelar</button>
          <button type="submit" class="btn btn-warning" id="identificar-submit">
            <i class="bi bi-check-lg me-1"></i>Identificar
          </button>
        </div>
      </div>
    </form>
  </div>
</div>

<script>
(function () {
  var modalEl = document.getElementById('modalIdentificar');
  if (!modalEl || typeof bootstrap === 'undefined') return;
  var modal = new bootstrap.Modal(modalEl);
  var form = document.getElementById('form-identificar');
  var select = document.getElementById('identificar-cliente');
  var aliasBox = document.getElementById('identificar-alias-box');
  var aliasCheck = document.getElementById('identificar-alias');
  var revisadoCheck = document.getElementById('identificar-revisado');
  var avisoBox = document.getElementById('identificar-aviso');
  var submit = document.getElementById('identificar-submit');
  var filaActual = null;
  var urlActual = '';

  function getCookie(name) {
    var value = '; ' + document.cookie;
    var parts = value.split('; ' + name + '=');
    if (parts.length === 2) return parts.pop().split(';').shift();
    return '';
  }

  function mostrarAviso(msg, tipo) {
    avisoBox.className = 'alert alert-' + (tipo || 'danger');
    avisoBox.textContent = msg;
  }

  function limpiarAviso() {
    avisoBox.className = 'alert alert-danger d-none';
    avisoBox.textContent = '';
  }

  document.querySelectorAll('.btn-identificar').forEach(function (b) {
    b.addEventListener('click', function (e) {
      e.stopPropagation();  // la fila entera navega al detalle
      filaActual = b.closest('tr');
      urlActual = b.getAttribute('data-url');
      limpiarAviso();
      select.value = '';
      revisadoCheck.checked = false;

      var sugerido = b.getAttribute('data-sugerido') || '';
      document.getElementById('identificar-sugerido').textContent = sugerido;
      document.getElementById('identificar-sugerido-box').classList.toggle('d-none', !sugerido);
      document.getElementById('identificar-doc-info').textContent = b.getAttribute('data-info') || '';
      // Sin nombre en el archivo no hay nada que recordar.
      aliasBox.classList.toggle('d-none', !sugerido);
      aliasCheck.checked = !!sugerido;
      document.getElementById('identificar-alias-nombre').textContent = sugerido ? '«' + sugerido + '»' : '';

      var pdf = b.getAttribute('data-pdf') || '';
      var linkPdf = document.getElementById('identificar-pdf');
      linkPdf.href = pdf || '#';
      linkPdf.classList.toggle('d-none', !pdf);

      modal.show();
    });
  });

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    limpiarAviso();
    if (!select.value) {
      mostrarAviso('Elegí un cliente.');
      return;
    }
    submit.disabled = true;

    var datos = new FormData();
    datos.append('cliente', select.value);
    if (aliasCheck.checked && !aliasBox.classList.contains('d-none')) datos.append('guardar_alias', '1');
    if (revisadoCheck.checked) datos.append('marcar_revisado', '1');

    fetch(urlActual, {
      method: 'POST',
      body: datos,
      headers: {'X-CSRFToken': getCookie('csrftoken'), 'X-Requested-With': 'XMLHttpRequest'},
    }).then(function (r) {
      return r.json().then(function (data) { return {status: r.status, data: data}; });
    }).then(function (res) {
      submit.disabled = false;
      if (!res.data.ok) {
        var errores = res.data.errors || {};
        var msgs = Object.keys(errores).map(function (k) { return errores[k].join(' '); });
        mostrarAviso(msgs.join(' ') || 'No se pudo identificar el documento.');
        return;
      }
      aplicarResultado(res.data);
    }).catch(function () {
      submit.disabled = false;
      mostrarAviso('No se pudo conectar. Intentá de nuevo.');
    });
  });

  function aplicarResultado(data) {
    if (filaActual) {
      var celda = filaActual.querySelector('td:nth-child(2)');
      if (celda) celda.textContent = data.cliente_nombre;
      var boton = filaActual.querySelector('.btn-identificar');
      if (boton) boton.remove();
      if (data.revisada) {
        filaActual.remove();
        bajarContadorPorRevisar();
      }
    }
    if (data.aviso) {
      // El documento se identificó igual: el alias es un efecto secundario.
      mostrarAviso(data.aviso, 'warning');
      return;
    }
    modal.hide();
  }

  function bajarContadorPorRevisar() {
    var badge = document.querySelector('#btn-por-revisar .badge');
    if (!badge) return;
    var n = (parseInt(badge.textContent, 10) || 1) - 1;
    if (n > 0) { badge.textContent = n; } else { badge.remove(); }
  }
})();
</script>
```

- [ ] **Step 6: Correr los tests y verificar que pasan**

```bash
docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_facturas --noinput -v 2
```

Esperado: PASS.

- [ ] **Step 7: Verificar en el navegador**

```bash
docker compose run --rm --no-deps -p 8002:8002 -e DEBUG=True -e ALLOWED_HOSTS=localhost,127.0.0.1 -v "$(pwd)":/app --entrypoint python web manage.py runserver 0.0.0.0:8002
```

Entrar a `http://localhost:8002/facturas/`, activar "Por revisar" y comprobar, sobre un documento sin identificar:
1. El badge naranja y la línea `Del archivo: "..."` se ven en la celda de cliente.
2. El botón <i>persona+</i> abre el modal **sin** navegar al detalle.
3. "Nuevo" abre el modal de cliente inline y, al crear, lo deja seleccionado en el `<select>`.
4. Al identificar sin marcar revisado, la celda pasa a mostrar el nombre y el modal se cierra, sin recargar.
5. Al identificar marcando revisado, la fila desaparece y el contador del botón "Por revisar" baja en uno.

- [ ] **Step 8: Commit**

```bash
git add apps/core/views/facturas.py templates/facturas/lista.html templates/facturas/_modal_identificar.html apps/core/tests_facturas/test_identificar_render.py apps/core/tests_facturas/test_perf_queries.py
git commit -m "feat(facturas): identificar cliente desde la lista con modal AJAX"
```

---

### Task 7: Textarea de alias en el formulario de cliente

**Files:**
- Modify: `apps/core/forms.py:92-103` (`ClienteForm`)
- Modify: `templates/clientes/form.html`
- Create: `apps/core/tests_facturas/test_cliente_form_aliases.py`

**Interfaces:**
- Consumes: `clientes.sincronizar_aliases()` (Task 2)
- Produces: `ClienteForm` con campo `aliases` (no-modelo). `ClienteForm.save()` sincroniza los alias.

- [ ] **Step 1: Escribir los tests que fallan**

Crear `apps/core/tests_facturas/test_cliente_form_aliases.py`:

```python
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
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

```bash
docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_facturas.test_cliente_form_aliases --noinput -v 2
```

Esperado: FAIL — `KeyError: 'aliases'` en `form.initial`.

- [ ] **Step 3: Agregar el campo al formulario**

Reemplazar `ClienteForm` en `apps/core/forms.py` por:

```python
class ClienteForm(forms.ModelForm):
    aliases = forms.CharField(
        required=False,
        label='Alias (uno por línea)',
        widget=forms.Textarea(attrs={
            'class': 'form-control', 'rows': 3,
            'placeholder': 'ACME S DE RL\nAcme HN',
        }),
        help_text='Otros nombres con los que este cliente aparece en los PDFs. '
                  'Sirven para emparejar los documentos que entran automáticamente.',
    )

    class Meta:
        model = Cliente
        fields = ['nombre', 'telefono', 'rtn', 'direccion', 'dias_credito', 'activo']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'telefono': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: +504 9999-9999'}),
            'rtn': forms.TextInput(attrs={'class': 'form-control'}),
            'direccion': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'dias_credito': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'placeholder': '0 = contado'}),
            'activo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.initial['aliases'] = '\n'.join(
                self.instance.aliases.values_list('alias', flat=True))

    def save(self, commit=True):
        from .services.facturas.clientes import sincronizar_aliases

        cliente = super().save(commit=commit)
        if commit:
            errores = sincronizar_aliases(cliente, self.cleaned_data.get('aliases', ''))
            if errores:
                # `clean_aliases` ya rechazó todo esto; llegar acá significa que
                # otra edición se metió en el medio. Se registra y se sigue: el
                # cliente se guarda igual, como en el resto del módulo, donde el
                # alias nunca hace fracasar la acción principal.
                _log.warning('Alias no sincronizados para cliente %s: %s',
                             cliente.pk, '; '.join(errores))
        return cliente
```

Agregar el método de validación, dentro de la misma clase, después de `__init__`:

```python
    def clean_aliases(self):
        """Rechaza los alias que chocan, juntando todos los problemas de una vez.

        La validación es un ensayo de `sincronizar_aliases` sin escribir nada:
        quien edita el textarea quiere ver de una todo lo que tiene que arreglar,
        no descubrirlo de a un error por guardado.
        """
        from .models import Cliente as _Cliente, ClienteAlias
        from .textnorm import norm

        texto = self.cleaned_data.get('aliases', '') or ''
        nombre = self.cleaned_data.get('nombre', '') or ''
        errores, vistos = [], set()
        for linea in texto.splitlines():
            linea = linea.strip()
            clave = norm(linea)
            if not clave or clave in vistos or clave == norm(nombre):
                continue
            vistos.add(clave)

            ajeno = ClienteAlias.objects.filter(alias_norm=clave).exclude(
                cliente_id=self.instance.pk).select_related('cliente').first()
            if ajeno:
                errores.append(f'«{linea}» ya está registrado como alias de '
                               f'{ajeno.cliente.nombre}.')
                continue
            choque = next((c for c in _Cliente.objects.exclude(pk=self.instance.pk)
                           if norm(c.nombre) == clave), None)
            if choque:
                errores.append(f'«{linea}» es el nombre del cliente {choque.nombre}; '
                               'un alias así nunca se usaría.')
        if errores:
            raise ValidationError(errores)
        return texto
```

Verificar que `ValidationError` esté importado en `forms.py`; si no, agregar `from django.core.exceptions import ValidationError`. Agregar también el logger en la cabecera del archivo, si no existe:

```python
import logging

_log = logging.getLogger(__name__)
```

- [ ] **Step 4: Agregar el textarea al template**

En `templates/clientes/form.html`, después del bloque del campo `nombre` (línea 21):

```html
        <div class="col-12">
          <label class="form-label" for="{{ form.aliases.id_for_label }}">
            <i class="bi bi-tags me-1"></i>Alias (uno por línea)
          </label>
          {{ form.aliases }}
          <div class="form-text">{{ form.aliases.help_text }}</div>
          {% if form.aliases.errors %}<div class="text-danger small">{{ form.aliases.errors }}</div>{% endif %}
        </div>
```

- [ ] **Step 5: Correr toda la suite**

```bash
docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core --noinput -v 1
```

Esperado: PASS. `ClienteForm` lo usan también las vistas de alta/edición de cliente y los tests de inventario; si alguno rompe, es porque instanciaba el form sin `aliases` — el campo es `required=False`, así que revisar el error concreto antes de tocar nada.

- [ ] **Step 6: Verificar en el navegador**

Con el runserver del Task 6 andando, ir a `http://localhost:8002/clientes/<id>/editar/`:
1. El textarea aparece con los alias existentes, uno por línea.
2. Quitar una línea y guardar borra ese alias.
3. Escribir un alias que ya pertenece a otro cliente muestra el error bajo el campo y no guarda.

- [ ] **Step 7: Commit**

```bash
git add apps/core/forms.py templates/clientes/form.html apps/core/tests_facturas/test_cliente_form_aliases.py
git commit -m "feat(clientes): administrar alias desde el formulario de cliente"
```

---

## Verificación final

- [ ] **Toda la suite pasa**

```bash
docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core --noinput -v 1
```

- [ ] **No quedan migraciones sin generar**

```bash
docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py makemigrations --check --dry-run
```

Esperado: `No changes detected`.

- [ ] **El ciclo completo funciona end-to-end.** Con el runserver andando:
  1. Identificar un documento sin identificar marcando "recordar alias".
  2. Confirmar que el alias aparece en el formulario de ese cliente.
  3. Mandar a la ingesta un PDF cuyo nombre use ese alias:

```bash
curl -s -X POST http://localhost:8002/facturas/api/ingest/ -H "X-API-Key: $FACTURAS_INGEST_TOKEN" -F "archivo=@docs/facturas/samples/Fact 9543 Inversiones Zaga.pdf;filename=Fact 9544 <EL ALIAS>.pdf"
```

  Esperado: `"requiere_revision": false` y el `"cliente"` correcto. **Ese es el objetivo entero de la feature**: el nombre se preguntó una vez y no vuelve a preguntarse.
