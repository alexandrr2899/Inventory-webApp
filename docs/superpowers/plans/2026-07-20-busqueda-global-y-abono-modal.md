# Búsqueda global + Registrar abono en modal — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reducir a 1–2 gestos encontrar un cliente/factura y registrar un abono, con un buscador global y el abono en modal.

**Architecture:** Un endpoint JSON `/api/buscar/` alimenta una barra de búsqueda siempre visible (panel centrado) que busca clientes y facturas. El formulario de abono se extrae a un partial reutilizado por la página completa (fallback) y por un modal que hace fetch/submit por AJAX. La lógica de reparto de pagos no cambia.

**Tech Stack:** Django 4.2, Bootstrap 5.3 (bundle ya cargado), JS vanilla en `static/js/`, PostgreSQL. Sin dependencias nuevas.

## Global Constraints

- **Tests solo por Docker** (no hay `python` local). Comando base:
  `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test <ruta> --noinput -v 2`
- **Las vistas se auto-exportan**: cada módulo nuevo en `apps/core/views/` debe agregarse con `from .<modulo> import *` en `apps/core/views/__init__.py` para que `views.<nombre>` funcione en `urls.py`.
- **Permisos:** búsqueda requiere `core.ver_facturas`; registrar abono requiere `core.registrar_pago_factura`. Usar `_perm('...')` y `@facturas_enabled`.
- **XSS:** los datos del servidor se insertan en el DOM con `textContent`/nodos, nunca `innerHTML` con nombres de cliente.
- **Progresivo:** sin JS, el abono sigue funcionando como página completa (no romper vistas/tests existentes).
- **En tests, login con** `self.client.force_login(user)` (django-axes rompe `client.login`).

---

### Task 1: Endpoint de búsqueda combinada `buscar_global`

**Files:**
- Create: `apps/core/views/busqueda.py`
- Modify: `apps/core/views/__init__.py` (agregar el re-export)
- Modify: `apps/core/urls.py` (agregar la ruta)
- Test: `apps/core/tests_facturas/test_busqueda.py`

**Interfaces:**
- Produces: `GET /api/buscar/?q=<term>` (name `buscar_global`) → `JsonResponse`
  `{"clientes": [{"id","nombre","saldo","url","puede_abonar"}], "facturas": [{"id","numero","cliente","tipo","estado","saldo","url"}]}`.

- [ ] **Step 1: Escribir el test que falla**

Create `apps/core/tests_facturas/test_busqueda.py`:

```python
from decimal import Decimal

from django.contrib.auth.models import Permission, User
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.core.models import (
    Cliente, DocumentoFactura, MetodoPago, Pago, AplicacionPago,
)


@override_settings(FACTURAS_MODULE_ENABLED=True, ALLOWED_HOSTS=['testserver', 'localhost'])
class BuscarGlobalTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u', password='x')
        for cod in ('ver_facturas', 'registrar_pago_factura'):
            self.user.user_permissions.add(Permission.objects.get(codename=cod))
        self.client.force_login(self.user)
        self.url = reverse('buscar_global')
        self.met = MetodoPago.objects.create(nombre='Efectivo', tipo='efectivo')
        self.cli = Cliente.objects.create(nombre='Renato Díaz')
        self.doc = DocumentoFactura.objects.create(
            cliente=self.cli, tipo_documento='factura', numero_documento='9543',
            fecha_documento=timezone.localdate(), monto_total=Decimal('1000'))

    def test_q_corta_devuelve_vacio(self):
        data = self.client.get(self.url, {'q': 'a'}).json()
        self.assertEqual(data, {'clientes': [], 'facturas': []})

    def test_encuentra_cliente_por_nombre_con_saldo(self):
        data = self.client.get(self.url, {'q': 'Rena'}).json()
        self.assertEqual(len(data['clientes']), 1)
        c = data['clientes'][0]
        self.assertEqual(c['nombre'], 'Renato Díaz')
        self.assertEqual(Decimal(c['saldo']), Decimal('1000'))
        self.assertTrue(c['puede_abonar'])

    def test_saldo_descuenta_pagos(self):
        pago = Pago.objects.create(cliente=self.cli, fecha_pago=timezone.localdate(),
                                   metodo_pago=self.met, monto=Decimal('400'))
        AplicacionPago.objects.create(pago=pago, documento=self.doc, monto=Decimal('400'))
        data = self.client.get(self.url, {'q': 'Rena'}).json()
        self.assertEqual(Decimal(data['clientes'][0]['saldo']), Decimal('600'))

    def test_encuentra_factura_por_numero_y_excluye_anulada(self):
        data = self.client.get(self.url, {'q': '9543'}).json()
        self.assertEqual(len(data['facturas']), 1)
        self.assertEqual(data['facturas'][0]['numero'], '9543')
        self.doc.estado_pago = 'anulada'; self.doc.save(update_fields=['estado_pago'])
        data = self.client.get(self.url, {'q': '9543'}).json()
        self.assertEqual(data['facturas'], [])

    def test_403_sin_permiso(self):
        otro = User.objects.create_user('o', password='x')
        self.client.force_login(otro)
        self.assertEqual(self.client.get(self.url, {'q': 'Rena'}).status_code, 403)

    @override_settings(FACTURAS_MODULE_ENABLED=False)
    def test_404_modulo_apagado(self):
        self.assertEqual(self.client.get(self.url, {'q': 'Rena'}).status_code, 404)

    def test_sin_n_mas_1_en_clientes(self):
        def crear(n):
            AplicacionPago.objects.all().delete()
            Pago.objects.all().delete()
            DocumentoFactura.objects.all().delete()
            Cliente.objects.all().delete()
            for i in range(n):
                c = Cliente.objects.create(nombre=f'Clix {i}')
                DocumentoFactura.objects.create(
                    cliente=c, tipo_documento='factura', numero_documento=f'X{i}',
                    fecha_documento=timezone.localdate(), monto_total=Decimal('100'))
        crear(3)
        with CaptureQueriesContext(connection) as ctx3:
            self.client.get(self.url, {'q': 'Clix'})
        crear(6)
        with CaptureQueriesContext(connection) as ctx6:
            self.client.get(self.url, {'q': 'Clix'})
        self.assertEqual(len(ctx3.captured_queries), len(ctx6.captured_queries))
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_facturas.test_busqueda --noinput -v 2`
Expected: FAIL (`NoReverseMatch: 'buscar_global'`).

