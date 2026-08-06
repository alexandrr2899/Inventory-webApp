# Editar abonos con saldo real y vencimiento para clientes de contado

Fecha: 2026-08-06

## Problema

**1. Editar un abono muestra las facturas como pagadas.** En el formulario de edición
la columna "Saldo pendiente" usa `documento.saldo_pendiente`, que ya descuenta las
aplicaciones del abono que se está editando. Una factura que ese abono dejó en cero
aparece con saldo `L 0.00` y estado pagada, así que no se ve cuánto se puede
redistribuir. El guardado sí es correcto (`editar_abono` borra las aplicaciones antes
de repartir): lo que engaña es la pantalla.

**2. El reparto se recorta en silencio.** `_aplicar_reparto` hace
`min(monto, saldo, restante)`. Si la suma de las filas supera el monto del abono, o
una fila supera el saldo de su factura, se guarda un reparto distinto al que escribió
la persona, sin ningún aviso.

**3. Facturas anuladas en el reparto.** Si una factura que el abono había pagado se
anula después, sigue apareciendo editable en la edición y `_aplicar_reparto` le puede
aplicar dinero.

**4. Los clientes de contado nunca tienen facturas vencidas.** El cálculo del
vencimiento es `if not doc.fecha_vencimiento and doc.fecha_documento and
cliente.dias_credito`. Con `dias_credito = 0` la condición es falsa, `fecha_vencimiento`
queda `NULL` y `status_service.calcular_estado_pago` nunca puede devolver `vencida`:
esos documentos quedan en `pendiente` para siempre.

## Diseño

### A. Vencimiento de contado

Helper único `calcular_vencimiento(cliente, fecha_documento)` en
`services/facturas/invoice_service.py`:

- `None` si no hay `fecha_documento`, o si el cliente es «Sin identificar» — un
  documento sin identificar no debe nacer vencido, y dejar su vencimiento vacío es lo
  que permite calcularlo con los días del cliente real al identificarlo.
- Si no: `fecha_documento + timedelta(days=cliente.dias_credito or 0)`. Contado (0 días)
  vence el mismo día del documento.

Reemplaza el cálculo duplicado en `invoice_service.crear_documento` y en
`views/facturas_cliente.factura_identificar`, conservando en ambos el guard de "solo si
`fecha_vencimiento` viene vacío", para no pisar una fecha extraída del PDF ni una puesta
a mano.

`status_service` no cambia: ya marca `vencida` con `hoy > fecha_vencimiento`, de modo
que una factura de contado sale **pendiente el día del documento y vencida al día
siguiente**.

Migración de datos que rellena `fecha_vencimiento` en los documentos que no la tienen
(con `fecha_documento`, cliente distinto de «Sin identificar») y recalcula `estado_pago`.
Efecto esperado: el resumen diario de vencidas empieza a contar esas facturas. Es un
único push agregado por día, así que no genera avalancha de notificaciones.

### B. Saldo editable al editar un abono

`payment_service.facturas_para_reparto(cliente, pago=None)` devuelve las filas
`(documento, saldo_editable, ya_aplicado)`, donde:

```
saldo_editable = saldo_pendiente + aplicado_por_este_abono
```

es decir, el saldo que tendría la factura si el abono no existiera. Se incluye la fila
cuando `saldo_editable > 0`: eso deja fuera a las facturas saldadas por otros abonos y
deja dentro a las que este abono cubrió. Sin `pago` equivale a las facturas pendientes,
así que alta y edición usan la misma función y el mismo template.

La columna de saldo muestra `saldo_editable` y se titula «Saldo sin este abono» en modo
edición, para que se entienda de dónde sale el número. `saldo_editable` es también el
tope de validación de cada fila y el `max` del input.

Las facturas anuladas quedan fuera de la lista editable y del reparto.

### C. Validación del reparto

El auto-reparto del remanente por antigüedad **se mantiene tal cual**: si la suma de las
filas es menor que el monto, el resto se sigue repartiendo a las facturas pendientes no
fijadas, y lo que sobre queda como saldo a favor.

Lo que cambia es que el reparto escrito a mano ya no se recorta en silencio.
`AbonoClienteForm` recibe las filas editables `(documento, saldo_editable)`, lee los
campos `aplicar_<pk>` en su `clean()` y devuelve `cleaned_data['aplicaciones']`. Da error
cuando la suma supera el monto del abono, cuando una fila supera el saldo de su factura,
o cuando una fila es negativa. Una fila ilegible (texto) se sigue tratando como vacía.
Los errores salen como `non_field_errors`, que el modal AJAX ya sabe mostrar.

