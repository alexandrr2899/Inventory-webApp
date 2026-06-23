# Diseño — Módulo Facturas

Fecha: 2026-06-23
Estado: aprobado para planificación

## 1. Objetivo

Agregar un módulo **Facturas** a la app de inventario (Django) que permita registrar y
gestionar dos tipos de documentos: **Factura** y **Envío**. Cada documento conserva su
nombre dentro del sistema.

En esta fase **no** se modifica inventario ni se descuenta stock. El código queda preparado
(servicios aislados) para integrar inventario más adelante, pero no se hace todavía.

## 2. Restricciones (de obligado cumplimiento)

- NO crear un nuevo modelo `Cliente`; usar el `core.Cliente` existente.
- NO crear una app Django nueva: **todo vive dentro de `apps/core`** (mismo `app_label`,
  migraciones en `core/migrations/`), pero **modular por archivos** (no monolito).
- NO modificar inventario ni descontar stock.
- NO modificar el contenido de la tab actual "Productos llevados" (`clientes/salidas.html`).
- Mantener Excel como fuente de generación de documentos (no se reemplaza).
- El módulo se llama **Facturas**; dentro existen documentos **Factura** y **Envío**.
- No usar OCR en esta fase.

## 3. Arquitectura

Todo dentro de `apps/core`, siguiendo la convención modular existente
(`views/conteos.py`, `views/inventario.py`, `services/`, etc.).

```
apps/core/
├── models.py                 # + DocumentoFactura, TarifaCliente, PagoFactura
├── forms.py                  # + formularios de facturas/pagos/tarifas
├── signals.py                # + recalcular estado de pago al guardar/borrar PagoFactura
├── admin.py                  # + registro admin de los 3 modelos
├── urls.py                   # + rutas de facturas (con guard del interruptor)
├── views/
│   ├── facturas.py           # dashboard, listado, detalle, upload, editar, anular, revisar
│   ├── facturas_pagos.py     # registrar pago / historial
│   ├── facturas_tarifas.py   # CRUD tarifas por cliente
│   └── facturas_cliente.py   # fragmento AJAX de la tab "Facturas" del cliente
├── services/
│   └── facturas/
│       ├── __init__.py
│       ├── pdf_service.py
│       ├── invoice_service.py
│       ├── payment_service.py
│       ├── status_service.py
│       └── pdf_extractors/
│           ├── base_extractor.py
│           ├── factura_extractor.py
│           └── envio_extractor.py
└── tests_facturas/           # paquete de pruebas del módulo
templates/facturas/...        # dashboard, lista, detalle, form_upload, form_pago, tarifas,
                              # _tab_cliente.html (fragmento)
```

### Interruptor de activación/desactivación

- Variable `FACTURAS_MODULE_ENABLED` (bool, leída con `python-decouple`, default `True`).
- Decorador `@facturas_enabled` aplicado a las vistas: devuelve **404** si está apagado.
- Context processor (o variable de contexto) `facturas_enabled` para condicionar el enlace
  del menú y la tab "Facturas" del cliente.
- Apagarlo no afecta inventario ni stock; el código sigue en `core` pero "no existe" para
  el usuario.

## 4. Modelos (en `apps/core/models.py`)

### DocumentoFactura

Campos: `cliente` (FK `core.Cliente`, PROTECT), `archivo_pdf` (FileField → `MEDIA_ROOT/facturas/`),
`tipo_documento` (`factura` | `envio`), `numero_documento`, `fecha_documento`,
`fecha_vencimiento`, `producto` (`camiseta` | `lisa` | `otro`), `total_libras` (Decimal),
`precio_por_libra` (Decimal, **snapshot**), `subtotal`, `isv`, `monto_total` (Decimal),
`texto_extraido` (Text), `estado_revision` (`pendiente` | `revisada` | `error`),
`estado_pago` (`pendiente` | `pagada` | `vencida` | `anulada`), `notas`,
`created_at`, `updated_at`.

Propiedades calculadas:
- `monto_pagado` = suma de `PagoFactura` relacionados.
- `saldo_pendiente` = `monto_total - monto_pagado`.
- `es_pago_parcial`, `vence_hoy`, `vence_en_7_dias`.

`estado_pago` se **persiste** (para poder filtrar) y se recalcula vía `status_service`.

Reglas:
- `tipo_documento = factura`: `monto_total`, `subtotal`, `isv` provienen del PDF (editable).
- `tipo_documento = envio`: `total_libras` del PDF; `precio_por_libra` desde la tarifa
  activa del cliente; `monto_total = total_libras × precio_por_libra`.

### TarifaCliente

Campos: `cliente` (FK), `producto` (`camiseta` | `lisa` | `otro`), `precio_por_libra` (Decimal),
`activa` (bool), `fecha_inicio`, `fecha_fin` (nullable), `notas`.

Reglas:
- Cada cliente puede tener precio distinto por producto (camiseta y lisa pueden diferir).
- Método de clase `activa_para(cliente, producto)` → la tarifa activa vigente.
- Al registrar un envío se copia el `precio_por_libra` al documento (snapshot).
- Validación: una sola tarifa `activa=True` por (cliente, producto).

### PagoFactura

Campos: `documento` (FK, CASCADE), `fecha_pago`, `metodo_pago`
(`efectivo` | `transferencia` | `deposito` | `cheque` | `tarjeta` | `otro`),
`monto` (Decimal), `referencia`, `comprobante` (FileField opcional), `notas`, `created_at`.

Permite varios pagos por documento. `post_save`/`post_delete` recalculan el estado del documento.

## 5. Servicios

