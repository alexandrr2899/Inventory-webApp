# Crear cliente inline al ingresar factura

**Fecha:** 2026-07-02
**Estado:** Aprobado (diseño)

## Problema

Al crear una factura, el cliente se elige de un `<select>` que solo lista clientes
**activos ya registrados**:

- **Subida individual** (`factura_upload` → `templates/facturas/form_upload.html`): campo
  `{{ form.cliente }}` del `DocumentoUploadForm` (un `<select class="form-select">`).
- **Lote** (revisión: `templates/facturas/lote_revisar.html`): un `<select
  name="fila-{i}-cliente" class="form-select form-select-sm">` por archivo; las filas que
  no emparejan cliente automáticamente se resaltan en amarillo.

Si el cliente no está registrado, hay que **abandonar la factura, ir a la sección
Clientes, crearlo y volver**. Esto interrumpe el flujo, sobre todo en el lote donde varias
facturas pueden ser de un cliente nuevo.

## Objetivo

Permitir **crear un cliente sin salir** del formulario de factura, mediante un botón
"+ Nuevo cliente" junto al selector que abre un modal con los campos del cliente; al
guardar, el nuevo cliente se agrega al selector y queda seleccionado.

## Decisiones tomadas (brainstorming)

- **Alcance:** ambos flujos (subida individual y revisión de lote).
- **Patrón:** botón "+ Nuevo cliente" → **modal con campos** (no selector "al vuelo", no
  selector buscable). Reutiliza los campos del cliente.
- **Duplicados:** si al crear el nombre coincide (case-insensitive) con un cliente
  existente, el modal **avisa y ofrece seleccionar el existente**, pero permite **forzar**
  la creación.
- **Permiso:** el endpoint y el botón se rigen por **`gestionar_facturas`** (el mismo que
  crear facturas). Esto **amplía deliberadamente** lo que ese rol puede hacer (crear
  clientes) aunque no tenga `editar_item`.
- Los `<select>` siguen siendo **nativos** (no se cambian a buscables).
- Los clientes creados inline nacen **activos**.

## Contexto del código actual

- Modelo `Cliente` (`apps/core/models.py`): campos `nombre`, `telefono`, `rtn`,
  `direccion`, `dias_credito` (PositiveInteger, 0 = contado), `activo`. **Sin** restricción
  de unicidad sobre `nombre`.
- `ClienteForm` (`apps/core/forms.py`): `['nombre','telefono','rtn','direccion',
  'dias_credito','activo']`.
- `cliente_crear` (`apps/core/views/catalogos.py`) exige `editar_item` y redirige a
  `cliente_lista` (flujo tradicional de la sección Clientes; **no se toca**).
- Rutas de facturas en `apps/core/urls.py` (p.ej. `facturas/documentos/nuevo/`,
  `facturas/documentos/lote/`). Los nombres de URL de clientes de catálogo viven bajo
  `clientes/...`.

## Componentes

### 1. `ClienteInlineForm` (nuevo, en `apps/core/forms.py`)

`ModelForm` de `Cliente` con `fields = ['nombre','telefono','rtn','direccion',
'dias_credito']` (**sin** `activo`). Mismos widgets/clases Bootstrap que `ClienteForm`
para las que apliquen. `nombre` es requerido (ya lo es en el modelo); el resto opcional.
Los clientes creados con este form quedan `activo=True` (valor por defecto del modelo).

### 2. Endpoint AJAX `cliente_crear_inline` (nuevo)

Vista en `apps/core/views/facturas_cliente.py`, ruta nueva bajo `facturas/` con nombre
`cliente_crear_inline`. Decoradores: `@login_required`,
`@permission_required(_perm('gestionar_facturas'), raise_exception=True)`, `@require_POST`
(usar el helper `_perm(...)` existente, como el resto de vistas de facturas). Si el módulo
de facturas usa el decorador `@facturas_enabled` en sus vistas, aplicarlo también aquí para
mantener la coherencia.

Entrada (POST, `application/x-www-form-urlencoded`): campos de `ClienteInlineForm` +
`forzar` opcional (`'1'` para forzar pese a duplicado). CSRF requerido (token estándar de
Django).

