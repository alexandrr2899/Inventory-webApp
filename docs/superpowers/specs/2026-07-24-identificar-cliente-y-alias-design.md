# Identificar cliente sin salir de la lista + alias de cliente

**Fecha:** 2026-07-24
**Estado:** Aprobado (diseño)

## Problema

Cuando la ingesta automática (n8n → Google Drive → `factura_api_ingest`) recibe un PDF cuyo
nombre no empareja exactamente con ningún cliente, el documento se crea igual pero asignado
al cliente ficticio **"Sin identificar"** (`facturas_api.py:44`), y el nombre que venía en el
archivo se guarda como **prosa dentro de `notas`** (`facturas_api.py:119`).

Resolverlo hoy cuesta cuatro cambios de página: abrir la ficha del documento → leer las notas
para descubrir el nombre → ir a Clientes → crear el cliente → volver a la factura → editarla
para asignarlo.

Además, **el sistema no aprende**: el mes que viene llega otro PDF del mismo cliente con el
mismo nombre raro y vuelve a caer en "Sin identificar".

## Decisiones tomadas (brainstorming)

- **No hay pantalla nueva.** Todo ocurre dentro de la pestaña "Por revisar" que ya existe en
  la lista de facturas.
- **Alias por cliente** para que el emparejado aprenda: cada nombre nuevo se pregunta una
  vez en la vida.
- **El alias se guarda con un checkbox marcado por defecto**, no automáticamente. Casi la
  misma fricción, pero permite escaparse cuando el nombre del archivo viene basura
  (`"FACT-0012 (1)"`).
- **El cliente "Sin identificar" se queda como está**: sigue siendo un `Cliente` real en la
  base. Cero migración de datos, cero riesgo. Se convive con que aparezca en los
  desplegables.
- **Identificar ≠ revisar**: el modal trae un checkbox «marcar como revisado»
  **desmarcado por defecto**. Los documentos de ingesta automática son justo los que nadie
  miró todavía.
- **Los alias se administran con un `textarea` (uno por línea)** en el formulario de cliente,
  no con una UI de chips vía AJAX.
- **Resolución por modal AJAX por fila**, no con selects embebidos en la tabla: la tabla ya
  tiene 15 columnas y la fila entera navega al detalle.

## Modelo de datos

### `ClienteAlias` (nuevo)

| Campo        | Tipo                                          | Notas                                                        |
|--------------|-----------------------------------------------|--------------------------------------------------------------|
| `cliente`    | `ForeignKey(Cliente, CASCADE, related_name='aliases')` | Al borrar el cliente se borran sus alias.           |
| `alias`      | `CharField(200)`                              | El texto tal como se escribió (lo que se ve en el textarea). |
| `alias_norm` | `CharField(200, db_index=True, editable=False)` | Versión normalizada. **Única en toda la tabla.**            |
| `created_at` | `DateTimeField(auto_now_add=True)`            | Permite distinguir los que nacieron solos.                   |

`Meta.ordering = ['alias']`. `Meta.constraints = [UniqueConstraint(fields=['alias_norm'],
name='cliente_alias_norm_unico')]`.

**La unicidad global de `alias_norm` es deliberada:** un alias no puede apuntar a dos
clientes, porque entonces el emparejado dejaría de ser determinista.

`alias_norm` se calcula en `save()` con la misma función `_norm()` que ya usa el matcher
(`bulk_service.py:52`): minúsculas, sin acentos, espacios colapsados.

### Cambios en `DocumentoFactura`

Se agrega `cliente_sugerido = CharField(max_length=200, blank=True)`.

Hoy ese nombre se escribe como prosa dentro de `notas`, donde ni la tabla lo puede mostrar
ni el checkbox de alias lo puede proponer. Pasa a campo propio; **`notas` se queda como
está**, para humanos.

**Migración con backfill:** una migración de datos extrae el nombre de las `notas` de los
documentos ya existentes (línea `Cliente sugerido por archivo: X`) y lo carga en
`cliente_sugerido`, para que los sin identificar actuales arranquen con la ficha completa.
La migración no modifica `notas`.

## Módulo nuevo: `services/facturas/clientes.py`

`_norm()` se mueve acá desde `bulk_service.py` (que la sigue usando, importada). Junto a
ella:

- **`cliente_sin_identificar()`** — hoy vive enterrada como `_cliente_sin_identificar()` en
  un endpoint (`facturas_api.py:44`). Ahora la necesitan tres lugares (ingesta, marcado en
  la lista, validación del modal), así que no puede seguir viviendo en una vista.
