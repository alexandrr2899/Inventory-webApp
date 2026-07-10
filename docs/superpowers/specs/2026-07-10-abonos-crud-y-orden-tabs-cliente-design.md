# CRUD de abonos y reorden de tabs en la ficha del cliente

**Fecha:** 2026-07-10

## Contexto

Hoy en la ficha del cliente (`cliente_salidas`) la tab de Facturas muestra una tabla
"Abonos del cliente" de **solo lectura**. El único CRUD existente sobre abonos es:

- **Crear** abono: `cliente_abono_nuevo` ([facturas_cliente.py](../../../apps/core/views/facturas_cliente.py)).
- **Borrar una aplicación** individual de un pago a una factura:
  `factura_pago_borrar` ([facturas_pagos.py](../../../apps/core/views/facturas_pagos.py)),
  que opera a nivel `AplicacionPago`, no a nivel `Pago`.

Falta poder **editar** un abono completo y **eliminar** el abono completo desde la
ficha del cliente. Además, en la ficha del cliente las tabs aparecen en el orden
"Productos llevados" (activa) → "Facturas"; se quiere invertirlo.

## Objetivos

1. Convertir los abonos en un CRUD completo (crear ya existe; agregar editar y eliminar
   el `Pago` completo) desde la tab de Facturas de la ficha del cliente.
2. En la ficha del cliente, mostrar **Facturas primero** (tab activa por defecto) y
   **Productos llevados** después.

## No-objetivos

- No se modifica el modelo de datos (`Pago`, `AplicacionPago`).
- No se cambia el borrado a nivel `AplicacionPago` (`factura_pago_borrar`), que sigue
  existiendo desde el detalle de factura.
- No se toca el registro de pago desde el detalle de factura (`factura_pago_nuevo`).

## Parte 1 — CRUD de abonos

### Servicio

En [payment_service.py](../../../apps/core/services/facturas/payment_service.py) se agrega:

```python
@transaction.atomic
def editar_abono(pago, *, fecha_pago, metodo_pago, monto,
                 referencia='', comprobante=None, notas='', aplicaciones=None):
    """Actualiza un Pago y rehace su reparto entre facturas.

    Borra las AplicacionPago existentes del pago y las vuelve a crear con la
    misma lógica de reparto que `registrar_abono`. Si `aplicaciones` es None se
    auto-reparte por antigüedad.
    """
```

Detalles:

- Actualiza los campos del `Pago` (`fecha_pago`, `metodo_pago`, `monto`, `referencia`,
  `notas`; y `comprobante` solo si viene uno nuevo, para no borrar el existente).
- Borra `pago.aplicaciones.all()` y luego reparte igual que `registrar_abono`
  (cada aplicación se topa al saldo de la factura y al remanente del pago; el
  sobrante queda como saldo a favor).
- Todo en una transacción. Las señales `post_delete`/`post_save` de `AplicacionPago`
  recalculan el estado de pago de cada factura afectada automáticamente.

> Nota de implementación: el reparto interno (bucle que crea `AplicacionPago` topando
> a saldo y remanente) está duplicado hoy solo en `registrar_abono`. Al agregar
> `editar_abono` se extrae ese bucle a un helper privado (p. ej. `_aplicar_reparto(pago,
> aplicaciones)`) reutilizado por ambas funciones.

### Vistas

En [facturas_cliente.py](../../../apps/core/views/facturas_cliente.py), ambas con
`@login_required`, `@permission_required(_perm('registrar_pago_factura'), raise_exception=True)`
y `@facturas_enabled`:

- **`cliente_abono_editar(request, pk)`** — `pk` es el id del `Pago`.
  - Obtiene el `Pago` y su `cliente`.
  - Calcula el conjunto de facturas para el reparto: las **pendientes**
    (`_facturas_pendientes(cliente)`) **unidas** con las facturas que ya tienen una
    `AplicacionPago` de *este* pago (aunque su saldo sea 0 por este mismo abono).
    Sin esta unión no se podría redistribuir hacia una factura que este abono dejó saldada.
  - GET: renderiza el formulario precargado. Cada fila del reparto viene con el monto
    actualmente aplicado por este pago a esa factura (o vacío si no tiene aplicación).
    Los datos del abono (`fecha_pago`, `metodo_pago`, `monto`, `referencia`, `notas`)
    se precargan como `initial` del `AbonoClienteForm`.
  - POST: valida `AbonoClienteForm`, construye `aplicaciones` desde los campos
    `aplicar_<pk>` (misma lógica que `cliente_abono_nuevo`), llama a
    `editar_abono(...)`, muestra mensaje de éxito y redirige a `cliente_salidas`.

