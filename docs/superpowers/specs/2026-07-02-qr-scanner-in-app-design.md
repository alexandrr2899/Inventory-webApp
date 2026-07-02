# Escáner QR in-app

**Fecha:** 2026-07-02
**Estado:** Aprobado (diseño)

## Problema

Los ítems ya tienen etiquetas QR de estante (feature previa) que codifican la **URL
absoluta a la ficha del ítem** (`item_detalle`). Hoy solo se pueden leer con la cámara
nativa del teléfono, que abre la URL en el navegador. Se quiere un **escáner integrado
dentro de la app (PWA)** para dos cosas:

1. **Desde cualquier pantalla** (navbar): escanear un QR y abrir la ficha del ítem.
2. **Dentro de entrada/salida**: escanear un QR y **agregar el ítem a la lista** del
   movimiento, en lugar de buscarlo manualmente en el selector.

## Decisiones tomadas (brainstorming)

- **Navbar → ir al detalle.** Escanear abre `item_detalle`. Escaneo único: al detectar,
  detiene la cámara y navega.
- **Entrada/salida → agregar a la lista.** Escanear agrega el ítem a la tabla del
  formulario. **Escaneo continuo**: tras agregar, muestra confirmación breve y la cámara
  sigue activa para el siguiente ítem; el usuario cierra cuando termina.
- **Duplicados en formularios:** si el ítem escaneado ya está en la lista, muestra aviso
  "ya está en la lista" y **resalta la fila existente**, sin duplicar.
- **Parseo robusto:** se ignora el host del QR; se extrae solo el **ID del ítem** del path
  y se opera sobre el origen actual. Funciona aunque el QR se haya generado en otro
  dominio/entorno.
- **QR no reconocido / ítem no disponible:** aviso inline en el modal; en modo continuo
  sigue escaneando.
- **Librería:** `html5-qrcode` por CDN (jsdelivr), consistente con Bootstrap/tom-select.
  Se usa su clase núcleo `Html5Qrcode` dentro de un **modal Bootstrap propio** para
  controlar estilo y ciclo de vida.
- **Permiso:** reutiliza `ver_inventario`. El botón/modal solo se renderiza con ese
  permiso. No se agregan permisos nuevos.

## Arquitectura

Un **componente compartido** de escaneo + **handlers por contexto**. El modal, la cámara,
la decodificación y el parseo a `itemId` son comunes y reutilizables; lo que se hace con
el `itemId` resultante cambia según la pantalla.

### Componente compartido

- **`templates/includes/qr_scanner.html`** — el modal Bootstrap: contenedor de video de
  la cámara + zona de avisos inline. Incluido **una vez** en `base.html`, solo si
  `user.is_authenticated` y `perms.core.ver_inventario`.
- **`static/js/qr-scanner.js`** — expone `QRScanner.open({ mode, onItem })`:
  - Arranca `Html5Qrcode` sobre `getUserMedia` al abrir; **detiene la cámara al cerrar**
    el modal (evita dejar la cámara encendida).
  - Al decodificar un texto, lo **parsea** con una función pura documentada
    (`parseItemId(text) -> id | null`): extrae el path y matchea el patrón del detalle de
    ítem (`/inventario/<id>/`). Si no matchea → aviso "QR no reconocido".
  - Entrega el `itemId` al handler `onItem(itemId)`.
  - `mode`: `'single'` (detiene tras un escaneo exitoso) o `'continuous'` (sigue activo,
    con un pequeño *debounce* para no re-disparar el mismo código).
  - El patrón (regex) del path se centraliza aquí.

### Los tres contextos

**1. Navbar (ir al ítem)**
- Botón icono `bi-qr-code-scan` en la navbar, junto al toggle de tema; visible solo con
  `perms.core.ver_inventario`.
- Abre `QRScanner.open({ mode: 'single', onItem })`.
- Handler: navega a `item_detalle` del origen actual con el `itemId`
  (`window.location = /inventario/<id>/`).
- **Validación de existencia/permiso:** la hace la propia vista `item_detalle`
  (`@permission_required('ver_inventario')` + `get_object_or_404`). Si no existe → 404
  normal de la app. No se crea endpoint nuevo.