- **`crear_alias(cliente, texto)`** — normaliza, ignora si es redundante, devuelve el error
  correspondiente si choca. Devuelve `(alias | None, error | None)`.
- **`sincronizar_aliases(cliente, texto_multilinea)`** — el diff que usa el textarea del
  formulario: parsea líneas, limpia vacías y repetidas, borra las que se fueron, crea las
  nuevas, deja intactas las que no cambiaron.

## Matching

`match_cliente()` (`bulk_service.py:60`) gana un paso intermedio:

1. Nombre exacto normalizado (como hoy).
2. **Alias exacto normalizado** ← nuevo.
3. "Contiene" en cualquier dirección, solo si `solo_exacto=False` (como hoy).

**El orden importa:**

- El alias va **después** del nombre real para que nunca pueda tapar a un cliente existente.
- Va **antes** del "contiene" porque un alias es una afirmación explícita del usuario y el
  "contiene" es una corazonada.

Como el paso 2 es una igualdad exacta, es tan confiable como el paso 1. **Por lo tanto la
ingesta automática (`solo_exacto=True`) empareja por alias y ya no manda el documento a
"Sin identificar"** — que es el objetivo de fondo de esta feature.

El paso 2 se resuelve con una única consulta indexada —
`ClienteAlias.objects.filter(alias_norm=objetivo).select_related('cliente').first()` — y no
cargando todos los alias en memoria. Queda una consulta extra por llamada a `match_cliente`,
del mismo orden que el `Cliente.objects.all()` que la función ya hace hoy.

## UI

### Lista de facturas (`templates/facturas/lista.html`)

Para los documentos cuyo cliente es "Sin identificar":

- **Celda de cliente:** badge naranja `Sin identificar` y, debajo, en gris chico,
  `Del archivo: "ACME S DE RL"` — el mismo lenguaje que ya usa `lote_revisar.html:59`.
- **Celda de acciones:** botón <i>persona+</i> junto a los de ver/PDF/pagar. Va dentro del
  `data-norow="1"` existente, así que clickearlo no dispara la navegación al detalle.

**Cómo sabe el template que un documento está sin identificar:** `facturas_lista` resuelve
`clientes.cliente_sin_identificar().pk` **una sola vez** y lo pasa al contexto como
`sin_identificar_id`; el template compara `doc.cliente_id == sin_identificar_id`. No se usa
una propiedad del modelo ni el string literal `'Sin identificar'`: una propiedad que llamara
al helper por fila dispararía una consulta por documento, justo lo que `test_perf_queries.py`
vigila.

### Modal `templates/facturas/_modal_identificar.html`

Uno solo para toda la página; el botón le pasa los datos por `data-*`, igual que hace hoy el
modal de pago rápido (`_modal_pago.html`).

```
┌─ Identificar cliente ──────────────────────────────┐
│  El archivo decía:  "ACME S DE RL"                 │
│  Factura F-0142 · L 12,400.00 · 03/07/2026         │
│  [ Ver PDF ↗ ]                                     │
│                                                    │
│  Cliente  [ ▾ elegí un cliente     ] [ + Nuevo ]   │
│                                                    │
│  ☑ Recordar "ACME S DE RL" como alias              │
│  ☐ Marcar el documento como revisado               │
│                                                    │
│                  [ Cancelar ]  [ Identificar ]     │
└────────────────────────────────────────────────────┘
```

- **El link al PDF** está porque el caso difícil no es hacer el clic, es no reconocer el
  nombre.
- **El botón "+ Nuevo"** es el modal de cliente inline que **ya existe y ya funciona**
  (`_cliente_modal.html` + `static/js/cliente-inline.js`): se le pasa
  `data-cliente-inline data-target="identificar-cliente"` y al crear el cliente lo deja
  seleccionado solo. No hay que escribir nada de eso.
- La lista de clientes **ya viene en el contexto de la página** (`facturas_lista` pasa
  `clientes`), así que el modal abre sin pedirle nada al servidor.
- **El checkbox de alias solo se renderiza si `cliente_sugerido` no está vacío.**

### Endpoint

`POST facturas/documentos/<pk>/identificar/` → vista `factura_identificar` en
`apps/core/views/facturas_cliente.py` (que ya es el archivo de las acciones AJAX de
cliente). URL name: `factura_identificar`.

