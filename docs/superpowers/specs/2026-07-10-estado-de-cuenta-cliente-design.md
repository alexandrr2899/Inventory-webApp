# Estado de cuenta por cliente (PDF)

**Fecha:** 2026-07-10

## Contexto

Hoy el estado de cuenta se arma **a mano en Excel** y se envía al cliente (ver formato
de referencia: encabezado con logo "Transformadora de Empaques", "Estado de Cuenta",
fecha y nombre del cliente; tabla de facturas/envíos con columnas Subcliente, Producto,
Fact, Fecha, Lbs, Precio, Valor, Pago, F. Canc; y una fila de totales con **Saldo Total**).

La app ya tiene todos los datos: `DocumentoFactura` (tipo, numero, fecha, categoría,
libras, precio, monto_total), `Pago`/`AplicacionPago` (pagos y su reparto), y
propiedades vivas `monto_pagado` / `saldo_pendiente`. Este proyecto genera ese mismo
estado de cuenta como **PDF** (y vista HTML) desde la ficha del cliente, para reemplazar
el trabajo manual sin cambiarle la cara al documento que recibe el cliente.

## Objetivos

1. Generar un estado de cuenta por cliente, filtrado por **rango de fechas (desde/hasta)**,
   que replique el formato actual del Excel.
2. Salida en **PDF** (descargable) más una **vista HTML** previa en pantalla.
3. Capturar el **subcliente** por factura (texto libre) para mostrarlo en el estado de cuenta.
4. Permitir **color configurable por categoría de producto** (p. ej. Camiseta=naranja,
   Lisa=verde) para el coloreado de las filas.

## No-objetivos

- No se genera Excel (el objetivo es reemplazar el Excel manual por PDF). Puede agregarse
  después.
- No se toca el reparto de pagos ni el CRUD de abonos (recién implementados).
- No se crea un modelo de subclientes ni un ABM: el subcliente es texto libre por factura.
- No hay saldo corrido / libro mayor con saldo acumulado fila por fila. El formato es una
  lista plana con totales, igual que el Excel actual.

## Cambios de modelo (2 campos nuevos + migración)

1. **`DocumentoFactura.subcliente`** — `models.CharField(max_length=120, blank=True)`.
   Texto libre. Vacío en los registros existentes.
2. **`CategoriaProducto.color`** — `models.CharField(max_length=7, blank=True)`,
   guarda un hex tipo `#FFA500`. Vacío = sin color.

Una sola migración crea ambos campos (nullable/blank, sin backfill).

## Captura de datos

### Subcliente
Se agrega `subcliente` a `DocumentoEditarForm`
([forms.py](../../../apps/core/forms.py) `DocumentoEditarForm`) — al final de `fields`,
con `widget = forms.TextInput(attrs={'class': 'form-control'})` — y su campo
correspondiente en [form_editar.html](../../../templates/facturas/form_editar.html).
Así se captura/edita en el flujo de edición de factura que ya existe (`factura_editar`,
permiso `gestionar_facturas`).

### Color por categoría
Se agrega `color` a `CategoriaProductoForm`
([forms.py](../../../apps/core/forms.py) `CategoriaProductoForm`) — en `fields` y con
`widget = forms.TextInput(attrs={'type': 'color', 'class': 'form-control form-control-color'})`
— y su input en el template del form de categoría. Se edita en el ABM de categorías que
ya existe (`categoria_producto_editar`).

## Servicio `estado_cuenta_service`

Nuevo módulo `apps/core/services/facturas/estado_cuenta_service.py`. Función pura y
testeable:

```python
def build(cliente, desde, hasta):
    """Arma los datos del estado de cuenta de `cliente` en el rango [desde, hasta].

    Devuelve un dict:
    {
      'cliente': cliente,
      'desde': desde, 'hasta': hasta,
      'filas': [
        {
          'subcliente': str,
          'producto': str,            # categoria.nombre (o '' si no tiene)
          'color': str,               # categoria.color (hex) o '' si no hay
          'etiqueta': str,            # numero_documento, con prefijo 'Envio ' si es envío
          'fecha': date,
          'libras': Decimal,          # total_libras
          'precio': Decimal,          # precio_por_libra
          'valor': Decimal,           # monto_total
          'pago': Decimal,            # monto_pagado
          'fecha_cancelacion': date | None,   # F. Canc: ver regla abajo
        }, ...
      ],
      'totales': {
        'libras': Decimal, 'valor': Decimal, 'pago': Decimal,
        'saldo': Decimal,          # valor - pago (del rango mostrado)
      },
    }
    """
```

Detalles:

- **Documentos incluidos:** `cliente.documentos` con `tipo_documento in (factura, envio)`,
  `fecha_documento` entre `desde` y `hasta` (inclusive), **excluyendo** `estado_pago='anulada'`.
  Orden: `fecha_documento`, luego `created_at` (cronológico, como el Excel).
- **`etiqueta`:** `f'Envio {numero_documento}'` si `tipo_documento == 'envio'`, si no
  `numero_documento` (o el `pk` si el número está vacío, como hace la tab de facturas).
- **`fecha_cancelacion` (F. Canc):** solo si `saldo_pendiente == 0`; es el
  **máximo `fecha_pago`** entre los `Pago` de las `AplicacionPago` del documento (la fecha
  del abono que lo cerró). Si el documento aún tiene saldo, `None`.
