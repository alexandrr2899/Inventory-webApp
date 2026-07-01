# Categorías de producto configurables + filtro — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reemplazar las categorías de producto fijas (`camiseta/lisa/otro`) por un modelo `CategoriaProducto` configurable con CRUD, migrar `producto` (facturas y tarifas) a FK, auto-clasificar envíos por palabra clave + categoría por defecto, y exponer el filtro por categoría en la lista.

**Architecture:** Nuevo modelo `CategoriaProducto` (patrón de `MetodoPago`). Se agrega FK `categoria` a `DocumentoFactura` y `TarifaCliente`, se migran los datos, y un cutover cambia servicio/clasificador/tarifas/formularios/display/filtro del string `producto` a la FK. Finalmente se retira el CharField `producto`.

**Tech Stack:** Django (`apps.core`), plantillas Django + Bootstrap, tests `django.test.TestCase`. **Solo Docker.**

## Global Constraints

- **Tests / manage.py SOLO vía Docker**, con `--noinput` en test (una BD de test previa provoca prompt interactivo → `EOFError`):
  `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core --noinput -v 1`
  makemigrations: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py makemigrations core`
- En tests de vistas usar `self.client.force_login(user)` (django-axes rompe `client.login`).
- Vistas en `apps/core/views/<modulo>.py` con `from .common import *`; usar `_perm('<codename>')` y `@login_required`/`@permission_required(..., raise_exception=True)`/`@facturas_enabled`.
- Última migración de `core`: `0023_delete_pagofactura`; las nuevas numeran `0024+`. Verificar con `makemigrations --check --dry-run`.
- Cada task deja `manage.py test apps.core --noinput` en verde.
- Plantillas base: `{% extends "base.html" %}` con `{% block title %}` y `{% block content %}`. Modelar CRUD nuevo sobre `templates/metodos_pago/` o `templates/maquinas/`.

---

### Task 1: Modelo `CategoriaProducto`

**Files:**
- Modify: `apps/core/models.py` (agregar tras `PRODUCTO_CHOICES`, antes de `class TarifaCliente`)
- Modify: `apps/core/admin.py`
- Create: `apps/core/migrations/0024_categoriaproducto.py` (autogenerada)
- Test: `apps/core/tests_facturas/test_categoria_producto.py`

**Interfaces:**
- Produces: `CategoriaProducto(nombre, palabra_clave, es_predeterminada, activa, orden)`; `CategoriaProducto.predeterminada()` (classmethod → instancia o None); `save()` garantiza a lo sumo una `es_predeterminada=True`; permiso `gestionar_categorias_producto`; `__str__ → nombre`.

- [ ] **Step 1: Escribir el test que falla**

Create `apps/core/tests_facturas/test_categoria_producto.py`:

```python
from django.test import TestCase

from apps.core.models import CategoriaProducto


class CategoriaProductoTests(TestCase):
    def test_str_y_defaults(self):
        c = CategoriaProducto.objects.create(nombre='Camiseta', palabra_clave='camiseta')
        self.assertEqual(str(c), 'Camiseta')
        self.assertTrue(c.activa)
        self.assertFalse(c.es_predeterminada)
        self.assertEqual(c.orden, 0)

    def test_una_sola_predeterminada(self):
        a = CategoriaProducto.objects.create(nombre='Lisa', es_predeterminada=True)
        b = CategoriaProducto.objects.create(nombre='Camiseta', es_predeterminada=True)
        a.refresh_from_db()
        self.assertFalse(a.es_predeterminada)
        self.assertTrue(b.es_predeterminada)
        self.assertEqual(CategoriaProducto.predeterminada(), b)

    def test_predeterminada_none_si_ninguna(self):
        CategoriaProducto.objects.create(nombre='Otro')
        self.assertIsNone(CategoriaProducto.predeterminada())
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_facturas.test_categoria_producto --noinput -v 2`
Expected: FAIL — `cannot import name 'CategoriaProducto'`.

- [ ] **Step 3: Agregar el modelo**

En `apps/core/models.py`, justo después del bloque `PRODUCTO_CHOICES = [...]` y antes de `class TarifaCliente`:

```python
class CategoriaProducto(models.Model):
    nombre = models.CharField(max_length=60)
    palabra_clave = models.CharField(
        max_length=60, blank=True,
        help_text='Si el nombre del archivo la contiene, el envío se clasifica en esta categoría.')
    es_predeterminada = models.BooleanField(
        default=False,
        help_text='Categoría asignada cuando ninguna palabra clave coincide.')
    activa = models.BooleanField(default=True)
    orden = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'Categoría de producto'
        verbose_name_plural = 'Categorías de producto'
        ordering = ['orden', 'nombre']
        permissions = [
            ('gestionar_categorias_producto', 'Puede gestionar categorías de producto'),
        ]

    def __str__(self):
        return self.nombre

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.es_predeterminada:
            CategoriaProducto.objects.exclude(pk=self.pk).filter(
                es_predeterminada=True).update(es_predeterminada=False)

    @classmethod
    def predeterminada(cls):
        return cls.objects.filter(es_predeterminada=True).first()