Lógica y respuestas **JSON**:

1. `form = ClienteInlineForm(request.POST)`; si `not form.is_valid()` →
   `JsonResponse({'ok': False, 'errors': form.errors}, status=400)`.
2. Si es válido, buscar duplicado por nombre case-insensitive:
   `Cliente.objects.filter(nombre__iexact=form.cleaned_data['nombre'].strip()).first()`.
   Si existe y `request.POST.get('forzar') != '1'` →
   `JsonResponse({'ok': False, 'duplicado': {'id': dup.pk, 'nombre': dup.nombre}}, status=200)`
   (no crea).
3. Si no hay duplicado o viene `forzar='1'` → `cliente = form.save()` y
   `JsonResponse({'ok': True, 'cliente': {'id': cliente.pk, 'nombre': cliente.nombre}}, status=201)`.

El endpoint **no** usa `messages` ni redirige; solo devuelve JSON.

### 3. Modal compartido `templates/facturas/_cliente_modal.html` (nuevo)

Modal Bootstrap con:
- Título "Nuevo cliente".
- Campos: `nombre` (requerido, con `autofocus` al abrir), `telefono`, `rtn`,
  `dias_credito` (número, min 0, placeholder "0 = contado"), `direccion` (textarea corta).
  Marcado Bootstrap consistente con `templates/clientes/form.html`.
- Una zona de avisos (`#cliente-modal-aviso`) para el mensaje de duplicado y errores
  generales; y `.invalid-feedback` por campo para errores de validación.
- Botones: **Crear** (submit del modal, no del form de factura) y **Cancelar**
  (`data-bs-dismiss`).
- Un contenedor oculto para el bloque "duplicado" con el nombre existente y dos acciones:
  **Usar existente** y **Crear de todos modos**.

El modal se incluye **una vez** en cada página que lo usa (`form_upload.html` y
`lote_revisar.html`), solo si el usuario tiene el permiso (ver §5).

### 4. Módulo JS `static/js/cliente-inline.js` (nuevo)

Sin dependencias más allá de Bootstrap (ya global). Expone el comportamiento:

- Cada botón "+ Nuevo cliente" tiene un `data-target` con el `id` del `<select>` destino.
  Al hacer clic, guarda el destino y abre el modal (limpia campos y avisos previos).
- **Crear** envía por `fetch` (POST, `credentials: 'same-origin'`, header
  `X-CSRFToken` leído de la cookie `csrftoken`, cuerpo `URLSearchParams` con los campos +
  `forzar` cuando aplique) al endpoint `cliente_crear_inline`.
