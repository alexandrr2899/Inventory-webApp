# Crear cliente inline al ingresar factura — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permitir crear un cliente sin salir del formulario de factura (subida individual y revisión de lote), mediante un botón "+ Nuevo cliente" que abre un modal, con creación por AJAX y detección de duplicados por nombre.

**Architecture:** Un endpoint AJAX (`cliente_crear_inline`) que valida con un `ClienteInlineForm`, detecta duplicados por nombre (case-insensitive, con opción de forzar) y devuelve JSON. Un modal Bootstrap compartido (`_cliente_modal.html`) y un módulo JS (`cliente-inline.js`) que envía el form, inyecta la opción en todos los `<select.cliente-select>` de la página y la auto-selecciona en el destino. Se integra en `form_upload.html` y `lote_revisar.html`.

**Tech Stack:** Django (vistas + ModelForm), Bootstrap 5 (modal), JS vanilla (fetch). Sin dependencias nuevas, sin migraciones.

## Global Constraints

- **Permiso:** endpoint y botón se rigen por `gestionar_facturas` (usar `_perm('gestionar_facturas')`). Amplía deliberadamente ese rol para crear clientes.
- **Clientes inline nacen `activo=True`** (valor por defecto del modelo; `ClienteInlineForm` no incluye `activo`).
- **Duplicados por `nombre` case-insensitive** (`nombre__iexact`), con flag `forzar='1'` para crear igual.
- **Respuestas del endpoint (JSON):** 201 `{ok:true, cliente:{id,nombre}}` éxito; 200 `{ok:false, duplicado:{id,nombre}}` duplicado sin forzar; 400 `{ok:false, errors:{...}}` validación; 403 sin permiso.
- **`<select>` nativos** (no buscables). Se les agrega la clase `cliente-select` para la inyección.
- **Decorador `@facturas_enabled`** en el endpoint (el módulo de facturas lo usa en todas sus vistas). Tests deben usar `@override_settings(FACTURAS_MODULE_ENABLED=True)`.
- **Sin migraciones ni dependencias nuevas.** No tocar el flujo tradicional `cliente_crear` de la sección Clientes.
- **UI en español.**
- **Tests solo en Docker, con volumen montado y `--noinput`:**
  `docker compose run --rm --no-deps -v "$(pwd)":/app --entrypoint python web manage.py test <ruta> -v 2 --noinput`
- **Tests van en `apps/core/tests_facturas/`.**

---

## Estructura de archivos

- **Modificar** `apps/core/forms.py` — agregar `ClienteInlineForm`.
- **Modificar** `apps/core/views/facturas_cliente.py` — agregar la vista `cliente_crear_inline` (se auto-exporta vía `from .facturas_cliente import *` en `views/__init__.py`).
- **Modificar** `apps/core/urls.py` — ruta `cliente_crear_inline`.
- **Modificar** `apps/core/forms.py` (`DocumentoUploadForm`) — agregar clase `cliente-select` al widget de `cliente`.
- **Crear** `templates/facturas/_cliente_modal.html` — modal compartido.
- **Crear** `static/js/cliente-inline.js` — módulo JS.
- **Modificar** `templates/facturas/form_upload.html` — botón + modal + script.
- **Modificar** `templates/facturas/lote_revisar.html` — botón por fila + modal + script.
- **Crear** `apps/core/tests_facturas/test_cliente_inline.py` — tests del endpoint y del render de `form_upload`.

---

### Task 1: Backend — `ClienteInlineForm` + endpoint `cliente_crear_inline`

Entrega: endpoint AJAX que crea clientes, detecta duplicados y respeta el permiso, con tests completos (TDD).

**Files:**
- Modify: `apps/core/forms.py`
- Modify: `apps/core/views/facturas_cliente.py`
- Modify: `apps/core/urls.py`
- Test: `apps/core/tests_facturas/test_cliente_inline.py`

