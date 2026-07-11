# Estado de cuenta por cliente (PDF) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generar el estado de cuenta de un cliente (rango de fechas) como PDF y vista HTML, replicando el formato Excel actual, con subcliente por factura y color configurable por categoría.

**Architecture:** Un campo `subcliente` en `DocumentoFactura` y `color` en `CategoriaProducto` (una migración). Un servicio puro `estado_cuenta_service.build(cliente, desde, hasta)` arma los datos. Una vista `cliente_estado_cuenta` renderiza una plantilla única en HTML (con filtro de rango + botón de descarga) o la convierte a PDF con `xhtml2pdf`. La captura de los dos campos nuevos se engancha en los formularios que ya existen (editar factura, editar categoría).

**Tech Stack:** Django (server-rendered + Bootstrap), `xhtml2pdf` (Python puro, sin librerías de sistema), corre **solo en Docker**.

## Global Constraints

- **Tests y manage.py corren solo en Docker** (no hay `python` local). Test:
  `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test <ruta> --noinput -v 1`
- **makemigrations** también por Docker:
  `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py makemigrations core`
- **Cambios de dependencias requieren reconstruir la imagen:** tras editar `requirements.txt`, correr `docker compose build web` antes de testear (la imagen baked no monta dependencias nuevas).
- En tests, **usar `self.client.force_login(user)`** (nunca `client.login`; django-axes rompe el login por formulario).
- Vistas de facturas requieren `@login_required`, `@permission_required(_perm('...'), raise_exception=True)`, `@facturas_enabled`. Permiso de este estado de cuenta: `ver_facturas`.
- Tests que renderizan plantillas de facturas requieren `@override_settings(FACTURAS_MODULE_ENABLED=True, ALLOWED_HOSTS=['testserver', 'localhost'])`.
- No recalcular estados de pago a mano: usar las propiedades vivas `monto_pagado` / `saldo_pendiente`.
- Commits: el usuario autoriza commit por tarea durante la ejecución del plan.

---

### Task 1: Campos de modelo `subcliente` y `color` + migración

**Files:**
- Modify: `apps/core/models.py` (clases `DocumentoFactura`, `CategoriaProducto`)
- Create: `apps/core/migrations/0030_estado_cuenta_campos.py` (generada por makemigrations)
- Test: `apps/core/tests_facturas/test_estado_cuenta.py` (nuevo)

**Interfaces:**
- Produces:
  - `DocumentoFactura.subcliente` — `CharField(max_length=120, blank=True)`, default `''`.
  - `CategoriaProducto.color` — `CharField(max_length=7, blank=True)`, default `''` (hex tipo `#FFA500`).

- [ ] **Step 1: Escribir el test que falla**

Crear `apps/core/tests_facturas/test_estado_cuenta.py`:

```python
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Permission, User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.models import (
    Cliente, DocumentoFactura, CategoriaProducto, MetodoPago,
)
from apps.core.services.facturas import payment_service


class ModeloCamposNuevosTests(TestCase):
    def test_documento_acepta_subcliente_y_categoria_color(self):
        cat = CategoriaProducto.objects.create(nombre='Camiseta', color='#FFA500')
        cli = Cliente.objects.create(nombre='Cli')
        doc = DocumentoFactura.objects.create(
            cliente=cli, tipo_documento='factura', categoria=cat,
            fecha_documento=timezone.localdate(), monto_total=Decimal('100.00'),
            subcliente='Johan')
        doc.refresh_from_db(); cat.refresh_from_db()
        self.assertEqual(doc.subcliente, 'Johan')
        self.assertEqual(cat.color, '#FFA500')

    def test_defaults_vacios(self):
        cat = CategoriaProducto.objects.create(nombre='Lisa')
        cli = Cliente.objects.create(nombre='Cli2')
        doc = DocumentoFactura.objects.create(
            cliente=cli, tipo_documento='factura', monto_total=Decimal('1.00'))
        self.assertEqual(doc.subcliente, '')
        self.assertEqual(cat.color, '')
```

- [ ] **Step 2: Correr y verificar que falla**

Run:
```bash
docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web \
  manage.py test apps.core.tests_facturas.test_estado_cuenta --noinput -v 1
```
Expected: FAIL con `TypeError: 'subcliente' is an invalid keyword argument` (o error de columna inexistente).