```

- [ ] **Step 4: Registrar en admin**

En `apps/core/admin.py`, agregar `CategoriaProducto` al import desde `..models` y al final:

```python
@admin.register(CategoriaProducto)
class CategoriaProductoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'palabra_clave', 'es_predeterminada', 'activa', 'orden')
    list_filter = ('activa', 'es_predeterminada')
    search_fields = ('nombre', 'palabra_clave')
```

- [ ] **Step 5: Crear migración y correr el test**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py makemigrations core`
Then: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_facturas.test_categoria_producto --noinput -v 2`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add apps/core/models.py apps/core/admin.py apps/core/migrations/0024_categoriaproducto.py apps/core/tests_facturas/test_categoria_producto.py
git commit -m "feat(facturas): modelo CategoriaProducto configurable"
```

---

### Task 2: FK `categoria` (nullable) en ambos modelos + siembra + migración de datos

**Files:**
- Modify: `apps/core/models.py` (`DocumentoFactura` y `TarifaCliente`: agregar FK `categoria`)
- Create: `apps/core/migrations/0025_add_categoria_fk.py` (autogenerada: 2 AddField)
- Create: `apps/core/migrations/0026_sembrar_y_migrar_categorias.py` (a mano, RunPython)
- Create: `apps/core/services/facturas/categorias.py` (helper reutilizable de siembra/mapeo)
- Test: `apps/core/tests_facturas/test_migracion_categorias.py`

**Interfaces:**
- Consumes: `CategoriaProducto` (Task 1).
- Produces: `DocumentoFactura.categoria` y `TarifaCliente.categoria` (FK nullable, PROTECT); `services.facturas.categorias.sembrar_y_migrar(CategoriaProducto, DocumentoFactura, TarifaCliente)` que crea Camiseta/Lisa(default)/Otro y mapea los strings existentes.

- [ ] **Step 1: Escribir el test que falla**

Create `apps/core/tests_facturas/test_migracion_categorias.py`:

```python
from django.test import TestCase

from apps.core.models import (
    Cliente, DocumentoFactura, TarifaCliente, CategoriaProducto,
)
from apps.core.services.facturas import categorias


class MigracionCategoriasTests(TestCase):
    def setUp(self):
        self.cli = Cliente.objects.create(nombre='Cli')
        self.doc = DocumentoFactura.objects.create(
            cliente=self.cli, tipo_documento='envio', producto='camiseta')
        self.tar = TarifaCliente.objects.create(
            cliente=self.cli, producto='lisa', precio_por_libra=10)

    def test_siembra_tres_categorias_con_predeterminada_lisa(self):
        categorias.sembrar_y_migrar(CategoriaProducto, DocumentoFactura, TarifaCliente)
        nombres = set(CategoriaProducto.objects.values_list('nombre', flat=True))
        self.assertEqual(nombres, {'Camiseta', 'Lisa', 'Otro'})
        self.assertEqual(CategoriaProducto.predeterminada().nombre, 'Lisa')

    def test_mapea_strings_a_fk(self):
        categorias.sembrar_y_migrar(CategoriaProducto, DocumentoFactura, TarifaCliente)
        self.doc.refresh_from_db(); self.tar.refresh_from_db()
        self.assertEqual(self.doc.categoria.nombre, 'Camiseta')
        self.assertEqual(self.tar.categoria.nombre, 'Lisa')
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_facturas.test_migracion_categorias --noinput -v 2`
Expected: FAIL — `No module named 'apps.core.services.facturas.categorias'` (o falta el campo `categoria`).

- [ ] **Step 3: Agregar los FK `categoria`**

En `apps/core/models.py`, en `DocumentoFactura` (junto a `producto`):

```python
    categoria = models.ForeignKey(
        'CategoriaProducto', on_delete=models.PROTECT, null=True, blank=True,
        related_name='documentos')
```

En `TarifaCliente` (junto a `producto`):

```python
    categoria = models.ForeignKey(
        'CategoriaProducto', on_delete=models.PROTECT, null=True, blank=True,
        related_name='tarifas')
```

- [ ] **Step 4: Helper de siembra/mapeo**

Create `apps/core/services/facturas/categorias.py`:

```python
"""categorias — siembra inicial de CategoriaProducto y mapeo de los strings viejos.

Recibe las clases como argumentos para usarse desde una data migration
(modelos históricos) y desde tests (modelos reales)."""

_SIEMBRA = [
    # (nombre, palabra_clave, es_predeterminada, orden)
    ('Camiseta', 'camiseta', False, 0),
    ('Lisa', 'lisa', True, 1),
    ('Otro', '', False, 2),
]

# string viejo de producto -> nombre de categoría
_MAPA = {'camiseta': 'Camiseta', 'lisa': 'Lisa', 'otro': 'Otro'}


def sembrar_y_migrar(CategoriaProducto, DocumentoFactura, TarifaCliente):
    por_nombre = {}
    for nombre, kw, default, orden in _SIEMBRA:
        obj, _ = CategoriaProducto.objects.get_or_create(
            nombre=nombre,
            defaults={'palabra_clave': kw, 'es_predeterminada': default, 'orden': orden})
        por_nombre[nombre] = obj

    def cat_para(prod, default_nombre=None):
        nombre = _MAPA.get((prod or '').strip().lower())
        if not nombre:
            nombre = default_nombre
        return por_nombre.get(nombre) if nombre else None

    for doc in DocumentoFactura.objects.all():
        cat = cat_para(doc.producto)          # documentos sin producto quedan sin categoría
        if cat is not None:
            doc.categoria = cat
            doc.save(update_fields=['categoria'])

    for tar in TarifaCliente.objects.all():
        cat = cat_para(tar.producto, default_nombre='Otro')  # las tarifas siempre tienen producto
        tar.categoria = cat
        tar.save(update_fields=['categoria'])
```

- [ ] **Step 5: Migraciones**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py makemigrations core`
(genera `0025_add_categoria_fk.py`).

Create `apps/core/migrations/0026_sembrar_y_migrar_categorias.py`:

```python
from django.db import migrations


def forwards(apps, schema_editor):
    from apps.core.services.facturas.categorias import sembrar_y_migrar
    sembrar_y_migrar(
        apps.get_model('core', 'CategoriaProducto'),
        apps.get_model('core', 'DocumentoFactura'),
        apps.get_model('core', 'TarifaCliente'),
    )


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0025_add_categoria_fk'),
    ]
    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
```

- [ ] **Step 6: Verificar migraciones y test**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py makemigrations --check --dry-run` → `No changes detected`.
Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_facturas.test_migracion_categorias --noinput -v 2` → PASS (2).
Run la suite completa → verde (cambio aditivo).

- [ ] **Step 7: Commit**

```bash
git add apps/core/models.py apps/core/services/facturas/categorias.py apps/core/migrations/0025_add_categoria_fk.py apps/core/migrations/0026_sembrar_y_migrar_categorias.py apps/core/tests_facturas/test_migracion_categorias.py
git commit -m "feat(facturas): FK categoria + siembra y migración de datos de categorías"
```

---

### Task 3: CRUD de `CategoriaProducto` (UI + permiso + nav)

**Files:**
- Create: `apps/core/views/categorias_producto.py`
- Modify: `apps/core/views/__init__.py` (barrel import)
- Modify: `apps/core/forms.py` (`CategoriaProductoForm`)
- Modify: `apps/core/urls.py` (4 rutas)
- Create: `templates/categorias_producto/lista.html`, `templates/categorias_producto/form.html`
- Modify: `templates/includes/nav_menu.html` (enlace en el grupo Facturas)
- Test: `apps/core/tests_facturas/test_categorias_producto_views.py`

**Interfaces:**
- Consumes: `CategoriaProducto`, permiso `gestionar_categorias_producto`.
- Produces: URLs `categoria_producto_lista/crear/editar/toggle_activo`.

- [ ] **Step 1: Escribir el test que falla**

Create `apps/core/tests_facturas/test_categorias_producto_views.py`:

```python
from django.contrib.auth.models import User, Permission
from django.test import TestCase
from django.urls import reverse

from apps.core.models import CategoriaProducto


class CategoriasProductoViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u', password='x')
        self.user.user_permissions.add(
            Permission.objects.get(codename='gestionar_categorias_producto'))
        self.client.force_login(self.user)

    def test_crear(self):
        resp = self.client.post(reverse('categoria_producto_crear'), {
            'nombre': 'Polo', 'palabra_clave': 'polo', 'orden': 0})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(CategoriaProducto.objects.filter(nombre='Polo').exists())

    def test_toggle(self):
        c = CategoriaProducto.objects.create(nombre='Lisa')
        self.client.post(reverse('categoria_producto_toggle_activo', args=[c.pk]))
        c.refresh_from_db()
        self.assertFalse(c.activa)

    def test_sin_permiso_403(self):
        self.client.logout()
        self.client.force_login(User.objects.create_user('u2', password='x'))
        resp = self.client.get(reverse('categoria_producto_lista'))
        self.assertEqual(resp.status_code, 403)
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_facturas.test_categorias_producto_views --noinput -v 2`
Expected: FAIL — `Reverse for 'categoria_producto_crear' not found`.

- [ ] **Step 3: Form**

En `apps/core/forms.py` (asegurar `CategoriaProducto` importado desde `.models`):

```python
class CategoriaProductoForm(forms.ModelForm):
    class Meta:
        model = CategoriaProducto
        fields = ['nombre', 'palabra_clave', 'es_predeterminada', 'activa', 'orden']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'palabra_clave': forms.TextInput(attrs={'class': 'form-control'}),
            'es_predeterminada': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'activa': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'orden': forms.NumberInput(attrs={'class': 'form-control'}),
        }