**Interfaces:**
- Produces:
  - `ClienteInlineForm` (ModelForm de `Cliente`, campos `nombre, telefono, rtn, direccion, dias_credito`).
  - Vista `cliente_crear_inline(request)` → `JsonResponse`. URL name `cliente_crear_inline` en `facturas/clientes/inline/`.
  - Contrato JSON: 201 `{ok:true, cliente:{id,nombre}}` · 200 `{ok:false, duplicado:{id,nombre}}` · 400 `{ok:false, errors:{campo:[msgs]}}` · 403 (PermissionDenied).

- [ ] **Step 1: Escribir los tests del endpoint (fallan)**

Crear `apps/core/tests_facturas/test_cliente_inline.py`:

```python
from django.contrib.auth.models import Permission, User
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.core.models import Cliente


@override_settings(FACTURAS_MODULE_ENABLED=True)
class ClienteCrearInlineTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u', password='x')
        self.user.user_permissions.add(
            Permission.objects.get(codename='gestionar_facturas'))
        self.url = reverse('cliente_crear_inline')

    def test_crea_cliente_activo(self):
        self.client.force_login(self.user)
        resp = self.client.post(self.url, {'nombre': 'Nuevo Cli', 'dias_credito': '15'})
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertTrue(data['ok'])
        c = Cliente.objects.get(pk=data['cliente']['id'])
        self.assertEqual(c.nombre, 'Nuevo Cli')
        self.assertTrue(c.activo)
        self.assertEqual(c.dias_credito, 15)

    def test_sin_permiso_403(self):
        otro = User.objects.create_user('u2', password='x')
        self.client.force_login(otro)
        resp = self.client.post(self.url, {'nombre': 'X'})
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(Cliente.objects.filter(nombre='X').exists())

    def test_nombre_vacio_400(self):
        self.client.force_login(self.user)
        resp = self.client.post(self.url, {'nombre': ''})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('nombre', resp.json()['errors'])
        self.assertEqual(Cliente.objects.count(), 0)

    def test_duplicado_sin_forzar_no_crea(self):
        Cliente.objects.create(nombre='Juan Pérez')
        self.client.force_login(self.user)
        resp = self.client.post(self.url, {'nombre': 'juan pérez'})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data['ok'])
        self.assertEqual(data['duplicado']['nombre'], 'Juan Pérez')
        self.assertEqual(Cliente.objects.filter(nombre__iexact='juan pérez').count(), 1)

    def test_duplicado_forzado_crea(self):
        Cliente.objects.create(nombre='Juan Pérez')
        self.client.force_login(self.user)
        resp = self.client.post(self.url, {'nombre': 'juan pérez', 'forzar': '1'})
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(Cliente.objects.filter(nombre__iexact='juan pérez').count(), 2)
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run:
```bash
docker compose run --rm --no-deps -v "$(pwd)":/app --entrypoint python web manage.py test apps.core.tests_facturas.test_cliente_inline -v 2 --noinput
```
Expected: FAIL — `reverse('cliente_crear_inline')` lanza `NoReverseMatch` (la ruta aún no existe).

- [ ] **Step 3: Agregar `ClienteInlineForm` a forms.py**

En `apps/core/forms.py`, junto a `ClienteForm` (después de su definición), agregar:

```python
class ClienteInlineForm(forms.ModelForm):
    """Alta rápida de cliente desde el flujo de factura. Sin `activo` (nace activo)."""
    class Meta:
        model = Cliente
        fields = ['nombre', 'telefono', 'rtn', 'direccion', 'dias_credito']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'telefono': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: +504 9999-9999'}),
            'rtn': forms.TextInput(attrs={'class': 'form-control'}),
            'direccion': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'dias_credito': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'placeholder': '0 = contado'}),
        }