- [ ] **Step 3: Agregar los campos**

En `apps/core/models.py`, dentro de `class DocumentoFactura`, junto a los otros campos de texto (después de `notas = models.TextField(blank=True)`):

```python
    subcliente = models.CharField(max_length=120, blank=True)
```

En `class CategoriaProducto`, después de `orden = models.PositiveIntegerField(default=0)`:

```python
    color = models.CharField(
        max_length=7, blank=True,
        help_text='Color hex (p. ej. #FFA500) para resaltar la categoría en el estado de cuenta.')
```

- [ ] **Step 4: Generar la migración**

Run:
```bash
docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web \
  manage.py makemigrations core
```
Expected: crea un archivo `apps/core/migrations/0030_*.py` que agrega `subcliente` y `color`. (Si el número difiere, usar el que genere.)

- [ ] **Step 5: Correr los tests y verificar que pasan**

Run:
```bash
docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web \
  manage.py test apps.core.tests_facturas.test_estado_cuenta --noinput -v 1
```
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add apps/core/models.py apps/core/migrations/ apps/core/tests_facturas/test_estado_cuenta.py
git commit -m "feat(facturas): campos subcliente (documento) y color (categoría)"
```

---

### Task 2: Servicio `estado_cuenta_service.build`

**Files:**
- Create: `apps/core/services/facturas/estado_cuenta_service.py`
- Test: `apps/core/tests_facturas/test_estado_cuenta.py` (agregar clase)

**Interfaces:**
- Consumes: `DocumentoFactura.subcliente`, `CategoriaProducto.color` (Task 1); propiedades `monto_pagado`, `saldo_pendiente`; relación `documento.aplicaciones` → `AplicacionPago.pago.fecha_pago`.
- Produces: `build(cliente, desde, hasta) -> dict` con claves `cliente, desde, hasta, filas, totales`. Cada fila: `{subcliente, producto, color, etiqueta, fecha, libras, precio, valor, pago, fecha_cancelacion}`. `totales`: `{libras, valor, pago, saldo}`.

- [ ] **Step 1: Escribir los tests que fallan**

Agregar a `apps/core/tests_facturas/test_estado_cuenta.py`:

```python
class EstadoCuentaServiceTests(TestCase):
    def setUp(self):
        from apps.core.services.facturas import estado_cuenta_service
        self.svc = estado_cuenta_service
        self.hoy = timezone.localdate()
        self.cli = Cliente.objects.create(nombre='Renato')
        self.cat = CategoriaProducto.objects.create(nombre='Camiseta', color='#FFA500')
        self.met = MetodoPago.objects.create(nombre='Efectivo', tipo='efectivo')
        self.f1 = DocumentoFactura.objects.create(
            cliente=self.cli, tipo_documento='factura', categoria=self.cat,
            numero_documento='125', fecha_documento=self.hoy - timedelta(days=5),
            total_libras=Decimal('2500'), precio_por_libra=Decimal('36.00'),
            monto_total=Decimal('90000.00'), subcliente='Johan')
        self.e1 = DocumentoFactura.objects.create(
            cliente=self.cli, tipo_documento='envio',
            numero_documento='870', fecha_documento=self.hoy - timedelta(days=3),
            total_libras=Decimal('2400'), precio_por_libra=Decimal('37.50'),
            monto_total=Decimal('90000.00'))

    def test_incluye_rango_y_excluye_anuladas(self):
        anulada = DocumentoFactura.objects.create(
            cliente=self.cli, tipo_documento='factura', numero_documento='X',
            fecha_documento=self.hoy, monto_total=Decimal('50.00'), estado_pago='anulada')
        fuera = DocumentoFactura.objects.create(
            cliente=self.cli, tipo_documento='factura', numero_documento='Y',
            fecha_documento=self.hoy - timedelta(days=40), monto_total=Decimal('50.00'))
        datos = self.svc.build(self.cli, self.hoy - timedelta(days=10), self.hoy)
        etiquetas = [f['etiqueta'] for f in datos['filas']]
        self.assertIn('125', etiquetas)
        self.assertIn('Envio 870', etiquetas)   # los envíos llevan prefijo
        self.assertNotIn('X', etiquetas)         # anulada excluida
        self.assertNotIn('Y', etiquetas)         # fuera de rango

    def test_fila_lleva_subcliente_y_color(self):
        datos = self.svc.build(self.cli, self.hoy - timedelta(days=10), self.hoy)
        fila125 = next(f for f in datos['filas'] if f['etiqueta'] == '125')
        self.assertEqual(fila125['subcliente'], 'Johan')
        self.assertEqual(fila125['producto'], 'Camiseta')
        self.assertEqual(fila125['color'], '#FFA500')

    def test_fecha_cancelacion_solo_si_saldo_cero(self):
        # f1 sin pago -> None; e1 pagada completa -> fecha del abono
        payment_service.registrar_abono(
            self.cli, fecha_pago=self.hoy, metodo_pago=self.met,
            monto=Decimal('90000.00'), aplicaciones=[(self.e1, Decimal('90000.00'))])
        datos = self.svc.build(self.cli, self.hoy - timedelta(days=10), self.hoy)
        fila_f1 = next(f for f in datos['filas'] if f['etiqueta'] == '125')
        fila_e1 = next(f for f in datos['filas'] if f['etiqueta'] == 'Envio 870')
        self.assertIsNone(fila_f1['fecha_cancelacion'])
        self.assertEqual(fila_e1['fecha_cancelacion'], self.hoy)

    def test_totales_y_saldo(self):
        payment_service.registrar_abono(
            self.cli, fecha_pago=self.hoy, metodo_pago=self.met,
            monto=Decimal('40000.00'), aplicaciones=[(self.f1, Decimal('40000.00'))])
        datos = self.svc.build(self.cli, self.hoy - timedelta(days=10), self.hoy)
        t = datos['totales']
        self.assertEqual(t['libras'], Decimal('4900'))          # 2500 + 2400
        self.assertEqual(t['valor'], Decimal('180000.00'))      # 90000 + 90000
        self.assertEqual(t['pago'], Decimal('40000.00'))
        self.assertEqual(t['saldo'], Decimal('140000.00'))      # valor - pago
