# Categorías de producto configurables + filtro en la lista

**Fecha:** 2026-06-30
**Estado:** Aprobado (diseño)

## Problema

Las categorías de producto de facturas/envíos (`camiseta`, `lisa`, `otro`) están fijas en
código (`PRODUCTO_CHOICES`). El negocio necesita:

1. **Agregar categorías nuevas** sin tocar código (ej. otra línea de producto).
2. **Filtrar** la lista de facturas/envíos por categoría desde la UI. El backend ya filtra
   por `producto`, pero **no hay control en la barra de filtros** que lo exponga.

Además, `producto` no es solo una etiqueta: **`TarifaCliente` fija el precio por libra por
categoría** (restricción única por `cliente`+`producto` activa), y la clasificación
automática desde el nombre del archivo (`filename_extractor`) asigna `camiseta`/`lisa`.

## Decisiones tomadas (brainstorming)

- **Categorías configurables desde la app** (modelo con CRUD), como `MetodoPago`.
- **Auto-clasificación por palabra clave + una categoría por defecto**: si el nombre del
  archivo contiene la palabra clave de alguna categoría, se asigna esa; si ninguna
  coincide, la categoría marcada por defecto.
- **`producto` pasa de choices fijos a FK** a la nueva categoría, en `DocumentoFactura` y
  `TarifaCliente`.
- **Borrado**: `PROTECT` + bandera `activa` (no se borran si están en uso; se desactivan).
- El fix previo "producto del envío por nombre" (camiseta/si-no-lisa) ya está en `master`;
  esta feature **generaliza** su clasificador sin cambiar el comportamiento de las 3
  categorías sembradas.

## Modelo de datos

### `CategoriaProducto` (nuevo)

| Campo               | Tipo                          | Notas                                            |
|---------------------|-------------------------------|--------------------------------------------------|
| `nombre`            | `CharField`                   | Ej. "Camiseta", "Lisa", "Otro".                  |
| `palabra_clave`     | `CharField(blank)`            | Para auto-clasificar por el nombre del archivo (case-insensitive). Vacía = no participa en auto-clasificación. |
| `es_predeterminada` | `BooleanField(default False)` | La categoría asignada cuando ninguna palabra clave coincide. |
| `activa`            | `BooleanField(default True)`  | Las inactivas no aparecen al clasificar/elegir; conservan historial. |
| `orden`             | `PositiveIntegerField`        | Orden de despliegue.                             |

`Meta.ordering = ['orden', 'nombre']`. `Meta.permissions =
[('gestionar_categorias_producto', 'Puede gestionar categorías de producto')]`.

**Invariante "exactamente una predeterminada":** al guardar una categoría con
`es_predeterminada=True`, se desactiva el flag en las demás (misma lógica que
`TarifaCliente` usa para "activa única"). Debe existir siempre una predeterminada; la
migración de siembra marca "Lisa" como predeterminada.

Helper de clase `predeterminada()` → la categoría con `es_predeterminada=True` (o `None`).

### Cambios en modelos existentes

**`DocumentoFactura`**
- Se agrega `categoria = ForeignKey(CategoriaProducto, PROTECT, null=True, blank=True,
  related_name='documentos')`.
- Se **retira** el campo `producto` (CharField) tras migrar los datos.

**`TarifaCliente`**
- Se agrega `categoria = ForeignKey(CategoriaProducto, PROTECT, related_name='tarifas')`.
- Se **retira** `producto` (CharField). La restricción única pasa a
  `(cliente, categoria)` con `condition=Q(activa=True)`.
- `TarifaCliente.activa_para(cliente, categoria)` recibe la categoría (FK) en vez del string.

**`PRODUCTO_CHOICES`** se retira del código una vez migrado.

## Auto-clasificación (filename_extractor)

`filename_extractor._producto_envio(base)` se reescribe para devolver una
`CategoriaProducto` (o su id) en vez del string:

1. Recorre `CategoriaProducto.objects.filter(activa=True)` (por `orden`).
2. La primera cuya `palabra_clave` (no vacía) aparezca en `base` (case-insensitive) gana.
3. Si ninguna coincide, devuelve `CategoriaProducto.predeterminada()`.

`extraer_de_nombre` deja de poner un string `producto`; en su lugar, para envíos, se
asigna la categoría vía `invoice_service` al crear/previsualizar el documento (el extractor
puede devolver `categoria_id` para mantener la separación de capas). El comportamiento con
las 3 categorías sembradas es idéntico al actual.

## Migración de datos (no destructiva)

1. Crear `CategoriaProducto` model (migración de esquema).
2. Sembrar: **Camiseta** (`palabra_clave='camiseta'`), **Lisa** (`palabra_clave='lisa'`,
   `es_predeterminada=True`), **Otro** (`palabra_clave=''`).
3. Agregar los FK `categoria` (nullable) a `DocumentoFactura` y `TarifaCliente`.
4. Data-migrate: por cada fila, mapear el string `producto` → la `CategoriaProducto` de
   igual nombre; los vacíos quedan sin categoría (documentos) o se asignan a "Otro"
   (tarifas, que siempre tenían producto).
5. Actualizar la restricción única de `TarifaCliente` a `(cliente, categoria)`.
6. Retirar los CharField `producto` y `PRODUCTO_CHOICES`.

Las migraciones deben aplicarse juntas y en orden (la de datos antes de retirar el
CharField).

## Vistas / UI

1. **Filtro en la lista** (`facturas_lista` + `templates/facturas/lista.html`): agregar el
   `<select name="producto">` (o `categoria`) en la barra de filtros, poblado desde
   `CategoriaProducto.objects.filter(activa=True)`. La vista filtra por `categoria_id`. Se
   conserva el resto de filtros.
2. **CRUD de categorías** (`Facturas → Categorías de producto`): lista + form, patrón de
   `metodos_pago`/`maquinas`, con permiso `gestionar_categorias_producto`. El form maneja
   `nombre`, `palabra_clave`, `es_predeterminada`, `activa`, `orden`.
3. **Formularios de documento y tarifa** (`DocumentoEditarForm`, `TarifaClienteForm`): el
   campo pasa a `ModelChoiceField(queryset=CategoriaProducto.objects.filter(activa=True))`.
4. **Display** (`_producto.html`) usa `doc.categoria.nombre`. El resaltado de fila
   hardcodeado a `producto == 'camiseta'` se generaliza (o se retira) para no depender de
   un string fijo.

## Permisos

- Nuevo `gestionar_categorias_producto` para el CRUD.
- El filtro y la edición reusan los permisos de facturas existentes.

## Pruebas (alcance)

- **Modelo:** invariante de predeterminada única; `predeterminada()`; `activa_para` por FK.
- **Auto-clasificación:** palabra clave coincide → esa categoría; ninguna → predeterminada;
  categoría nueva con su palabra clave se auto-aplica; inactivas se ignoran.
- **Migración:** los strings `camiseta/lisa/otro` mapean a sus categorías sin pérdida;
  `monto`/tarifas intactas.
- **Filtro:** la lista filtra por categoría; el select se puebla desde categorías activas.
- **CRUD:** crear/editar/activar categoría; permiso denegado → 403.
- **Tarifas:** la restricción única por `(cliente, categoria)` se respeta; el cobro sigue
  usando la categoría.

## Fuera de alcance (YAGNI)

- Múltiples palabras clave por categoría (una sola por ahora).
- Jerarquía/subcategorías de producto.
- Reasignar masivamente documentos entre categorías desde la UI.