```

- [ ] **Step 4: Agregar la vista al final de facturas_cliente.py**

En `apps/core/views/facturas_cliente.py`, en la línea de import de forms, agregar `ClienteInlineForm`:

```python
from ..forms import AbonoClienteForm, ClienteInlineForm
```

Y al final del archivo, agregar la vista:

```python
@login_required
@permission_required(_perm('gestionar_facturas'), raise_exception=True)
@facturas_enabled
@require_POST
def cliente_crear_inline(request):
    """Alta rápida de cliente (AJAX/JSON) desde el flujo de factura."""
    form = ClienteInlineForm(request.POST)
    if not form.is_valid():
        return JsonResponse({'ok': False, 'errors': form.errors}, status=400)
    nombre = form.cleaned_data['nombre'].strip()
    dup = Cliente.objects.filter(nombre__iexact=nombre).first()
    if dup and request.POST.get('forzar') != '1':
        return JsonResponse(
            {'ok': False, 'duplicado': {'id': dup.pk, 'nombre': dup.nombre}}, status=200)
    cliente = form.save()
    return JsonResponse(
        {'ok': True, 'cliente': {'id': cliente.pk, 'nombre': cliente.nombre}}, status=201)
```

(`JsonResponse`, `require_POST`, `login_required`, `permission_required`, `_perm`, `facturas_enabled`, `Cliente` ya están disponibles vía `from .common import *`.)

- [ ] **Step 5: Registrar la ruta en urls.py**

En `apps/core/urls.py`, junto a las otras rutas de facturas/clientes (cerca de `path('facturas/clientes/<int:pk>/tarifas/', ...)`), agregar:

```python
    path('facturas/clientes/inline/', views.cliente_crear_inline, name='cliente_crear_inline'),
```

- [ ] **Step 6: Correr los tests y verificar que pasan**

Run:
```bash
docker compose run --rm --no-deps -v "$(pwd)":/app --entrypoint python web manage.py test apps.core.tests_facturas.test_cliente_inline -v 2 --noinput
```
Expected: PASS (5 tests OK).

- [ ] **Step 7: Commit**

```bash
git add apps/core/forms.py apps/core/views/facturas_cliente.py apps/core/urls.py apps/core/tests_facturas/test_cliente_inline.py
git commit -m "feat(facturas): endpoint AJAX de alta rápida de cliente (inline)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Modal + JS compartidos e integración en subida individual

Entrega: en `form_upload.html`, un botón "+ Nuevo" junto al selector de cliente abre el modal; al crear, el cliente se agrega al selector y queda seleccionado. Test de render del botón/modal.

**Files:**
- Create: `templates/facturas/_cliente_modal.html`
- Create: `static/js/cliente-inline.js`
- Modify: `apps/core/forms.py` (`DocumentoUploadForm`)
- Modify: `templates/facturas/form_upload.html`
- Test: `apps/core/tests_facturas/test_cliente_inline.py` (agregar clase de render)

**Interfaces:**
- Consumes (de Task 1): endpoint `cliente_crear_inline` y su contrato JSON.
- Produces (consumido por Task 3):
  - Partial `templates/facturas/_cliente_modal.html` con `#clienteInlineModal` (atributo `data-url` = URL del endpoint), campos del form, zona de aviso `#cliente-modal-aviso`, bloque duplicado `#cliente-modal-duplicado`.
  - `static/js/cliente-inline.js`: activa botones `[data-cliente-nuevo][data-target="<id-select>"]`, inyecta opciones en `select.cliente-select`, selecciona en el destino.
  - Convención: cada `<select>` de cliente lleva la clase `cliente-select`; cada botón lleva `data-cliente-nuevo` y `data-target` con el `id` del select.

- [ ] **Step 1: Escribir el test de render de form_upload (falla)**

En `apps/core/tests_facturas/test_cliente_inline.py`, agregar al final:

```python
@override_settings(FACTURAS_MODULE_ENABLED=True)
class FormUploadClienteInlineRenderTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('up', password='x')
        for cn in ['ver_facturas', 'gestionar_facturas']:
            self.user.user_permissions.add(Permission.objects.get(codename=cn))
        self.client.force_login(self.user)

    def test_upload_incluye_boton_y_modal(self):
        resp = self.client.get(reverse('factura_upload'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'data-cliente-nuevo')
        self.assertContains(resp, 'id="clienteInlineModal"')
        self.assertContains(resp, 'cliente-select')
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run:
```bash
docker compose run --rm --no-deps -v "$(pwd)":/app --entrypoint python web manage.py test apps.core.tests_facturas.test_cliente_inline.FormUploadClienteInlineRenderTests -v 2 --noinput
```
Expected: FAIL — no aparecen `data-cliente-nuevo` / `clienteInlineModal` / `cliente-select`.

- [ ] **Step 3: Agregar la clase `cliente-select` al widget de cliente en `DocumentoUploadForm`**

En `apps/core/forms.py`, en `DocumentoUploadForm`, cambiar el widget de `cliente`:

```python
    cliente = forms.ModelChoiceField(
        queryset=Cliente.objects.filter(activo=True).order_by('nombre'),
        widget=forms.Select(attrs={'class': 'form-select cliente-select'}),
    )