- Maneja las respuestas:
  - **201 `{ok:true, cliente}`** → construye un `<option value=cliente.id>cliente.nombre</option>`,
    lo **inserta en orden alfabético en todos** los `<select.cliente-select>` de la página
    (evitando duplicar si ya existe esa opción), lo **selecciona** en el `<select>` destino,
    dispara un evento `change` en el destino, cierra el modal.
  - **200 `{ok:false, duplicado}`** → muestra el bloque duplicado con
    "Ya existe «`duplicado.nombre`»" y las acciones:
    - **Usar existente** → selecciona `duplicado.id` en el destino (si no está como opción,
      la agrega), dispara `change`, cierra el modal.
    - **Crear de todos modos** → reenvía el `fetch` con `forzar='1'`.
  - **400 `{ok:false, errors}`** → pinta cada mensaje en el `.invalid-feedback` del campo
    correspondiente (`errors` es `{campo: [mensajes]}`); errores no asociados a un campo van
    a `#cliente-modal-aviso`.
  - **403 u otros** → aviso genérico en `#cliente-modal-aviso` ("No se pudo crear el
    cliente."), sin cerrar el modal.

El script se carga en las páginas que lo usan (vía `{% block extra_js %}` o inclusión
directa), después de Bootstrap.

### 5. Integración en los formularios

**Subida individual (`templates/facturas/form_upload.html`):**
- Añadir la clase `cliente-select` y un `id` estable (p.ej. `id="id_cliente"`, el que
  Django ya asigna al widget) al `<select>` de `{{ form.cliente }}`. Para ello, en
  `DocumentoUploadForm` agregar `class': 'form-select cliente-select'` al widget de
  `cliente` (mantiene `form-select`).
- Junto al selector, un botón "+ Nuevo cliente" con `data-target="id_cliente"`, visible
  solo con permiso (ver abajo).
- Incluir `_cliente_modal.html` y cargar `cliente-inline.js`.

**Revisión de lote (`templates/facturas/lote_revisar.html`):**
- Añadir la clase `cliente-select` a cada `<select name="fila-{i}-cliente">` y un `id`
  único por fila (p.ej. `id="cliente-fila-{{ forloop.counter0 }}"`).
- En la celda de cliente de cada fila, un botón "+ Nuevo cliente" con `data-target` al `id`
  de esa fila.
- Incluir `_cliente_modal.html` **una vez** (fuera del loop) y cargar `cliente-inline.js`.
- Al crear, la inyección en **todos** los `.cliente-select` hace que el cliente nuevo quede
  disponible en las demás filas, y queda seleccionado en la fila de origen.

**Visibilidad del botón (permiso):** el botón "+ Nuevo cliente" y la inclusión del modal se
envuelven en `{% if perms.core.gestionar_facturas %}`. (Ambas vistas ya exigen ese permiso
para renderizarse, así que en la práctica siempre estará; la guarda mantiene la coherencia
y protege si el markup se reutiliza.)

## Ruta y nombres

- Añadir en `apps/core/urls.py`: `path('facturas/clientes/inline/',
  views.cliente_crear_inline, name='cliente_crear_inline')`. El JS obtiene la URL desde un
  atributo `data-url` en el botón o el modal (renderizado con `{% url
  'cliente_crear_inline' %}`), para no hardcodearla.

## Manejo de errores

- Sin permiso → el botón no se renderiza; el endpoint responde 403 (JSON o
  `PermissionDenied`).
- Validación (nombre vacío) → `400` con `errors`, pintado inline; el modal no se cierra.
- Duplicado sin forzar → no crea; ofrece usar el existente o forzar.
- Fallo de red/servidor → aviso genérico en el modal; no se pierde lo escrito.

## Pruebas (alcance)

Ubicar en `apps/core/tests_facturas/` (paquete existente de tests de facturas).

- **Endpoint — crear:** POST válido con `gestionar_facturas` → 201, JSON
  `{ok:true, cliente:{id,nombre}}`, y el `Cliente` existe y está `activo=True`.
- **Endpoint — permiso:** POST sin `gestionar_facturas` → 403; no se crea nada.
- **Endpoint — validación:** POST con `nombre` vacío → 400, `errors` contiene `nombre`; no
  se crea.
- **Endpoint — duplicado sin forzar:** existe "Juan Pérez"; POST `nombre="juan pérez"` sin
  `forzar` → 200 con `duplicado:{id,nombre}` y **no** se crea un segundo cliente.
- **Endpoint — duplicado forzado:** mismo caso con `forzar='1'` → 201 y ahora existen dos
  clientes con ese nombre.
- **Render:** `form_upload` y `lote_revisar` incluyen el botón "+ Nuevo cliente" y el modal
  para un usuario con `gestionar_facturas`.

La lógica JS no tiene arnés de pruebas en este repo; se cubre con verificación manual
(crear cliente en subida individual y en una fila del lote; caso duplicado; caso nombre
vacío).

## Fuera de alcance (YAGNI)

- Convertir los `<select>` de cliente en buscables (TomSelect).
- Editar clientes inline.
- Deduplicar por teléfono o RTN (solo por `nombre`).
- Restricción de unicidad a nivel de base de datos sobre `Cliente.nombre` (se mantiene la
  verificación blanda en la app).
- Tocar el flujo tradicional `cliente_crear` de la sección Clientes.

## Notas de ejecución

- **Tests solo en Docker**, con volumen montado y `--noinput`:
  `docker compose run --rm --no-deps -v "$(pwd)":/app --entrypoint python web manage.py
  test apps.core.tests_facturas -v 2 --noinput`.
- No hay cambios de dependencias ni de esquema (no se añaden campos ni migraciones): el
  cambio es una vista + form + templates + JS.