- **`cliente_abono_borrar(request, pk)`** — `@require_POST`, `pk` es el id del `Pago`.
  - Obtiene el `Pago`, guarda `cliente_pk`, hace `pago.delete()` (cascade elimina sus
    `AplicacionPago`; las señales recalculan las facturas), mensaje de éxito y redirige
    a `cliente_salidas`.

### Formulario y plantilla

- Se reutiliza `AbonoClienteForm` (ya cubre todos los campos editables).
- `form_abono.html` se generaliza para servir crear y editar mediante variables de
  contexto:
  - `titulo` / texto del botón submit ("Registrar abono" vs "Guardar cambios").
  - `action_url` (el `<form action>`): `cliente_abono_nuevo` o `cliente_abono_editar`.
  - En edición, las filas del reparto muestran el `value` con el monto aplicado actual
    (en lugar de siempre vacío con placeholder "auto").
  - El comprobante existente se muestra como enlace si ya hay uno cargado.

Las vistas pasan estas variables; `cliente_abono_nuevo` se ajusta para pasar las mismas
claves de contexto (equivalentes al comportamiento actual).

### URLs

En [urls.py](../../../apps/core/urls.py), junto a `cliente_abono_nuevo`:

```python
path('facturas/abonos/<int:pk>/editar/', views.cliente_abono_editar, name='cliente_abono_editar'),
path('facturas/abonos/<int:pk>/borrar/', views.cliente_abono_borrar, name='cliente_abono_borrar'),
```

(El `pk` aquí es el id del `Pago`, a diferencia de `cliente_abono_nuevo` cuyo `pk` es el
del cliente.)

### UI en la tab de Facturas

En [_tab_cliente.html](../../../templates/facturas/_tab_cliente.html), tabla "Abonos del
cliente": se agrega una columna **Acciones** (visible solo con
`perms.core.registrar_pago_factura`) con:

- Botón/enlace **Editar** → `cliente_abono_editar` del pago.
- Botón **Eliminar** → `<form method="post">` a `cliente_abono_borrar` con
  `onsubmit="return confirm(...)"` y `{% csrf_token %}`.

## Parte 2 — Orden de tabs en la ficha del cliente

En [salidas.html](../../../templates/clientes/salidas.html):

- Invertir el orden de los `<li>` en `#clienteTabs`: **Facturas** primero, **Productos
  llevados** después.
- **Facturas** pasa a ser la tab activa por defecto (clase `active` en su botón y
  `show active` en su panel `#tab-facturas`); **Productos llevados** deja de tenerlas.
- El JS de carga diferida hoy solo carga el fragmento de facturas al hacer clic en la
  tab. Como Facturas será la tab inicial, se ajusta para que el fragmento se cargue al
  cargar la página (disparar `cargar('')` en el `DOMContentLoaded` / init si la tab de
  facturas está activa, además de mantener el `shown.bs.tab` para cuando se regresa a ella).

## Manejo de errores

- Formularios inválidos re-renderizan `form_abono.html` con errores (comportamiento actual).
- `editar_abono` es atómica: si algo falla, no queda el pago con reparto a medias.
- El monto aplicado nunca excede el saldo de la factura ni el remanente del pago (lógica
  reutilizada).

## Pruebas

Nuevos tests en `apps/core/tests_facturas/` (siguiendo el estilo de
`test_abono_service.py` y `test_abono_view.py`):

**Servicio (`editar_abono`):**
- Editar el monto rehace el reparto y ajusta el saldo de las facturas.
- Reducir el monto libera saldo en facturas antes saldadas.
- Editar sin `aplicaciones` auto-reparte por antigüedad.
- Editar solo metadatos (misma cantidad) conserva un reparto equivalente.
- No se borra el comprobante si no se envía uno nuevo.
- Atomicidad: un fallo no deja aplicaciones inconsistentes.

**Vistas:**
- `cliente_abono_editar` GET precarga el form y muestra facturas pendientes + las ya
  aplicadas por este pago.
- `cliente_abono_editar` POST edita y redirige.
- `cliente_abono_borrar` elimina el pago, recalcula facturas y redirige.
- Permisos: sin `registrar_pago_factura` → 403.

**UI/render:**
- La tabla de abonos muestra los botones Editar/Eliminar con permiso y no sin él.
- `salidas.html` renderiza Facturas como primera tab y activa; Productos llevados segunda.