```

- [ ] **Step 4: Crear el modal compartido**

Crear `templates/facturas/_cliente_modal.html`:

```html
{# Modal para crear un Cliente sin salir del formulario de factura. #}
<div class="modal fade" id="clienteInlineModal" tabindex="-1" aria-hidden="true"
     data-url="{% url 'cliente_crear_inline' %}">
  <div class="modal-dialog modal-dialog-centered">
    <div class="modal-content">
      <div class="modal-header">
        <h5 class="modal-title"><i class="bi bi-person-plus me-2"></i>Nuevo cliente</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Cerrar"></button>
      </div>
      <div class="modal-body">
        <div id="cliente-modal-aviso"></div>
        <div id="cliente-modal-duplicado" class="alert alert-warning d-none">
          Ya existe «<strong id="cliente-dup-nombre"></strong>».
          <div class="d-flex gap-2 mt-2">
            <button type="button" class="btn btn-sm btn-primary" id="cliente-dup-usar">Usar existente</button>
            <button type="button" class="btn btn-sm btn-outline-danger" id="cliente-dup-forzar">Crear de todos modos</button>
          </div>
        </div>
        <form id="clienteInlineForm" onsubmit="return false;">
          <div class="mb-2">
            <label class="form-label">Nombre <span class="text-danger">*</span></label>
            <input type="text" name="nombre" class="form-control" required>
            <div class="invalid-feedback" id="err-nombre"></div>
          </div>
          <div class="row g-2">
            <div class="col-md-6 mb-2">
              <label class="form-label">Teléfono</label>
              <input type="text" name="telefono" class="form-control" placeholder="Ej: +504 9999-9999">
              <div class="invalid-feedback" id="err-telefono"></div>
            </div>
            <div class="col-md-6 mb-2">
              <label class="form-label">RTN</label>
              <input type="text" name="rtn" class="form-control">
              <div class="invalid-feedback" id="err-rtn"></div>
            </div>
          </div>
          <div class="mb-2">
            <label class="form-label">Días de crédito</label>
            <input type="number" name="dias_credito" class="form-control" min="0" placeholder="0 = contado">
            <div class="invalid-feedback" id="err-dias_credito"></div>
          </div>
          <div class="mb-2">
            <label class="form-label">Dirección</label>
            <textarea name="direccion" class="form-control" rows="2"></textarea>
            <div class="invalid-feedback" id="err-direccion"></div>
          </div>
        </form>
      </div>
      <div class="modal-footer">
        <button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Cancelar</button>
        <button type="button" class="btn btn-primary" id="cliente-inline-crear">
          <i class="bi bi-check-lg me-1"></i>Crear
        </button>
      </div>
    </div>
  </div>
</div>
```

- [ ] **Step 5: Crear el módulo JS**

Crear `static/js/cliente-inline.js`:

```javascript
/* cliente-inline.js — crea un Cliente sin salir del formulario de factura.
   Un botón [data-cliente-nuevo][data-target="<id-del-select>"] abre #clienteInlineModal;
   al crear (fetch al endpoint en modal[data-url]) inyecta la opción en todos los
   <select.cliente-select> y la selecciona en el destino. */
(function () {
  'use strict';

  var modalEl = document.getElementById('clienteInlineModal');
  if (!modalEl) return;

  var url       = modalEl.dataset.url;
  var form      = document.getElementById('clienteInlineForm');
  var aviso     = document.getElementById('cliente-modal-aviso');
  var dupBox    = document.getElementById('cliente-modal-duplicado');
  var dupNombre = document.getElementById('cliente-dup-nombre');
  var btnCrear  = document.getElementById('cliente-inline-crear');
  var btnUsar   = document.getElementById('cliente-dup-usar');
  var btnForzar = document.getElementById('cliente-dup-forzar');
  var CAMPOS    = ['nombre', 'telefono', 'rtn', 'direccion', 'dias_credito'];
  var targetId  = null;   // id del <select> destino
  var dupId     = null;   // id del cliente duplicado ofrecido

  function csrftoken() {
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }
  function bsModal() { return bootstrap.Modal.getOrCreateInstance(modalEl); }

  function limpiar() {
    aviso.innerHTML = '';
    dupBox.classList.add('d-none');
    dupId = null;
    CAMPOS.forEach(function (c) {
      var inp = form.elements[c];
      if (inp) { inp.value = ''; inp.classList.remove('is-invalid'); }
      var fb = document.getElementById('err-' + c);
      if (fb) fb.textContent = '';
    });
  }

  function selects() { return document.querySelectorAll('select.cliente-select'); }

  function insertarOpcion(id, nombre) {
    selects().forEach(function (sel) {
      if (sel.querySelector('option[value="' + id + '"]')) return;
      var opt = document.createElement('option');
      opt.value = String(id);
      opt.textContent = nombre;
      var puesto = false;
      for (var i = 0; i < sel.options.length; i++) {
        var o = sel.options[i];
        if (o.value && o.textContent.localeCompare(nombre, 'es') > 0) {
          sel.insertBefore(opt, o); puesto = true; break;
        }
      }
      if (!puesto) sel.appendChild(opt);
    });
  }

  function seleccionarEnDestino(id) {
    var dest = document.getElementById(targetId);
    if (dest) {
      dest.value = String(id);
      dest.dispatchEvent(new Event('change', { bubbles: true }));
    }
  }

  function mostrarErrores(errors) {
    Object.keys(errors).forEach(function (campo) {
      var inp = form.elements[campo];
      var fb = document.getElementById('err-' + campo);
      if (inp) inp.classList.add('is-invalid');
      if (fb) fb.textContent = errors[campo].join(' ');
      else aviso.innerHTML =
        '<div class="alert alert-danger py-2 mb-0"></div>';
      if (!fb && aviso.firstChild) aviso.firstChild.textContent = errors[campo].join(' ');
    });
  }

  function avisoTexto(msg) {
    var div = document.createElement('div');
    div.className = 'alert alert-danger py-2 mb-0';
    div.textContent = msg;
    aviso.innerHTML = '';
    aviso.appendChild(div);
  }

  function enviar(forzar) {
    aviso.innerHTML = '';
    var datos = new URLSearchParams();
    CAMPOS.forEach(function (c) {
      var inp = form.elements[c];
      if (inp) { inp.classList.remove('is-invalid'); datos.append(c, inp.value); }
      var fb = document.getElementById('err-' + c); if (fb) fb.textContent = '';
    });
    if (forzar) datos.append('forzar', '1');

    fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'X-CSRFToken': csrftoken(), 'X-Requested-With': 'XMLHttpRequest' },
      body: datos,
    }).then(function (r) {
      return r.json().then(function (data) { return { status: r.status, data: data }; })
                     .catch(function () { return { status: r.status, data: {} }; });
    }).then(function (res) {
      var d = res.data;
      if (res.status === 201 && d.ok) {
        insertarOpcion(d.cliente.id, d.cliente.nombre);
        seleccionarEnDestino(d.cliente.id);
        bsModal().hide();
      } else if (d.duplicado) {
        dupId = d.duplicado.id;
        dupNombre.textContent = d.duplicado.nombre;
        dupBox.classList.remove('d-none');
      } else if (d.errors) {
        mostrarErrores(d.errors);
      } else {
        avisoTexto('No se pudo crear el cliente.');
      }
    }).catch(function () {
      avisoTexto('Error de red. Intentá de nuevo.');
    });
  }

  document.querySelectorAll('[data-cliente-nuevo]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      targetId = btn.getAttribute('data-target');
      limpiar();
      bsModal().show();
    });
  });

  if (btnCrear)  btnCrear.addEventListener('click', function () { enviar(false); });
  if (btnForzar) btnForzar.addEventListener('click', function () { enviar(true); });
  if (btnUsar)   btnUsar.addEventListener('click', function () {
    if (dupId != null) { insertarOpcion(dupId, dupNombre.textContent); seleccionarEnDestino(dupId); }
    bsModal().hide();
  });

  modalEl.addEventListener('shown.bs.modal', function () {
    var n = form.elements['nombre']; if (n) n.focus();
  });
})();
```

- [ ] **Step 6: Integrar en form_upload.html**

En `templates/facturas/form_upload.html`:

6a. Agregar `{% load static %}` en la segunda línea (después de `{% extends "base.html" %}`):

```html
{% extends "base.html" %}
{% load static %}
```

6b. Reemplazar el bloque del cliente (líneas ~20-22, el `<div class="mb-3">` con `{{ form.cliente }}`) por:

```html
          <div class="mb-3">
            <label class="form-label">Cliente</label>
            <div class="input-group">
              {{ form.cliente }}
              {% if perms.core.gestionar_facturas %}
              <button type="button" class="btn btn-outline-primary"
                      data-cliente-nuevo data-target="id_cliente">
                <i class="bi bi-person-plus me-1"></i>Nuevo
              </button>
              {% endif %}
            </div>
          </div>