- [ ] **Step 3: Crear la vista**

Create `apps/core/views/busqueda.py`:

```python
"""busqueda.py — Búsqueda global combinada de clientes y facturas."""
from decimal import Decimal

from django.db.models import Sum, Q, Value, DecimalField
from django.db.models.functions import Coalesce

from .common import *  # noqa: F401,F403

from ..models import Cliente, DocumentoFactura, AplicacionPago

_LIMITE = 6
_DEC = DecimalField(max_digits=12, decimal_places=2)


def _saldos_por_cliente(cliente_ids):
    """{cliente_id: saldo_adeudado} en 2 consultas (Σ monto_total − Σ aplicaciones)."""
    if not cliente_ids:
        return {}
    docs = (DocumentoFactura.objects
            .filter(cliente_id__in=cliente_ids).exclude(estado_pago='anulada')
            .values('cliente_id')
            .annotate(total=Coalesce(Sum('monto_total'), Value(Decimal('0')), output_field=_DEC)))
    total_docs = {r['cliente_id']: r['total'] for r in docs}
    aplic = (AplicacionPago.objects
             .filter(documento__cliente_id__in=cliente_ids)
             .exclude(documento__estado_pago='anulada')
             .values('documento__cliente_id')
             .annotate(total=Coalesce(Sum('monto'), Value(Decimal('0')), output_field=_DEC)))
    total_aplic = {r['documento__cliente_id']: r['total'] for r in aplic}
    return {cid: total_docs.get(cid, Decimal('0')) - total_aplic.get(cid, Decimal('0'))
            for cid in cliente_ids}


@login_required
@permission_required(_perm('ver_facturas'), raise_exception=True)
@facturas_enabled
def buscar_global(request):
    q = (request.GET.get('q') or '').strip()
    if len(q) < 2:
        return JsonResponse({'clientes': [], 'facturas': []})

    puede_abonar = request.user.has_perm(_perm('registrar_pago_factura'))

    clientes_qs = list(Cliente.objects.filter(nombre__icontains=q).order_by('nombre')[:_LIMITE])
    saldos = _saldos_por_cliente([c.pk for c in clientes_qs])
    clientes = [{
        'id': c.pk, 'nombre': c.nombre,
        'saldo': str(saldos.get(c.pk, Decimal('0'))),
        'url': reverse('cliente_salidas', args=[c.pk]),
        'puede_abonar': puede_abonar,
    } for c in clientes_qs]

    facturas_qs = DocumentoFactura.anotar_pagado(
        DocumentoFactura.objects
        .filter(Q(numero_documento__icontains=q) | Q(cliente__nombre__icontains=q))
        .exclude(estado_pago='anulada')
        .select_related('cliente')
        .order_by('-fecha_documento', '-created_at'))[:_LIMITE]
    facturas = [{
        'id': d.pk, 'numero': d.numero_documento or str(d.pk),
        'cliente': d.cliente.nombre, 'tipo': d.tipo_documento,
        'estado': 'vencida' if d.esta_vencida else d.estado_pago,
        'saldo': str(d.saldo_pendiente),
        'url': reverse('factura_detalle', args=[d.pk]),
    } for d in facturas_qs]

    return JsonResponse({'clientes': clientes, 'facturas': facturas})
```

- [ ] **Step 4: Registrar el re-export y la ruta**

In `apps/core/views/__init__.py`, after line `from .facturas_estado_cuenta import *`:

```python
from .busqueda import *                    # noqa: F401,F403
```

In `apps/core/urls.py`, inside `urlpatterns`, after the `api/categoria/nueva/` line:

```python
    path('api/buscar/', views.buscar_global, name='buscar_global'),
```

- [ ] **Step 5: Correr los tests y verificar que pasan**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_facturas.test_busqueda --noinput -v 2`
Expected: PASS (7 tests OK).

- [ ] **Step 6: Commit**

```bash
git add apps/core/views/busqueda.py apps/core/views/__init__.py apps/core/urls.py apps/core/tests_facturas/test_busqueda.py
git commit -m "feat(facturas): endpoint /api/buscar/ (clientes + facturas)"
```

---

### Task 2: Barra de búsqueda global en la interfaz

**Files:**
- Modify: `templates/base.html` (botón en navbar + overlay + include del JS)
- Create: `static/js/buscador.js`
- Modify: `static/css/app.css` (estilos del overlay)
- Test: `apps/core/tests_facturas/test_busqueda_render.py`

**Interfaces:**
- Consumes: `GET /api/buscar/` (Task 1).
- Produces: elemento `#btnBuscarGlobal` con `data-buscar-url`, overlay `#buscadorOverlay`, y evento JS `buscador:abono` con `{detail: {clienteId, nombre}}` (lo consume Task 5).