```

- [ ] **Step 4: Vistas**

Create `apps/core/views/categorias_producto.py`:

```python
"""categorias_producto.py — CRUD de categorías de producto."""
from .common import *  # noqa: F401,F403

from ..models import CategoriaProducto
from ..forms import CategoriaProductoForm


@login_required
@permission_required(_perm('gestionar_categorias_producto'), raise_exception=True)
def categoria_producto_lista(request):
    categorias = CategoriaProducto.objects.all()
    return render(request, 'categorias_producto/lista.html', {'categorias': categorias})


@login_required
@permission_required(_perm('gestionar_categorias_producto'), raise_exception=True)
def categoria_producto_crear(request):
    if request.method == 'POST':
        form = CategoriaProductoForm(request.POST)
        if form.is_valid():
            c = form.save()
            messages.success(request, f'Categoría "{c.nombre}" creada.')
            return redirect('categoria_producto_lista')
    else:
        form = CategoriaProductoForm()
    return render(request, 'categorias_producto/form.html',
                  {'form': form, 'titulo': 'Nueva categoría de producto'})


@login_required
@permission_required(_perm('gestionar_categorias_producto'), raise_exception=True)
def categoria_producto_editar(request, pk):
    categoria = get_object_or_404(CategoriaProducto, pk=pk)
    if request.method == 'POST':
        form = CategoriaProductoForm(request.POST, instance=categoria)
        if form.is_valid():
            categoria = form.save()
            messages.success(request, f'Categoría "{categoria.nombre}" actualizada.')
            return redirect('categoria_producto_lista')
    else:
        form = CategoriaProductoForm(instance=categoria)
    return render(request, 'categorias_producto/form.html',
                  {'form': form, 'titulo': f'Editar: {categoria.nombre}', 'categoria': categoria})


@login_required
@permission_required(_perm('gestionar_categorias_producto'), raise_exception=True)
@require_POST
def categoria_producto_toggle_activo(request, pk):
    categoria = get_object_or_404(CategoriaProducto, pk=pk)
    categoria.activa = not categoria.activa
    categoria.save(update_fields=['activa'])
    messages.success(request, f'Categoría "{categoria.nombre}" {"activada" if categoria.activa else "desactivada"}.')
    return redirect('categoria_producto_lista')
```

En `apps/core/views/__init__.py`, agregar junto a las demás líneas de facturas:
`from .categorias_producto import *   # noqa: F401,F403`

- [ ] **Step 5: URLs**

En `apps/core/urls.py`, junto a las rutas de facturas:

```python
    path('facturas/categorias/', views.categoria_producto_lista, name='categoria_producto_lista'),
    path('facturas/categorias/nueva/', views.categoria_producto_crear, name='categoria_producto_crear'),
    path('facturas/categorias/<int:pk>/editar/', views.categoria_producto_editar, name='categoria_producto_editar'),
    path('facturas/categorias/<int:pk>/toggle/', views.categoria_producto_toggle_activo, name='categoria_producto_toggle_activo'),
```

- [ ] **Step 6: Plantillas**

Leer `templates/metodos_pago/lista.html` y `templates/metodos_pago/form.html` y crear los espejos en `templates/categorias_producto/`.

`templates/categorias_producto/lista.html`:

```html
{% extends "base.html" %}
{% block title %}Categorías de producto{% endblock %}
{% block content %}
<div class="page-header d-flex justify-content-between align-items-center mb-3">
  <h1 class="h4 mb-0">Categorías de producto</h1>
  <a href="{% url 'categoria_producto_crear' %}" class="btn btn-primary btn-sm">Nueva categoría</a>
</div>
<table class="table table-sm align-middle">
  <thead><tr><th>Nombre</th><th>Palabra clave</th><th>Por defecto</th><th>Estado</th><th></th></tr></thead>
  <tbody>
    {% for c in categorias %}
    <tr>
      <td>{{ c.nombre }}</td>
      <td class="text-muted">{{ c.palabra_clave|default:"—" }}</td>
      <td>{% if c.es_predeterminada %}<span class="badge bg-primary">Sí</span>{% endif %}</td>
      <td>{% if c.activa %}<span class="badge bg-success">Activa</span>{% else %}<span class="badge bg-secondary">Inactiva</span>{% endif %}</td>
      <td class="text-end">
        <a href="{% url 'categoria_producto_editar' c.pk %}" class="btn btn-sm btn-outline-secondary">Editar</a>
        <form method="post" action="{% url 'categoria_producto_toggle_activo' c.pk %}" class="d-inline">
          {% csrf_token %}
          <button class="btn btn-sm btn-outline-secondary">{% if c.activa %}Desactivar{% else %}Activar{% endif %}</button>
        </form>
      </td>
    </tr>
    {% empty %}
    <tr><td colspan="5" class="text-muted">Sin categorías.</td></tr>
    {% endfor %}
  </tbody>
</table>
{% endblock %}
```

`templates/categorias_producto/form.html`:

```html
{% extends "base.html" %}
{% block title %}{{ titulo }}{% endblock %}
{% block content %}
<div class="page-header mb-3"><h1 class="h4 mb-0">{{ titulo }}</h1></div>
<form method="post" class="col-lg-6">
  {% csrf_token %}
  {{ form.as_p }}
  <button class="btn btn-primary">Guardar</button>
  <a href="{% url 'categoria_producto_lista' %}" class="btn btn-link">Cancelar</a>
</form>
{% endblock %}
```

- [ ] **Step 7: Enlace en nav**

En `templates/includes/nav_menu.html`, dentro del grupo Facturas (después del enlace "Subir en bloque", antes del `</div>` que cierra `#navFacturas-{{ mid }}`), agregar:

```html
{% if perms.core.gestionar_categorias_producto %}
<a href="{% url 'categoria_producto_lista' %}" class="nav-link {% if 'categoria' in un %}active{% endif %}">
  <i class="bi bi-tags"></i> Categorías de producto
</a>
{% endif %}
```

- [ ] **Step 8: Correr suite**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_facturas.test_categorias_producto_views --noinput -v 2` → PASS (3). Luego suite completa verde.

- [ ] **Step 9: Commit**

```bash
git add apps/core/views/categorias_producto.py apps/core/views/__init__.py apps/core/forms.py apps/core/urls.py templates/categorias_producto/ templates/includes/nav_menu.html apps/core/tests_facturas/test_categorias_producto_views.py
git commit -m "feat(facturas): CRUD de categorías de producto"
```

---

### Task 4: Cutover — `producto` string → `categoria` FK (servicio, clasificador, tarifas, forms, display, filtro)

**Files:**
- Modify: `apps/core/models.py` (`TarifaCliente`: `activa_para`, `__str__`, constraint, ordering; `categoria` de tarifa a non-null)
- Modify: `apps/core/services/facturas/invoice_service.py`
- Modify: `apps/core/services/facturas/pdf_extractors/filename_extractor.py`
- Modify: `apps/core/services/facturas/bulk_service.py`
- Modify: `apps/core/views/facturas_tarifas.py`
- Modify: `apps/core/views/facturas.py` (`facturas_lista` filtro por categoría)
- Modify: `apps/core/forms.py` (`DocumentoEditarForm`, `TarifaClienteForm`)
- Modify: `templates/facturas/_producto.html`, `templates/facturas/lista.html`
- Create: `apps/core/migrations/0027_tarifa_categoria_constraint.py` (autogenerada: constraint swap + alter categoria non-null en TarifaCliente)
- Modify tests: `test_invoice_service.py`, `test_extractors.py`, `test_bulk_service.py`, `test_views.py` y cualquier test que use `producto` string.
- Test (nuevo): `apps/core/tests_facturas/test_clasificar_categoria.py`

**Interfaces:**
- Consumes: `CategoriaProducto`, `categoria` FK (Task 2), CRUD (Task 3).
- Produces:
  - `invoice_service.clasificar_categoria(nombre_archivo) -> CategoriaProducto | None` (palabra clave en el nombre → esa categoría activa; si ninguna, `CategoriaProducto.predeterminada()`).
  - `invoice_service.crear_documento(*, cliente, tipo_documento, archivo=None, categoria=None, datos=None, texto_extraido='')` (ya no recibe `producto`; para envío sin `categoria` clasifica por el nombre del archivo; tarifa por categoría).
  - `TarifaCliente.activa_para(cliente, categoria)` filtra por `categoria`.
  - `previsualizar(...)` devuelve en `datos` la clave `categoria_id` sugerida.

- [ ] **Step 1: Escribir el test que falla (clasificador)**

Create `apps/core/tests_facturas/test_clasificar_categoria.py`:

```python
from django.test import TestCase