```

6c. Incluir el modal dentro de `{% block content %}`, justo antes de su `{% endblock %}` (después de `</div>` de cierre del `row`):

```html
{% if perms.core.gestionar_facturas %}{% include "facturas/_cliente_modal.html" %}{% endif %}
```

6d. Cargar el script dentro del `{% block extra_js %}` existente, después del `</script>` actual:

```html
{% if perms.core.gestionar_facturas %}
<script src="{% static 'js/cliente-inline.js' %}"></script>
{% endif %}
```

- [ ] **Step 7: Correr el test de render y verificar que pasa**

Run:
```bash
docker compose run --rm --no-deps -v "$(pwd)":/app --entrypoint python web manage.py test apps.core.tests_facturas.test_cliente_inline -v 2 --noinput
```
Expected: PASS (6 tests OK — 5 del endpoint + 1 de render).

- [ ] **Step 8: Verificación manual (subida individual)**

Requiere el módulo de facturas activo y sesión con `gestionar_facturas`:
1. Ir a Facturas → Subir documento.
2. Clic en "Nuevo" junto al selector de Cliente → se abre el modal.
3. Crear un cliente nuevo → aparece seleccionado en el `<select>`; el modal se cierra.
4. Repetir con un nombre que ya existe → aviso "Ya existe «...»"; probar "Usar existente" y "Crear de todos modos".
5. Dejar el nombre vacío y Crear → error inline bajo "Nombre".

- [ ] **Step 9: Commit**

```bash
git add templates/facturas/_cliente_modal.html static/js/cliente-inline.js apps/core/forms.py templates/facturas/form_upload.html apps/core/tests_facturas/test_cliente_inline.py
git commit -m "feat(facturas): crear cliente inline en subida individual de factura

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Integración en la revisión de lote