- [ ] **Step 1: Escribir el test de render que falla**

Create `apps/core/tests_facturas/test_busqueda_render.py`:

```python
from django.contrib.auth.models import Permission, User
from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(FACTURAS_MODULE_ENABLED=True, ALLOWED_HOSTS=['testserver', 'localhost'])
class BuscadorRenderTests(TestCase):
    def _login(self, con_facturas):
        u = User.objects.create_user('u', password='x')
        if con_facturas:
            u.user_permissions.add(Permission.objects.get(codename='ver_facturas'))
        self.client.force_login(u)

    def test_boton_presente_con_permiso(self):
        self._login(con_facturas=True)
        resp = self.client.get(reverse('dashboard'))
        self.assertContains(resp, 'id="btnBuscarGlobal"')
        self.assertContains(resp, 'id="buscadorOverlay"')

    def test_boton_ausente_sin_permiso(self):
        self._login(con_facturas=False)
        resp = self.client.get(reverse('dashboard'))
        self.assertNotContains(resp, 'id="btnBuscarGlobal"')
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_facturas.test_busqueda_render --noinput -v 2`
Expected: FAIL (no aparece `btnBuscarGlobal`).

- [ ] **Step 3: Agregar el botón y el overlay en `base.html`**

In `templates/base.html`, inside `<div class="d-flex align-items-center gap-2 ms-auto">`, immediately after the theme-toggle button (the `</button>` on line ~89), add:

```html
      {% if user.is_authenticated and perms.core.ver_facturas %}
      <button type="button" id="btnBuscarGlobal" class="btn btn-sm btn-outline-light"
              data-buscar-url="{% url 'buscar_global' %}"
              title="Buscar cliente o factura" aria-label="Buscar cliente o factura">
        <i class="bi bi-search"></i>
        <span class="d-none d-lg-inline ms-1">Buscar</span>
        <kbd class="d-none d-lg-inline ms-1">/</kbd>
      </button>
      {% endif %}
```

In `templates/base.html`, right after the closing `</nav>` (line ~107), add:

```html
{% if user.is_authenticated and perms.core.ver_facturas %}
<div id="buscadorOverlay" class="buscador-overlay" hidden>
  <div class="buscador-panel" role="dialog" aria-modal="true" aria-label="Buscar cliente o factura">
    <div class="buscador-input-wrap">
      <i class="bi bi-search"></i>
      <input type="text" id="buscadorInput" placeholder="Buscar cliente o factura…" autocomplete="off" spellcheck="false">
      <kbd>esc</kbd>
    </div>
    <div id="buscadorResultados" class="buscador-resultados" role="listbox"></div>
  </div>
</div>
{% endif %}
```

In `templates/base.html`, before the final `</script>`/closing (after the line `<script src="{% static 'js/qr-scanner.js' %}"></script>`, line ~218), add:

```html
{% if user.is_authenticated and perms.core.ver_facturas %}
<script src="{% static 'js/buscador.js' %}"></script>
{% endif %}
```

- [ ] **Step 4: Crear `static/js/buscador.js`**

Create `static/js/buscador.js`:

```javascript
(function () {
  var btn = document.getElementById('btnBuscarGlobal');
  var overlay = document.getElementById('buscadorOverlay');
  if (!btn || !overlay) return;

  var input = document.getElementById('buscadorInput');
  var out = document.getElementById('buscadorResultados');
  var url = btn.getAttribute('data-buscar-url');
  var timer = null, filas = [], sel = -1;

  function abrir() {
    overlay.hidden = false;
    input.value = ''; out.innerHTML = ''; filas = []; sel = -1;
    setTimeout(function () { input.focus(); }, 10);
  }
  function cerrar() { overlay.hidden = true; }

  function money(v) { return 'L ' + Number(v).toLocaleString('es-HN', {minimumFractionDigits: 2, maximumFractionDigits: 2}); }

  function fila(opts) {
    var a = document.createElement(opts.href ? 'a' : 'div');
    a.className = 'buscador-row';
    if (opts.href) a.href = opts.href;
    var name = document.createElement('span');
    name.className = 'br-name'; name.textContent = opts.nombre;
    a.appendChild(name);
    if (opts.meta) {
      var m = document.createElement('span');
      m.className = 'br-meta ' + (opts.metaClass || ''); m.textContent = opts.meta;
      a.appendChild(m);
    }
    if (opts.abono) {
      var q = document.createElement('button');
      q.type = 'button'; q.className = 'br-quick'; q.textContent = '+ Abono';
      q.addEventListener('click', function (e) {
        e.preventDefault(); e.stopPropagation(); cerrar();
        document.dispatchEvent(new CustomEvent('buscador:abono',
          {detail: {clienteId: opts.abono.id, nombre: opts.nombre}}));
      });
      a.appendChild(q);
    }
    filas.push(a);
    return a;
  }

  function seccion(titulo) {
    var s = document.createElement('div');
    s.className = 'buscador-sec'; s.textContent = titulo;
    return s;
  }

  function render(data) {
    out.innerHTML = ''; filas = []; sel = -1;
    if (data.clientes.length) {
      out.appendChild(seccion('Clientes'));
      data.clientes.forEach(function (c) {
        out.appendChild(fila({
          nombre: c.nombre, href: c.url,
          meta: Number(c.saldo) > 0 ? 'Debe ' + money(c.saldo) : 'Al día',
          metaClass: Number(c.saldo) > 0 ? 'br-debe' : 'br-ok',
          abono: c.puede_abonar ? {id: c.id} : null,
        }));
      });
    }
    if (data.facturas.length) {
      out.appendChild(seccion('Facturas'));
      data.facturas.forEach(function (f) {
        out.appendChild(fila({
          nombre: '#' + f.numero + ' · ' + f.cliente, href: f.url,
          meta: f.estado, metaClass: 'br-badge',
        }));
      });
    }
    if (!data.clientes.length && !data.facturas.length) {
      var e = document.createElement('div');
      e.className = 'buscador-empty'; e.textContent = 'Sin resultados';
      out.appendChild(e);
    }
  }

  function buscar() {
    var q = input.value.trim();
    if (q.length < 2) { out.innerHTML = ''; filas = []; return; }
    fetch(url + '?q=' + encodeURIComponent(q), {headers: {'X-Requested-With': 'XMLHttpRequest'}})
      .then(function (r) { return r.ok ? r.json() : {clientes: [], facturas: []}; })
      .then(render)
      .catch(function () { out.innerHTML = ''; });
  }

  function mover(d) {
    if (!filas.length) return;
    if (sel >= 0) filas[sel].classList.remove('hl');
    sel = (sel + d + filas.length) % filas.length;
    filas[sel].classList.add('hl');
    filas[sel].scrollIntoView({block: 'nearest'});
  }

  btn.addEventListener('click', abrir);
  overlay.addEventListener('click', function (e) { if (e.target === overlay) cerrar(); });
  input.addEventListener('input', function () { clearTimeout(timer); timer = setTimeout(buscar, 200); });
  input.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') { cerrar(); }
    else if (e.key === 'ArrowDown') { e.preventDefault(); mover(1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); mover(-1); }
    else if (e.key === 'Enter' && sel >= 0 && filas[sel].href) { window.location = filas[sel].href; }
  });
  document.addEventListener('keydown', function (e) {
    if (overlay.hidden && (e.key === '/' || ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k'))) {
      var t = document.activeElement;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
      e.preventDefault(); abrir();
    }
  });
})();
```

- [ ] **Step 5: Agregar estilos en `static/css/app.css`**

Append to `static/css/app.css`:

```css
/* ── Buscador global ─────────────────────────────────────────────── */
.buscador-overlay { position: fixed; inset: 0; z-index: 1080;
  background: rgba(10,15,30,.45); display: flex; justify-content: center;
  align-items: flex-start; padding-top: 10vh; }
.buscador-panel { width: min(560px, 92vw); background: var(--bs-body-bg, #fff);
  border-radius: 14px; box-shadow: 0 24px 60px rgba(0,0,0,.35); overflow: hidden; }
.buscador-input-wrap { display: flex; align-items: center; gap: 10px;
  padding: 14px 16px; border-bottom: 1px solid rgba(0,0,0,.08); }
.buscador-input-wrap input { flex: 1; border: 0; outline: 0; font-size: 16px;
  background: transparent; color: inherit; }
.buscador-input-wrap kbd { font-size: 11px; opacity: .6; }
.buscador-resultados { max-height: 60vh; overflow-y: auto; }
.buscador-sec { font-size: 11px; text-transform: uppercase; letter-spacing: .05em;
  color: #8a93a6; padding: 10px 16px 4px; }
.buscador-row { display: flex; align-items: center; gap: 10px; padding: 10px 16px;
  font-size: 14.5px; text-decoration: none; color: inherit; cursor: pointer; }
.buscador-row.hl, .buscador-row:hover { background: rgba(79,131,255,.10); }
.br-name { font-weight: 600; }
.br-meta { margin-left: auto; font-size: 12.5px; text-align: right; }
.br-debe { color: #a12833; font-weight: 600; } .br-ok { color: #146c43; }
.br-badge { text-transform: capitalize; }
.br-quick { margin-left: auto; font-size: 12px; background: #eaf0ff; color: #2b56c6;
  border: 0; border-radius: 6px; padding: 3px 9px; font-weight: 600; cursor: pointer; }
.buscador-empty { padding: 16px; text-align: center; color: #8a93a6; }
```

