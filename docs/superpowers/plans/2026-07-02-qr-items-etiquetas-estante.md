# QR en ítems para etiquetas de estante — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generar un QR por ítem que enlaza a su ficha (`item_detalle`), mostrarlo en la ficha (imprimir/descargar) y ofrecer una hoja de etiquetas imprimible en lote filtrada a repuestos y consumibles.

**Architecture:** Un servicio puro `qr.py` aísla la librería `qrcode`. Un endpoint genera el PNG del QR al vuelo (`inventario/<pk>/qr.png`) codificando la URL absoluta de la ficha. La ficha y una nueva pantalla de etiquetas consumen ese endpoint con `<img>`.

**Tech Stack:** Django (`apps.core`), librería `qrcode` (usa Pillow, ya presente), plantillas Django + Bootstrap con CSS `@media print`. **Solo Docker.**

## Global Constraints

- **Tests / manage.py SOLO vía Docker**, con `--noinput` en test:
  `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core --noinput -v 1`
- **La imagen debe reconstruirse tras cambiar `requirements.txt`**: la imagen "baked" trae los paquetes instalados; el código se monta en vivo pero las dependencias no. Tras agregar `qrcode`, correr `docker compose build web` ANTES de cualquier test que lo importe.
- En tests de vistas usar `self.client.force_login(user)` (django-axes rompe `client.login`).
- Vistas de inventario en `apps/core/views/inventario.py` con `from .common import *` (provee `render`, `login_required`, `permission_required`, `_perm`, `get_object_or_404`, `reverse`). Reusar permiso `ver_inventario`. No se agregan permisos nuevos.
- **Orden de URLs**: en `apps/core/urls.py` las rutas de segmento fijo (`inventario/etiquetas/`) van ANTES de las paramétricas `inventario/<int:pk>/...`. La ruta `inventario/<int:pk>/qr.png` va junto a las demás `<int:pk>`.
- El QR codifica `request.build_absolute_uri(reverse('item_detalle', args=[item.pk]))`.
- Cada task deja `manage.py test apps.core --noinput` en verde.

---

### Task 1: Dependencia `qrcode` + servicio de generación

**Files:**
- Modify: `requirements.txt` (agregar `qrcode`)
- Create: `apps/core/services/qr.py`
- Test: `apps/core/tests_inventario/test_qr_service.py` (paquete NUEVO `apps/core/tests_inventario/` con `__init__.py`. NO usar `apps/core/tests/`: ya existe el módulo `apps/core/tests.py` y un paquete `tests/` colisionaría con él. Se sigue la convención del paquete `apps/core/tests_facturas/`.)

**Interfaces:**
- Produces: `apps.core.services.qr.qr_png_bytes(data: str) -> bytes` — PNG del QR para `data`.

- [ ] **Step 1: Agregar la dependencia y reconstruir la imagen**

En `requirements.txt`, agregar al final:

```
qrcode==7.4.2
```

Reconstruir la imagen para instalar la librería:
Run: `docker compose build web`
Expected: build OK, `qrcode` instalado.

- [ ] **Step 2: Escribir el test que falla**

Create `apps/core/tests_inventario/__init__.py` (vacío) y `apps/core/tests_inventario/test_qr_service.py`:

```python
from django.test import SimpleTestCase

from apps.core.services import qr


class QrServiceTests(SimpleTestCase):
    def test_devuelve_png_no_vacio(self):
        data = 'https://ejemplo.com/inventario/1/'
        out = qr.qr_png_bytes(data)
        self.assertIsInstance(out, bytes)
        self.assertGreater(len(out), 0)
        # Cabecera PNG.
        self.assertEqual(out[:8], b'\x89PNG\r\n\x1a\n')

    def test_datos_distintos_dan_pngs_distintos(self):
        a = qr.qr_png_bytes('https://ejemplo.com/inventario/1/')
        b = qr.qr_png_bytes('https://ejemplo.com/inventario/2/')
        self.assertNotEqual(a, b)
```

