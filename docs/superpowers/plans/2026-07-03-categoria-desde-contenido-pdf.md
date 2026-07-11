# Categoría desde contenido del PDF — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extender la clasificación de categorías para que busque la `palabra_clave` en el contenido extraído del PDF (además del nombre del archivo), y para que facturas sin coincidencia queden sin categoría en lugar de usar la predeterminada.

**Architecture:** Todo el cambio vive en `invoice_service.py`. Se cambia la firma de `clasificar_categoria` para recibir un haystack libre (nombre + texto del PDF) y un flag `con_predeterminada`. `previsualizar` y `crear_documento` arman ese haystack y usan el flag correcto según el tipo de documento.

**Tech Stack:** Django ORM, PyMuPDF (ya usados — sin dependencias nuevas).

## Global Constraints

- TDD: escribir el test que falla (RED) antes de implementar.
- Tests corren siempre en Docker: `docker compose run --rm --no-deps -v "$(pwd)":/app --entrypoint python web manage.py test <path> --noinput`
- No migraciones de esquema — solo cambio de datos en admin para `palabra_clave = "lisa, blanca"`.
- No cambiar `CategoriaProducto.predeterminada()` ni lógica de tarifa en envíos.
- Categorías activas de referencia: Camiseta (`camiseta`), Lisa (`lisa, blanca`), Poliducto (`poliducto`).

---

## Mapa de archivos

| Archivo | Acción | Qué cambia |
|---|---|---|
| `apps/core/services/facturas/invoice_service.py` | Modificar | `clasificar_categoria`, `previsualizar`, `crear_documento` |
| `apps/core/tests_facturas/test_clasificar_categoria.py` | Modificar | Añadir tests de multi-keyword y `con_predeterminada` |
| `apps/core/tests_facturas/test_invoice_service.py` | Modificar | Añadir clases `PrevisualizarCategoriaTests` y `CrearDocumentoCategoriaTests` |

---

## Task 1: Actualizar `clasificar_categoria` — multi-keyword y `con_predeterminada`

**Files:**
- Modify: `apps/core/services/facturas/invoice_service.py:19-27`
- Test: `apps/core/tests_facturas/test_clasificar_categoria.py`

**Interfaces:**
- Produce: `clasificar_categoria(haystack: str, con_predeterminada: bool = True) -> CategoriaProducto | None`
  - Busca cada parte de `palabra_clave` (split por coma) en `haystack` (case-insensitive).
  - Primera categoría activa que coincida gana (orden por `orden, nombre`).
  - Sin coincidencia: devuelve `CategoriaProducto.predeterminada()` si `con_predeterminada=True`, `None` si `False`.

- [ ] **Step 1: Escribir los tests que fallan**

Añadir al final de `apps/core/tests_facturas/test_clasificar_categoria.py`:

```python
    def test_multiples_keywords_primera_parte_coincide(self):
        self.lisa.palabra_clave = 'lisa, blanca'
        self.lisa.save(update_fields=['palabra_clave'])
        c = invoice_service.clasificar_categoria('Lb Bolsa Lisa\n345 kg')
        self.assertEqual(c, self.lisa)

    def test_multiples_keywords_segunda_parte_coincide(self):
        self.lisa.palabra_clave = 'lisa, blanca'
        self.lisa.save(update_fields=['palabra_clave'])
        c = invoice_service.clasificar_categoria('Lb Bolsa Blanca\n345 kg')
        self.assertEqual(c, self.lisa)

    def test_sin_coincidencia_con_predeterminada_false_devuelve_none(self):
        c = invoice_service.clasificar_categoria('Rollo de Poliducto x 100yd', con_predeterminada=False)
        self.assertIsNone(c)

    def test_sin_coincidencia_con_predeterminada_true_devuelve_predeterminada(self):
        c = invoice_service.clasificar_categoria('Rollo de Poliducto x 100yd', con_predeterminada=True)
        self.assertEqual(c, self.lisa)

    def test_keyword_en_segunda_linea_del_haystack(self):
        # Simula: primera línea = nombre del archivo, segunda = texto del PDF
        c = invoice_service.clasificar_categoria('Fact 9544 Inversiones San Juan.pdf\nLb Bolsa Camiseta\n2000.00')
        self.assertEqual(c, self.camiseta)
```