- [ ] **Step 6: Correr el test de render y verificar que pasa**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_facturas.test_busqueda_render --noinput -v 2`
Expected: PASS (2 tests OK).

- [ ] **Step 7: Verificación en navegador (manual)**

Levantar el runserver de Docker (puerto 8002 según el flujo del proyecto) y confirmar: `/` abre el overlay; escribir 2+ letras muestra clientes y facturas; ↑↓ y Enter navegan; "+ Abono" cierra el overlay (el modal se conecta en Task 5). Anotar OK en el PR.

- [ ] **Step 8: Commit**

```bash
git add templates/base.html static/js/buscador.js static/css/app.css apps/core/tests_facturas/test_busqueda_render.py
git commit -m "feat(facturas): barra de búsqueda global con panel centrado"
```

---

### Task 3: Extraer el formulario de abono a un partial reutilizable

**Files:**
- Create: `templates/facturas/_form_abono.html`
- Modify: `templates/facturas/form_abono.html` (incluye el partial)
- Test: `apps/core/tests_facturas/test_abono_view.py` (los existentes deben seguir verdes)

**Interfaces:**
- Produces: partial `facturas/_form_abono.html` que renderiza el `<form>` completo (campos + reparto + botones) usando el contexto `form, pendientes, action_url, submit_label, cliente, pago`.

- [ ] **Step 1: Crear el partial**

Create `templates/facturas/_form_abono.html` con el contenido del `<form>` actual de `form_abono.html` (líneas 17–115), sin el `{% extends %}` ni el `{% block %}`:

```html
{% load facturas_extras %}
<form method="post" action="{{ action_url }}" enctype="multipart/form-data" data-abono-form>
  {% csrf_token %}
  {% if form.non_field_errors %}
  <div class="alert alert-danger">{{ form.non_field_errors }}</div>
  {% endif %}

  <div class="card mb-3">
    <div class="card-header fw-semibold">Datos del abono</div>
    <div class="card-body">
      <div class="row g-3">
        <div class="col-12 col-md-3">
          <label class="form-label">{{ form.fecha_pago.label }}</label>
          {{ form.fecha_pago }}
          {% if form.fecha_pago.errors %}<div class="text-danger small">{{ form.fecha_pago.errors }}</div>{% endif %}
        </div>
        <div class="col-12 col-md-3">
          <label class="form-label">{{ form.metodo_pago.label }}</label>
          {{ form.metodo_pago }}
          {% if form.metodo_pago.errors %}<div class="text-danger small">{{ form.metodo_pago.errors }}</div>{% endif %}
        </div>
        <div class="col-12 col-md-3">
          <label class="form-label">{{ form.monto.label }}</label>
          {{ form.monto }}
          {% if form.monto.errors %}<div class="text-danger small">{{ form.monto.errors }}</div>{% endif %}
        </div>
        <div class="col-12 col-md-3">
          <label class="form-label">{{ form.referencia.label }}</label>
          {{ form.referencia }}
          {% if form.referencia.errors %}<div class="text-danger small">{{ form.referencia.errors }}</div>{% endif %}
        </div>
      </div>
    </div>
  </div>

  <div class="card mb-3">
    <div class="card-header fw-semibold">Reparto entre facturas (editable)</div>
    <div class="card-body">
      <p class="text-muted small mb-2">Deja los montos en blanco para repartir automáticamente de la más antigua a la más reciente.</p>
      <div class="table-responsive">
        <table class="table table-sm align-middle">
          <thead class="table-light">
            <tr>
              <th>Factura</th><th>Fecha</th>
              <th class="text-end">Saldo pendiente</th>
              <th style="min-width:140px">Aplicar</th>
            </tr>
          </thead>
          <tbody>
            {% for row in pendientes %}
            <tr>
              <td><a href="{% url 'factura_detalle' row.doc.pk %}">{{ row.doc.numero_documento|default:row.doc.pk }}</a></td>
              <td class="text-nowrap">{{ row.doc.fecha_documento|date:"d/m/Y" }}</td>
              <td class="text-end fw-bold">L {{ row.doc.saldo_pendiente|moneda }}</td>
              <td>
                <input type="number" step="0.01" min="0" name="aplicar_{{ row.doc.pk }}"
                       value="{{ row.aplicado|default_if_none:'' }}"
                       class="form-control form-control-sm" placeholder="auto">
              </td>
            </tr>
            {% empty %}
            <tr><td colspan="4" class="text-muted text-center py-2">
              Sin facturas pendientes — el abono quedará como saldo a favor.
            </td></tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <div class="card mb-3">
    <div class="card-header fw-semibold">Comprobante y notas</div>
    <div class="card-body">
      <div class="mb-3">
        <label class="form-label">{{ form.comprobante.label }}</label>
        {% if pago and pago.comprobante %}
        <div class="small mb-1"><a href="{{ pago.comprobante.url }}" target="_blank">Ver comprobante actual</a></div>
        {% endif %}
        {{ form.comprobante }}
        {% if form.comprobante.errors %}<div class="text-danger small">{{ form.comprobante.errors }}</div>{% endif %}
      </div>
      <div>
        <label class="form-label">{{ form.notas.label }}</label>
        {{ form.notas }}
        {% if form.notas.errors %}<div class="text-danger small">{{ form.notas.errors }}</div>{% endif %}
      </div>
    </div>
  </div>

  <div class="d-flex gap-2">
    <button type="submit" class="btn btn-primary btn-lg flex-fill flex-md-grow-0">
      <i class="bi bi-check-lg me-2"></i>{{ submit_label }}
    </button>
    <a href="{% url 'cliente_salidas' cliente.pk %}" class="btn btn-outline-secondary btn-lg" data-abono-cancel>Cancelar</a>
  </div>
</form>
```

- [ ] **Step 2: Reemplazar el cuerpo de `form_abono.html` por el include**

Replace `templates/facturas/form_abono.html` con:

```html
{% extends "base.html" %}
{% load facturas_extras %}
{% block title %}{{ titulo }} · {{ cliente.nombre }}{% endblock %}