- **Totales:** suma de `libras`, `valor`, `pago` de las filas; `saldo = Σvalor − Σpago`.
  Este saldo es el del **rango mostrado** (coincide con el Saldo Total del Excel), no el
  saldo global del cliente.
- Usa las propiedades vivas `monto_pagado`/`saldo_pendiente` del modelo; no recalcula nada
  a mano.

## Vista y PDF

Nuevo módulo de vista (o dentro de `facturas_cliente.py`): `cliente_estado_cuenta(request, pk)`
con `@login_required`, `@permission_required(_perm('ver_facturas'), raise_exception=True)`,
`@facturas_enabled`.

- Lee `desde`/`hasta` de `request.GET`. Default: `hasta = hoy`, `desde = hoy − 60 días`
  (rango acotado para que el PDF no crezca sin límite). Fechas inválidas o ausentes → se
  usa el default.
- Llama a `estado_cuenta_service.build(cliente, desde, hasta)`.
- **HTML (default):** renderiza `estado_cuenta.html` con un pequeño formulario de rango
  (desde/hasta + "Consultar") y un botón **"Descargar PDF"** que apunta al mismo endpoint
  con `?format=pdf&desde=...&hasta=...`.
- **PDF (`?format=pdf`):** renderiza **la misma plantilla** a string y la pasa por
  `xhtml2pdf` (`pisa.CreatePDF`), devolviendo `HttpResponse(content_type='application/pdf')`
  con `Content-Disposition: attachment; filename="estado-cuenta-<cliente>-<hasta>.pdf"`.

URL en [urls.py](../../../apps/core/urls.py), junto a las de cliente:
```python
path('facturas/clientes/<int:pk>/estado-cuenta/', views.cliente_estado_cuenta, name='cliente_estado_cuenta'),
```

Botón **"Estado de cuenta"** en el encabezado de la ficha del cliente
([salidas.html](../../../templates/clientes/salidas.html)), junto a "Editar"/"Clientes",
detrás de `facturas_enabled and perms.core.ver_facturas`.

### Dependencia nueva
`xhtml2pdf` (y su dependencia `reportlab`, Python puro, sin librerías de sistema) se agrega
a `requirements.txt`. Requiere reconstruir la imagen (`docker compose build web`).

## Plantilla `estado_cuenta.html`

Una sola plantilla sirve para pantalla y PDF (xhtml2pdf soporta HTML/CSS básico:
tablas, `background-color`, imágenes, texto). Contenido:

- **Encabezado:** logo (imagen embebida por ruta estática/`data:` URI para que xhtml2pdf
  la incruste), título "Estado de Cuenta", fecha (la de `hasta`), y nombre del cliente.
- **Tabla** con columnas, en este orden (igual al Excel):
  **Subcliente · Producto · Fact · Fecha · Lbs · Precio · Valor · Pago · F. Canc**.
  - La celda **Fact** (o la fila) lleva `style="background-color: {{ fila.color }}"` cuando
    `fila.color` no está vacío; sin color si la categoría no tiene uno configurado.
  - Montos con el filtro `moneda` existente; fechas `d/m/Y`; `F. Canc` vacío si `None`.
  - Solo se generan las filas que existen (sin filas "FALSO" de relleno).
- **Fila de totales:** Σ Lbs, Σ Valor, Σ Pago.
- **Saldo Total** resaltado (= `totales.saldo`).
- El formulario de rango y el botón "Descargar PDF" se muestran solo en HTML (envueltos en
  algo que no aparezca en el PDF, p. ej. un bloque condicionado por una variable `es_pdf`
  que la vista pasa como `False` en HTML y `True` en PDF).

## Manejo de errores

- Rango inválido o vacío → se usan los defaults; nunca revienta.
- Cliente sin documentos en el rango → tabla vacía con totales en 0 y Saldo 0 (no error).
- Si `xhtml2pdf` reporta error al generar (`pisa_status.err`), la vista responde con
  HTTP 500 y un mensaje claro en el log; el HTML sigue disponible como alternativa.

## Pruebas

Nuevo `apps/core/tests_facturas/test_estado_cuenta.py`:

**Servicio (`build`):**
- Incluye solo documentos del rango y excluye anuladas.
- `etiqueta` antepone "Envio " a los envíos y usa el número en facturas.
- `fecha_cancelacion` se llena solo cuando `saldo_pendiente == 0` y es el `fecha_pago`
  del abono que lo cerró; queda `None` si aún hay saldo.
- Totales: Σ libras/valor/pago y `saldo = Σvalor − Σpago` correctos.
- `subcliente` y `color` (de la categoría) se propagan a la fila.

**Vista:**
- HTML: `status 200`, contiene el nombre del cliente y las etiquetas de sus documentos.
- `?format=pdf`: `status 200`, `Content-Type == 'application/pdf'`, contenido no vacío
  (empieza con `%PDF`).
- Permisos: sin `ver_facturas` → 403.
- Requiere `@override_settings(FACTURAS_MODULE_ENABLED=True)` (como los otros tests de la tab).

**Captura:**
- `factura_editar` guarda `subcliente`.
- `CategoriaProductoForm` acepta y guarda `color`.
