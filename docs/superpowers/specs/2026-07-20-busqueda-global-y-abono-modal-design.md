# Búsqueda global (clientes + facturas) y Registrar abono en modal

**Fecha:** 2026-07-20
**Estado:** Diseño aprobado (mockups validados con el usuario)

## Problema

Registrar un pago/abono o encontrar la cuenta de un cliente cuesta demasiados
clics. Para un abono de cliente hoy el camino es: menú → *Facturas* (desplegar)
→ *Clientes* → buscar → abrir cliente → pestaña *Facturas* → botón *Registrar
abono* → formulario de página completa (~6 pasos). El usuario arranca **igual de
seguido por cliente que por factura**, así que la solución debe servir a ambos
puntos de partida desde cualquier pantalla.

## Objetivo

Reducir a 1–2 gestos el acceso a: (a) encontrar un cliente o una factura, y
(b) registrar un abono de cliente. Sin recargar página y funcionando igual en
escritorio (mostrador) y móvil (PWA).

## Alcance

**Incluye:**
- Búsqueda global combinada de **clientes + facturas**, con entrada siempre
  visible en la barra superior y panel de resultados centrado (look "command
  palette").
- Registrar abono de cliente en **modal** (reemplaza la página completa como
  camino principal; la página se mantiene como *fallback* sin JS).

**No incluye (YAGNI):**
- Búsqueda de ítems de inventario u otras entidades (extensible después).
- Búsqueda difusa/fonética; se usa `icontains` simple.
- Cambios en la lógica de reparto de pagos (ya existe y está testeada).

## Diseño validado (UI)

- **Entrada:** campo de búsqueda siempre visible en la barra superior
  (`base.html`), solo para usuarios con permiso `ver_facturas`. Atajos:
  `/` y `Ctrl/Cmd+K` la enfocan/abren; `Esc` cierra. En móvil es un ícono 🔍
  que abre el panel a pantalla completa.
- **Panel:** overlay centrado con el input arriba y resultados en dos secciones:
  - **Clientes** (máx. 6): nombre, cuánto **debe**, y acción rápida **"＋ Abono"**.
  - **Facturas** (máx. 6): número, cliente y **estado** (Pendiente/Vencida/…).
  - Navegación con `↑↓`, `Enter` abre. Al elegir un cliente → su ficha; una
    factura → su detalle. "＋ Abono" abre el modal de abono sin navegar.
- **Modal de abono:** cabecera con cliente + *Debe* / *Saldo a favor*; campos
  Fecha, Método de pago, **Monto** (destacado), Referencia, Comprobante, Notas;
  y un **reparto automático** (factura más vieja primero) que se recalcula al
  tipear el monto, con opción **✎ Editar** para asignar montos a mano (lo que
  sobra queda como saldo a favor). Al registrar: se cierra y la pantalla de
  atrás se actualiza sola.

## Componentes

### 1. Endpoint de búsqueda combinada

- **Ruta:** `GET /api/buscar/?q=<término>` → `busqueda.buscar_global`.
- **Decoradores:** `@login_required`, `@permission_required('core.ver_facturas',
  raise_exception=True)`, `@facturas_enabled`.
- **Respuesta JSON:**
  ```json
  {
    "clientes": [{"id": 1, "nombre": "Renato Díaz", "saldo": "1240.00", "url": "/clientes/1/salidas/", "puede_abonar": true}],
    "facturas": [{"id": 9, "numero": "9543", "cliente": "Inversiones Zaga", "tipo": "factura", "estado": "pendiente", "saldo": "3500.00", "url": "/facturas/documentos/9/"}]
  }
  ```
- **Reglas:** `q` con < 2 caracteres → listas vacías. Clientes por `nombre__icontains`;
  facturas por `numero_documento__icontains` **o** `cliente__nombre__icontains`,
  excluyendo anuladas. Límite 6 por sección, ordenadas por relevancia simple
  (coincidencia de prefijo primero, luego alfabético/fecha desc).
- **Rendimiento:** usar agregación anotada para el saldo (patrón
  `DocumentoFactura.anotar_pagado` / propiedades ya optimizadas) para evitar
  N+1. `select_related('cliente')` en facturas. Verificado con test de conteo
  de queries (estilo `test_perf_queries.py`).
- **`puede_abonar`:** refleja `registrar_pago_factura` del usuario; controla si
  se muestra "＋ Abono".

### 2. Búsqueda en el front

- Input en la barra superior de `base.html` + overlay centrado. Lógica en
  `static/js/buscador.js` (no inline en la plantilla).
- Debounce ~200 ms, mínimo 2 caracteres. Resultados renderizados construyendo
  nodos DOM con `textContent` (nunca `innerHTML` con datos del servidor) para
  evitar XSS con nombres de cliente.
- Teclado: `/` y `Ctrl/Cmd+K` abren; `↑↓` mueven el resaltado; `Enter` abre el
  resaltado; `Esc` cierra. Clic también funciona.
- "＋ Abono" en una fila de cliente dispara la apertura del modal de abono
  (componente 3) con ese `cliente_id`.

### 3. Registrar abono en modal

- **Partial reutilizable:** extraer el cuerpo del formulario de
  `templates/facturas/form_abono.html` a `templates/facturas/_form_abono.html`
  (campos + tabla de reparto + hooks JS). La página completa y el modal lo
  incluyen ambos → una sola fuente de verdad.
- **Vistas (`facturas_cliente.py`):**
  - `cliente_abono_nuevo` y `cliente_abono_editar`: si la petición es AJAX
    (`X-Requested-With: XMLHttpRequest`) o `?fragment=1`, el **GET** devuelve
    solo el partial; el **POST** devuelve JSON `{"ok": true, "saldo": "…"}` en
    éxito o `{"ok": false, "errors": {…}}` (400) en error (reusar
    `_form_errors_json`). Sin AJAX, se mantiene el comportamiento actual
    (render/redirect de página completa) como *fallback*.
  - La lógica de reparto (`_leer_reparto` + `payment_service.registrar_abono`/
    `editar_abono`) **no cambia**.
- **Modal en el front:** contenedor de modal compartido (en `base.html` o
  incluido en las páginas de facturas) que hace `fetch` del partial, lo inyecta,
  y envía el formulario por `fetch`. Lógica en `static/js/abono-modal.js`.
- **Al enviar con éxito:** cerrar modal, mostrar toast "Abono registrado" y:
  - si estamos en la ficha del cliente, refrescar el fragmento
    `cliente_facturas_fragment` (ya existe) para actualizar saldos/lista;
  - si se abrió desde el buscador, actualizar el saldo mostrado de esa fila.
- **Disparadores:** (a) botón *Registrar abono* de `_tab_cliente.html` abre el
  modal en vez de navegar; (b) "＋ Abono" del buscador.

## Flujo de datos

```
Barra superior (input)
   └─(debounce)→ GET /api/buscar/?q=…  → JSON  → render overlay
        ├─ clic cliente/factura → navega a su URL
        └─ "＋ Abono" → GET fragment abono → modal
                              └─ submit → POST (AJAX) → JSON
                                    ├─ ok  → cerrar + toast + refrescar fragmento
                                    └─ err → mostrar errores inline (modal abierto)
```

## Manejo de errores

- Búsqueda: `q` corto → vacío; sin permiso → 403 JSON; módulo apagado → 404;
  error inesperado → listas vacías (no romper la barra).
- Modal: errores de formulario como JSON 400 renderizados inline; error de red
  → el modal queda abierto con mensaje y datos intactos.
- Progresivo: sin JS, el buscador degrada a un submit normal a una página de
  resultados simple, y el abono usa el formulario de página completa existente.

## Seguridad / permisos

- Endpoint de búsqueda: `ver_facturas`. "＋ Abono" y POST de abono:
  `registrar_pago_factura`.
- Salida escapada: JSON + inserción por `textContent`/nodos DOM; nunca
  interpolar nombres en `innerHTML`.

## Pruebas

- **Búsqueda:** encuentra clientes por nombre y facturas por número y por nombre
  de cliente; excluye anuladas; respeta límite; `q` corto → vacío; saldo
  correcto; **403 sin `ver_facturas`**; **404 con módulo apagado**; conteo de
  queries acotado (sin N+1).
- **Abono modal:** GET fragment devuelve el formulario; POST AJAX crea abono +
  reparto y devuelve JSON `ok`; errores de formulario → JSON 400; **el
  *fallback* de página completa sigue verde** (tests existentes intactos);
  denegado sin `registrar_pago_factura`.

## Archivos afectados

- `templates/base.html` — input de búsqueda, overlay y contenedor de modal.
- `static/js/buscador.js` (nuevo), `static/js/abono-modal.js` (nuevo).
- `apps/core/views/busqueda.py` (nuevo) — `buscar_global`.
- `apps/core/urls.py` — ruta `api/buscar/`.
- `apps/core/views/facturas_cliente.py` — soporte fragment/JSON en abono
  nuevo/editar.
- `templates/facturas/_form_abono.html` (nuevo, extraído) y
  `templates/facturas/form_abono.html` (incluye el partial).
- `templates/facturas/_tab_cliente.html` — botón abre modal.
- `apps/core/tests_facturas/` — tests de búsqueda y abono modal.

## Notas de arquitectura

- Vista de búsqueda pequeña y enfocada (una responsabilidad); JS en archivos
  dedicados para no engordar `base.html`.
- El partial `_form_abono.html` unifica página y modal, evitando duplicar el
  formulario de reparto.