{% block content %}
<div class="page-header">
  <h1><i class="bi bi-cash-coin me-2"></i>{{ titulo }} · {{ cliente.nombre }}</h1>
</div>

<div class="row mb-3">
  <div class="col">
    <span class="text-muted">Saldo a favor actual: <strong>L {{ cliente.saldo_a_favor|moneda }}</strong></span>
    <span class="ms-3 text-muted">Total adeudado: <strong>L {{ cliente.total_adeudado|moneda }}</strong></span>
  </div>
</div>

{% include "facturas/_form_abono.html" %}
{% endblock %}
```

- [ ] **Step 3: Correr los tests de abono existentes y verificar que siguen pasando**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_facturas.test_abono_view apps.core.tests_facturas.test_abono_service --noinput -v 2`
Expected: PASS (sin regresiones — el HTML de la página completa es equivalente).

- [ ] **Step 4: Commit**

```bash
git add templates/facturas/_form_abono.html templates/facturas/form_abono.html
git commit -m "refactor(facturas): extraer _form_abono.html reutilizable"
```

---

### Task 4: Soporte AJAX (fragment + JSON) en las vistas de abono

**Files:**
- Modify: `apps/core/views/facturas_cliente.py` (`cliente_abono_nuevo`, `cliente_abono_editar`)
- Create: `templates/facturas/_abono_fragment.html`
- Test: `apps/core/tests_facturas/test_abono_modal.py`

**Interfaces:**
- Consumes: partial `facturas/_form_abono.html` (Task 3).
- Produces: en `cliente_abono_nuevo`/`cliente_abono_editar`, cuando la petición trae header `X-Requested-With: XMLHttpRequest`:
  - **GET** → `facturas/_abono_fragment.html` (HTML del modal).
  - **POST** éxito → `JsonResponse({'ok': True, 'saldo': '<saldo_a_favor>'})`.
  - **POST** con errores → `JsonResponse({'ok': False, 'errors': {...}}, status=400)`.

- [ ] **Step 1: Escribir el test que falla**

Create `apps/core/tests_facturas/test_abono_modal.py`:

```python
from decimal import Decimal

from django.contrib.auth.models import Permission, User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Cliente, DocumentoFactura, MetodoPago, Pago

AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}


@override_settings(FACTURAS_MODULE_ENABLED=True, ALLOWED_HOSTS=['testserver', 'localhost'])
class AbonoModalTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u', password='x')
        for cod in ('ver_facturas', 'gestionar_facturas', 'registrar_pago_factura'):
            self.user.user_permissions.add(Permission.objects.get(codename=cod))
        self.client.force_login(self.user)
        self.met = MetodoPago.objects.create(nombre='Efectivo', tipo='efectivo')
        self.cli = Cliente.objects.create(nombre='Renato')
        self.doc = DocumentoFactura.objects.create(
            cliente=self.cli, tipo_documento='factura', numero_documento='9543',
            fecha_documento=timezone.localdate(), monto_total=Decimal('1000'))
        self.url = reverse('cliente_abono_nuevo', args=[self.cli.pk])

    def test_get_ajax_devuelve_fragmento(self):
        resp = self.client.get(self.url, **AJAX)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'data-abono-form')
        self.assertNotContains(resp, '<nav')  # no es la página completa

    def test_post_ajax_registra_y_devuelve_json(self):
        resp = self.client.post(self.url, {
            'fecha_pago': timezone.localdate().isoformat(),
            'metodo_pago': self.met.pk, 'monto': '400',
        }, **AJAX)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['ok'])
        self.assertEqual(Pago.objects.filter(cliente=self.cli).count(), 1)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.saldo_pendiente, Decimal('600'))

    def test_post_ajax_invalido_devuelve_errores(self):
        resp = self.client.post(self.url, {'monto': ''}, **AJAX)
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.json()['ok'])
        self.assertIn('monto', resp.json()['errors'])

    def test_post_normal_sigue_redirigiendo(self):
        resp = self.client.post(self.url, {
            'fecha_pago': timezone.localdate().isoformat(),
            'metodo_pago': self.met.pk, 'monto': '400',
        })
        self.assertEqual(resp.status_code, 302)
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_facturas.test_abono_modal --noinput -v 2`
Expected: FAIL (GET AJAX devuelve la página completa; POST AJAX redirige en vez de JSON).

- [ ] **Step 3: Crear el fragmento del modal**

Create `templates/facturas/_abono_fragment.html`:

```html
{% load facturas_extras %}
<div class="modal-header">
  <div>
    <h5 class="modal-title mb-1"><i class="bi bi-cash-coin me-2"></i>{{ titulo }} · {{ cliente.nombre }}</h5>
    <div class="small text-muted">
      Debe: <strong class="text-danger">L {{ cliente.total_adeudado|moneda }}</strong>
      · Saldo a favor: <strong class="text-success">L {{ cliente.saldo_a_favor|moneda }}</strong>
    </div>
  </div>
  <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Cerrar"></button>
</div>
<div class="modal-body">
  {% include "facturas/_form_abono.html" %}
</div>
```

- [ ] **Step 4: Agregar el helper y ramificar las vistas**

In `apps/core/views/facturas_cliente.py`, add a helper after `_form_errors_json`:

```python
def _es_ajax(request):
    return request.headers.get('x-requested-with') == 'XMLHttpRequest'
```