**2. Entrada (`templates/movimientos/entrada.html`)**
- Botón "Escanear" junto a "Agregar ítem".
- Abre `QRScanner.open({ mode: 'continuous', onItem })`.
- Handler:
  - Verifica que el `itemId` exista en `ITEMS_DATA` (catálogo del form). Si no → aviso
    "ítem no disponible".
  - Si ya hay una fila con ese ítem → aviso "ya está en la lista" + resalta la fila
    existente, no duplica.
  - Si no → `agregarFila(itemId)` (función ya existente) y confirmación breve.

**3. Salida (`templates/movimientos/salida.html`)**
- Botón "Escanear".
- Abre `QRScanner.open({ mode: 'continuous', onItem })`.
- Handler (enrutado por pestaña, porque salida tiene 4 catálogos/paneles):
  - Busca el `itemId` en `ITEMS_PRODUCTO / ITEMS_REPUESTO / ITEMS_CONSUMIBLE /
    ITEMS_OTROS` para determinar la pestaña/panel.
  - Si no está en ninguno → aviso "ítem no disponible para salida".
  - Si está: **activa la pestaña** correspondiente y llama a `agregarFilaPT(...)`
    (producto terminado) o `agregarFila(panel, ...)` según el panel, con el `itemId`
    pre-cargado.
  - Duplicado (ya en la lista de ese panel) → aviso + resalta, sin duplicar.

## Contenido y parseo del QR

El QR guarda `https://<host>/inventario/<id>/` (feature previa,
`request.build_absolute_uri(reverse('item_detalle', ...))`). El escáner **ignora el host**
y extrae solo `<id>` con el regex del path. Así el escaneo es robusto a cambios de dominio
y siempre opera sobre el origen desde el que se está usando la app.

## Componentes a crear/editar

- **Nuevo** `templates/includes/qr_scanner.html` — modal del escáner.
- **Nuevo** `static/js/qr-scanner.js` — API `QRScanner.open`, decodificación, `parseItemId`.
- **Editar** `templates/base.html`:
  - Cargar `html5-qrcode` por CDN.
  - Botón icono de cámara en la navbar (con `perms.core.ver_inventario`).
  - Incluir el partial del modal y `qr-scanner.js`.
- **Editar** `templates/movimientos/entrada.html` — botón "Escanear" + handler.
- **Editar** `templates/movimientos/salida.html` — botón "Escanear" + handler con
  enrutado por pestaña.

## Manejo de errores (en el modal)

- Permiso de cámara denegado → "No se pudo acceder a la cámara. Permite el acceso en tu
  navegador."
- Contexto no seguro (http fuera de `localhost`) → "El escáner requiere HTTPS."
- Sin cámara disponible → aviso.
- QR no reconocido / ítem no disponible / duplicado → aviso inline; en modo continuo
  sigue escaneando.

## Permisos

Reutiliza `ver_inventario` para el botón/modal en la navbar. Los botones de entrada/salida
viven en pantallas que ya exigen sus permisos de movimiento. No se agregan permisos
nuevos.

## Dependencias

`html5-qrcode` se carga por **CDN jsdelivr** (como Bootstrap y tom-select). No cambia
`requirements.txt` ni requiere rebuild de la imagen.

## Pruebas (alcance)

- **Test Django (render):** el botón/modal del escáner se renderiza en `base.html` **solo**
  con `ver_inventario` y **no** sin ese permiso.
- **Parseo:** `parseItemId` se aísla como función pura JS documentada; casos: URL válida de
  ítem (con y sin host), path que no matchea, texto arbitrario. Testeable a mano.
- **Verificación manual:** cámara real requiere HTTPS/localhost y dispositivo con cámara;
  se verifica el flujo navbar (navega) y el flujo entrada/salida (agrega + continuo +
  duplicado + no disponible).

## Restricción clave

La cámara solo funciona en **contexto seguro** (HTTPS o `localhost`). En prod PWA ya es
HTTPS; en pruebas por LAN sobre http no funcionará.

## Fuera de alcance (YAGNI)

- Endpoint de validación previa del ID (se delega en `item_detalle` y en `ITEMS_DATA`).
- Escaneo de códigos que no sean QR de ítems de la app.
- Linterna/torch y selección manual de cámara.
- Acceso al escáner desde el bottom-nav móvil (solo navbar por ahora).
- QR que codifique acciones directas (registrar salida sin abrir la ficha).
