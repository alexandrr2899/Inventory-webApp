# Inventario: orden de tabs + orden por columna — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permitir reordenar globalmente las tabs del inventario (drag, con permiso) y ordenar la tabla por columna (asc/desc, server-side).

**Architecture:** Un modelo singleton `InventarioConfig` guarda el orden de tabs como lista de claves. La vista `inventario_lista` lee ese orden (reconciliado con un set canónico definido en código) y aplica también `order_by` por columna según query params. Un endpoint POST con permiso persiste el nuevo orden de tabs; el frontend usa SortableJS en un modal.

**Tech Stack:** Django 4.2, PostgreSQL, Bootstrap (modal), SortableJS (servido local), whitenoise.

**Spec:** `docs/superpowers/specs/2026-06-18-inventario-orden-tabs-y-columnas-design.md`

---

## Entorno de pruebas (leer antes de empezar)

No hay venv local; los tests corren en Docker contra Postgres. Antes de la primera tarea, dejá la DB y Redis levantados:

```bash
docker compose up -d db redis
```

**Comando de test canónico** (referido abajo como `[TEST] <ruta>`):

```bash
docker compose run --rm --entrypoint "" web python manage.py test <ruta> -v2
```

Si la imagen no refleja cambios de código (porque el código va dentro de la imagen, no montado), reconstruí antes de testear:

```bash
docker compose build web
```

> Para iterar más rápido durante esta feature podés montar el código en cada corrida agregando `-v "$(pwd):/app"` al `docker compose run`, evitando el rebuild. Ej:
> `docker compose run --rm --entrypoint "" -v "$(pwd):/app" web python manage.py test apps.core.tests -v2`
> Usá esa variante en los pasos `[TEST]`.

**Nota de exports:** `apps/core/views/inventario.py` NO tiene `__all__`, así que todo nombre público (sin `_` inicial) se re-exporta vía `from .inventario import *` en `apps/core/views/__init__.py`. Por eso `get_orden_tabs`, `TABS_INVENTARIO` e `inventario_tabs_orden` quedan importables como `apps.core.views.<nombre>` y usables desde `urls.py` y los tests.

---

## Estructura de archivos

- `apps/core/models.py` — nuevo modelo `InventarioConfig` (singleton + permiso).
- `apps/core/migrations/0017_inventarioconfig.py` — migración (escrita a mano).
- `apps/core/views/inventario.py` — constantes `TABS_INVENTARIO`/`ORDEN_COLS`, helper `get_orden_tabs()`, vista `inventario_tabs_orden`, cambios en `inventario_lista`.
- `apps/core/urls.py` — ruta `inventario_tabs_orden`.
- `apps/core/management/commands/setup_groups.py` — otorgar permiso a Administrador y Supervisor.
- `templates/inventario/lista.html` — tabs data-driven, modal de orden, headers ordenables, selector móvil, JS.
- `static/js/sortable.min.js` — librería SortableJS (servida local).
- `apps/core/tests.py` — tests de ambas features.

---

## Task 1: Modelo `InventarioConfig` + migración

**Files:**
- Modify: `apps/core/models.py`
- Create: `apps/core/migrations/0017_inventarioconfig.py`
- Test: `apps/core/tests.py`

- [ ] **Step 1: Agregar el modelo al final de `apps/core/models.py`**

```python
class InventarioConfig(models.Model):
    """
    Configuración singleton del inventario (una sola fila, pk=1).
    Por ahora guarda el orden de las tabs de la lista de inventario.
    """
    orden_tabs = models.JSONField(default=list)

    class Meta:
        verbose_name = 'Configuración de inventario'
        verbose_name_plural = 'Configuración de inventario'
        permissions = [
            ('ordenar_tabs_inventario', 'Puede ordenar las tabs del inventario'),
        ]

    def __str__(self):
        return 'Configuración de inventario'
```

- [ ] **Step 2: Crear la migración `apps/core/migrations/0017_inventarioconfig.py`**