from apps.core.models import CategoriaProducto
from apps.core.services.facturas import invoice_service


class ClasificarCategoriaTests(TestCase):
    def setUp(self):
        self.camiseta = CategoriaProducto.objects.create(nombre='Camiseta', palabra_clave='camiseta', orden=0)
        self.lisa = CategoriaProducto.objects.create(nombre='Lisa', palabra_clave='lisa', es_predeterminada=True, orden=1)

    def test_palabra_clave_coincide(self):
        c = invoice_service.clasificar_categoria('RENATO DIAZ Envio camiseta 126.pdf')
        self.assertEqual(c, self.camiseta)

    def test_sin_coincidencia_usa_predeterminada(self):
        c = invoice_service.clasificar_categoria('Antonio Sanchez 126.pdf')
        self.assertEqual(c, self.lisa)

    def test_categoria_nueva_con_su_palabra_clave(self):
        polo = CategoriaProducto.objects.create(nombre='Polo', palabra_clave='polo', orden=2)
        c = invoice_service.clasificar_categoria('Marvin Polo 77.pdf')
        self.assertEqual(c, polo)

    def test_inactiva_se_ignora(self):
        self.camiseta.activa = False
        self.camiseta.save(update_fields=['activa'])
        c = invoice_service.clasificar_categoria('X Envio camiseta 9.pdf')
        self.assertEqual(c, self.lisa)  # cae a la predeterminada
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_facturas.test_clasificar_categoria --noinput -v 2`
Expected: FAIL — `module 'invoice_service' has no attribute 'clasificar_categoria'`.

- [ ] **Step 3: Clasificador en `invoice_service`**

En `apps/core/services/facturas/invoice_service.py`, agregar el import y la función:

```python
from apps.core.models import DocumentoFactura, TarifaCliente, CategoriaProducto
```

```python
def clasificar_categoria(nombre_archivo):
    """Categoría de un envío según el nombre: primera cuya palabra clave aparezca; si
    ninguna, la predeterminada."""
    base = (nombre_archivo or '')
    for cat in CategoriaProducto.objects.filter(activa=True).order_by('orden', 'nombre'):
        kw = (cat.palabra_clave or '').strip()
        if kw and kw.lower() in base.lower():
            return cat
    return CategoriaProducto.predeterminada()
```

- [ ] **Step 4: `crear_documento` usa categoría**

En `invoice_service.py`, quitar `'producto'` de `_CAMPOS_DIRECTOS` y reescribir `crear_documento`:

```python
_CAMPOS_DIRECTOS = (
    'numero_documento', 'fecha_documento', 'fecha_vencimiento', 'subtotal', 'isv',
    'monto_total', 'total_libras',
)


@transaction.atomic
def crear_documento(*, cliente, tipo_documento, archivo=None, categoria=None,
                    datos=None, texto_extraido=''):
    """Crea un DocumentoFactura. Para envío aplica tarifa activa (snapshot)."""
    datos = dict(datos or {})
    doc = DocumentoFactura(
        cliente=cliente, tipo_documento=tipo_documento,
        texto_extraido=texto_extraido, estado_revision='pendiente')
    if archivo is not None:
        doc.archivo_pdf = archivo

    for campo in _CAMPOS_DIRECTOS:
        if campo in datos and datos[campo] is not None:
            setattr(doc, campo, datos[campo])

    if not doc.fecha_vencimiento and doc.fecha_documento and cliente.dias_credito:
        doc.fecha_vencimiento = doc.fecha_documento + timedelta(days=cliente.dias_credito)

    if tipo_documento == 'envio':
        if categoria is None:
            nombre = getattr(archivo, 'name', '') or ''
            categoria = clasificar_categoria(nombre)
        doc.categoria = categoria
        tarifa = TarifaCliente.activa_para(cliente, categoria) if categoria else None
        if tarifa and doc.total_libras is not None:
            doc.precio_por_libra = tarifa.precio_por_libra
            doc.monto_total = (doc.total_libras * tarifa.precio_por_libra).quantize(Decimal('0.01'))
    elif categoria is not None:
        doc.categoria = categoria

    doc.save()
    status_service.actualizar_estado_pago(doc)
    return doc
```

En `previsualizar`, tras armar `datos`, sugerir la categoría (para envíos):

```python
    if tipo_documento == 'envio':
        cat = clasificar_categoria(nombre)
        if cat is not None:
            datos['categoria_id'] = cat.pk