- [ ] **Step 2: Verificar que los tests fallan (RED)**

```bash
docker compose run --rm --no-deps -v "$(pwd)":/app --entrypoint python web manage.py test apps.core.tests_facturas.test_clasificar_categoria --noinput 2>&1 | tail -20
```

Esperado: `FAIL` en los 5 tests nuevos. Los tests existentes deben seguir en `OK`.

- [ ] **Step 3: Implementar el cambio en `clasificar_categoria`**

Reemplazar las líneas 19-27 de `apps/core/services/facturas/invoice_service.py`:

```python
def clasificar_categoria(haystack, con_predeterminada=True):
    """Primera categoría activa cuya palabra_clave aparece en haystack (case-insensitive).

    palabra_clave puede contener varias palabras separadas por coma: cualquiera que coincida cuenta.
    Si ninguna categoría coincide: devuelve predeterminada() si con_predeterminada=True, else None.
    """
    texto = (haystack or '').lower()
    for cat in CategoriaProducto.objects.filter(activa=True).order_by('orden', 'nombre'):
        kw = (cat.palabra_clave or '').strip()
        if kw and any(p.strip().lower() in texto for p in kw.split(',')):
            return cat
    return CategoriaProducto.predeterminada() if con_predeterminada else None
```

- [ ] **Step 4: Verificar que todos los tests pasan (GREEN)**

```bash
docker compose run --rm --no-deps -v "$(pwd)":/app --entrypoint python web manage.py test apps.core.tests_facturas.test_clasificar_categoria --noinput 2>&1 | tail -10
```

Esperado: `Ran 10 tests ... OK`

- [ ] **Step 5: Commit**

```bash
git add apps/core/services/facturas/invoice_service.py \
        apps/core/tests_facturas/test_clasificar_categoria.py
git commit -m "feat(facturas): clasificar_categoria acepta haystack libre y palabras clave múltiples"
```

---

## Task 2: Actualizar `previsualizar` — clasificar facturas también

**Files:**
- Modify: `apps/core/services/facturas/invoice_service.py:64-68`
- Test: `apps/core/tests_facturas/test_invoice_service.py`

**Interfaces:**
- Consume: `clasificar_categoria(haystack, con_predeterminada=True)` (Task 1)
- Produce: `previsualizar(tipo_documento, archivo)` → `datos['categoria_id']` presente cuando hay coincidencia para facturas; ausente cuando no coincide.

- [ ] **Step 1: Escribir los tests que fallan**

Añadir al final de `apps/core/tests_facturas/test_invoice_service.py`:

```python
from unittest.mock import patch


class PrevisualizarCategoriaTests(TestCase):
    def setUp(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        CategoriaProducto.objects.all().delete()
        self.camiseta = CategoriaProducto.objects.create(
            nombre='Camiseta', palabra_clave='camiseta', orden=0)
        self.lisa = CategoriaProducto.objects.create(
            nombre='Lisa', palabra_clave='lisa, blanca', es_predeterminada=True, orden=1)
        self.SimpleUploadedFile = SimpleUploadedFile

    def _run_previsualizar(self, tipo, nombre_archivo, texto_pdf):
        archivo = self.SimpleUploadedFile(nombre_archivo, b'%PDF', content_type='application/pdf')
        with patch('apps.core.services.facturas.invoice_service.pdf_service') as mock_pdf, \
             patch('apps.core.services.facturas.invoice_service.filename_extractor') as mock_fe:
            mock_pdf.extraer_texto.return_value = texto_pdf
            mock_pdf.get_extractor.return_value.extraer.return_value = {}
            mock_fe.extraer_de_nombre.return_value = {}
            return invoice_service.previsualizar(tipo, archivo)

    def test_factura_keyword_en_contenido_asigna_categoria(self):
        result = self._run_previsualizar(
            'factura', 'Fact 9546 Tekniplasticos.pdf', 'Lb Bolsa Camiseta\n2000.00')
        self.assertEqual(result['datos']['categoria_id'], self.camiseta.pk)

    def test_factura_sin_coincidencia_no_incluye_categoria_id(self):
        result = self._run_previsualizar(
            'factura', 'Fact 9544 Inversiones San Juan.pdf', 'Rollo de Poliducto x 100yd')
        self.assertNotIn('categoria_id', result['datos'])

    def test_envio_sin_coincidencia_usa_predeterminada(self):
        result = self._run_previsualizar(
            'envio', 'Envio 123 Cliente.pdf', 'texto sin keywords')
        self.assertEqual(result['datos']['categoria_id'], self.lisa.pk)

    def test_envio_keyword_en_contenido_asigna_categoria(self):
        result = self._run_previsualizar(
            'envio', 'Envio 123 Cliente.pdf', 'Lb Bolsa Camiseta\n500 Lb')
        self.assertEqual(result['datos']['categoria_id'], self.camiseta.pk)
```