```python
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0016_conteo_editar_perm'),
    ]

    operations = [
        migrations.CreateModel(
            name='InventarioConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('orden_tabs', models.JSONField(default=list)),
            ],
            options={
                'verbose_name': 'Configuración de inventario',
                'verbose_name_plural': 'Configuración de inventario',
                'permissions': [('ordenar_tabs_inventario', 'Puede ordenar las tabs del inventario')],
            },
        ),
    ]
```

- [ ] **Step 3: Escribir el test que verifica el modelo y el permiso**

Agregar al final de `apps/core/tests.py`:

```python
@override_settings(ALLOWED_HOSTS=['testserver', 'localhost'])
class InventarioConfigModelTests(TestCase):
    def test_singleton_y_permiso_existen(self):
        from apps.core.models import InventarioConfig
        from django.contrib.auth.models import Permission

        config, creado = InventarioConfig.objects.get_or_create(pk=1)
        self.assertTrue(creado)
        self.assertEqual(config.orden_tabs, [])
        self.assertTrue(
            Permission.objects.filter(codename='ordenar_tabs_inventario').exists()
        )
```

- [ ] **Step 4: Correr el test (verificar que pasa con la migración aplicada)**

`[TEST] apps.core.tests.InventarioConfigModelTests`
Expected: PASS (la migración crea la tabla y el permiso).

- [ ] **Step 5: Commit**

```bash
git add apps/core/models.py apps/core/migrations/0017_inventarioconfig.py apps/core/tests.py
git commit -m "feat: modelo InventarioConfig + permiso ordenar_tabs_inventario"
```

---

## Task 2: Constantes de tabs + helper `get_orden_tabs()`

**Files:**
- Modify: `apps/core/views/inventario.py`
- Test: `apps/core/tests.py`

- [ ] **Step 1: Escribir los tests del helper**

Agregar al final de `apps/core/tests.py`:

```python
@override_settings(ALLOWED_HOSTS=['testserver', 'localhost'])
class GetOrdenTabsTests(TestCase):
    def test_orden_canonico_sin_config(self):
        from apps.core.views import get_orden_tabs
        claves = [t['clave'] for t in get_orden_tabs()]
        self.assertEqual(
            claves, ['todos', 'producto', 'repuesto', 'consumible', 'bajo_stock']
        )

    def test_reconcilia_guardado_con_canonico(self):
        from apps.core.models import InventarioConfig
        from apps.core.views import get_orden_tabs
        # Incluye una clave desconocida (se descarta) y omite varias (se agregan al final)
        InventarioConfig.objects.create(
            pk=1, orden_tabs=['bajo_stock', 'desconocida', 'producto']
        )
        claves = [t['clave'] for t in get_orden_tabs()]
        self.assertEqual(claves[:2], ['bajo_stock', 'producto'])
        self.assertEqual(len(claves), 5)
        self.assertEqual(
            set(claves), {'todos', 'producto', 'repuesto', 'consumible', 'bajo_stock'}
        )

    def test_ignora_duplicados_guardados(self):
        from apps.core.models import InventarioConfig
        from apps.core.views import get_orden_tabs
        InventarioConfig.objects.create(pk=1, orden_tabs=['todos', 'todos', 'producto'])
        claves = [t['clave'] for t in get_orden_tabs()]
        self.assertEqual(len(claves), 5)
        self.assertEqual(claves.count('todos'), 1)
```

- [ ] **Step 2: Correr los tests (deben fallar)**

`[TEST] apps.core.tests.GetOrdenTabsTests`
Expected: FAIL con `ImportError: cannot import name 'get_orden_tabs'`.

- [ ] **Step 3: Implementar constantes y helper en `apps/core/views/inventario.py`**

Justo después de la línea `from .stock import *  # noqa: F401,F403` (cabecera del archivo), agregar:

```python
# ─── TABS DEL INVENTARIO ──────────────────────────────────────────────────────
# Definición canónica (orden por defecto + metadata de presentación). El orden
# real lo guarda InventarioConfig; get_orden_tabs() reconcilia ambos.
TABS_INVENTARIO = [
    {'clave': 'todos',      'etiqueta': 'Todos'},
    {'clave': 'producto',   'etiqueta': 'Producto',   'color': '#198754'},
    {'clave': 'repuesto',   'etiqueta': 'Repuesto'},
    {'clave': 'consumible', 'etiqueta': 'Consumible'},
    {'clave': 'bajo_stock', 'etiqueta': 'Bajo stock', 'danger': True},
]
TABS_CLAVES = [t['clave'] for t in TABS_INVENTARIO]
_TABS_POR_CLAVE = {t['clave']: t for t in TABS_INVENTARIO}

# Columnas ordenables de la tabla → campo ORM (Task 4)
ORDEN_COLS = {
    'nombre':    'nombre',
    'codigo':    'codigo',
    'tipo':      'tipo',
    'categoria': 'categoria__nombre',
    'stock':     'stock_calc',
}


def get_orden_tabs():
    """
    Devuelve las tabs en el orden guardado (InventarioConfig singleton),
    reconciliado con el set canónico: respeta el orden guardado para claves
    válidas (sin duplicar), y agrega al final cualquier tab canónica ausente.
    Descarta claves desconocidas. Siempre devuelve las 5 tabs con su metadata.
    """
    from ..models import InventarioConfig
    config, _ = InventarioConfig.objects.get_or_create(pk=1)
    ordenadas = []
    vistas = set()
    for clave in (config.orden_tabs or []):
        if clave in _TABS_POR_CLAVE and clave not in vistas:
            ordenadas.append(clave)
            vistas.add(clave)
    for clave in TABS_CLAVES:
        if clave not in vistas:
            ordenadas.append(clave)
            vistas.add(clave)
    return [_TABS_POR_CLAVE[c] for c in ordenadas]
```

- [ ] **Step 4: Correr los tests (deben pasar)**

`[TEST] apps.core.tests.GetOrdenTabsTests`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/core/views/inventario.py apps/core/tests.py
git commit -m "feat: TABS_INVENTARIO + get_orden_tabs con reconciliación"
```

---

## Task 3: Endpoint para guardar el orden de tabs

**Files:**
- Modify: `apps/core/views/inventario.py`, `apps/core/urls.py`
- Test: `apps/core/tests.py`

- [ ] **Step 1: Escribir los tests del endpoint**

Agregar al final de `apps/core/tests.py`:

```python
@override_settings(ALLOWED_HOSTS=['testserver', 'localhost'])
class GuardarOrdenTabsTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import Permission
        self.editor = User.objects.create_user('editor', password='x')
        self.editor.user_permissions.add(
            Permission.objects.get(codename='ordenar_tabs_inventario')
        )
        self.viewer = User.objects.create_user('viewer', password='x')

    def _post(self, user, orden):
        import json as _json
        self.client.force_login(user)
        return self.client.post(
            reverse('inventario_tabs_orden'),
            data=_json.dumps({'orden': orden}),
            content_type='application/json',
        )

    def test_guarda_permutacion_valida_con_permiso(self):
        from apps.core.models import InventarioConfig
        orden = ['bajo_stock', 'producto', 'todos', 'consumible', 'repuesto']
        resp = self._post(self.editor, orden)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(InventarioConfig.objects.get(pk=1).orden_tabs, orden)

    def test_sin_permiso_403(self):
        resp = self._post(self.viewer,
                          ['todos', 'producto', 'repuesto', 'consumible', 'bajo_stock'])
        self.assertEqual(resp.status_code, 403)

    def test_permutacion_invalida_400(self):
        # Falta 'bajo_stock'
        resp = self._post(self.editor, ['todos', 'producto', 'repuesto', 'consumible'])
        self.assertEqual(resp.status_code, 400)

    def test_clave_desconocida_400(self):
        resp = self._post(self.editor,
                          ['todos', 'producto', 'repuesto', 'consumible', 'XXX'])
        self.assertEqual(resp.status_code, 400)
```

- [ ] **Step 2: Correr los tests (deben fallar)**

`[TEST] apps.core.tests.GuardarOrdenTabsTests`
Expected: FAIL (no existe la url `inventario_tabs_orden`).

- [ ] **Step 3: Agregar el import de `HttpResponseBadRequest` en `apps/core/views/inventario.py`**

Justo debajo de `from .stock import *  # noqa: F401,F403`:

```python
from django.http import HttpResponseBadRequest
```

- [ ] **Step 4: Implementar la vista `inventario_tabs_orden` en `apps/core/views/inventario.py`**

Agregar (después de `get_orden_tabs`):

```python
@login_required
@require_POST
@permission_required(_perm('ordenar_tabs_inventario'), raise_exception=True)
def inventario_tabs_orden(request):
    """Persiste el orden global de tabs. Body JSON: {"orden": [clave, ...]}."""
    from ..models import InventarioConfig
    try:
        nuevo = json.loads(request.body).get('orden')
    except (ValueError, TypeError, AttributeError):
        return HttpResponseBadRequest('JSON inválido.')

    if (not isinstance(nuevo, list)
            or len(nuevo) != len(TABS_CLAVES)
            or set(nuevo) != set(TABS_CLAVES)):
        return HttpResponseBadRequest(
            'El orden debe ser una permutación exacta de las tabs.'
        )

    config, _ = InventarioConfig.objects.get_or_create(pk=1)
    config.orden_tabs = nuevo
    config.save(update_fields=['orden_tabs'])
    return JsonResponse({'ok': True})
```

(`json`, `require_POST`, `login_required`, `permission_required`, `_perm`, `JsonResponse` ya vienen de `from .common import *`.)

- [ ] **Step 5: Registrar la ruta en `apps/core/urls.py`**

Debajo de la línea de `path('inventario/<int:pk>/historial/', ...)`:

```python
    path('inventario/tabs/orden/', views.inventario_tabs_orden, name='inventario_tabs_orden'),
```

- [ ] **Step 6: Correr los tests (deben pasar)**

