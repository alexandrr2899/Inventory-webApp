# Inventario: reordenar tabs + ordenar tabla por columna

**Fecha:** 2026-06-18
**Estado:** Aprobado (diseño)

Dos features sobre la misma vista `inventario_lista` (`templates/inventario/lista.html`):

- **Feature A — Reordenar las tabs del inventario.** Orden global, todas las tabs
  reordenables libremente vía drag-and-drop, persistente, editable solo con permiso.
- **Feature B — Ordenar la tabla por columna.** Clic en el encabezado de una columna
  ordena las filas asc/desc (server-side).

Son independientes entre sí y conviven sin chocar.

---

## Estado actual (contexto)

- `inventario_lista` ([apps/core/views/inventario.py](../../../apps/core/views/inventario.py))
  devuelve una lista plana ordenada por `orden, nombre`, paginada de a 100, con
  búsqueda server-side por `q` (nombre/código).
- Las tabs (_Todos · Producto · Repuesto · Consumible · Bajo stock_) están
  **escritas a mano** en `templates/inventario/lista.html` y filtran la página
  cargada del lado del cliente (JS, por `data-tipo`). Los contadores por tab los
  calcula el JS.
- La vista móvil es una lista de tarjetas (`d-md-none`), sin encabezados de tabla.

---

## Feature A — Reordenar tabs

### A.1 Modelo de datos

Modelo singleton nuevo en `apps/core/models.py`:

```python
class InventarioConfig(models.Model):
    orden_tabs = models.JSONField(default=list)  # ej: ["bajo_stock","producto","todos","consumible","repuesto"]

    class Meta:
        verbose_name = 'Configuración de inventario'
        verbose_name_plural = 'Configuración de inventario'
        permissions = [
            ('ordenar_tabs_inventario', 'Puede ordenar las tabs del inventario'),
        ]
```

- Una sola fila. Se obtiene con `InventarioConfig.objects.get_or_create(pk=1)` (creación
  perezosa; sin data-migration).
- `orden_tabs` vacío ⇒ se usa el orden canónico por defecto.

### A.2 Definición canónica de las tabs (en código)

Constante en `apps/core/views/inventario.py` (mueve a datos lo que hoy está en la plantilla):

```python
TABS_INVENTARIO = [
    {'clave': 'todos',      'etiqueta': 'Todos'},
    {'clave': 'producto',   'etiqueta': 'Producto',   'color': '#198754'},
    {'clave': 'repuesto',   'etiqueta': 'Repuesto'},
    {'clave': 'consumible', 'etiqueta': 'Consumible'},
    {'clave': 'bajo_stock', 'etiqueta': 'Bajo stock', 'danger': True},
]
TABS_CLAVES = {t['clave'] for t in TABS_INVENTARIO}
```

Helper `get_orden_tabs()`:
- Lee `orden_tabs` del singleton.
- **Reconcilia** con las claves canónicas: respeta el orden guardado para claves
  conocidas, agrega al final cualquier tab canónica ausente, descarta claves
  desconocidas. Siempre devuelve las 5 tabs (metadata completa) en un orden válido.

### A.3 Aplicar el orden (vista + plantilla)

- `inventario_lista` agrega al contexto:
  - `tabs_ordenadas`: lista de dicts (metadata) en el orden guardado.
  - `puede_ordenar_tabs`: `request.user.has_perm('core.ordenar_tabs_inventario')`.
- `templates/inventario/lista.html`: deja de tener las tabs hardcodeadas; itera
  `tabs_ordenadas` y renderiza cada botón a partir del dict (clave → `data-tab`,
  etiqueta, color/danger). El JS de conteo de badges no cambia.
- **Tab activa por defecto:** sigue siendo `todos` (por significado, no por posición).
  El JS mantiene `tabActual = 'todos'` y aplica la clase `active` al botón cuyo
  `data-tab === 'todos'`, esté donde esté.

### A.4 Guardar el orden (endpoint)

- Ruta nueva en `apps/core/urls.py`: `path('inventario/tabs/orden/', views.inventario_tabs_orden, name='inventario_tabs_orden')`.
- Vista `inventario_tabs_orden`, `@require_POST` + `@permission_required('core.ordenar_tabs_inventario', raise_exception=True)`.
- Recibe la lista de claves nuevas (fetch con CSRF; JSON body o `orden[]`).
- **Validación:** la lista debe ser una **permutación exacta** de `TABS_CLAVES`
  (sin faltantes, duplicados ni claves desconocidas). Si no, `HttpResponseBadRequest` (400).
- Si OK: guarda en el singleton y responde `JsonResponse({'ok': True})`.