```

(Agregar cerca del final de `previsualizar`, antes del `return`. `nombre` ya existe en la función.)

- [ ] **Step 5: `filename_extractor` deja de clasificar producto**

En `apps/core/services/facturas/pdf_extractors/filename_extractor.py`: eliminar la función `_producto_envio` y todas las asignaciones `datos['producto'] = _producto_envio(base)` (la agregada al final de `extraer_de_nombre`). El extractor ya no devuelve `producto`. Mantener `_PRODUCTOS` y el regex `producto_pat` (siguen sirviendo para separar el nombre del cliente del token de producto en `<CLIENTE> <PRODUCTO> <NUM>`). Actualizar los tests de `test_extractors.py` que aseveraban `d['producto']`: retirar esas aserciones (la clasificación ahora se prueba en `test_clasificar_categoria.py`); conservar las de `tipo_documento`, `numero_documento`, `cliente_nombre`.

- [ ] **Step 6: `TarifaCliente` por categoría**

En `apps/core/models.py`, `TarifaCliente`:
- Cambiar `categoria` a **non-null**: `categoria = models.ForeignKey('CategoriaProducto', on_delete=models.PROTECT, related_name='tarifas')` (quitar `null=True, blank=True`).
- `Meta.ordering = ['cliente', 'categoria', '-fecha_inicio']`.
- Reemplazar la `UniqueConstraint` por: `fields=['cliente', 'categoria']`, `name='tarifa_unica_activa_por_cliente_categoria'`, misma `condition=Q(activa=True)`.
- `__str__`: `f'{self.cliente.nombre} · {self.categoria.nombre} · L {self.precio_por_libra}/lb'`.
- `activa_para`:

```python
    @classmethod
    def activa_para(cls, cliente, categoria):
        """Tarifa activa vigente del cliente para la categoría, o None."""
        return cls.objects.filter(
            cliente=cliente, categoria=categoria, activa=True,
        ).order_by('-fecha_inicio').first()