`[TEST] apps.core.tests.GuardarOrdenTabsTests`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/core/views/inventario.py apps/core/urls.py apps/core/tests.py
git commit -m "feat: endpoint inventario_tabs_orden con validación y permiso"
```

---

## Task 4: `inventario_lista` — contexto de tabs + orden por columna

**Files:**
- Modify: `apps/core/views/inventario.py`
- Test: `apps/core/tests.py`

- [ ] **Step 1: Escribir los tests de la vista**

Agregar al final de `apps/core/tests.py`:

```python
@override_settings(ALLOWED_HOSTS=['testserver', 'localhost'])
class InventarioListaOrdenTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import Permission
        cache.clear()
        self.user = User.objects.create_user('op2', password='x')
        self.user.user_permissions.add(Permission.objects.get(codename='ver_inventario'))
        self.ub = Ubicacion.objects.create(nombre='Bodega', tipo='bodega')
        # Tres items de tipos distintos
        for codigo, nombre, tipo in (
            ('A', 'Alfa', 'producto'),
            ('B', 'Beta', 'repuesto'),
            ('C', 'Gamma', 'consumible'),
        ):
            Item.objects.create(codigo=codigo, nombre=nombre, tipo=tipo,
                                unidad_medida='u', stock_minimo=Decimal('0'))

    def test_contexto_incluye_tabs_y_permiso(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('inventario_lista'))
        self.assertEqual(resp.status_code, 200)
        claves = [t['clave'] for t in resp.context['tabs_ordenadas']]
        self.assertEqual(len(claves), 5)
        self.assertFalse(resp.context['puede_ordenar_tabs'])  # sin permiso de orden

    def test_orden_por_tipo_desc(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('inventario_lista'),
                               {'orden_col': 'tipo', 'orden_dir': 'desc'})
        tipos = [d['item'].tipo for d in resp.context['items_data']]
        self.assertEqual(tipos, sorted(tipos, reverse=True))

    def test_orden_col_invalida_cae_a_default(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('inventario_lista'),
                               {'orden_col': 'inexistente', 'orden_dir': 'asc'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['orden_col'], '')
```

- [ ] **Step 2: Correr los tests (deben fallar)**

`[TEST] apps.core.tests.InventarioListaOrdenTests`
Expected: FAIL (`KeyError: 'tabs_ordenadas'` / orden no aplicado).

- [ ] **Step 3: Modificar `inventario_lista` en `apps/core/views/inventario.py`**

En la construcción del queryset, después del filtro `if q:` y ANTES de `paginator = Paginator(qs, 100)`, insertar el orden por columna:

```python
    # ── Orden por columna (server-side). Default: orden manual (orden, nombre). ──
    orden_col = request.GET.get('orden_col', '')
    orden_dir = request.GET.get('orden_dir', 'asc')
    campo = ORDEN_COLS.get(orden_col)
    if campo:
        prefijo = '-' if orden_dir == 'desc' else ''
        qs = qs.order_by(f'{prefijo}{campo}')
```

Reemplazar la construcción final de `context` por:

```python
    context = {
        'items_data': items_data,
        'q': q,
        'page_obj': page_obj,
        'tabs_ordenadas': get_orden_tabs(),
        'puede_ordenar_tabs': request.user.has_perm(_perm('ordenar_tabs_inventario')),
        'orden_col': orden_col if campo else '',
        'orden_dir': orden_dir if orden_dir in ('asc', 'desc') else 'asc',
    }
    return render(request, 'inventario/lista.html', context)
```

- [ ] **Step 4: Correr los tests (deben pasar)**

`[TEST] apps.core.tests.InventarioListaOrdenTests`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/core/views/inventario.py apps/core/tests.py
git commit -m "feat: inventario_lista expone tabs_ordenadas y orden por columna"
```

---

## Task 5: Otorgar el permiso en `setup_groups`

**Files:**
- Modify: `apps/core/management/commands/setup_groups.py`

- [ ] **Step 1: Agregar el permiso al grupo Administrador**

En `apps/core/management/commands/setup_groups.py`, en la lista de `'Administrador'`, reemplazar la línea:

```python
        'editar_conteo', 'anular_conteo',
```

por:

```python
        'editar_conteo', 'anular_conteo',
        'ordenar_tabs_inventario',
```

- [ ] **Step 2: Agregar el permiso al grupo Supervisor**

En la lista de `'Supervisor'`, reemplazar:

```python
        'registrar_conteo', 'aplicar_conciliacion', 'ver_reportes',
        'registrar_produccion',
    ],
```

por:

```python
        'registrar_conteo', 'aplicar_conciliacion', 'ver_reportes',
        'registrar_produccion',
        'ordenar_tabs_inventario',
    ],
```

- [ ] **Step 3: Verificar que el comando corre sin error**

Run: `docker compose run --rm --entrypoint "" -v "$(pwd):/app" web python manage.py setup_groups`
Expected: termina sin excepción; menciona los grupos actualizados.

- [ ] **Step 4: Commit**

```bash
git add apps/core/management/commands/setup_groups.py
git commit -m "feat: otorgar ordenar_tabs_inventario a Administrador y Supervisor"
```

---

## Task 6: Frontend — tabs data-driven, modal de orden, headers ordenables

**Files:**
- Modify: `templates/inventario/lista.html`
- Create: `static/js/sortable.min.js`
- Test: `apps/core/tests.py` (asserts de render)

- [ ] **Step 1: Descargar SortableJS a `static/js/`**

```bash
mkdir -p static/js
curl -L https://cdn.jsdelivr.net/npm/sortablejs@1.15.2/Sortable.min.js -o static/js/sortable.min.js
test -s static/js/sortable.min.js && echo OK
```
Expected: `OK` (archivo no vacío).

- [ ] **Step 2: Leer `templates/inventario/lista.html` completo**

Run: abrir el archivo y ubicar:
- el bloque `<!-- Tabs -->` (≈ línea 55) con los `<li class="nav-item"><button ... data-tab="...">`,
- los `<thead>` de la tabla desktop (≈ línea 106-110) con los `<th>`,
- el bloque `{% block extra_js %}`/`<script>` al final,
- cómo se incluye `{% load static %}` (debe estar arriba; si no, agregarlo).

- [ ] **Step 3: Reordenar los bloques `<li>` de tabs según `tabs_ordenadas` (preservando su markup exacto)**

El JS existente escribe los contadores en IDs fijos (`cnt-todos`, `cnt-producto`, `cnt-repuesto`, `cnt-consumible`, `cnt-bajo`) y cada tab tiene markup visual propio (puntos de color, ícono, etiqueta plural). **No** generalizar a un loop con `data-count`: rompería los contadores. En su lugar, mantener cada bloque `<li>` **verbatim** y solo cambiar el ORDEN, envolviéndolos en un `{% for %}` que selecciona por clave.

Reemplazar todo el `<ul class="nav nav-pills gap-1" id="tabs-tipo"> ... </ul>` (líneas ≈57-90) por:

```html
  <ul class="nav nav-pills gap-1" id="tabs-tipo">
    {% for tab in tabs_ordenadas %}
    {% if tab.clave == 'todos' %}
    <li class="nav-item">
      <button class="nav-link active tab-btn fw-semibold" data-tab="todos">
        Todos <span class="badge bg-white text-dark ms-1" id="cnt-todos">0</span>
      </button>
    </li>
    {% elif tab.clave == 'producto' %}
    <li class="nav-item">
      <button class="nav-link tab-btn fw-semibold" data-tab="producto" style="--tab-color:#198754">
        <span class="d-inline-block rounded-circle me-1"
              style="width:8px;height:8px;background:#198754"></span>
        Productos <span class="badge bg-success ms-1" id="cnt-producto">0</span>
      </button>
    </li>
    {% elif tab.clave == 'repuesto' %}
    <li class="nav-item">
      <button class="nav-link tab-btn fw-semibold" data-tab="repuesto">
        <span class="d-inline-block rounded-circle me-1"
              style="width:8px;height:8px;background:#fd7e14"></span>
        Repuestos <span class="badge ms-1" style="background:#fd7e14" id="cnt-repuesto">0</span>
      </button>
    </li>
    {% elif tab.clave == 'consumible' %}
    <li class="nav-item">
      <button class="nav-link tab-btn fw-semibold" data-tab="consumible">
        <span class="d-inline-block rounded-circle me-1"
              style="width:8px;height:8px;background:#0dcaf0"></span>
        Consumibles <span class="badge ms-1" style="background:#0dcaf0;color:#000" id="cnt-consumible">0</span>
      </button>
    </li>
    {% elif tab.clave == 'bajo_stock' %}
    <li class="nav-item">
      <button class="nav-link tab-btn fw-semibold text-danger" data-tab="bajo_stock">
        <i class="bi bi-exclamation-triangle-fill me-1"></i>
        Stock bajo <span class="badge bg-danger ms-1" id="cnt-bajo">0</span>
      </button>
    </li>
    {% endif %}
    {% endfor %}
  </ul>
  {% if puede_ordenar_tabs %}
  <button type="button" class="btn btn-sm btn-outline-secondary ms-2"
          data-bs-toggle="modal" data-bs-target="#modalOrdenTabs" title="Ordenar tabs">
    <i class="bi bi-arrow-down-up"></i>
  </button>
  {% endif %}
```

Este enfoque conserva el diseño y los IDs `cnt-*`, por lo que el JS de contadores sigue funcionando sin cambios. La tab `todos` mantiene su clase `active` (sigue siendo la activa por defecto, esté donde esté).

- [ ] **Step 4: Agregar el modal de orden (solo si hay permiso), al final del bloque de contenido**

Antes de `{% endblock %}` del contenido (o junto al resto de modales si los hubiera):

```html
{% if puede_ordenar_tabs %}
<div class="modal fade" id="modalOrdenTabs" tabindex="-1" aria-hidden="true">
  <div class="modal-dialog modal-dialog-centered">
    <div class="modal-content">
      <div class="modal-header">
        <h5 class="modal-title">Ordenar tabs del inventario</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Cerrar"></button>
      </div>
      <div class="modal-body">
        <p class="text-muted small">Arrastrá para reordenar. El orden aplica para todos.</p>
        <ul class="list-group" id="sortable-tabs">
          {% for tab in tabs_ordenadas %}
          <li class="list-group-item d-flex align-items-center" data-clave="{{ tab.clave }}"
              style="cursor:grab">
            <i class="bi bi-grip-vertical me-2 text-muted"></i>{{ tab.etiqueta }}
          </li>
          {% endfor %}
        </ul>
        <div id="orden-tabs-error" class="text-danger small mt-2 d-none"></div>
      </div>
      <div class="modal-footer">
        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancelar</button>
        <button type="button" class="btn btn-primary" id="btnGuardarOrdenTabs">Guardar</button>
      </div>
    </div>
  </div>
</div>
{% endif %}
```

- [ ] **Step 5: Hacer ordenables los `<th>` de la tabla desktop**

Para cada columna ordenable (Nombre, Código, Tipo, Categoría, Stock), reemplazar el `<th>Texto</th>` por un encabezado con enlace que setea los query params, preservando `q`. Ejemplo para Tipo (replicar el patrón cambiando `col` y la etiqueta):

```html
<th>
  <a href="?orden_col=tipo&orden_dir={% if orden_col == 'tipo' and orden_dir == 'asc' %}desc{% else %}asc{% endif %}{% if q %}&q={{ q|urlencode }}{% endif %}"
     class="text-decoration-none text-reset">
    Tipo
    {% if orden_col == 'tipo' %}<i class="bi bi-caret-{% if orden_dir == 'asc' %}up{% else %}down{% endif %}-fill small"></i>{% endif %}
  </a>
</th>
```

Claves `orden_col` por columna: `nombre`, `codigo`, `tipo`, `categoria`, `stock`. Las columnas "Ubicación" y "pendientes" quedan como `<th>` normales (no ordenables).

- [ ] **Step 6: Agregar el selector "Ordenar por" para móvil**

Encima de la lista de tarjetas (`d-md-none`), agregar:

```html
<div class="d-md-none mb-2">
  <select class="form-select form-select-sm" id="orden-movil">
    <option value="">Orden por defecto</option>
    <option value="nombre|asc"    {% if orden_col == 'nombre' and orden_dir == 'asc' %}selected{% endif %}>Nombre ↑</option>
    <option value="nombre|desc"   {% if orden_col == 'nombre' and orden_dir == 'desc' %}selected{% endif %}>Nombre ↓</option>
    <option value="tipo|asc"      {% if orden_col == 'tipo' and orden_dir == 'asc' %}selected{% endif %}>Tipo ↑</option>
    <option value="tipo|desc"     {% if orden_col == 'tipo' and orden_dir == 'desc' %}selected{% endif %}>Tipo ↓</option>
    <option value="categoria|asc" {% if orden_col == 'categoria' and orden_dir == 'asc' %}selected{% endif %}>Categoría ↑</option>
    <option value="stock|asc"     {% if orden_col == 'stock' and orden_dir == 'asc' %}selected{% endif %}>Stock ↑</option>
    <option value="stock|desc"    {% if orden_col == 'stock' and orden_dir == 'desc' %}selected{% endif %}>Stock ↓</option>
  </select>
</div>
```

- [ ] **Step 7: Agregar el JS (SortableJS + guardar orden + selector móvil)**

Asegurar `{% load static %}` arriba del template. En el bloque de scripts, agregar:

```html
<script src="{% static 'js/sortable.min.js' %}"></script>
<script>
(function () {
  // ── Selector de orden en móvil ──
  var selMovil = document.getElementById('orden-movil');
  if (selMovil) {
    selMovil.addEventListener('change', function () {
      var url = new URL(window.location.href);
      if (!this.value) {
        url.searchParams.delete('orden_col');
        url.searchParams.delete('orden_dir');
      } else {
        var parts = this.value.split('|');
        url.searchParams.set('orden_col', parts[0]);
        url.searchParams.set('orden_dir', parts[1]);
      }
      window.location.href = url.toString();
    });
  }

  // ── Drag & drop de tabs (solo si el modal existe = con permiso) ──
  var lista = document.getElementById('sortable-tabs');
  if (lista && window.Sortable) {
    Sortable.create(lista, { animation: 150, handle: '.bi-grip-vertical' });
    var btn = document.getElementById('btnGuardarOrdenTabs');
    var errBox = document.getElementById('orden-tabs-error');
    btn.addEventListener('click', function () {
      var orden = Array.prototype.map.call(
        lista.querySelectorAll('li'), function (li) { return li.dataset.clave; }
      );
      fetch("{% url 'inventario_tabs_orden' %}", {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': "{{ csrf_token }}",
        },
        body: JSON.stringify({ orden: orden }),
      })
      .then(function (r) {
        if (r.ok) { window.location.reload(); return; }
        return r.text().then(function (t) {
          errBox.textContent = t || 'No se pudo guardar el orden.';
          errBox.classList.remove('d-none');
        });
      })
      .catch(function () {
        errBox.textContent = 'Error de red al guardar.';
        errBox.classList.remove('d-none');
      });
    });
  }
})();
</script>
```

- [ ] **Step 8: Escribir tests de render**

Agregar al final de `apps/core/tests.py`:

```python
@override_settings(ALLOWED_HOSTS=['testserver', 'localhost'])
class InventarioListaRenderTabsTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import Permission
        cache.clear()
        self.perm_ver = Permission.objects.get(codename='ver_inventario')
        self.perm_ord = Permission.objects.get(codename='ordenar_tabs_inventario')

    def test_boton_ordenar_oculto_sin_permiso(self):
        u = User.objects.create_user('v1', password='x')
        u.user_permissions.add(self.perm_ver)
        self.client.force_login(u)
        resp = self.client.get(reverse('inventario_lista'))
        self.assertNotContains(resp, 'modalOrdenTabs')

    def test_boton_ordenar_visible_con_permiso(self):
        u = User.objects.create_user('v2', password='x')
        u.user_permissions.add(self.perm_ver, self.perm_ord)
        self.client.force_login(u)
        resp = self.client.get(reverse('inventario_lista'))
        self.assertContains(resp, 'modalOrdenTabs')
        self.assertContains(resp, 'sortable-tabs')

    def test_tabs_se_renderizan_en_orden_guardado(self):
        from apps.core.models import InventarioConfig
        InventarioConfig.objects.create(
            pk=1, orden_tabs=['bajo_stock', 'todos', 'producto', 'repuesto', 'consumible'])
        u = User.objects.create_user('v3', password='x')
        u.user_permissions.add(self.perm_ver)
        self.client.force_login(u)
        resp = self.client.get(reverse('inventario_lista'))
        html = resp.content.decode()
        # 'Bajo stock' aparece antes que 'Producto' en el HTML
        self.assertLess(html.index('data-tab="bajo_stock"'), html.index('data-tab="producto"'))
```

- [ ] **Step 9: Correr los tests de render**

`[TEST] apps.core.tests.InventarioListaRenderTabsTests`
Expected: PASS.

- [ ] **Step 10: Correr TODA la suite (regresión)**

`[TEST] apps.core.tests`
Expected: PASS (todos los tests, incluidos los previos del proyecto).

- [ ] **Step 11: Verificación visual en el navegador (preview)**

Levantar la app y comprobar manualmente: (1) las tabs se ven y filtran como antes; (2) con permiso aparece el botón de orden, el modal arrastra y al guardar recarga con el orden nuevo; (3) clic en encabezados ordena la tabla y muestra el indicador ▲/▼; (4) el selector móvil ordena. Tomar screenshot como evidencia.

- [ ] **Step 12: Commit**

```bash
git add templates/inventario/lista.html static/js/sortable.min.js apps/core/tests.py
git commit -m "feat: UI de orden de tabs (drag) y orden por columna en inventario"
```

---

## Cierre

- [ ] **Verificación final:** correr `[TEST] apps.core.tests` una última vez → todo PASS.
- [ ] **No hacer push** sin autorización del usuario (preferencia del proyecto: pedir antes de commit/push — los commits aquí ya fueron autorizados como parte del flujo; confirmar el push).

## Notas de despliegue

- La feature agrega `static/js/sortable.min.js`: el `collectstatic` del entrypoint lo recoge automáticamente al desplegar.
- La migración `0017` corre sola en el arranque (`migrate` del entrypoint).
- `setup_groups` corre en el arranque y otorga el permiso nuevo a Administrador/Supervisor.