```

- [ ] **Step 2: Correr y verificar que falla**

Run:
```bash
docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web \
  manage.py test apps.core.tests_facturas.test_estado_cuenta.EstadoCuentaServiceTests --noinput -v 1
```
Expected: FAIL con `ModuleNotFoundError: ... estado_cuenta_service` (o ImportError).

- [ ] **Step 3: Implementar el servicio**

Crear `apps/core/services/facturas/estado_cuenta_service.py`:

```python
"""estado_cuenta_service — arma los datos del estado de cuenta por cliente."""
from decimal import Decimal


def _fecha_cancelacion(doc):
    """Fecha del abono que cerró la factura (saldo 0), o None si aún tiene saldo."""
    if doc.saldo_pendiente > 0:
        return None
    fechas = [a.pago.fecha_pago for a in doc.aplicaciones.select_related('pago')]
    return max(fechas) if fechas else None


def build(cliente, desde, hasta):
    """Datos del estado de cuenta de `cliente` en el rango [desde, hasta] (inclusive)."""
    docs = (cliente.documentos
            .filter(tipo_documento__in=('factura', 'envio'),
                    fecha_documento__gte=desde, fecha_documento__lte=hasta)
            .exclude(estado_pago='anulada')
            .select_related('categoria')
            .order_by('fecha_documento', 'created_at'))
    filas = []
    tot_libras = tot_valor = tot_pago = Decimal('0')
    for doc in docs:
        libras = doc.total_libras or Decimal('0')
        valor = doc.monto_total or Decimal('0')
        pago = doc.monto_pagado
        etiqueta = doc.numero_documento or str(doc.pk)
        if doc.tipo_documento == 'envio':
            etiqueta = f'Envio {etiqueta}'
        filas.append({
            'subcliente': doc.subcliente,
            'producto': doc.categoria.nombre if doc.categoria else '',
            'color': doc.categoria.color if doc.categoria else '',
            'etiqueta': etiqueta,
            'fecha': doc.fecha_documento,
            'libras': libras,
            'precio': doc.precio_por_libra,
            'valor': valor,
            'pago': pago,
            'fecha_cancelacion': _fecha_cancelacion(doc),
        })
        tot_libras += libras
        tot_valor += valor
        tot_pago += pago
    return {
        'cliente': cliente,
        'desde': desde, 'hasta': hasta,
        'filas': filas,
        'totales': {
            'libras': tot_libras, 'valor': tot_valor, 'pago': tot_pago,
            'saldo': tot_valor - tot_pago,
        },
    }
