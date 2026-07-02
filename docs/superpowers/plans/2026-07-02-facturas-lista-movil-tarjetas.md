# Lista de facturas: vista de tarjetas en móvil — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** En `templates/facturas/lista.html`, mostrar la tabla solo en desktop y una vista de tarjetas (una por documento) en móvil, eliminando el scroll horizontal.

**Architecture:** Cambio de una sola plantilla. La `<table>` existente se envuelve en `d-none d-md-block`; se agrega un bloque `d-md-none` con tarjetas que reutilizan las clases/atributos existentes (`fac-row`/`data-href`/`data-norow`/`btn-pago`), los includes (`_badges.html`, `_producto.html`) y el filtro `|moneda`. Sin cambios de vista, modelo, contexto ni JS.

**Tech Stack:** Django templates + Bootstrap (utilidades responsive `d-md-none`/`d-none d-md-block`).

## Global Constraints

- **Tests / manage.py SOLO vía Docker**, con `--noinput`:
  `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core --noinput -v 1`
- Solo se modifica `templates/facturas/lista.html` (+ un test liviano). NO tocar vistas, modelos ni el JS existente.
- Reutilizar: `facturas/_badges.html` (estado), `facturas/_producto.html` (categoría), filtro `|moneda` (ya cargado en la plantilla).
- El JS existente en `lista.html` (`.fac-row` navega por `data-href`, salta si el click cae en `[data-norow]`) y el `btn-pago` del `_modal_pago.html` deben seguir funcionando para las tarjetas — usar las MISMAS clases/atributos.
- La suite completa queda verde.

---

### Task 1: Vista de tarjetas en móvil para la lista de facturas

**Files:**
- Modify: `templates/facturas/lista.html` (envolver la tabla en `d-none d-md-block`; agregar el bloque `d-md-none` de tarjetas)
- Test: `apps/core/tests_facturas/test_views.py` (agregar un smoke test; si el nombre del archivo o clase de tests de la lista difiere, ubicarlo donde vivan los tests de `facturas_lista` — verificar con `grep -rn "facturas_lista" apps/core/tests_facturas/`)

**Interfaces:**
- Consumes: contexto existente de `facturas_lista` (`documentos`, `return_url`, permisos). No produce interfaces nuevas.

- [ ] **Step 1: Escribir el test que falla**

Primero ubicar el archivo/clase de tests de la lista: `grep -rn "facturas_lista" apps/core/tests_facturas/`. Agregar en la clase de tests correspondiente (que ya prepara un usuario con `ver_facturas` y `force_login`) un test que verifique que la respuesta trae AMBOS modos (tarjetas móvil + tabla desktop). Si no hay una clase adecuada, crear una mínima siguiendo el patrón del archivo. Ejemplo de test (adaptar el `setUp`/permisos al patrón existente del archivo):

```python
    def test_lista_incluye_tarjetas_movil_y_tabla(self):
        from apps.core.models import Cliente, DocumentoFactura
        from decimal import Decimal
        cli = Cliente.objects.create(nombre='Cli QR')
        DocumentoFactura.objects.create(
            cliente=cli, tipo_documento='factura', numero_documento='F-9',
            monto_total=Decimal('100.00'))
        resp = self.client.get(reverse('facturas_lista'))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        # Contenedor de tarjetas (móvil) y la tabla (desktop) deben coexistir.
        self.assertIn('d-md-none', html)
        self.assertIn('<table', html)
        self.assertIn('Cli QR', html)
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_facturas.test_views -v 2 --noinput 2>&1 | grep -E "FAIL|ERROR|OK|Ran "`
Expected: FAIL en el nuevo test — la plantilla aún no tiene `d-md-none` (hoy solo hay tabla).

(Si el test se ubicó en otro archivo, ajustar la ruta del `manage.py test`.)

- [ ] **Step 3: Envolver la tabla en solo-desktop y agregar las tarjetas móvil**

En `templates/facturas/lista.html`, la sección actual empieza (alrededor de la línea 138) con:

```html
<div class="card border-0 shadow-sm">
  <div class="table-responsive">
    <table class="table table-sm table-hover mb-0 align-middle">
```

Reemplazar la apertura `<div class="card border-0 shadow-sm">` por el bloque de tarjetas móvil seguido de la misma tarjeta pero marcada solo-desktop. Es decir, INSERTAR antes el bloque móvil y AGREGAR `d-none d-md-block` a la card de la tabla:

```html
<!-- Móvil: tarjetas (una por documento) -->
<div class="d-md-none">
  {% for doc in documentos %}
  <div class="card mb-2 fac-row" style="cursor:pointer"
       data-href="{% url 'factura_detalle' doc.pk %}?next={{ return_url|urlencode }}">
    <div class="card-body py-2 px-3">
      <div class="d-flex justify-content-between align-items-start mb-1">
        <span>
          {% if doc.tipo_documento == 'envio' %}
          <span class="badge bg-info-subtle text-info-emphasis"><i class="bi bi-truck me-1"></i>Envío</span>
          {% else %}
          <span class="badge bg-primary-subtle text-primary-emphasis"><i class="bi bi-receipt me-1"></i>Factura</span>
          {% endif %}
        </span>
        <span>{% include "facturas/_badges.html" with doc=doc %}</span>
      </div>
      <div class="fw-bold">{{ doc.cliente.nombre }}</div>
      <div class="text-muted small mb-1">
        #{{ doc.numero_documento|default:"–" }} · {% include "facturas/_producto.html" with doc=doc %}
      </div>
      <div class="d-flex flex-wrap gap-3 small mb-1">
        <span>Total <strong>L {{ doc.monto_total|moneda }}</strong></span>
        <span class="text-success">Pagado L {{ doc.monto_pagado|moneda }}</span>
        <span class="{% if doc.saldo_pendiente > 0 %}text-danger fw-bold{% endif %}">Saldo L {{ doc.saldo_pendiente|moneda }}</span>
      </div>
      <div class="text-muted small mb-2">
        <i class="bi bi-calendar3 me-1"></i>{{ doc.fecha_documento|date:"d/m/Y"|default:"–" }}
        · Vence {{ doc.fecha_vencimiento|date:"d/m/Y"|default:"–" }}
      </div>
      <div class="d-flex gap-1" data-norow="1">
        <a href="{% url 'factura_detalle' doc.pk %}?next={{ return_url|urlencode }}"
           class="btn btn-sm btn-outline-primary"><i class="bi bi-eye me-1"></i>Ver</a>
        {% if doc.archivo_pdf %}
        <a href="{% url 'factura_pdf' doc.pk %}" target="_blank"
           class="btn btn-sm btn-outline-secondary" title="PDF"><i class="bi bi-file-earmark-pdf-fill text-danger"></i></a>
        {% endif %}
        {% if perms.core.registrar_pago_factura and doc.estado_pago != 'anulada' and doc.estado_pago != 'pagada' %}
        <button type="button" class="btn btn-sm btn-outline-success btn-pago" title="Registrar pago"
                data-url="{% url 'factura_pago_nuevo' doc.pk %}"
                data-saldo="{{ doc.saldo_pendiente|stringformat:'.2f' }}"
                data-info="{{ doc.get_tipo_documento_display }} {{ doc.numero_documento }} · {{ doc.cliente.nombre }}">
          <i class="bi bi-cash-coin me-1"></i>Pago
        </button>
        {% endif %}
      </div>
    </div>
  </div>
  {% empty %}
  <div class="text-center text-muted py-4">
    <i class="bi bi-inbox fs-3 d-block mb-2"></i>Sin documentos para los filtros seleccionados.
  </div>
  {% endfor %}
</div>

<!-- Desktop: tabla -->
<div class="card border-0 shadow-sm d-none d-md-block">
  <div class="table-responsive">
    <table class="table table-sm table-hover mb-0 align-middle">
```

El resto de la tabla (thead, tbody, `</table></div></div>`) queda EXACTAMENTE igual. No tocar el `{% block extra_js %}` ni el `{% include "facturas/_modal_pago.html" %}` (si está) — el JS de `.fac-row` y `.btn-pago` ya aplica a las tarjetas por usar las mismas clases.

Notas:
- `_producto.html` ya hace su propio `{% load facturas_extras %}`, así que el badge de categoría con color funciona dentro de la tarjeta.
- Las tarjetas usan `class="fac-row"` + `data-href` (mismo comportamiento de navegación que las filas) y las acciones van dentro de `data-norow="1"` para no disparar el tap de la tarjeta.

- [ ] **Step 4: Correr el test y verificar que pasa**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_facturas.test_views -v 2 --noinput 2>&1 | grep -E "FAIL|ERROR|OK|Ran "`
Expected: PASS. Luego correr la suite completa:
`docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core --noinput -v 1`
Expected: verde.

- [ ] **Step 5: Verificación visual (obligatoria por ser cambio de layout)**

Levantar el server de dev (config `Django Dev (live mount)` en `.claude/launch.json`, puerto 8002), loguear, ir a `/facturas/`:
- A ~375px (móvil): se ven **tarjetas**, sin scroll horizontal; el tap en la tarjeta abre la ficha; el botón "Pago" abre el modal.
- A ≥768px (desktop): se ve la **tabla** como antes.
Tomar screenshot de ambos.

- [ ] **Step 6: Commit**

```bash
git add templates/facturas/lista.html apps/core/tests_facturas/test_views.py
git commit -m "feat(facturas): vista de tarjetas de la lista en móvil"
```

---

## Notas de despliegue

- Cambio solo de plantilla; sin migraciones ni dependencias. En el próximo redeploy el `collectstatic`/servido de templates lo toma automáticamente.
