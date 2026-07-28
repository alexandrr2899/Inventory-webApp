# Movimientos por método de pago

**Fecha:** 2026-07-28
**Estado:** Aprobado (diseño)

## Problema

Ya existen métodos de pago (`MetodoPago`) y abonos de clientes (`Pago`) que se
registran contra un método. No hay forma de ver, por método, qué abonos han
entrado. El usuario quiere ver los movimientos de cada método de pago.

## Alcance

- **Movimientos = abonos recibidos** (`Pago`) con ese método. El modelo `Pago`
  solo representa entradas (dinero que entra del cliente); no hay egresos, así
  que no se modela ningún tipo de salida (YAGNI).
- Una **página de detalle por método** accesible desde la lista de métodos.
- Fuera de alcance: reporte con filtro multi-método, export CSV, egresos.

## Diseño

### Ruta y acceso

- Nueva URL: `facturas/metodos-pago/<int:pk>/movimientos/`, nombre
  `metodo_pago_movimientos`.
- Se entra desde `templates/metodos_pago/lista.html` haciendo clic en el nombre
  del método (tarjeta móvil y fila de escritorio) más un botón/ícono explícito
  "Ver movimientos" (`bi-list-ul` o similar).
- Permiso: se reutiliza `gestionar_metodos_pago` (el mismo que ya protege el
  módulo de métodos), sin tocar roles.

### Vista (backend)

Archivo: `apps/core/views/metodos_pago.py`, función `metodo_pago_movimientos`.

- Filtro de fechas con el patrón de `cliente_estado_cuenta`
  (`_parse_fecha` / `strptime '%Y-%m-%d'`), parámetros `desde` / `hasta` en el
  querystring.
- **Rango por defecto:** `hasta = hoy`, `desde = primer día del mes actual`
  (`hoy.replace(day=1)`).
- Query base:
  `Pago.objects.filter(metodo_pago=metodo, fecha_pago__range=[desde, hasta])`
  con `select_related('cliente')` y
  `prefetch_related('aplicaciones__documento')` para evitar N+1.
- **Total recibido** en el rango: `aggregate(Sum('monto'))` (Coalesce a 0).
- Paginación con `Paginator` (como otras listas), p. ej. 50 por página; el
  total del rango se calcula sobre el queryset completo, no sobre la página.

### Plantilla

Nueva plantilla `templates/metodos_pago/movimientos.html`:

- Cabecera: nombre del método + tipo + total recibido del rango.
- Formulario GET con `desde` / `hasta` (inputs `type=date`) y botón filtrar.
- Lista responsiva (tabla en escritorio, tarjetas en móvil), una fila por
  abono:
  - **Fecha** (`fecha_pago`)
  - **Cliente** → enlace a `cliente_estado_cuenta`
  - **Monto**
  - **Referencia**
  - **Facturas aplicadas**: enlaces a los documentos de cada `AplicacionPago`
    (o "—" si el abono aún no se aplicó a ninguna factura)
  - **Comprobante**: ícono para abrir el archivo si `pago.comprobante` existe
- Estado vacío cuando no hay movimientos en el rango.

### Pruebas

Nuevo archivo en `apps/core/tests_facturas/` (estilo de los tests existentes):

- La vista exige el permiso `gestionar_metodos_pago` (403 sin él).
- Solo muestra abonos del método indicado (no los de otros métodos).
- Filtra correctamente por rango de fechas (`desde`/`hasta`).
- El total recibido corresponde a la suma de los abonos del rango.
- Rango por defecto = mes actual cuando no se pasan parámetros.

## Notas

- No se añaden migraciones ni cambios de modelo.
- No se añade export CSV en esta iteración.
