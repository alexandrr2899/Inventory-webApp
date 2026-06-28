# Pagos a nivel de cliente y métodos de pago configurables

**Fecha:** 2026-06-28
**Estado:** Aprobado (diseño)

## Problema

Hoy cada pago (`PagoFactura`) está atado **obligatoriamente a una sola factura** y el
método de pago es una lista fija en código (`efectivo, transferencia, deposito, cheque,
tarjeta, otro`).

Esto no refleja la operación real:

1. Un cliente **va abonando** y a veces un mismo abono **termina de pagar una factura y
   continúa con la siguiente**. Con el modelo actual hay que partir el pago a mano y
   registrarlo factura por factura.
2. Se necesitan **métodos de pago personalizables** para distinguir, por ejemplo,
   transferencias a cuentas bancarias distintas ya establecidas.

## Decisiones tomadas (brainstorming)

- **Aplicación del abono:** automática por antigüedad (factura más vieja primero,
  sobrante a la siguiente) **pero editable** antes de confirmar.
- **Exceso de pago:** queda como **saldo a favor** del cliente y se **aplica
  automáticamente** a la próxima factura que se registre.
- **Métodos de pago:** configurables con **nombre + tipo** (sin campos separados de
  banco/cuenta; el nombre libre los distingue, ej. "Transferencia BAC").
- **Flujo de registro:** **ambos lugares** — abono general desde la ficha del cliente y
  "Registrar pago" desde el detalle de una factura.
- **Anular factura con pagos aplicados:** el dinero aplicado se **libera y vuelve al
  saldo a favor** del cliente (no se pierde).

## Modelo de datos

### `MetodoPago` (nuevo)

Métodos configurables que reemplazan la lista fija `PagoFactura.METODO_CHOICES`.

| Campo    | Tipo                          | Notas                                              |
|----------|-------------------------------|----------------------------------------------------|
| `nombre` | `CharField`                   | Texto libre, ej. "Transferencia BAC", "Efectivo".  |
| `tipo`   | `CharField` (choices)         | `efectivo/transferencia/deposito/cheque/tarjeta/otro` — para íconos y agrupación. |
| `activo` | `BooleanField` (default True) | Los inactivos no aparecen al registrar nuevos pagos pero conservan su historial. |
| `orden`  | `PositiveIntegerField`        | Orden de despliegue.                               |

`Meta.ordering = ['orden', 'nombre']`.

### `Pago` (nuevo)

El abono a nivel de **cliente** (reemplaza conceptualmente a `PagoFactura`).

| Campo         | Tipo                                  | Notas                                  |
|---------------|---------------------------------------|----------------------------------------|
| `cliente`     | `FK Cliente` (PROTECT, `related_name='pagos'`) | Dueño del abono.              |
| `fecha_pago`  | `DateField` (default hoy)             |                                        |
| `metodo_pago` | `FK MetodoPago` (PROTECT)             |                                        |
| `monto`       | `DecimalField(12,2)`                  | Total del abono.                       |
| `referencia`  | `CharField(120, blank)`               |                                        |
| `comprobante` | `FileField` (upload a `facturas/pagos/%Y/%m/`) |                              |
| `notas`       | `TextField(blank)`                    |                                        |
| `created_at`  | `DateTimeField(auto_now_add)`         |                                        |

Propiedades:
- `monto_aplicado` = suma de `self.aplicaciones.monto`.
- `saldo_sin_aplicar` = `monto - monto_aplicado` (la porción que aún es crédito a favor).

`Meta.ordering = ['-fecha_pago', '-created_at']`.

### `AplicacionPago` (nuevo)

Reparte un `Pago` entre una o varias facturas.

| Campo        | Tipo                                  | Notas                                  |
|--------------|---------------------------------------|----------------------------------------|
| `pago`       | `FK Pago` (CASCADE, `related_name='aplicaciones'`) |                          |
| `documento`  | `FK DocumentoFactura` (PROTECT, `related_name='aplicaciones'`) |               |
| `monto`      | `DecimalField(12,2)`                  | `> 0` (constraint).                    |
| `created_at` | `DateTimeField(auto_now_add)`         |                                        |

### Cambios en modelos existentes

**`DocumentoFactura`**
- `monto_pagado` pasa a sumar `self.aplicaciones` (antes `self.pagos`).
- `saldo_pendiente`, `es_pago_parcial`, `esta_vencida` no cambian su lógica (dependen de
  `monto_pagado`).

**`Cliente`** — nuevas propiedades:
- `saldo_a_favor` = suma de `saldo_sin_aplicar` de todos sus `pagos`.
- `total_adeudado` = suma de `saldo_pendiente` de sus facturas no anuladas.