- [ ] **Step 3: Correr el test y verificar que falla**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_inventario.test_qr_service --noinput -v 2`
Expected: FAIL — `No module named 'apps.core.services.qr'`.

- [ ] **Step 4: Implementar el servicio**

Create `apps/core/services/qr.py`:

```python
"""qr — generación de códigos QR como PNG. Aísla la librería `qrcode`."""
import io

import qrcode


def qr_png_bytes(data):
    """Devuelve los bytes PNG de un código QR que codifica `data`."""
    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()
```

- [ ] **Step 5: Correr el test y verificar que pasa**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_inventario.test_qr_service --noinput -v 2`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add requirements.txt apps/core/services/qr.py apps/core/tests_inventario/
git commit -m "feat(inventario): servicio de generación de QR (dependencia qrcode)"
```

---

### Task 2: Endpoint de imagen QR del ítem

**Files:**
- Modify: `apps/core/views/inventario.py` (agregar la vista `item_qr_png`)
- Modify: `apps/core/urls.py` (ruta `inventario/<int:pk>/qr.png`)
- Test: `apps/core/tests_inventario/test_qr_views.py`

**Interfaces:**
- Consumes: `apps.core.services.qr.qr_png_bytes` (Task 1).
- Produces: URL `item_qr_png` (`inventario/<int:pk>/qr.png`) → `HttpResponse` PNG.

- [ ] **Step 1: Escribir el test que falla**

Create `apps/core/tests_inventario/test_qr_views.py`:

```python
from django.contrib.auth.models import User, Permission
from django.test import TestCase
from django.urls import reverse

from apps.core.models import Item