```

- [ ] **Step 4: Correr y verificar que pasan**

Run:
```bash
docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web \
  manage.py test apps.core.tests_facturas.test_estado_cuenta.EstadoCuentaServiceTests --noinput -v 1
```
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/core/services/facturas/estado_cuenta_service.py apps/core/tests_facturas/test_estado_cuenta.py
git commit -m "feat(facturas): servicio estado_cuenta_service.build"
```

---

### Task 3: Vista + PDF + plantilla + URL + botón + dependencia

**Files:**
- Modify: `requirements.txt`
- Create: `apps/core/views/facturas_estado_cuenta.py`
- Modify: `apps/core/views/__init__.py`
- Create: `templates/facturas/estado_cuenta.html`
- Modify: `apps/core/urls.py` (junto a las rutas de cliente, ~línea 102)
- Modify: `templates/clientes/salidas.html` (encabezado, ~líneas 26-33)
- Test: `apps/core/tests_facturas/test_estado_cuenta.py` (agregar clase)

**Interfaces:**
- Consumes: `estado_cuenta_service.build` (Task 2).
- Produces: vista `cliente_estado_cuenta(request, pk)` (URL name `cliente_estado_cuenta`); HTML por defecto, PDF con `?format=pdf`.

- [ ] **Step 1: Agregar la dependencia y reconstruir la imagen**

En `requirements.txt`, agregar una línea:
```
xhtml2pdf==0.2.16
```
Luego reconstruir la imagen (la nueva dependencia debe quedar dentro del contenedor):
```bash
docker compose build web
```
Expected: build OK, con `xhtml2pdf` y su dependencia `reportlab` instaladas.

- [ ] **Step 2: Escribir los tests que fallan**

Agregar a `apps/core/tests_facturas/test_estado_cuenta.py`:

```python
@override_settings(FACTURAS_MODULE_ENABLED=True, ALLOWED_HOSTS=['testserver', 'localhost'])
class EstadoCuentaViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u', password='x')
        self.user.user_permissions.add(Permission.objects.get(codename='ver_facturas'))
        self.cli = Cliente.objects.create(nombre='Renato Diaz')
        DocumentoFactura.objects.create(
            cliente=self.cli, tipo_documento='factura', numero_documento='125',
            fecha_documento=timezone.localdate(), total_libras=Decimal('2500'),
            precio_por_libra=Decimal('36.00'), monto_total=Decimal('90000.00'))

    def test_html_ok(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('cliente_estado_cuenta', args=[self.cli.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Estado de Cuenta')
        self.assertContains(resp, 'Renato Diaz')
        self.assertContains(resp, '125')

    def test_pdf_ok(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('cliente_estado_cuenta', args=[self.cli.pk]), {'format': 'pdf'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')
        self.assertTrue(resp.content.startswith(b'%PDF'))

    def test_sin_permiso_403(self):
        otro = User.objects.create_user('sinperm', password='x')
        self.client.force_login(otro)
        resp = self.client.get(reverse('cliente_estado_cuenta', args=[self.cli.pk]))
        self.assertEqual(resp.status_code, 403)
```

- [ ] **Step 3: Correr y verificar que fallan**

Run:
```bash
docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web \
  manage.py test apps.core.tests_facturas.test_estado_cuenta.EstadoCuentaViewTests --noinput -v 1
```
Expected: FAIL con `NoReverseMatch: Reverse for 'cliente_estado_cuenta' not found`.

- [ ] **Step 4: Crear el módulo de vista**

Crear `apps/core/views/facturas_estado_cuenta.py`:

```python
"""facturas_estado_cuenta.py — Estado de cuenta por cliente (HTML y PDF)."""
import os
from io import BytesIO

from django.template.loader import render_to_string
from xhtml2pdf import pisa

from .common import *  # noqa: F401,F403

from ..models import Cliente
from ..services.facturas import estado_cuenta_service


def _parse_fecha(raw, default):
    if not raw:
        return default
    try:
        return dt_datetime.strptime(raw, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return default


def _pdf_link_callback(uri, rel):
    """Resuelve URLs /static/ y /media/ a rutas de archivo para xhtml2pdf."""
    if uri.startswith(settings.MEDIA_URL):
        return os.path.join(settings.MEDIA_ROOT, uri[len(settings.MEDIA_URL):])
    if uri.startswith(settings.STATIC_URL):
        rel_path = uri[len(settings.STATIC_URL):]
        candidato = os.path.join(settings.STATIC_ROOT, rel_path)
        if os.path.exists(candidato):
            return candidato
        for d in settings.STATICFILES_DIRS:
            alt = os.path.join(d, rel_path)
            if os.path.exists(alt):
                return alt
        return candidato
    return uri


def _render_pdf(html):
    salida = BytesIO()
    resultado = pisa.CreatePDF(src=html, dest=salida, link_callback=_pdf_link_callback, encoding='utf-8')
    if resultado.err:
        return None
    return salida.getvalue()


@login_required
@permission_required(_perm('ver_facturas'), raise_exception=True)
@facturas_enabled
def cliente_estado_cuenta(request, pk):
    cliente = get_object_or_404(Cliente, pk=pk)
    hoy = timezone.localdate()
    hasta = _parse_fecha(request.GET.get('hasta'), hoy)
    desde = _parse_fecha(request.GET.get('desde'), hasta - timedelta(days=60))
    datos = estado_cuenta_service.build(cliente, desde, hasta)
    es_pdf = request.GET.get('format') == 'pdf'
    html = render_to_string('facturas/estado_cuenta.html', {'es_pdf': es_pdf, **datos}, request=request)
    if not es_pdf:
        return HttpResponse(html)
    pdf = _render_pdf(html)
    if pdf is None:
        return HttpResponse('Error al generar el PDF.', status=500)
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = f'attachment; filename="estado-cuenta-{cliente.pk}-{hasta.isoformat()}.pdf"'
    return resp
```

(`dt_datetime`, `timedelta`, `settings`, `timezone`, `HttpResponse`, `get_object_or_404`, `login_required`, `permission_required`, `_perm`, `facturas_enabled` vienen de `from .common import *`.)

- [ ] **Step 5: Registrar el módulo de vistas**

En `apps/core/views/__init__.py`, junto a las otras líneas `from .facturas_* import *`, agregar:

```python
from .facturas_estado_cuenta import *   # noqa: F401,F403
```

- [ ] **Step 6: Crear la plantilla**

Crear `templates/facturas/estado_cuenta.html`:

```html
{% load static facturas_extras %}
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @page { size: letter landscape; margin: 1.4cm; }
  body { font-family: Helvetica, Arial, sans-serif; font-size: 10px; color: #000; }
  table.hdr { width: 100%; margin-bottom: 10px; }
  table.hdr td { vertical-align: middle; }
  .title { text-align: center; font-size: 18px; font-weight: bold; }
  .cliente { text-align: center; font-size: 13px; color: #1a5fb4; font-weight: bold; }
  table.doc { width: 100%; border-collapse: collapse; }
  table.doc th, table.doc td { border: 1px solid #cccccc; padding: 3px 5px; }
  table.doc th { background-color: #f0f0f0; }
  .num { text-align: right; }
  .tot td { font-weight: bold; background-color: #fafafa; }
  .saldo td { font-size: 14px; font-weight: bold; background-color: #cfe2ff; }
  .filtro { margin-bottom: 12px; font-size: 13px; }
</style>
</head>
<body>
  {% if not es_pdf %}
  <div class="filtro">
    <form method="get" style="display:inline">
      Desde <input type="date" name="desde" value="{{ desde|date:'Y-m-d' }}">
      Hasta <input type="date" name="hasta" value="{{ hasta|date:'Y-m-d' }}">
      <button type="submit">Consultar</button>
    </form>
    <a href="?format=pdf&amp;desde={{ desde|date:'Y-m-d' }}&amp;hasta={{ hasta|date:'Y-m-d' }}">Descargar PDF</a>
  </div>
  {% endif %}

  <table class="hdr">
    <tr>
      <td style="width:25%"><img src="{% static 'images/logo.png' %}" style="height:46px"></td>
      <td style="width:50%">
        <div class="title">Estado de Cuenta</div>
        <div class="cliente">{{ cliente.nombre }}</div>
      </td>
      <td style="width:25%; text-align:right">{{ hasta|date:'d/m/Y' }}</td>
    </tr>
  </table>

  <table class="doc">
    <thead>
      <tr>
        <th>Subcliente</th><th>Producto</th><th>Fact</th><th>Fecha</th>
        <th class="num">Lbs</th><th class="num">Precio</th><th class="num">Valor</th>
        <th class="num">Pago</th><th>F. Canc</th>
      </tr>
    </thead>
    <tbody>
      {% for f in filas %}
      <tr>
        <td>{{ f.subcliente }}</td>
        <td>{{ f.producto }}</td>
        <td{% if f.color %} style="background-color: {{ f.color }}"{% endif %}>{{ f.etiqueta }}</td>
        <td>{{ f.fecha|date:'d/m/Y' }}</td>
        <td class="num">{{ f.libras|floatformat:'-2' }}</td>
        <td class="num">{% if f.precio %}L {{ f.precio|moneda }}{% endif %}</td>
        <td class="num">L {{ f.valor|moneda }}</td>
        <td class="num">{% if f.pago %}L {{ f.pago|moneda }}{% endif %}</td>
        <td>{{ f.fecha_cancelacion|date:'d/m/Y' }}</td>
      </tr>
      {% empty %}
      <tr><td colspan="9" style="text-align:center; padding:10px">Sin documentos en el rango.</td></tr>
      {% endfor %}
    </tbody>
    <tfoot>
      <tr class="tot">
        <td colspan="4" class="num">Totales</td>
        <td class="num">{{ totales.libras|floatformat:'-2' }}</td>
        <td></td>
        <td class="num">L {{ totales.valor|moneda }}</td>
        <td class="num">L {{ totales.pago|moneda }}</td>
        <td></td>
      </tr>
      <tr class="saldo">
        <td colspan="6" class="num">Saldo Total</td>
        <td colspan="3" class="num">L {{ totales.saldo|moneda }}</td>
      </tr>
    </tfoot>
  </table>
</body>
</html>
```

- [ ] **Step 7: Agregar la URL**

En `apps/core/urls.py`, junto a las rutas de cliente (después de `cliente_abono_editar`/`cliente_abono_borrar`, ~línea 104):

```python
    path('facturas/clientes/<int:pk>/estado-cuenta/', views.cliente_estado_cuenta, name='cliente_estado_cuenta'),
```

- [ ] **Step 8: Agregar el botón en la ficha del cliente**

En `templates/clientes/salidas.html`, en el `<div class="d-flex gap-2">` del encabezado (antes del botón "Editar", ~línea 27):

```html
    {% if facturas_enabled and perms.core.ver_facturas %}
    <a href="{% url 'cliente_estado_cuenta' cliente.pk %}" class="btn btn-light btn-sm fw-semibold">
      <i class="bi bi-file-earmark-text me-1"></i>Estado de cuenta
    </a>
    {% endif %}
```

- [ ] **Step 9: Correr los tests y verificar que pasan**

Run:
```bash
docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web \
  manage.py test apps.core.tests_facturas.test_estado_cuenta.EstadoCuentaViewTests --noinput -v 1
```
Expected: PASS (3 tests). Si `test_pdf_ok` falla al resolver el logo, revisar `_pdf_link_callback` con systematic-debugging (un logo no resuelto no debería marcar `err`, pero un error de parseo sí).

- [ ] **Step 10: Commit**

```bash
git add requirements.txt apps/core/views/facturas_estado_cuenta.py apps/core/views/__init__.py templates/facturas/estado_cuenta.html apps/core/urls.py templates/clientes/salidas.html apps/core/tests_facturas/test_estado_cuenta.py
git commit -m "feat(facturas): estado de cuenta por cliente en HTML y PDF"
```

---

### Task 4: Captura de `subcliente` y `color` en los formularios

**Files:**
- Modify: `apps/core/forms.py` (`DocumentoEditarForm`, `CategoriaProductoForm`)
- Modify: `templates/facturas/form_editar.html`
- Modify: `templates/categorias_producto/form.html`
- Test: `apps/core/tests_facturas/test_estado_cuenta.py` (agregar clase)