- [ ] **Step 2: Verificar que los tests fallan (RED)**

```bash
docker compose run --rm --no-deps -v "$(pwd)":/app --entrypoint python web manage.py test apps.core.tests_facturas.test_invoice_service.PrevisualizarCategoriaTests --noinput 2>&1 | tail -20
```

Esperado: `FAIL` en `test_factura_keyword_en_contenido_asigna_categoria` y `test_factura_sin_coincidencia_no_incluye_categoria_id` (el bloque factura no existe aún). Los tests de envío también fallan porque el haystack no incluye `texto` todavía.

- [ ] **Step 3: Implementar el cambio en `previsualizar`**

Reemplazar las líneas 64-68 de `apps/core/services/facturas/invoice_service.py`:

```python
    # Sugerir categoría para preseleccionar al revisar (factura: solo si hay coincidencia).
    haystack = nombre + '\n' + texto
    if tipo_documento == 'envio':
        cat = clasificar_categoria(haystack)
        if cat is not None:
            datos['categoria_id'] = cat.pk
    elif tipo_documento == 'factura':
        cat = clasificar_categoria(haystack, con_predeterminada=False)
        if cat is not None:
            datos['categoria_id'] = cat.pk
```

El bloque anterior era:
```python
    # Envío: sugerir la categoría según el nombre del archivo (para preseleccionar al revisar).
    if tipo_documento == 'envio':
        cat = clasificar_categoria(nombre)
        if cat is not None:
            datos['categoria_id'] = cat.pk
```

- [ ] **Step 4: Verificar que todos los tests de invoice_service pasan (GREEN)**

```bash
docker compose run --rm --no-deps -v "$(pwd)":/app --entrypoint python web manage.py test apps.core.tests_facturas.test_invoice_service --noinput 2>&1 | tail -10
```

Esperado: `Ran N tests ... OK`

- [ ] **Step 5: Commit**

```bash
git add apps/core/services/facturas/invoice_service.py \
        apps/core/tests_facturas/test_invoice_service.py
git commit -m "feat(facturas): previsualizar sugiere categoría para facturas desde el contenido del PDF"
```

---

## Task 3: Actualizar `crear_documento` — auto-clasificar desde `texto_extraido`

**Files:**
- Modify: `apps/core/services/facturas/invoice_service.py:98-107`
- Test: `apps/core/tests_facturas/test_invoice_service.py`

**Interfaces:**
- Consume: `clasificar_categoria(haystack, con_predeterminada=True)` (Task 1)
- Produce: `crear_documento(...)` → para facturas sin `categoria` explícita, busca en `texto_extraido`; sin coincidencia `doc.categoria` queda `None`. Para envíos sin `categoria` explícita, usa predeterminada si no hay coincidencia (comportamiento actual).

- [ ] **Step 1: Escribir los tests que fallan**

Añadir al final de `apps/core/tests_facturas/test_invoice_service.py`, después de `PrevisualizarCategoriaTests`:

```python
class CrearDocumentoCategoriaTests(TestCase):
    def setUp(self):
        from decimal import Decimal
        CategoriaProducto.objects.all().delete()
        self.cliente = Cliente.objects.create(nombre='Cliente Test')
        self.camiseta = CategoriaProducto.objects.create(
            nombre='Camiseta', palabra_clave='camiseta', orden=0)
        self.lisa = CategoriaProducto.objects.create(
            nombre='Lisa', palabra_clave='lisa, blanca', es_predeterminada=True, orden=1)

    def test_factura_keyword_en_texto_extraido_asigna_categoria(self):
        doc = invoice_service.crear_documento(
            cliente=self.cliente,
            tipo_documento='factura',
            texto_extraido='Lb Bolsa Camiseta\n2000.00',
        )
        self.assertEqual(doc.categoria, self.camiseta)

    def test_factura_sin_coincidencia_queda_sin_categoria(self):
        doc = invoice_service.crear_documento(
            cliente=self.cliente,
            tipo_documento='factura',
            texto_extraido='Rollo de Poliducto x 100yd',
        )
        self.assertIsNone(doc.categoria)

    def test_envio_keyword_en_texto_extraido_asigna_categoria(self):
        doc = invoice_service.crear_documento(
            cliente=self.cliente,
            tipo_documento='envio',
            texto_extraido='Lb Bolsa Camiseta\n500 Lb',
        )
        self.assertEqual(doc.categoria, self.camiseta)

    def test_envio_sin_coincidencia_usa_predeterminada(self):
        doc = invoice_service.crear_documento(
            cliente=self.cliente,
            tipo_documento='envio',
            texto_extraido='Rollo de Poliducto x 100yd',
        )
        self.assertEqual(doc.categoria, self.lisa)

    def test_categoria_explicita_no_se_sobreescribe(self):
        doc = invoice_service.crear_documento(
            cliente=self.cliente,
            tipo_documento='factura',
            categoria=self.camiseta,
            texto_extraido='Lb Bolsa Lisa',  # keyword de lisa, pero pasamos camiseta
        )
        self.assertEqual(doc.categoria, self.camiseta)
```

- [ ] **Step 2: Verificar que los tests fallan (RED)**

```bash
docker compose run --rm --no-deps -v "$(pwd)":/app --entrypoint python web manage.py test apps.core.tests_facturas.test_invoice_service.CrearDocumentoCategoriaTests --noinput 2>&1 | tail -20
```

Esperado: `FAIL` en al menos `test_factura_keyword_en_texto_extraido_asigna_categoria` y `test_envio_keyword_en_texto_extraido_asigna_categoria` (la clasificación actual usa solo el nombre del archivo, no `texto_extraido`).

- [ ] **Step 3: Implementar el cambio en `crear_documento`**

Reemplazar las líneas 98-107 de `apps/core/services/facturas/invoice_service.py`:

```python
    if tipo_documento == 'envio':
        if categoria is None:
            nombre = getattr(archivo, 'name', '') or ''
            categoria = clasificar_categoria(nombre + '\n' + texto_extraido)
        doc.categoria = categoria
        tarifa = TarifaCliente.activa_para(cliente, categoria) if categoria else None
        if tarifa and doc.total_libras is not None:
            doc.precio_por_libra = tarifa.precio_por_libra
            doc.monto_total = (doc.total_libras * tarifa.precio_por_libra).quantize(Decimal('0.01'))
    else:
        if categoria is None:
            nombre = getattr(archivo, 'name', '') or ''
            categoria = clasificar_categoria(nombre + '\n' + texto_extraido, con_predeterminada=False)
        if categoria is not None:
            doc.categoria = categoria
```

El bloque anterior era:
```python
    if tipo_documento == 'envio':
        if categoria is None:
            categoria = clasificar_categoria(getattr(archivo, 'name', '') or '')
        doc.categoria = categoria
        tarifa = TarifaCliente.activa_para(cliente, categoria) if categoria else None
        if tarifa and doc.total_libras is not None:
            doc.precio_por_libra = tarifa.precio_por_libra
            doc.monto_total = (doc.total_libras * tarifa.precio_por_libra).quantize(Decimal('0.01'))
    elif categoria is not None:
        doc.categoria = categoria
```

- [ ] **Step 4: Verificar que todos los tests de facturas pasan (GREEN)**

```bash
docker compose run --rm --no-deps -v "$(pwd)":/app --entrypoint python web manage.py test apps.core.tests_facturas --noinput 2>&1 | tail -15
```

Esperado: `Ran N tests ... OK` — todos los tests nuevos y los existentes.

- [ ] **Step 5: Commit**

```bash
git add apps/core/services/facturas/invoice_service.py \
        apps/core/tests_facturas/test_invoice_service.py
git commit -m "feat(facturas): crear_documento clasifica categoría desde contenido del PDF"
```

---

## Post-implementación: actualizar dato en admin

Una vez desplegado, entrar al admin de Django y editar la categoría **Lisa**:
- Campo `palabra_clave`: cambiar a `lisa, blanca`

Esto no requiere migración ni código — es solo configuración de datos.