In `cliente_abono_nuevo`, replace the `if request.method == 'POST':` block's success/GET handling so it reads:

```python
    if request.method == 'POST':
        form = AbonoClienteForm(request.POST, request.FILES)
        if form.is_valid():
            cd = form.cleaned_data
            aplicaciones, tiene_edicion = _leer_reparto(request, pendientes)
            payment_service.registrar_abono(
                cliente, fecha_pago=cd['fecha_pago'], metodo_pago=cd['metodo_pago'],
                monto=cd['monto'], referencia=cd.get('referencia', ''),
                comprobante=cd.get('comprobante'), notas=cd.get('notas', ''),
                aplicaciones=aplicaciones if tiene_edicion else None,
            )
            if _es_ajax(request):
                return JsonResponse({'ok': True, 'saldo': str(cliente.saldo_a_favor)})
            messages.success(request, 'Abono registrado.')
            return redirect('cliente_salidas', pk=cliente.pk)
        elif _es_ajax(request):
            return JsonResponse({'ok': False, 'errors': _form_errors_json(form)}, status=400)
    else:
        form = AbonoClienteForm(initial={'fecha_pago': timezone.localdate()})

    plantilla = 'facturas/_abono_fragment.html' if _es_ajax(request) else 'facturas/form_abono.html'
    return render(request, plantilla, {
        'form': form, 'cliente': cliente,
        'pendientes': [{'doc': d, 'aplicado': None} for d in pendientes],
        'modo_edicion': False, 'pago': None,
        'action_url': reverse('cliente_abono_nuevo', args=[cliente.pk]),
        'titulo': 'Registrar abono', 'submit_label': 'Registrar abono',
    })
```

Apply the same three changes (`JsonResponse` on success, `elif _es_ajax` on invalid, `plantilla` switch on render) to `cliente_abono_editar`, keeping its existing context (`modo_edicion=True`, `pago=pago`, its `action_url` and `docs`/`aplicado_por_doc`). Its render becomes:

```python
    plantilla = 'facturas/_abono_fragment.html' if _es_ajax(request) else 'facturas/form_abono.html'
    return render(request, plantilla, {
        'form': form, 'cliente': cliente,
        'pendientes': [{'doc': d, 'aplicado': aplicado_por_doc.get(d.pk)} for d in docs],
        'modo_edicion': True, 'pago': pago,
        'action_url': reverse('cliente_abono_editar', args=[pago.pk]),
        'titulo': 'Editar abono', 'submit_label': 'Guardar cambios',
    })
```

And in `cliente_abono_editar`, wrap its success `return` and add the invalid branch the same way:

```python
            if _es_ajax(request):
                return JsonResponse({'ok': True, 'saldo': str(cliente.saldo_a_favor)})
            messages.success(request, 'Abono actualizado.')
            return redirect('cliente_salidas', pk=cliente.pk)
        elif _es_ajax(request):
            return JsonResponse({'ok': False, 'errors': _form_errors_json(form)}, status=400)
```

- [ ] **Step 5: Correr los tests y verificar que pasan**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_facturas.test_abono_modal apps.core.tests_facturas.test_abono_view --noinput -v 2`
Expected: PASS (nuevos + existentes verdes).

- [ ] **Step 6: Commit**

```bash
git add apps/core/views/facturas_cliente.py templates/facturas/_abono_fragment.html apps/core/tests_facturas/test_abono_modal.py
git commit -m "feat(facturas): abono por AJAX (fragmento GET + JSON POST)"
```

---

### Task 5: Cablear el modal de abono (ficha de cliente + buscador)

**Files:**
- Modify: `templates/base.html` (contenedor de modal + include del JS)
- Create: `static/js/abono-modal.js`
- Modify: `templates/facturas/_tab_cliente.html` (botón abre modal)
- Test: `apps/core/tests_facturas/test_abono_modal.py` (agregar test de render del disparador)

**Interfaces:**
- Consumes: endpoint AJAX de abono (Task 4), evento `buscador:abono` (Task 2), contenedor de modal Bootstrap.
- Produces: función global `window.abrirAbono(clienteId)` y el elemento `#abonoModal`.

- [ ] **Step 1: Escribir el test de render que falla**

Append to `apps/core/tests_facturas/test_abono_modal.py`:

```python
    def test_tab_cliente_boton_abre_modal(self):
        resp = self.client.get(reverse('cliente_facturas_fragment', args=[self.cli.pk]))
        self.assertContains(resp, 'data-abrir-abono')

    def test_base_incluye_contenedor_modal(self):
        resp = self.client.get(reverse('dashboard'))
        self.assertContains(resp, 'id="abonoModal"')
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_facturas.test_abono_modal --noinput -v 2`
Expected: FAIL (`data-abrir-abono` / `abonoModal` ausentes).

- [ ] **Step 3: Agregar el contenedor de modal y el JS en `base.html`**

In `templates/base.html`, right after the `#buscadorOverlay` block added in Task 2, add:

```html
{% if user.is_authenticated and perms.core.registrar_pago_factura %}
<div class="modal fade" id="abonoModal" tabindex="-1" aria-hidden="true"
     data-abono-base-url="{% url 'cliente_abono_nuevo' 0 %}">
  <div class="modal-dialog modal-dialog-centered modal-lg">
    <div class="modal-content" id="abonoModalContent"></div>
  </div>
</div>
{% endif %}
```

