# API interna de Jaime

API JSON de solo lectura para consultar clientes, cuentas por cobrar e inventario.
No usa sesiones de Django y no ofrece operaciones de creación, edición, pago,
anulación ni eliminación.

## Configuración y autenticación

Defina un token largo y aleatorio en el entorno del servicio web:

```env
JAIME_API_TOKEN=
```

Un valor ausente o vacío deshabilita el acceso. Cada petición debe incluir:

```http
Authorization: Bearer <JAIME_API_TOKEN>
```

Ejemplo base (el valor mostrado es solo una variable local del shell):

```bash
export JAIME_TOKEN='reemplace-por-el-token-configurado'
curl -sS -H "Authorization: Bearer ${JAIME_TOKEN}" \
  'http://localhost:8000/api/jaime/clientes/buscar/?q=Textiles'
```

Todos los endpoints aceptan exclusivamente `GET`. Cualquier
`POST`, `PUT`, `PATCH` o `DELETE` responde `405 Method Not Allowed`.

## Endpoints

### Buscar clientes

`GET /api/jaime/clientes/buscar/?q=texto`

`q` es obligatorio. Busca parcialmente, sin distinguir mayúsculas, en los campos
reales `nombre`, `rtn`, `telefono` y en alias registrados. Devuelve como máximo
20 coincidencias.

```bash
curl -sS -G -H "Authorization: Bearer ${JAIME_TOKEN}" \
  --data-urlencode 'q=Cliente ABC' \
  'http://localhost:8000/api/jaime/clientes/buscar/'
```

```json
{
  "ok": true,
  "data": [
    {"id": 123, "nombre": "Cliente ABC", "rtn": "0801...", "telefono": "9999-0000"}
  ]
}
```

### Saldo de cliente

`GET /api/jaime/clientes/<id>/saldo/`

Suma los saldos de documentos no anulados mediante las aplicaciones de pagos
existentes. El vencimiento se calcula dinámicamente con la fecha local de Django.

```bash
curl -sS -H "Authorization: Bearer ${JAIME_TOKEN}" \
  'http://localhost:8000/api/jaime/clientes/123/saldo/'
```

```json
{
  "ok": true,
  "data": {
    "cliente_id": 123,
    "cliente": "Cliente ABC",
    "saldo_pendiente": 25000.0,
    "cantidad_facturas_pendientes": 4,
    "cantidad_facturas_vencidas": 2,
    "saldo_vencido": 10000.0
  }
}
```

### Facturas pendientes

`GET /api/jaime/facturas/pendientes/`

Parámetros opcionales:

- `cliente_id`: identificador entero de un cliente existente.
- `limite`: entero entre 1 y 100; por defecto 20.

Incluye todos los tipos de documentos que el sistema considera deuda (`factura`,
`envio` y `apertura`) cuando conservan saldo, y excluye anulados. El resumen
corresponde a los registros devueltos después de aplicar `limite`.

```bash
curl -sS -G -H "Authorization: Bearer ${JAIME_TOKEN}" \
  --data-urlencode 'cliente_id=123' --data-urlencode 'limite=50' \
  'http://localhost:8000/api/jaime/facturas/pendientes/'
```

```json
{
  "ok": true,
  "data": {
    "facturas": [
      {
        "id": 10, "numero": "FAC-001", "tipo": "factura",
        "cliente_id": 123, "cliente": "Cliente ABC",
        "fecha": "2026-07-01", "vencimiento": "2026-07-31",
        "total": 12000.0, "pagado": 2000.0, "saldo": 10000.0,
        "vencida": true
      }
    ],
    "resumen": {"cantidad": 1, "total_pendiente": 10000.0}
  }
}
```

### Facturas vencidas

`GET /api/jaime/facturas/vencidas/`

Acepta los mismos parámetros `cliente_id` y `limite`. Solo incluye documentos
con saldo cuya fecha de vencimiento sea anterior a la fecha local. Se ordena del
mayor atraso al menor.

```bash
curl -sS -G -H "Authorization: Bearer ${JAIME_TOKEN}" \
  --data-urlencode 'cliente_id=123' --data-urlencode 'limite=50' \
  'http://localhost:8000/api/jaime/facturas/vencidas/'
```

La respuesta usa la misma estructura de facturas pendientes y agrega
`dias_vencida`; el resumen contiene `cantidad` y `total_vencido`.

### Consultar inventario

`GET /api/jaime/inventario/`

Parámetros opcionales:

- `q`: búsqueda parcial en código, nombre, descripción o categoría.
- `limite`: entero entre 1 y 100; por defecto 20.

La existencia es la suma del `Stock` real en todas las ubicaciones. Solo se
devuelven ítems activos.

```bash
curl -sS -G -H "Authorization: Bearer ${JAIME_TOKEN}" \
  --data-urlencode 'q=camiseta negra' --data-urlencode 'limite=20' \
  'http://localhost:8000/api/jaime/inventario/'
```

```json
{
  "ok": true,
  "data": [
    {
      "id": 7, "codigo": "CAM-NEGRA", "nombre": "Camiseta negra",
      "descripcion": "Camiseta de algodón", "existencia": 120.0,
      "unidad": "unidades", "tipo": "producto", "categoria": "Camisetas"
    }
  ]
}
```

## Errores

| HTTP | `error` | Motivo |
| --- | --- | --- |
| 400 | `parametro_requerido` | Falta un parámetro obligatorio. |
| 400 | `parametro_invalido` | Un identificador o límite no es válido. |
| 401 | `unauthorized` | Token ausente, vacío, incorrecto o no configurado. |
| 404 | `cliente_no_encontrado` | El cliente solicitado no existe. |
| 405 | `method_not_allowed` | Se intentó usar un método distinto de GET. |

```json
{
  "ok": false,
  "error": "parametro_invalido",
  "detail": "limite debe estar entre 1 y 100."
}
```

Una respuesta de autenticación no incluye detalles adicionales:

```json
{"ok": false, "error": "unauthorized"}
```