```

Generar la migración: `... makemigrations core` (crea `0027_*` con AlterField de `categoria` a non-null, RemoveConstraint/AddConstraint y AlterModelOptions). Como todas las tarifas ya tienen `categoria` (Task 2), el AlterField non-null no falla.

- [ ] **Step 7: Vista de tarifas + forms**

En `apps/core/views/facturas_tarifas.py`, cambiar los dos bloques `filter(cliente=..., producto=tarifa.producto, activa=True)` por `producto` → `categoria` (`filter(cliente=..., categoria=tarifa.categoria, activa=True)`).

En `apps/core/forms.py`:
- `TarifaClienteForm.Meta.fields`: reemplazar `'producto'` por `'categoria'`; en `__init__` (o declarativamente) limitar el queryset a activas:

```python
class TarifaClienteForm(forms.ModelForm):
    class Meta:
        model = TarifaCliente
        fields = ['categoria', 'precio_por_libra', 'activa', 'fecha_inicio', 'fecha_fin', 'notas']
        widgets = {
            'categoria': forms.Select(attrs={'class': 'form-select'}),
            'precio_por_libra': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'activa': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'fecha_inicio': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'),
            'fecha_fin': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'),
            'notas': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['categoria'].queryset = CategoriaProducto.objects.filter(activa=True)
```

- `DocumentoEditarForm`: reemplazar `'producto'` por `'categoria'` en `Meta.fields` y en `widgets` (usar `forms.Select`). En `__init__`, limitar `self.fields['categoria'].queryset = CategoriaProducto.objects.filter(activa=True)`. Quitar el `producto = forms.ChoiceField(...)` del formulario de lote si aplica (buscar en `forms.py` el `producto = forms.ChoiceField(...)` alrededor de la línea 439 y cambiarlo a un `ModelChoiceField` de categorías activas, requerido=False, o retirarlo si el lote no lo usa tras el cambio de `bulk_service`).

Asegurar `CategoriaProducto` importado en `forms.py`.

- [ ] **Step 8: `bulk_service` usa categoría**

En `apps/core/services/facturas/bulk_service.py`: donde arma `datos` y llama `crear_documento(..., producto=fila.get('producto') or None, ...)`, cambiar a pasar `categoria`. Si la fila trae un id de categoría (`fila.get('categoria')`), resolverlo a instancia; si no, pasar `categoria=None` (crear_documento clasificará por el nombre del archivo para envíos). Retirar la clave `'producto'` del dict de filas (líneas ~119, ~157-158) y cualquier uso del string producto. Ajustar el encabezado/preview del lote para mostrar/seleccionar categoría en vez del string.

- [ ] **Step 9: Display + filtro en la lista**

`templates/facturas/_producto.html` → mostrar la categoría por nombre:

```html
{% if doc.categoria %}<span class="badge bg-info text-dark">{{ doc.categoria.nombre }}</span>
{% else %}<span class="text-muted">—</span>{% endif %}
```

En `apps/core/views/facturas.py`, `facturas_lista`: cambiar el filtro de `producto` a `categoria`:

```python
    categoria_id = request.GET.get('categoria', '')
    ...
    if categoria_id:
        qs = qs.filter(categoria_id=categoria_id)
```

En el contexto, reemplazar `'producto_choices': ...` por `'categorias': CategoriaProducto.objects.filter(activa=True)` y en `filtros` reemplazar `'producto': producto` por `'categoria': categoria_id`. Importar `CategoriaProducto` en el módulo.

En `templates/facturas/lista.html`, en la barra de filtros, agregar el `<select name="categoria">`:

```html
<select name="categoria" class="form-select form-select-sm">
  <option value="">Todas las categorías</option>
  {% for c in categorias %}
  <option value="{{ c.pk }}" {% if filtros.categoria == c.pk|stringformat:'s' %}selected{% endif %}>{{ c.nombre }}</option>
  {% endfor %}
</select>
```

(Colocarlo junto a los otros selects de filtro; leer la barra de filtros existente en `lista.html` para insertarlo con el mismo estilo/estructura de columnas.)

El resaltado de fila `{% if doc.producto == 'camiseta' %}...border-left...{% endif %}` (línea ~153 de `lista.html`): cambiarlo a `{% if doc.categoria and doc.categoria.palabra_clave == 'camiseta' %}` o retirarlo. Recomendado: retirar el estilo hardcodeado para no depender de una categoría específica.

- [ ] **Step 10: Actualizar tests afectados y correr la suite**

Buscar y ajustar todos los tests que usan `producto` string o `crear_documento(producto=...)`:
`grep -rn "producto=\|'producto'\|\"producto\"\|\.producto" apps/core/tests_facturas/`
- `test_invoice_service.py`: cambiar llamadas a `crear_documento` para pasar `categoria=<CategoriaProducto>` (o depender de la clasificación por nombre), y crear las categorías necesarias en `setUp`.
- `test_bulk_service.py`: ajustar filas/preview a categoría.
- `test_extractors.py`: retirar aserciones sobre `d['producto']` (Step 5).
- Cualquier test de tarifas que use `producto=` → `categoria=`.

Run la suite completa: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core --noinput -v 1` → verde. Iterar hasta que pase.

- [ ] **Step 11: Commit**

```bash
git add -A
git commit -m "feat(facturas): cutover de producto (string) a categoria (FK) en servicio, tarifas, forms, display y filtro"
```

---

### Task 5: Retirar el CharField `producto` y `PRODUCTO_CHOICES`

**Files:**
- Modify: `apps/core/models.py` (quitar `producto` de `DocumentoFactura` y `TarifaCliente`; quitar `PRODUCTO_CHOICES`)
- Create: `apps/core/migrations/0028_remove_producto.py` (autogenerada: 2 RemoveField)
- Grep de seguridad: sin referencias a `producto` string ni `PRODUCTO_CHOICES` en código de app.

**Interfaces:**
- Consumes: nada nuevo (los datos ya viven en `categoria` desde Task 2/4).
- Produces: esquema sin la columna `producto`.

- [ ] **Step 1: Verificar que nada de app usa el string `producto` ni `PRODUCTO_CHOICES`**

Run: `grep -rn "PRODUCTO_CHOICES\|\.producto\b\|'producto'\|\"producto\"" apps/ templates/ --include=*.py --include=*.html | grep -v "/migrations/"`
Expected: sin hits relevantes al string de producto (los usos de `producto_terminado`/`tipo == 'producto'` del inventario NO son de este campo y se dejan). Si aparece alguno de facturas/tarifas, corregirlo antes de continuar.

- [ ] **Step 2: Quitar los campos y el choices**

En `apps/core/models.py`: eliminar `producto = models.CharField(... PRODUCTO_CHOICES ...)` de `DocumentoFactura` y de `TarifaCliente`, y eliminar el bloque `PRODUCTO_CHOICES = [...]`.

- [ ] **Step 3: Migración**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py makemigrations core` (crea `0028_*` con los `RemoveField`).
Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py makemigrations --check --dry-run` → `No changes detected`.

- [ ] **Step 4: Suite completa**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core --noinput -v 1` → verde.

- [ ] **Step 5: Commit**

```bash
git add apps/core/models.py apps/core/migrations/0028_remove_producto.py
git commit -m "refactor(facturas): retirar CharField producto y PRODUCTO_CHOICES tras migración a categoría"
```

---

## Notas de despliegue

- Migraciones **0024–0028** deben aplicarse juntas y en orden: `0026` siembra y copia datos antes de que `0027` haga la categoría de tarifa non-null y `0028` borre el CharField. No desplegar el código del cutover (Task 4) sin haber aplicado `0026`.
- Tras desplegar, revisar en **Facturas → Categorías de producto** que exista una marcada "por defecto" (la siembra deja **Lisa**), y crear las categorías nuevas del negocio con su palabra clave.
