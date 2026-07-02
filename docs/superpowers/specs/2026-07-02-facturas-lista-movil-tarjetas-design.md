# Lista de facturas: vista de tarjetas en móvil

**Fecha:** 2026-07-02
**Estado:** Aprobado (diseño)

## Problema

La lista de facturas/envíos (`templates/facturas/lista.html`) muestra una tabla de **15
columnas** dentro de un `table-responsive`. En el celular eso obliga a **scroll
horizontal**, incómodo para el uso principal (que es móvil). Otras pantallas del proyecto
(inventario, métodos de pago, categorías) ya resuelven esto con **tabla en desktop +
tarjetas en móvil**; la lista de facturas es la excepción.

## Decisión

Aplicar el mismo patrón responsive: envolver la tabla actual en un bloque solo-desktop y
agregar un bloque solo-móvil con una **tarjeta por documento**. **Solo cambia la
plantilla** `lista.html` — sin cambios de vista, modelo ni contexto (se sigue usando
`documentos`).

## Alcance

Solo la **tabla** de la lista. NO cambian: el resumen superior
(Facturado/Cobrado/Pendiente/Vencido), la barra de filtros, las pestañas de estado, ni la
tabla de desktop.

## Diseño

### Estructura responsive
- La `<table>` actual (líneas ~138-212) se envuelve en `<div class="d-none d-md-block">`.
- Antes de ella, un `<div class="d-md-none">` con las tarjetas.

### Tarjeta (una por `doc` en `documentos`)
Reutiliza el comportamiento existente: la tarjeta es "clickable" hacia la ficha usando la
misma clase y atributo que la fila (`class="fac-row"` + `data-href="{% url
'factura_detalle' doc.pk %}?next={{ return_url|urlencode }}"`), y los botones de acción
llevan `data-norow="1"` para no disparar el tap de la tarjeta. El botón de pago reutiliza
`btn-pago` con `data-url`/`data-saldo`/`data-info` (mismo modal `_modal_pago.html`).

Contenido:
- **Cabecera:** badge de tipo (Factura/Envío) a la izquierda + badge de estado
  (`_badges.html`) a la derecha.
- **Cliente** en negrita + número de documento (`doc.numero_documento`, `–` si vacío).
- Badge de **categoría** (`_producto.html`).
- **Montos** en fila compacta: Total (`doc.monto_total|moneda`, negrita), Saldo
  (`doc.saldo_pendiente|moneda`, rojo si `> 0`), Pagado (`doc.monto_pagado|moneda`, verde).
- **Fechas:** documento (`fecha_documento`) y vencimiento (`fecha_vencimiento`), `–` si
  vacías.
- **Acciones** (`data-norow="1"`): Ver detalle; PDF (solo si `doc.archivo_pdf`); Registrar
  pago (solo si `perms.core.registrar_pago_factura` y estado no `anulada`/`pagada`) — mismos
  criterios que la tabla.
- **Estado vacío** propio: "Sin documentos para los filtros seleccionados."

### Estilo
Tarjetas Bootstrap (`card mb-2`), consistentes con las de inventario/métodos de pago
(borde suave, cuerpo compacto). El resaltado de saldo pendiente en rojo/negrita se
mantiene.

## Reutilización
- Includes: `facturas/_badges.html` (estado), `facturas/_producto.html` (categoría).
- Filtro `|moneda` (ya cargado en la plantilla).
- JS existente de `fac-row` (navegación por `data-href`) y `btn-pago` (abre el modal). Las
  tarjetas usan las mismas clases/atributos, así que no se agrega JS nuevo.

## Pruebas
- Al ser solo plantilla/CSS de layout, la verificación principal es **visual en el
  navegador** (móvil ~375px: se ven tarjetas, sin scroll horizontal; desktop: se ve la
  tabla).
- Test liviano: la vista `facturas_lista` responde 200 y el HTML contiene el contenedor de
  tarjetas móvil (`d-md-none`) y sigue conteniendo la tabla (`table`), para no romper
  ninguno de los dos modos. (No se testea el layout visual.)

## Fuera de alcance (YAGNI)
- Rediseñar filtros, resumen o la ficha de factura (otra iteración si hace falta).
- Paginación/scroll infinito.
- Cambios en columnas de la tabla de desktop.