Entrega: en `lote_revisar.html`, cada fila tiene un botón "+ Nuevo" que crea el cliente y lo deja disponible/seleccionado en esa fila (y disponible en las demás).

**Files:**
- Modify: `templates/facturas/lote_revisar.html`

**Interfaces:**
- Consumes (de Task 2): partial `facturas/_cliente_modal.html`, `static/js/cliente-inline.js`, y la convención `select.cliente-select` + botón `[data-cliente-nuevo][data-target]`.

- [ ] **Step 1: Agregar `{% load static %}`**

En `templates/facturas/lote_revisar.html`, segunda línea (después de `{% extends "base.html" %}`):

```html
{% extends "base.html" %}
{% load static %}
```

- [ ] **Step 2: Marcar el select de cliente y agregar el botón por fila**

Reemplazar la celda del cliente (el `<td style="min-width:170px">` con el `<select>` y el bloque sugerido, líneas ~43-53) por:

```html
            <td style="min-width:170px">
              <select name="fila-{{ forloop.counter0 }}-cliente"
                      id="cliente-fila-{{ forloop.counter0 }}"
                      class="form-select form-select-sm cliente-select" required>
                <option value="">— elegir —</option>
                {% for c in clientes %}
                <option value="{{ c.pk }}" {% if c.pk|stringformat:'s' == fila.cliente_id|stringformat:'s' %}selected{% endif %}>{{ c.nombre }}</option>
                {% endfor %}
              </select>
              {% if fila.cliente_sugerido and not fila.cliente_id %}
              <div class="small text-muted">Del archivo: "{{ fila.cliente_sugerido }}"</div>
              {% endif %}
              {% if perms.core.gestionar_facturas %}
              <button type="button" class="btn btn-outline-primary btn-sm mt-1"
                      data-cliente-nuevo data-target="cliente-fila-{{ forloop.counter0 }}">
                <i class="bi bi-person-plus"></i> Nuevo
              </button>
              {% endif %}
            </td>
```

- [ ] **Step 3: Incluir el modal y el script (una vez) al final del template**

En `templates/facturas/lote_revisar.html`, después de `{% endblock %}` del `content` (fin del archivo), agregar un bloque `extra_js`:

```html
{% block extra_js %}
{% if perms.core.gestionar_facturas %}
{% include "facturas/_cliente_modal.html" %}
<script src="{% static 'js/cliente-inline.js' %}"></script>
{% endif %}
{% endblock %}
```

- [ ] **Step 4: Smoke check + verificación manual**

Smoke (no rompe carga de templates):
```bash
docker compose run --rm --no-deps -v "$(pwd)":/app --entrypoint python web manage.py check
```
Expected: "System check identified no issues".

Verificación manual (requiere subir un lote de PDFs para llegar a la pantalla de revisión):
1. Facturas → Subir lote → seleccionar varios PDFs → Revisar.
2. En una fila sin cliente (resaltada en amarillo), clic en "Nuevo" → modal.
3. Crear cliente → queda seleccionado en esa fila y aparece como opción en las demás filas.
4. Probar el caso duplicado ("Usar existente" / "Crear de todos modos").

- [ ] **Step 5: Commit**

```bash
git add templates/facturas/lote_revisar.html
git commit -m "feat(facturas): crear cliente inline en la revisión de lote

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Notas de verificación global

- Correr toda la suite de facturas tras Task 1 y Task 2:
  ```bash
  docker compose run --rm --no-deps -v "$(pwd)":/app --entrypoint python web manage.py test apps.core.tests_facturas -v 1 --noinput
  ```
- La lógica JS (`cliente-inline.js`) no tiene arnés de pruebas automatizadas en este repo; se cubre con las verificaciones manuales. El endpoint (Task 1) y el render de `form_upload` (Task 2) sí tienen tests automatizados.
- Sin migraciones ni dependencias nuevas: no correr `makemigrations` ni `docker compose build`.
- **Autorización de commits:** si se ejecuta en un entorno donde aplica la preferencia del usuario, pedir autorización antes de cada `git commit`.