### A.5 Interacción (frontend)

- Si `puede_ordenar_tabs`: botón "Ordenar" junto a la barra de tabs que abre un
  **modal de Bootstrap** con las tabs en lista vertical.
- **SortableJS** servido local desde `static/` (whitenoise, sin CDN) hace la lista
  arrastrable. Botón *Guardar* → `fetch` POST al endpoint con CSRF → al confirmar
  (respuesta `{ok:true}`), se hace `location.reload()` para repintar la barra de tabs
  con el orden nuevo. Ante error, se muestra un mensaje y no se recarga.
- Vertical + modal: funciona bien en móvil (las tabs reales scrollean horizontal,
  donde arrastrar molesta).
- **Verificación al implementar:** confirmar que Bootstrap JS (para el modal) ya está
  cargado en `templates/base.html`; si no, usar un modal mínimo propio.

### A.6 Permisos y seeds

`apps/core/management/commands/setup_groups.py` otorga `ordenar_tabs_inventario` a
**Administrador** y **Supervisor**. Quien no lo tenga ve el orden pero no el botón.

---

## Feature B — Ordenar tabla por columna

### B.1 Enfoque: server-side

Query params `?orden_col=<col>&orden_dir=asc|desc`. Server-side por consistencia con
la paginación (100/pág) y con la búsqueda `q` (ya server-side).

### B.2 Columnas ordenables → campo ORM

| Columna   | Campo de orden            |
|-----------|---------------------------|
| Nombre    | `nombre`                  |
| Código    | `codigo`                  |
| Tipo      | `tipo`                    |
| Categoría | `categoria__nombre`       |
| Stock     | `stock_calc` (anotación existente) |

- "Ubicación principal" y "pendientes" se calculan en Python (no son campos de la
  query) ⇒ **no** ordenables en v1.
- Mapa explícito `ORDEN_COLS = {'nombre': 'nombre', 'codigo': 'codigo', 'tipo': 'tipo',
  'categoria': 'categoria__nombre', 'stock': 'stock_calc'}`. Una `orden_col` fuera del
  mapa se ignora (cae al default).
- **Default** (sin params válidos): orden manual actual `('orden', 'nombre')`.
- Con params: `qs.order_by(<campo>)` (asc) o `-<campo>` (desc).

### B.3 UI

- **Desktop (tabla):** los `<th>` ordenables se vuelven enlaces/clickeables que
  setean los query params; indicador ▲/▼ en la columna activa. El clic recarga.
  Alterna asc → desc en la misma columna.
- **Móvil (tarjetas):** selector compacto "Ordenar por" con las mismas opciones
  (mismos query params), para poder ordenar en planta.
- Se combina con `q` (server-side) y con el filtro de tab (client-side; se re-aplica
  tras cargar, preservando el orden de filas).

---

## Tests

Feature A:
- `get_orden_tabs()` devuelve el orden canónico cuando no hay config.
- `get_orden_tabs()` reconcilia: ignora claves desconocidas guardadas y agrega tabs
  canónicas ausentes al final.
- `inventario_tabs_orden`: con permiso guarda una permutación válida (200, persiste);
  sin permiso → 403; permutación inválida (faltante/duplicada/clave rara) → 400.
- `inventario_lista` renderiza las tabs en el orden guardado y muestra/oculta el botón
  "Ordenar" según permiso.

Feature B:
- `inventario_lista?orden_col=tipo&orden_dir=desc` devuelve los ítems en ese orden.
- `orden_col` inválida o `orden_dir` inválida ⇒ cae al default sin romper.
- El orden se combina correctamente con `q`.

---

## Archivos afectados

- `apps/core/models.py` — modelo `InventarioConfig` + permiso. (+ migración nueva)
- `apps/core/views/inventario.py` — `TABS_INVENTARIO`, `get_orden_tabs()`, `ORDEN_COLS`,
  update `inventario_lista`, nueva vista `inventario_tabs_orden`.
- `apps/core/urls.py` — ruta `inventario_tabs_orden`.
- `templates/inventario/lista.html` — tabs data-driven + modal de orden + headers
  ordenables + selector móvil + JS (SortableJS, fetch).
- `static/` — `sortable.min.js` (servido local).
- `apps/core/management/commands/setup_groups.py` — otorgar `ordenar_tabs_inventario`.
- `apps/core/tests.py` — tests de ambas features.

## Fuera de alcance (v1)

- Tabs por categoría dinámica (hoy las tabs son el set fijo de tipos + Todos/Bajo stock).
- Ordenar por "Ubicación principal" o "pendientes" (derivados en Python).
- Orden de tabs por usuario (se eligió global + permiso).