- **`status_service.calcular_estado_pago(doc)`**: si `saldo <= 0` → `pagada`; si `saldo > 0` y
  `hoy > fecha_vencimiento` → `vencida`; si `saldo > 0` y `hoy <= fecha_vencimiento` →
  `pendiente`. Respeta `anulada` (manual): si ya está anulada no se sobrescribe.
- **`payment_service.registrar_pago(doc, **datos)`**: crea `PagoFactura`, recalcula
  pagado/saldo/estado y guarda.
- **`invoice_service.crear_desde_pdf(cliente, tipo, archivo, producto=None)`**: orquesta el
  alta: extrae texto, aplica extractor según tipo, para envío busca tarifa activa y calcula
  `monto_total`; guarda con `estado_revision='pendiente'`. Permite editar todos los campos.
- **`pdf_service.extraer_texto(archivo)`**: PyMuPDF (`fitz`). `pdfplumber` queda preparado
  como fallback opcional (documentado, no instalado por defecto).
- **`pdf_extractors/`**:
  - `base_extractor.BaseExtractor`: interfaz; método `extraer(texto) -> dict`.
  - `factura_extractor`: intenta número, fecha, subtotal, ISV, total, cliente.
  - `envio_extractor`: intenta número, fecha, cliente, producto, total_libras, detalle de líneas.
  - Se ajustan a los **PDFs reales** ubicados en `docs/facturas/samples/`.

## 6. Vistas y templates

- **Dashboard** (`/facturas/`): tarjetas — total documentos del mes, total facturado,
  total cobrado, total pendiente, total vencido, facturas pendientes, envíos pendientes.
- **Listado general** (`/facturas/documentos/`): Facturas + Envíos juntos. Columnas y filtros
  según spec (tipo, cliente, producto, estado pago, pendientes/pagadas/vencidas/anuladas,
  rango de fechas). Acciones: ver, registrar pago, editar, abrir PDF, anular.
- **Detalle** (`/facturas/documentos/<pk>/`): todos los campos + texto extraído + historial de
  pagos. Acciones: registrar pago, editar, marcar revisado, anular, descargar PDF.
- **Carga de PDF** (`/facturas/documentos/nuevo/`): seleccionar cliente, tipo, subir PDF,
  extraer, (si envío) seleccionar producto y aplicar tarifa, editar campos, guardar pendiente.
- **Registro de pago** (`/facturas/documentos/<pk>/pago/`): fecha, método, monto, referencia,
  comprobante, notas → recalcula al guardar.
- **CRUD Tarifas** (`/facturas/clientes/<pk>/tarifas/`): definir precios por libra para
  camiseta / lisa / otro.

### Tab "Facturas" en la vista del cliente

- Refactor de `templates/clientes/salidas.html`: el contenido actual de "Productos llevados"
  se **envuelve sin cambios** dentro de un contenedor Bootstrap `nav-tabs`. Se agrega la tab
  "Facturas" al lado.
- La tab "Facturas" carga por **AJAX** un fragmento (`facturas_cliente` →
  `templates/facturas/_tab_cliente.html`) para no penalizar el rendimiento de la página actual.
- Contenido de la tab: resumen superior (total facturado, pagado, pendiente, vencido, # facturas,
  # envíos), tabla filtrable (Facturas / Envíos / Todos) con columnas del spec, y acciones
  (abrir documento, registrar pago, ver historial, abrir PDF). Acceso a Tarifas del cliente.
- Acoplamiento solo por **nombre de URL**; si `FACTURAS_MODULE_ENABLED` está apagado, la tab no
  se renderiza. El contenido de "Productos llevados" no se modifica.

## 7. Permisos

**El módulo Facturas es exclusivo de Administrador.** Ningún otro grupo lo ve ni accede.

Nuevos permisos custom en `DocumentoFactura.Meta.permissions`:
`ver_facturas`, `gestionar_facturas` (subir/editar), `registrar_pago_factura`,
`anular_factura`, `gestionar_tarifas`.

En `setup_groups.py`:
- **Administrador**: todos los permisos de facturas.
- **Supervisor**: ninguno.
- **Operador**: ninguno.

Las vistas usan `@permission_required(_perm('...'), raise_exception=True)`, igual que el resto.
El enlace del menú y la tab "Facturas" del cliente se condicionan además a
`FACTURAS_MODULE_ENABLED` **y** a que el usuario tenga `ver_facturas` (que solo tiene
Administrador), de modo que para Supervisor/Operador el módulo es invisible.

## 8. Alertas / badges

Helpers de template + propiedades de modelo: `pendiente`, `pagada`, `vencida`, `anulada`,
`pago_parcial`, `vence_hoy`, `vence_en_7_dias`.

## 9. Dependencias

- `requirements.txt`: añadir **`PyMuPDF`**.
- `pdfplumber`: documentado como opcional (fallback para tablas), no instalado por defecto.

## 10. Pruebas (`apps/core/tests_facturas/`)

- Subida de PDF y creación de documento.
- Extracción de factura (número, fecha, subtotal, ISV, total).
- Extracción de envío (número, fecha, total_libras).
- Cálculo de monto de envío usando la tarifa del cliente (snapshot).
- Registro de pagos y múltiples pagos por documento.
- Cálculo de saldo.
- Cambio automático a `pagada` cuando saldo <= 0.
- Cambio automático a `vencida` por fecha de vencimiento.
- Estado `anulada` manual (no se sobrescribe).
- Visualización de documentos en la tab "Facturas" del cliente.

## 11. Fuera de alcance (esta fase)

- Integración con inventario / descuento de stock.
- OCR.
- Generación de PDFs (sigue siendo Excel).
- Reemplazo del flujo de Excel.