**`PagoFactura`** — se **retira** tras migrar los datos.

## Lógica de aplicación

### Servicio `payment_service` (reescrito)

`registrar_abono(cliente, *, fecha_pago, metodo_pago, monto, referencia='', comprobante=None, notas='', aplicaciones=None)`

1. Crea el `Pago`.
2. Si `aplicaciones` viene explícito (el usuario editó el reparto), crea esas
   `AplicacionPago` validando que la suma no exceda `monto` ni el saldo de cada factura.
3. Si no viene, **auto-reparte**: facturas pendientes del cliente ordenadas de la más
   vieja a la más nueva; por cada una crea una `AplicacionPago` por `min(saldo_factura,
   restante)` hasta agotar `monto`.
4. El remanente queda **sin aplicar** = saldo a favor.
5. Recalcula el estado de cada factura afectada (vía signal de `AplicacionPago`).

`proponer_reparto(cliente, monto)` — helper que devuelve el reparto sugerido (factura →
monto) **sin** persistir, para pintar la tabla editable en la UI.

`aplicar_saldo_a_favor(documento)` — al registrar/crear una factura nueva, consume el
saldo a favor disponible del cliente (pagos con `saldo_sin_aplicar > 0`, del más viejo al
más nuevo) creando `AplicacionPago` hasta cubrir el saldo de la factura.

`liberar_aplicaciones(documento)` — al anular una factura, elimina sus `AplicacionPago`
(el dinero vuelve a quedar como saldo a favor de cada `Pago`).

### Recálculo de estado (signals)

Los signals `post_save`/`post_delete` se mueven de `PagoFactura` a **`AplicacionPago`** y
llaman a `status_service.actualizar_estado_pago(instance.documento)`. La anulación de
factura dispara `liberar_aplicaciones`.

## Flujos de UI

Ambos puntos de entrada crean los mismos registros (`Pago` + `AplicacionPago`).

1. **Ficha del cliente → "Registrar abono"**
   - Form: monto total + método + fecha + referencia/comprobante/notas.
   - Tabla de facturas pendientes con el reparto propuesto (auto por antigüedad),
     **editable** por fila.
   - Muestra el saldo a favor resultante.
   - La ficha del cliente lista sus abonos y su saldo a favor actual.

2. **Detalle de factura → "Registrar pago"** (se mantiene)
   - Crea un `Pago` para el cliente + una sola `AplicacionPago` a esa factura por el
     monto ingresado. Caso simplificado del flujo general.

3. **Configuración → "Métodos de pago"**
   - CRUD de `MetodoPago` siguiendo el patrón de los catálogos existentes.

## Migración de datos

Migración de datos (no destructiva) antes de retirar `PagoFactura`:

1. Crear un `MetodoPago` por cada valor distinto usado en `PagoFactura.metodo_pago`
   (mapeo: `nombre = label del choice`, `tipo = el mismo valor`).
2. Por cada `PagoFactura` existente:
   - Crear `Pago` (cliente = `documento.cliente`, mismos `fecha_pago`, `monto`,
     `referencia`, `comprobante`, `notas`; `metodo_pago` = el `MetodoPago` mapeado).
   - Crear una `AplicacionPago(pago, documento, monto = monto completo)`.
3. Verificar que `monto_pagado` de cada factura queda idéntico al previo.
4. Migración posterior retira el modelo `PagoFactura`.

## Permisos

- Reusar `registrar_pago_factura` para registrar abonos y pagos.
- Nuevo permiso `gestionar_metodos_pago` para el CRUD de métodos.

## Pruebas (alcance)

- **Modelos/propiedades:** `monto_aplicado`, `saldo_sin_aplicar`, `saldo_a_favor`,
  `total_adeudado`, `monto_pagado` con aplicaciones.
- **Servicio:** auto-reparto por antigüedad, reparto editado, generación de saldo a favor,
  auto-aplicación de saldo a favor al crear factura, liberación al anular.
- **Signals:** estado de factura recalculado al crear/editar/borrar aplicaciones y al
  anular.
- **Migración:** los pagos viejos producen `monto_pagado` idéntico.
- **Vistas:** ambos flujos de registro y el CRUD de métodos (permisos incluidos).

## Fuera de alcance (YAGNI)

- Campos separados de banco / número de cuenta en `MetodoPago`.
- Conciliación bancaria o importación de estados de cuenta.
- Reembolsos de saldo a favor en efectivo (solo se aplica a facturas).