class ItemQrPngTests(TestCase):
    def setUp(self):
        self.item = Item.objects.create(
            codigo='R-001', nombre='Rodamiento', tipo='repuesto', unidad_medida='u')
        self.user = User.objects.create_user('u', password='x')
        self.user.user_permissions.add(Permission.objects.get(codename='ver_inventario'))

    def test_devuelve_png(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('item_qr_png', args=[self.item.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'image/png')
        self.assertEqual(resp.content[:8], b'\x89PNG\r\n\x1a\n')

    def test_sin_permiso_403(self):
        otro = User.objects.create_user('u2', password='x')
        self.client.force_login(otro)
        resp = self.client.get(reverse('item_qr_png', args=[self.item.pk]))
        self.assertEqual(resp.status_code, 403)

    def test_item_inexistente_404(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('item_qr_png', args=[999999]))
        self.assertEqual(resp.status_code, 404)
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_inventario.test_qr_views --noinput -v 2`
Expected: FAIL — `Reverse for 'item_qr_png' not found`.

- [ ] **Step 3: Agregar la vista**

En `apps/core/views/inventario.py`, agregar el import de `HttpResponse` y del servicio cerca de los imports del tope, y la vista (por ejemplo tras `item_detalle`):

```python
from django.http import HttpResponse
from ..services import qr as qr_service


@login_required
@permission_required(_perm('ver_inventario'), raise_exception=True)
def item_qr_png(request, pk):
    item = get_object_or_404(Item, pk=pk)
    url = request.build_absolute_uri(reverse('item_detalle', args=[item.pk]))
    return HttpResponse(qr_service.qr_png_bytes(url), content_type='image/png')
```

(Si `HttpResponse` ya está disponible vía `from .common import *`, no dupliques el import; `inventario.py` ya importa `from django.http import HttpResponseBadRequest`, así que agregar `HttpResponse` a esa línea o en una nueva es válido.)

- [ ] **Step 4: Agregar la URL**

En `apps/core/urls.py`, junto a las otras rutas `inventario/<int:pk>/...` (después de `item_detalle`):

```python
    path('inventario/<int:pk>/qr.png', views.item_qr_png, name='item_qr_png'),
```

- [ ] **Step 5: Correr y verificar que pasa**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_inventario.test_qr_views --noinput -v 2`
Expected: PASS (3 tests). Luego correr `apps.core` completo en verde.

- [ ] **Step 6: Commit**

```bash
git add apps/core/views/inventario.py apps/core/urls.py apps/core/tests_inventario/test_qr_views.py
git commit -m "feat(inventario): endpoint de imagen QR del ítem"
```

---

### Task 3: QR en la ficha del ítem

**Files:**
- Modify: `templates/inventario/detalle.html` (bloque QR + imprimir/descargar)
- Test: `apps/core/tests_inventario/test_qr_views.py` (agregar un test de render)

**Interfaces:**
- Consumes: URL `item_qr_png` (Task 2), `item` en el contexto de `item_detalle`.

- [ ] **Step 1: Escribir el test que falla**

Agregar a `apps/core/tests_inventario/test_qr_views.py` una clase:

```python
class ItemDetalleQrTests(TestCase):
    def setUp(self):
        self.item = Item.objects.create(
            codigo='R-002', nombre='Faja', tipo='consumible', unidad_medida='u')
        self.user = User.objects.create_user('v', password='x')
        self.user.user_permissions.add(Permission.objects.get(codename='ver_inventario'))
        self.client.force_login(self.user)

    def test_ficha_incluye_img_del_qr(self):
        resp = self.client.get(reverse('item_detalle', args=[self.item.pk]))
        self.assertEqual(resp.status_code, 200)
        qr_url = reverse('item_qr_png', args=[self.item.pk])
        self.assertContains(resp, qr_url)
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_inventario.test_qr_views.ItemDetalleQrTests --noinput -v 2`
Expected: FAIL — la ficha aún no incluye la URL del QR.

- [ ] **Step 3: Agregar el bloque QR a la ficha**

Leer `templates/inventario/detalle.html` para ubicar un lugar coherente (p. ej. una tarjeta lateral o al final de los datos del ítem). Agregar:

```html
<div class="card mb-3" id="qr-etiqueta">
  <div class="card-body text-center">
    <h2 class="h6 text-muted">Etiqueta QR</h2>
    <img src="{% url 'item_qr_png' item.pk %}" alt="QR {{ item.codigo }}"
         style="width:160px;height:160px" class="my-2">
    <div class="small text-muted">{{ item.codigo }}</div>
    <div class="d-flex gap-2 justify-content-center mt-2 d-print-none">
      <button type="button" class="btn btn-sm btn-outline-secondary" onclick="window.print()">
        <i class="bi bi-printer"></i> Imprimir
      </button>
      <a class="btn btn-sm btn-outline-secondary" href="{% url 'item_qr_png' item.pk %}" download="qr-{{ item.codigo }}.png">
        <i class="bi bi-download"></i> Descargar PNG
      </a>
    </div>
  </div>
</div>
```

(Verificar que `item` está en el contexto — lo está: `item_detalle` pasa `{'item': item, ...}`. `d-print-none` de Bootstrap oculta los botones al imprimir.)

- [ ] **Step 4: Correr y verificar que pasa**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_inventario.test_qr_views.ItemDetalleQrTests --noinput -v 2`
Expected: PASS. Luego `apps.core` completo en verde.

- [ ] **Step 5: Commit**

```bash
git add templates/inventario/detalle.html apps/core/tests_inventario/test_qr_views.py
git commit -m "feat(inventario): QR con imprimir/descargar en la ficha del ítem"
```

---

### Task 4: Hoja de etiquetas en lote

**Files:**
- Modify: `apps/core/views/inventario.py` (vista `item_etiquetas`)
- Modify: `apps/core/urls.py` (ruta `inventario/etiquetas/`, ANTES de `inventario/<int:pk>/`)
- Create: `templates/inventario/etiquetas.html`
- Modify: `templates/inventario/lista.html` (botón "Etiquetas QR") — verificar el nombre real del template de `inventario_lista`
- Modify: `templates/includes/nav_menu.html` (enlace bajo Inventario)
- Test: `apps/core/tests_inventario/test_qr_views.py` (clase para la hoja)

**Interfaces:**
- Consumes: modelo `Item` (campos `tipo`, `categoria`, `activo`), URL `item_qr_png`.
- Produces: URL `item_etiquetas` (`inventario/etiquetas/`).

- [ ] **Step 1: Escribir el test que falla**

Agregar a `apps/core/tests_inventario/test_qr_views.py`:

```python
class ItemEtiquetasTests(TestCase):
    def setUp(self):
        self.rep = Item.objects.create(codigo='R-1', nombre='Rep', tipo='repuesto', unidad_medida='u')
        self.con = Item.objects.create(codigo='C-1', nombre='Con', tipo='consumible', unidad_medida='u')
        self.prod = Item.objects.create(codigo='P-1', nombre='Prod', tipo='producto', unidad_medida='u')
        self.user = User.objects.create_user('w', password='x')
        self.user.user_permissions.add(Permission.objects.get(codename='ver_inventario'))
        self.client.force_login(self.user)

    def test_por_defecto_solo_repuestos_y_consumibles(self):
        resp = self.client.get(reverse('item_etiquetas'))
        self.assertEqual(resp.status_code, 200)
        items = list(resp.context['items'])
        self.assertIn(self.rep, items)
        self.assertIn(self.con, items)
        self.assertNotIn(self.prod, items)

    def test_filtro_tipo_producto(self):
        resp = self.client.get(reverse('item_etiquetas'), {'tipo': 'producto'})
        items = list(resp.context['items'])
        self.assertEqual(items, [self.prod])

    def test_filtro_todos(self):
        resp = self.client.get(reverse('item_etiquetas'), {'tipo': 'todos'})
        items = list(resp.context['items'])
        self.assertEqual(set(items), {self.rep, self.con, self.prod})

    def test_sin_permiso_403(self):
        self.client.logout()
        self.client.force_login(User.objects.create_user('w2', password='x'))
        resp = self.client.get(reverse('item_etiquetas'))
        self.assertEqual(resp.status_code, 403)
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_inventario.test_qr_views.ItemEtiquetasTests --noinput -v 2`
Expected: FAIL — `Reverse for 'item_etiquetas' not found`.

- [ ] **Step 3: Agregar la vista**

En `apps/core/views/inventario.py`:

```python
@login_required
@permission_required(_perm('ver_inventario'), raise_exception=True)
def item_etiquetas(request):
    tipo = request.GET.get('tipo', '')
    items = Item.objects.filter(activo=True)
    if tipo in ('producto', 'repuesto', 'consumible'):
        items = items.filter(tipo=tipo)
    elif tipo == 'todos':
        pass
    else:
        # Por defecto: solo repuestos y consumibles.
        items = items.filter(tipo__in=['repuesto', 'consumible'])
    categoria_id = request.GET.get('categoria', '')
    if categoria_id:
        items = items.filter(categoria_id=categoria_id)
    items = items.order_by('tipo', 'orden', 'nombre')
    return render(request, 'inventario/etiquetas.html', {
        'items': items,
        'tipo': tipo,
        'categoria_id': categoria_id,
        'categorias': Categoria.objects.all(),
    })
```

(`Categoria` está disponible en el módulo vía `from .common import *` / modelos; si no, importarla desde `..models`.)

- [ ] **Step 4: Agregar la URL (segmento fijo, ANTES de `<int:pk>`)**

En `apps/core/urls.py`, junto a `inventario/tabs/orden/` (rutas de segmento fijo, antes de `inventario/<int:pk>/`):

```python
    path('inventario/etiquetas/', views.item_etiquetas, name='item_etiquetas'),
```

- [ ] **Step 5: Plantilla imprimible**

Create `templates/inventario/etiquetas.html`:

```html
{% extends "base.html" %}
{% block title %}Etiquetas QR{% endblock %}
{% block content %}
<div class="page-header d-flex justify-content-between align-items-center d-print-none">
  <h1 class="h4 mb-0"><i class="bi bi-qr-code me-2"></i>Etiquetas QR</h1>
  <button type="button" class="btn btn-primary btn-sm" onclick="window.print()">
    <i class="bi bi-printer me-1"></i>Imprimir
  </button>
</div>

<form method="get" class="row g-2 align-items-end mb-3 d-print-none">
  <div class="col-6 col-md-3">
    <label class="form-label">Tipo</label>
    <select name="tipo" class="form-select">
      <option value="" {% if tipo == '' %}selected{% endif %}>Repuestos y consumibles</option>
      <option value="repuesto" {% if tipo == 'repuesto' %}selected{% endif %}>Solo repuestos</option>
      <option value="consumible" {% if tipo == 'consumible' %}selected{% endif %}>Solo consumibles</option>
      <option value="producto" {% if tipo == 'producto' %}selected{% endif %}>Solo productos</option>
      <option value="todos" {% if tipo == 'todos' %}selected{% endif %}>Todos</option>
    </select>
  </div>
  <div class="col-6 col-md-3">
    <label class="form-label">Categoría</label>
    <select name="categoria" class="form-select">
      <option value="">Todas</option>
      {% for c in categorias %}
      <option value="{{ c.pk }}" {% if categoria_id == c.pk|stringformat:'s' %}selected{% endif %}>{{ c.nombre }}</option>
      {% endfor %}
    </select>
  </div>
  <div class="col-auto">
    <button class="btn btn-outline-secondary">Filtrar</button>
  </div>
</form>

<div class="etiquetas-grid">
  {% for item in items %}
  <div class="etiqueta">
    <img src="{% url 'item_qr_png' item.pk %}" alt="QR {{ item.codigo }}">
    <div class="etiqueta-codigo">{{ item.codigo }}</div>
    <div class="etiqueta-nombre">{{ item.nombre }}</div>
  </div>
  {% empty %}
  <p class="text-muted">No hay ítems para el filtro seleccionado.</p>
  {% endfor %}
</div>

<style>
  .etiquetas-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 10px;
  }
  .etiqueta {
    border: 1px solid #ccc;
    border-radius: 6px;
    padding: 8px;
    text-align: center;
    break-inside: avoid;
  }
  .etiqueta img { width: 120px; height: 120px; }
  .etiqueta-codigo { font-weight: 700; font-size: .9rem; }
  .etiqueta-nombre { font-size: .75rem; color: #555; }
  @media print {
    .etiquetas-grid { grid-template-columns: repeat(3, 1fr); gap: 6px; }
    .etiqueta { border: 1px solid #999; }
  }
</style>
{% endblock %}
```

- [ ] **Step 6: Enlaces de acceso**

Leer `templates/inventario/lista.html` (el template de `inventario_lista` — verificar el nombre exacto con `grep -n "render" apps/core/views/inventario.py` en la función `inventario_lista`) y agregar en su encabezado, junto a los botones existentes:

```html
{% if perms.core.ver_inventario %}
<a href="{% url 'item_etiquetas' %}" class="btn btn-outline-secondary btn-sm">
  <i class="bi bi-qr-code me-1"></i>Etiquetas QR
</a>
{% endif %}
```

En `templates/includes/nav_menu.html`, justo debajo del enlace "Inventario" (línea ~8-10), agregar:

```html
{% if perms.core.ver_inventario %}
<a href="{% url 'item_etiquetas' %}" class="nav-link {% if un == 'item_etiquetas' %}active{% endif %}">
  <i class="bi bi-qr-code"></i> Etiquetas QR
</a>
{% endif %}
```

- [ ] **Step 7: Correr y verificar que pasa**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_inventario.test_qr_views.ItemEtiquetasTests --noinput -v 2`
Expected: PASS (4 tests). Luego `apps.core` completo en verde.

- [ ] **Step 8: Commit**

```bash
git add apps/core/views/inventario.py apps/core/urls.py templates/inventario/etiquetas.html templates/inventario/lista.html templates/includes/nav_menu.html apps/core/tests_inventario/test_qr_views.py
git commit -m "feat(inventario): hoja de etiquetas QR en lote (repuestos y consumibles)"
```

---

## Notas de despliegue

- La dependencia nueva `qrcode` requiere **rebuild de la imagen** en el próximo deploy (Portainer: pull/rebuild, no solo restart), igual que cualquier cambio de `requirements.txt`. No hay migraciones en esta feature.
- El QR se genera al vuelo desde el host de la petición, así que al imprimir desde el sitio en producción queda con el dominio real; no requiere configuración.