La validación vive en el formulario y no en el servicio a propósito: el tope del
servicio (`min(monto, saldo, restante)`) es de lo que depende «pagar esta factura» desde
el detalle, donde un monto mayor al saldo debe desbordar hacia las otras facturas y al
saldo a favor. Ahí el recorte es la intención; en el reparto escrito a mano, no.

Dos invariantes sí se refuerzan en el servicio, porque ningún llamador depende de lo
contrario: `_aplicar_reparto` ignora las facturas anuladas y las de otro cliente. Y
`factura_pago_nuevo` rechaza de entrada registrar un pago sobre un documento anulado.

`editar_abono` borra las aplicaciones **antes** de bloquear las facturas pendientes: así
las que ese abono había dejado en cero vuelven a estar pendientes y entran en el mismo
lote de bloqueo, en vez de bloquearse sueltas más tarde con un orden impredecible.

En el template, un totalizador en vivo muestra `aplicado / monto / resto` mientras se
escribe, para ver el desbalance antes de enviar.

### D. Saldo inicial (deuda anterior al sistema)

Un cliente que ya debía dinero antes de empezar a cargar sus facturas necesita que esa
deuda exista en el sistema; si no, su primer abono se reparte solo entre las facturas
nuevas y lo viejo queda invisible.

Se modela como **documento de apertura**: `tipo_documento = 'apertura'`, un tercer valor
de `TIPO_CHOICES`. Es un documento y no un campo `saldo_inicial` en `Cliente` porque la
deuda vieja se comporta igual que una factura pendiente — recibe `AplicacionPago`, suma
en `total_adeudado`, sale en el estado de cuenta y envejece. Un campo suelto obligaría a
meterle una excepción a cada uno de esos cálculos.

El tipo aparte es lo que evita que la deuda vieja se cuente como venta: los reportes de
facturación agregan por tipo con whitelist `('factura', 'envio')`, así que la apertura
queda fuera sin tocarlos. Lo que sí se ajusta es `estado_cuenta_service`, que filtraba
con esa misma whitelist y debe incluirla (con etiqueta «Saldo inicial»).

`invoice_service.registrar_saldo_inicial(cliente, monto, fecha, notas)`:

- `fecha_vencimiento = fecha_documento` aunque el cliente tenga días de crédito: es
  deuda que ya venía corriendo, no una venta nueva.
- `estado_revision = 'revisada'` (no hay PDF que revisar).
- aplica el saldo a favor que el cliente ya tuviera.
- uno por cliente: el segundo intento es `ValidationError`.

En las listas (tab del cliente y listado de facturas) lleva su propio badge «Saldo
inicial», porque el badge se elegía con `if envio / else Factura` y la apertura habría
salido rotulada como factura.

Se registra desde un botón «Saldo inicial» en la pestaña de facturas del cliente
(permiso `gestionar_facturas`), que desaparece cuando ya hay uno. El formulario de
subida de PDF no ofrece «apertura» como tipo, porque no se sube: se registra a mano.

Como la apertura es el documento más antiguo del cliente, el auto-reparto por antigüedad
la cobra primero, que es el comportamiento deseado.

## Pruebas

- `test_invoice_service`: contado obtiene `fecha_vencimiento = fecha_documento`; emitida
  hoy es `pendiente` y emitida ayer es `vencida`; «Sin identificar» queda sin
  vencimiento; una fecha explícita del PDF no se pisa.
- `test_identificar_view`: identificar un documento le calcula el vencimiento con los
  días del cliente real (y con contado, el día del documento).
- `test_backfill_vencimiento`: corre la función de la migración contra el registro real
  de modelos — contado viejo queda vencido, el de hoy sigue pendiente, no se pisa un
  vencimiento existente, «Sin identificar» y las anuladas quedan como estaban.
- `test_abono_view`: al editar, las facturas que ese abono pagó muestran su saldo
  completo (no cero); pasarse del monto o del saldo devuelve error y no guarda nada; un
  reparto parcial sigue auto-repartiendo el resto.
- `test_abono_service`: no se aplica a facturas anuladas; `facturas_para_reparto`
  devuelve el saldo sin el abono.
- `test_saldo_inicial`: la apertura suma en lo adeudado, vence el día del corte pese a
  los días de crédito, la cobra el primer abono antes que las facturas nuevas, no
  aparece en los totales de facturación, sí en el estado de cuenta, es única por
  cliente y consume el saldo a favor previo; más la vista (alta, segundo intento,
  monto negativo, permisos).