- **Parámetros:** `cliente` (id), `guardar_alias` (bool), `marcar_revisado` (bool).
- **Permiso:** `gestionar_facturas`, el mismo que editar.
- **Respuesta OK:** `{ok: true, cliente_nombre, revisada, alias_creado, aviso}`.
- **Respuesta error:** `{ok: false, errors}` con el mismo formato que
  `_form_errors_json()` ya usa en ese archivo.

Al identificar se llama a `status_service.actualizar_estado_pago(doc)` y a
`payment_service.aplicar_saldo_a_favor(doc)`, igual que hace `factura_editar`: el documento
cambia de cliente, así que puede corresponderle un saldo a favor del cliente real.

### Actualización de la fila (sin recargar)

Al volver el OK: la celda de cliente pasa a mostrar el nombre real, el badge y el botón
desaparecen. Si se marcó revisado, la fila se desvanece (se está en la pestaña "Por
revisar") y el contador del botón "Por revisar" baja en uno. Es el mismo patrón de
fragmento + JSON de los commits recientes de abono.

### Textarea de alias (`templates/clientes/form.html`)

Campo *Alias (uno por línea)* debajo del nombre, con ayuda «Otros nombres con los que
aparece este cliente en los PDFs». `ClienteForm` gana un campo no-modelo (`forms.CharField`
con `Textarea`, `required=False`) que carga los alias existentes en `initial` y al guardar
llama a `sincronizar_aliases()`. Sin JS.

## Manejo de errores

**La regla que gobierna todo lo demás:** identificar el documento es la acción principal;
guardar el alias es un efecto secundario. **Si el alias falla, el documento se identifica
igual** y se avisa. Nunca se pierde la acción que importaba por culpa de la que no.

| Situación                                          | Comportamiento                                                                                                   |
|----------------------------------------------------|------------------------------------------------------------------------------------------------------------------|
| El alias ya existe y apunta a **otro** cliente      | El documento se asigna. Aviso: «"ACME S DE RL" ya está registrado como alias de *Acme Sur*; no se guardó».        |
| El alias es idéntico al nombre de su propio cliente | Se ignora en silencio: sería redundante, ya lo empareja el paso 1.                                                |
| El alias choca con el **nombre** de otro cliente    | Se rechaza con el mismo aviso. Un alias así nunca se alcanzaría (el paso 1 gana siempre) y solo confunde.         |
| `cliente_sugerido` vacío                            | No se ofrece el checkbox de alias.                                                                               |
| Otro usuario ya identificó ese documento            | HTTP 409 + «Ya fue identificado como *X*»; la fila se refresca sola.                                             |
| Se eligió "Sin identificar" en el `<select>`        | Se rechaza en validación de la vista.                                                                            |
| Textarea con líneas repetidas o vacías              | Se limpian antes de sincronizar; los choques se listan **todos juntos** en un solo error de formulario.          |

## Pruebas

En `apps/core/tests_facturas/`, siguiendo la organización que ya existe:

- **`test_cliente_alias.py`** — normalización de `alias_norm`; unicidad global; cascada al
  borrar el cliente; las tres validaciones de choque.
- **`test_match_alias.py`** — el alias empareja; **no** tapa un nombre real; gana al
  "contiene"; funciona con `solo_exacto=True`.
- **`test_identificar_view.py`** — asigna cliente; crea el alias; respeta el checkbox
  desmarcado; marca revisado solo si se pidió; permisos; alias duplicado → documento
  asignado + aviso; 409 en el doble envío.
- **`test_cliente_form_aliases.py`** — el textarea agrega, quita y deja intacto lo que no
  cambió.
- **Ampliar `test_api_ingest.py`** — un PDF cuyo nombre coincide con un alias entra
  **directo al cliente correcto**, sin pasar por "Sin identificar".
- **Migración con backfill** — un documento viejo con el nombre en `notas` termina con
  `cliente_sugerido` cargado.
- **Ampliar `test_perf_queries.py`** — la lista con varios documentos sin identificar no
  agrega consultas por fila.

Todo corre en Docker, como el resto de la suite.

## Fuera de alcance (a propósito)

- **Matching difuso por similitud** (Levenshtein y parientes).
- **Alias con comodines o expresiones.**
- **Alias por RTN.**
- **Resolver varios documentos en bloque.**

Los tres primeros son adivinanzas disfrazadas de precisión: el "contiene" actual ya cubre el
caso con revisión humana, y en la ingesta automática no hay nadie para corregir un mal match.
El cuarto se descartó porque los alias hacen que el caso masivo se extinga solo — con el
emparejado aprendiendo, el volumen de sin identificar tiende a cero.