In `templates/base.html`, after the `buscador.js` include, add:

```html
{% if user.is_authenticated and perms.core.registrar_pago_factura %}
<script src="{% static 'js/abono-modal.js' %}"></script>
{% endif %}
```

- [ ] **Step 4: Crear `static/js/abono-modal.js`**

Create `static/js/abono-modal.js`:

```javascript
(function () {
  var modalEl = document.getElementById('abonoModal');
  if (!modalEl || !window.bootstrap) return;

  var content = document.getElementById('abonoModalContent');
  var bsModal = new bootstrap.Modal(modalEl);
  // base URL con pk=0; se reemplaza por el id real.
  var baseUrl = modalEl.getAttribute('data-abono-base-url');

  // baseUrl trae pk=0 en el medio (…/clientes/0/abono/); reemplazar ese segmento.
  function urlFor(id) { return baseUrl.replace('/0/', '/' + id + '/'); }

  function csrf() {
    var m = document.cookie.match(/csrftoken=([^;]+)/);
    return m ? m[1] : '';
  }

  function limpiarErrores(form) {
    form.querySelectorAll('.js-abono-error').forEach(function (n) { n.remove(); });
  }

  function mostrarErrores(form, errors) {
    limpiarErrores(form);
    Object.keys(errors).forEach(function (campo) {
      var input = form.querySelector('[name="' + campo + '"]');
      var msg = document.createElement('div');
      msg.className = 'text-danger small js-abono-error';
      msg.textContent = errors[campo].join(' ');
      if (input && input.parentNode) input.parentNode.appendChild(msg);
      else form.prepend(msg);  // errores no ligados a un campo (p. ej. __all__)
    });
  }

  function wireForm() {
    var form = content.querySelector('form[data-abono-form]');
    if (!form) return;
    var cancel = content.querySelector('[data-abono-cancel]');
    if (cancel) cancel.addEventListener('click', function (e) { e.preventDefault(); bsModal.hide(); });
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var fd = new FormData(form);
      fetch(form.action, {
        method: 'POST', body: fd,
        headers: {'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': csrf()},
      }).then(function (r) {
        return r.json().then(function (data) { return {ok: r.ok, data: data}; });
      }).then(function (res) {
        if (res.ok && res.data.ok) {
          bsModal.hide();
          if (window.recargarTabCliente) window.recargarTabCliente();
          else window.location.reload();
        } else {
          // Mostrar los errores del formulario inline, conservando lo tipeado.
          mostrarErrores(form, (res.data && res.data.errors) || {});
        }
      }).catch(function () { alert('No se pudo registrar el abono.'); });
    });
  }

  window.abrirAbono = function (clienteId) {
    fetch(urlFor(clienteId), {headers: {'X-Requested-With': 'XMLHttpRequest'}})
      .then(function (r) { return r.text(); })
      .then(function (html) { content.innerHTML = html; bsModal.show(); wireForm(); })
      .catch(function () { alert('No se pudo abrir el abono.'); });
  };

  document.addEventListener('buscador:abono', function (e) {
    window.abrirAbono(e.detail.clienteId);
  });
  document.addEventListener('click', function (e) {
    var t = e.target.closest('[data-abrir-abono]');
    if (t) { e.preventDefault(); window.abrirAbono(t.getAttribute('data-abrir-abono')); }
  });
})();
```

- [ ] **Step 5: Cambiar el botón en `_tab_cliente.html`**

In `templates/facturas/_tab_cliente.html`, replace the "Registrar abono" link (line ~44):

```html
  <button type="button" class="btn btn-sm btn-success" data-abrir-abono="{{ cliente.pk }}">
    <i class="bi bi-cash-coin me-1"></i>Registrar abono
  </button>
```

- [ ] **Step 6: Correr los tests y verificar que pasan**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_facturas.test_abono_modal --noinput -v 2`
Expected: PASS.

- [ ] **Step 7: Suite completa (regresión)**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core --noinput -v 1`
Expected: OK (todos los tests verdes).

- [ ] **Step 8: Verificación en navegador (manual)**

En runserver Docker: desde la ficha de un cliente, "Registrar abono" abre el modal, se registra sin recargar y el saldo se actualiza; desde el buscador, "+ Abono" abre el mismo modal. Anotar OK en el PR.

- [ ] **Step 9: Commit**

```bash
git add templates/base.html static/js/abono-modal.js templates/facturas/_tab_cliente.html apps/core/tests_facturas/test_abono_modal.py
git commit -m "feat(facturas): registrar abono en modal desde ficha y buscador"
```

---

## Notas de ejecución

- **`recargarTabCliente`:** el JS de la ficha de cliente (que ya carga el fragmento `cliente_facturas_fragment` por AJAX) debería exponer una función global `window.recargarTabCliente()` que vuelva a pedir el fragmento; si no existe, el modal cae a `window.location.reload()`. Revisar el JS existente de la ficha de cliente al ejecutar Task 5 y, si es trivial, exponer esa función (mejora la experiencia sin recargar). El fragmento debe envolver su contenido en un contenedor con `id="tabClienteFacturas"`.
- **Fallback sin JS:** la página `form_abono.html` sigue siendo la ruta cuando no hay JS; no eliminar `cliente_abono_nuevo`/`editar` como vistas de página completa.
