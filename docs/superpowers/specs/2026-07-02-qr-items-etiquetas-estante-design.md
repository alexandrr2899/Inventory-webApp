# QR en ítems para etiquetas de estante

**Fecha:** 2026-07-02
**Estado:** Aprobado (diseño)

## Problema

Los estantes ya tienen etiquetas con el nombre del ítem, pero no hay una forma rápida
de, estando frente al estante, ver el stock actual o registrar una entrada/salida. Se
quiere pegar un **código QR** junto a la etiqueta de cada estante (principalmente de
**repuestos y consumibles**) que, al escanearlo con el celular, abra la ficha del ítem.

La ficha (`item_detalle`) ya muestra el stock por ubicación y los botones de
entrada/salida, así que el QR solo necesita enlazar a ella.

## Decisiones tomadas (brainstorming)

- **Al escanear**, el QR abre la **ficha del ítem** (`item_detalle`). Si no hay sesión,
  el flujo normal lleva al login y luego a la ficha.
- **Generación en el servidor** con la librería `qrcode` (Pillow ya está instalado).
- **Dos formas de obtener el QR**: en la ficha individual (uno por uno) y en una **hoja
  de etiquetas en lote** imprimible.
- **Etiqueta minimalista**: el QR es lo principal; el texto (código, y nombre chico) va
  solo como **guía de colocación** para saber qué QR pegar en qué estante. La etiqueta
  del estante ya aporta el nombre.
- El QR funciona para cualquier ítem, pero la hoja en lote **arranca filtrada a
  repuestos + consumibles**.

## Contenido del QR

La **URL absoluta** a `item_detalle` del ítem, construida con el host de la petición
(`request.build_absolute_uri(reverse('item_detalle', args=[item.pk]))`). Así, al generar
o imprimir desde el sitio en producción, el QR queda con el dominio real sin configurar
nada. Se usa el `pk` del ítem (coincide con la ruta existente `inventario/<int:pk>/`).

## Componentes

### 1. Servicio de generación de QR

Nuevo módulo `apps/core/services/qr.py`:

- `qr_png_bytes(data: str) -> bytes` — genera el PNG del QR para el texto dado usando
  `qrcode` (corrección de error media, borde y tamaño de módulo fijos). Sin estado, fácil
  de testear con bytes de salida (verificar cabecera PNG y que no esté vacío).

Esto aísla la dependencia `qrcode` detrás de una función; las vistas no la importan
directamente.

### 2. Endpoint de imagen QR

Nueva vista `item_qr_png(request, pk)` → `inventario/<int:pk>/qr.png`:

- Permiso `ver_inventario`.
- Arma la URL absoluta de la ficha del ítem y responde
  `HttpResponse(qr_png_bytes(url), content_type='image/png')`.
- Se consume como `<img src="{% url 'item_qr_png' item.pk %}">` desde la ficha y la hoja
  de etiquetas (no se guarda archivo; se genera al vuelo).

### 3. QR en la ficha (`item_detalle`)

En `templates/inventario/detalle.html` (el template de `item_detalle`) se agrega un
bloque con:
- La imagen del QR (`item_qr_png`).
- Botón **Imprimir etiqueta** (abre `window.print()` con CSS que imprime solo el QR + el
  código).
- Enlace **Descargar PNG** (al mismo endpoint, el navegador lo baja).

### 4. Hoja de etiquetas en lote

Nueva vista `item_etiquetas(request)` → `inventario/etiquetas/` (permiso
`ver_inventario`):

- **Filtros** (GET): `tipo` (por defecto incluye `repuesto` y `consumible`; opción de
  incluir `producto`/otros) y `categoria`. La vista arma el queryset de ítems activos
  filtrado.
- Renderiza `templates/inventario/etiquetas.html`: una **cuadrícula imprimible** donde
  cada celda es QR + código (+ nombre en letra chica como guía). CSS `@media print` para
  que quede limpio al imprimir (sin nav, sin botones), ~3 columnas, celdas de tamaño
  parejo para recortar.
- Botón **Imprimir** que llama `window.print()`.

### 5. Accesos

- Enlace a la hoja de etiquetas desde el nav (grupo Inventario) y/o un botón en
  `inventario_lista`, guardado por `ver_inventario`.

## Dependencias

- Agregar `qrcode==<versión estable>` a `requirements.txt`. Usa Pillow (ya presente) para
  el PNG. Implica **rebuild de la imagen** en el próximo deploy (como cualquier cambio de
  dependencias en este proyecto).

## Permisos

- Reutiliza `ver_inventario` para el endpoint de imagen, la hoja de etiquetas y el bloque
  en la ficha. No se agregan permisos nuevos.

## Pruebas (alcance)

- **Servicio:** `qr_png_bytes` devuelve bytes con cabecera PNG válida y no vacíos para una
  URL de ejemplo.
- **Endpoint QR:** responde 200 con `content_type='image/png'`; exige `ver_inventario`
  (403 sin permiso).
- **Hoja de etiquetas:** responde 200; por defecto incluye solo repuestos + consumibles;
  el filtro por tipo/categoría acota el conjunto; exige `ver_inventario`.
- **Contenido del QR:** la URL codificada apunta a `item_detalle` del ítem correcto
  (verificable decodificando el PNG en el test, o afirmando la URL que se pasa al
  servicio si se refactoriza para exponerla).

## Fuera de alcance (YAGNI)

- Escáner integrado dentro de la app (se usa la cámara/lector del teléfono, que abre la
  URL directamente).
- QR que codifique acciones directas (registrar salida sin abrir la ficha).
- Tamaños de etiqueta configurables o plantillas de impresión por hoja (Avery, etc.):
  una cuadrícula genérica imprimible es suficiente por ahora.
- Almacenar el PNG del QR como archivo (se genera al vuelo).
