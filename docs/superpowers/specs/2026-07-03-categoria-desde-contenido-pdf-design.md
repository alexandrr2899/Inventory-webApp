# Spec: Clasificar categoría desde contenido del PDF

**Fecha:** 2026-07-03  
**Estado:** aprobado por el usuario  

---

## Contexto

`clasificar_categoria(nombre_archivo)` busca la `palabra_clave` de cada `CategoriaProducto` activa dentro del nombre del archivo. Esto funciona bien para envíos (cuyo nombre suele incluir el tipo de material), pero falla en facturas, donde el nombre es típicamente "Fact NNNN Cliente XYZ.pdf" y no revela el producto.

El texto extraído del PDF sí contiene descripciones de producto claras:
- `Lb Bolsa Blanca`, `Lb Bolsa Lisa` → categoría **Lisa**
- `Lb Bolsa Camiseta` → categoría **Camiseta**
- `Rollo de Poliducto x 100yd` → categoría **Poliducto**

---

## Categorías configuradas

| Categoría | `palabra_clave` tras el cambio | Matchea en contenido |
|---|---|---|
| Camiseta | `camiseta` | `Lb Bolsa Camiseta` |
| Lisa | `lisa, blanca` | `Lb Bolsa Lisa`, `Lb Bolsa Blanca` |
| Poliducto | `poliducto` | `Rollo de Poliducto x 100yd` |

---

## Decisiones de diseño

| Pregunta | Decisión |
|---|---|
| ¿Qué fuente se usa? | Contenido del PDF + nombre del archivo (haystack combinado) |
| ¿Aplica a facturas y envíos? | Sí, ambos |
| Si no hay coincidencia en una factura | Queda sin categoría (`None`) |
| Si no hay coincidencia en un envío | Usa `predeterminada()` (tarifa requiere categoría) |
| Palabras clave múltiples por categoría | Separadas por coma en el campo `palabra_clave` existente |

---

## Cambios

### 1. `clasificar_categoria` en `invoice_service.py`

**Firma nueva:**
```python
def clasificar_categoria(haystack, con_predeterminada=True):
```

- `haystack`: texto libre (nombre del archivo + contenido del PDF).
- `con_predeterminada`: si `True` devuelve `predeterminada()` cuando ninguna coincide; si `False` devuelve `None`.
- La búsqueda soporta múltiples palabras clave separadas por coma:
  ```python
  kw = (cat.palabra_clave or '').strip()
  if kw and any(p.strip().lower() in haystack.lower() for p in kw.split(',')):
      return cat
  ```
- El primer match gana (orden por `cat.orden, cat.nombre`), igual que antes.

### 2. `previsualizar` en `invoice_service.py`

Arma el haystack combinado con el texto ya disponible:
```python
haystack = nombre + '\n' + texto
```

- **Factura:** `clasificar_categoria(haystack, con_predeterminada=False)` → asigna `categoria_id` solo si hubo coincidencia.
- **Envío:** `clasificar_categoria(haystack)` → siempre asigna `categoria_id` (con predeterminada de fallback).

Antes, la sugerencia de categoría era exclusiva de envíos. Ahora aplica a ambos tipos.

### 3. `crear_documento` en `invoice_service.py`

Cuando `categoria is None` (el usuario no eligió ninguna manualmente):
- **Envío:** `clasificar_categoria(haystack, con_predeterminada=True)` — comportamiento idéntico al actual, ahora también mira el contenido.
- **Factura:** `clasificar_categoria(haystack, con_predeterminada=False)` — si no coincide nada, `doc.categoria` queda como `None`.

El `texto_extraido` ya llega como parámetro. El `nombre` se obtiene de `getattr(archivo, 'name', '') or ''`.

### 4. Datos de configuración (admin)

Actualizar en admin el valor de `palabra_clave` para la categoría **Lisa**: de `lisa` (si era así) a `lisa, blanca`.  
No requiere migración de esquema — es solo un cambio de dato.

---

## Sin cambios

- Modelo `CategoriaProducto` y sus migraciones.
- Templates ni vistas.
- El `filename_extractor` (sigue extrayendo número, tipo, cliente del nombre).
- Comportamiento de envíos cuando el usuario elige categoría manualmente.
- La lógica de tarifa (precio/libra × libras) en `crear_documento`.

---

## Pruebas

### `test_invoice_service.py` — `ClasificarCategoriaTests`

| Test | Escenario |
|---|---|
| `test_coincide_en_contenido` | Keyword en el haystack extraído del PDF → devuelve esa categoría |
| `test_coincide_en_nombre` | Keyword solo en el nombre del archivo → devuelve esa categoría |
| `test_multiples_keywords_alguna_coincide` | `palabra_clave = "lisa, blanca"`, haystack tiene "Bolsa Blanca" → devuelve Lisa |
| `test_sin_coincidencia_con_predeterminada` | Ninguna coincidencia, `con_predeterminada=True` → devuelve predeterminada |
| `test_sin_coincidencia_sin_predeterminada` | Ninguna coincidencia, `con_predeterminada=False` → devuelve `None` |

### `test_invoice_service.py` — `PrevisualizarCategoriaTests`

| Test | Escenario |
|---|---|
| `test_factura_keyword_en_contenido` | Factura con keyword solo en texto del PDF → `datos['categoria_id']` presente |
| `test_factura_sin_coincidencia` | Factura sin keyword → `categoria_id` ausente en `datos` |
| `test_envio_sin_coincidencia` | Envío sin keyword → `categoria_id` = predeterminada |

### `test_invoice_service.py` — `CrearDocumentoCategoriaTests`

| Test | Escenario |
|---|---|
| `test_factura_keyword_en_texto_extraido` | `texto_extraido` tiene keyword → `doc.categoria` asignada |
| `test_factura_sin_coincidencia_queda_sin_categoria` | Sin coincidencia → `doc.categoria is None` |
| `test_envio_sin_coincidencia_usa_predeterminada` | Envío sin coincidencia → `doc.categoria` = predeterminada, tarifa aplicada |
| `test_categoria_manual_se_respeta` | Usuario pasa `categoria=X` → no se reclasifica |

---

## Fuera de alcance

- OCR para PDFs escaneados sin texto (si no hay texto, el nombre sigue siendo el haystack).
- Coincidencia difusa o por puntaje.
- Múltiples categorías por documento.
- Cambiar el separador de coma a otro formato.