**Interfaces:**
- Consumes: campos `DocumentoFactura.subcliente`, `CategoriaProducto.color` (Task 1).
- Produces: ambos campos editables desde `factura_editar` y `categoria_producto_editar`.

- [ ] **Step 1: Escribir los tests que fallan**

Agregar a `apps/core/tests_facturas/test_estado_cuenta.py` (import al inicio del archivo):

```python
from apps.core.forms import DocumentoEditarForm, CategoriaProductoForm
```

Y la clase:

```python
class CapturaCamposFormTests(TestCase):
    def test_documento_editar_form_guarda_subcliente(self):
        cli = Cliente.objects.create(nombre='Cli')
        doc = DocumentoFactura.objects.create(
            cliente=cli, tipo_documento='factura', monto_total=Decimal('100.00'))
        form = DocumentoEditarForm({
            'cliente': cli.pk, 'tipo_documento': 'factura', 'numero_documento': 'F-1',
            'estado_revision': 'pendiente', 'subtotal': '0', 'isv': '0',
            'monto_total': '100', 'subcliente': 'Johan',
        }, instance=doc)
        self.assertTrue(form.is_valid(), form.errors)
        guardado = form.save()
        self.assertEqual(guardado.subcliente, 'Johan')

    def test_categoria_form_guarda_color(self):
        form = CategoriaProductoForm({'nombre': 'Camiseta', 'orden': '0', 'color': '#FFA500'})
        self.assertTrue(form.is_valid(), form.errors)
        cat = form.save()
        self.assertEqual(cat.color, '#FFA500')
```

- [ ] **Step 2: Correr y verificar que fallan**

Run:
```bash
docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web \
  manage.py test apps.core.tests_facturas.test_estado_cuenta.CapturaCamposFormTests --noinput -v 1
```
Expected: FAIL — el `subcliente`/`color` no se guardan (los campos no están en los forms).

- [ ] **Step 3: Agregar los campos a los formularios**

En `apps/core/forms.py`, `DocumentoEditarForm.Meta.fields`: agregar `'subcliente'` al final de la lista. En `widgets`, agregar:

```python
            'subcliente': forms.TextInput(attrs={'class': 'form-control'}),
```

En `CategoriaProductoForm.Meta.fields`: agregar `'color'`. En `widgets`, agregar:

```python
            'color': forms.TextInput(attrs={'type': 'color', 'class': 'form-control form-control-color'}),
```

- [ ] **Step 4: Agregar los campos a las plantillas**

En `templates/facturas/form_editar.html`, agregar un bloque para `subcliente` (junto a los otros campos del form; seguir el patrón de columnas existente):

```html
        <div class="col-12 col-md-4">
          <label class="form-label">Subcliente</label>
          {{ form.subcliente }}
          {% if form.subcliente.errors %}<div class="text-danger small">{{ form.subcliente.errors }}</div>{% endif %}
        </div>
```

En `templates/categorias_producto/form.html`, agregar dentro del `<div class="row g-3">` (después del bloque de "Palabra clave", ~línea 32):

```html
        <div class="col-12 col-md-4">
          <label class="form-label">Color</label>
          {{ form.color }}
          <div class="form-text">Resalta la categoría en el estado de cuenta.</div>
          {% if form.color.errors %}<div class="text-danger small">{{ form.color.errors }}</div>{% endif %}
        </div>
```

- [ ] **Step 5: Correr y verificar que pasan**

Run:
```bash
docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web \
  manage.py test apps.core.tests_facturas.test_estado_cuenta.CapturaCamposFormTests --noinput -v 1
```
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add apps/core/forms.py templates/facturas/form_editar.html templates/categorias_producto/form.html apps/core/tests_facturas/test_estado_cuenta.py
git commit -m "feat(facturas): capturar subcliente (factura) y color (categoría) en los formularios"
```

---

### Task 5: Regresión completa

**Files:** ninguno (verificación).

- [ ] **Step 1: Correr toda la suite de facturas**

Run:
```bash
docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web \
  manage.py test apps.core.tests_facturas --noinput -v 1
```
Expected: OK, sin regresiones (incluye los tests nuevos de `test_estado_cuenta` y los previos de abonos/pagos/tab).

- [ ] **Step 2 (si algo falla): depurar** siguiendo superpowers:systematic-debugging antes de dar por terminado.
