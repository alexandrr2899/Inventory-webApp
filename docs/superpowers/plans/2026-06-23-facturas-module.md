# Módulo Facturas — Plan de Implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agregar un módulo "Facturas" (documentos tipo Factura y Envío) a la app de inventario Django, con carga de PDF, extracción de datos, tarifas por cliente, pagos múltiples, estados automáticos y una tab en la vista de cliente — sin tocar inventario ni stock.

**Architecture:** Todo vive dentro de `apps/core` (mismo `app_label`, migraciones en `core/migrations/`), modular por archivos siguiendo la convención existente: vistas en `apps/core/views/facturas*.py`, lógica en `apps/core/services/facturas/`, plantillas en `templates/facturas/`. El módulo se activa/desactiva con `FACTURAS_MODULE_ENABLED` y es exclusivo del grupo Administrador.

**Tech Stack:** Django 4.2, PostgreSQL, PyMuPDF (extracción de texto), Bootstrap 5 (UI), python-decouple (config), openpyxl (ya presente).

## Global Constraints

- App: NO crear app Django nueva. Todo en `apps/core` (`app_label='core'`).
- Modelo Cliente: usar `core.Cliente` existente; NO crear otro.
- NO modificar inventario ni descontar stock en esta fase.
- NO modificar el contenido de la tab "Productos llevados" (`templates/clientes/salidas.html`) — solo envolverlo en tabs.
- Permisos: módulo exclusivo de Administrador. Permisos custom: `ver_facturas`, `gestionar_facturas`, `registrar_pago_factura`, `anular_factura`, `gestionar_tarifas`.
- Interruptor: `FACTURAS_MODULE_ENABLED = config('FACTURAS_MODULE_ENABLED', default=True, cast=bool)`.
- Productos: choices `('camiseta','Camiseta'), ('lisa','Lisa'), ('otro','Otro')`.
- Montos: siempre `DecimalField(max_digits=12, decimal_places=2)`. Libras y precio: `max_digits=12, decimal_places=2`.
- Helper de permiso: `_perm('codename')` → `'core.codename'` (en `apps/core/views/common.py`).
- Vistas: `@login_required` + `@permission_required(_perm('...'), raise_exception=True)`, igual que el resto.
- Cada módulo de vistas nuevo se importa en `apps/core/views/__init__.py` con `from .modulo import *`.
- Archivos PDF: `FileField(upload_to='facturas/%Y/%m/')` en `MEDIA_ROOT`.
- NO OCR. PyMuPDF (`fitz`) para texto; `pdfplumber` solo documentado como opcional.
- PDFs de muestra reales: `docs/facturas/samples/` (el usuario los provee; afinan los extractores en la Task 14).
- Rama de trabajo: `feat/facturas-module` (ya creada). NO hacer push sin autorización.

---

## File Structure

**Crear:**
- `apps/core/services/facturas/__init__.py`
- `apps/core/services/facturas/status_service.py` — cálculo de estado de pago
- `apps/core/services/facturas/payment_service.py` — registrar pago + recálculo
- `apps/core/services/facturas/invoice_service.py` — alta desde PDF
- `apps/core/services/facturas/pdf_service.py` — extracción de texto (PyMuPDF)
- `apps/core/services/facturas/pdf_extractors/__init__.py`
- `apps/core/services/facturas/pdf_extractors/base_extractor.py`
- `apps/core/services/facturas/pdf_extractors/factura_extractor.py`
- `apps/core/services/facturas/pdf_extractors/envio_extractor.py`
- `apps/core/views/facturas.py` — dashboard, listado, detalle, upload, editar, anular, revisar
- `apps/core/views/facturas_pagos.py` — registrar pago / historial
- `apps/core/views/facturas_tarifas.py` — CRUD tarifas por cliente
- `apps/core/views/facturas_cliente.py` — fragmento AJAX tab cliente
- `apps/core/tests_facturas/__init__.py`
- `apps/core/tests_facturas/test_models.py`
- `apps/core/tests_facturas/test_status_service.py`
- `apps/core/tests_facturas/test_payment_service.py`
- `apps/core/tests_facturas/test_extractors.py`
- `apps/core/tests_facturas/test_invoice_service.py`
- `apps/core/tests_facturas/test_views.py`
- `apps/core/tests_facturas/test_cliente_tab.py`
- `templates/facturas/dashboard.html`
- `templates/facturas/lista.html`
- `templates/facturas/detalle.html`
- `templates/facturas/form_upload.html`
- `templates/facturas/form_editar.html`
- `templates/facturas/form_pago.html`
- `templates/facturas/tarifas.html`
- `templates/facturas/_tab_cliente.html` — fragmento AJAX
- `templates/facturas/_badges.html` — include de badges de estado

**Modificar:**
- `config/settings.py` — flag `FACTURAS_MODULE_ENABLED` + context processor
- `apps/core/models.py` — 3 modelos nuevos
- `apps/core/forms.py` — formularios nuevos
- `apps/core/signals.py` — recálculo al guardar/borrar pago
- `apps/core/views/common.py` — decorador `facturas_enabled` + helper de contexto
- `apps/core/views/__init__.py` — importar módulos nuevos
- `apps/core/urls.py` — rutas nuevas
- `apps/core/admin.py` — registrar modelos
- `apps/core/context_processors.py` (crear si no existe) — `facturas_enabled`
- `apps/core/management/commands/setup_groups.py` — permisos a Administrador
- `templates/clientes/salidas.html` — envolver en tabs + tab Facturas
- `templates/includes/nav_menu.html` — enlace al módulo
- `requirements.txt` — PyMuPDF

---

## Task 1: Dependencia, flag de configuración y decorador del interruptor

**Files:**
- Modify: `requirements.txt`
- Modify: `config/settings.py:168` (zona MEDIA / añadir flag)
- Create: `apps/core/context_processors.py`
- Modify: `config/settings.py:89` (context_processors)
- Modify: `apps/core/views/common.py` (decorador `facturas_enabled`)
- Test: `apps/core/tests_facturas/__init__.py`, `apps/core/tests_facturas/test_views.py`

**Interfaces:**
- Produces: `settings.FACTURAS_MODULE_ENABLED: bool`
- Produces: `apps.core.views.common.facturas_enabled(viewfunc)` — decorador; si el flag está apagado, `raise Http404`.
- Produces: context var `facturas_enabled` en todas las plantillas (vía `apps.core.context_processors.facturas_flags`).

- [ ] **Step 1: Añadir PyMuPDF a requirements**

En `requirements.txt`, añadir al final:

```
PyMuPDF==1.24.5
# pdfplumber==0.11.4  # opcional: fallback para extracción de tablas (no usado por defecto)
```

Instalar: `pip install PyMuPDF==1.24.5`

- [ ] **Step 2: Añadir el flag en settings**

En `config/settings.py`, en la sección de MEDIA (tras `MEDIA_ROOT`, ~línea 171), añadir:

```python
# ─── MÓDULO FACTURAS ──────────────────────────────────────────────────────────
# Interruptor del módulo Facturas (Factura + Envío). Apagarlo lo oculta por
# completo (menú, tab de cliente y rutas → 404). No afecta inventario ni stock.
FACTURAS_MODULE_ENABLED = config('FACTURAS_MODULE_ENABLED', default=True, cast=bool)
```

- [ ] **Step 3: Crear el context processor**

Crear `apps/core/context_processors.py`:

```python
"""Context processors de core."""
from django.conf import settings


def facturas_flags(request):
    """Expone el estado del módulo Facturas a todas las plantillas."""
    return {
        'facturas_enabled': getattr(settings, 'FACTURAS_MODULE_ENABLED', False),
    }
```

- [ ] **Step 4: Registrar el context processor**

En `config/settings.py`, dentro de `TEMPLATES[0]['OPTIONS']['context_processors']` (~línea 94), añadir tras `'django.template.context_processors.tz',`:

```python
                'apps.core.context_processors.facturas_flags',
```

- [ ] **Step 5: Añadir el decorador del interruptor**

En `apps/core/views/common.py`, tras la definición de `_perm` (~línea 65), añadir:

```python
def facturas_enabled(viewfunc):
    """Devuelve 404 si el módulo Facturas está desactivado por configuración."""
    @wraps(viewfunc)
    def _wrapped(request, *args, **kwargs):
        if not getattr(settings, 'FACTURAS_MODULE_ENABLED', False):
            raise Http404('Módulo Facturas desactivado.')
        return viewfunc(request, *args, **kwargs)
    return _wrapped
```

Asegurar que `facturas_enabled` quede exportado por el barrel: si `common.py` define `__all__`, añadir `'facturas_enabled'`.

- [ ] **Step 6: Crear el paquete de tests y un test del decorador**

Crear `apps/core/tests_facturas/__init__.py` (vacío).

Crear `apps/core/tests_facturas/test_views.py`:

```python
from django.test import TestCase, override_settings
from django.http import Http404
from django.test import RequestFactory

from apps.core.views.common import facturas_enabled


@facturas_enabled
def _vista_dummy(request):
    from django.http import HttpResponse
    return HttpResponse('ok')


class InterruptorFacturasTests(TestCase):
    def setUp(self):
        self.rf = RequestFactory()

    @override_settings(FACTURAS_MODULE_ENABLED=False)
    def test_decorador_404_cuando_apagado(self):
        with self.assertRaises(Http404):
            _vista_dummy(self.rf.get('/'))

    @override_settings(FACTURAS_MODULE_ENABLED=True)
    def test_decorador_pasa_cuando_encendido(self):
        resp = _vista_dummy(self.rf.get('/'))
        self.assertEqual(resp.status_code, 200)
```

- [ ] **Step 7: Ejecutar los tests**

Run: `python manage.py test apps.core.tests_facturas.test_views -v 2`
Expected: PASS (2 tests).

- [ ] **Step 8: Commit**

```bash
git add requirements.txt config/settings.py apps/core/context_processors.py apps/core/views/common.py apps/core/tests_facturas/
git commit -m "feat(facturas): flag de módulo, context processor y decorador interruptor"
```

---

## Task 2: Modelos DocumentoFactura, TarifaCliente, PagoFactura + permisos + migración

**Files:**
- Modify: `apps/core/models.py` (añadir al final, antes de cualquier `# EOF`)
- Test: `apps/core/tests_facturas/test_models.py`

**Interfaces:**
- Produces: `core.DocumentoFactura`, `core.TarifaCliente`, `core.PagoFactura`.
- Produces: `DocumentoFactura.monto_pagado` (property → Decimal), `.saldo_pendiente` (property → Decimal), `.es_pago_parcial` (property → bool), `.vence_hoy` (property → bool), `.vence_en_7_dias` (property → bool).
- Produces: `TarifaCliente.activa_para(cliente, producto)` (classmethod → `TarifaCliente | None`).
- Produces: permisos `ver_facturas`, `gestionar_facturas`, `registrar_pago_factura`, `anular_factura`, `gestionar_tarifas` en `DocumentoFactura.Meta.permissions`.

- [ ] **Step 1: Escribir los tests de modelo (fallan)**

Crear `apps/core/tests_facturas/test_models.py`:

```python
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.core.models import (
    Cliente, DocumentoFactura, TarifaCliente, PagoFactura,
)


class DocumentoFacturaPropsTests(TestCase):
    def setUp(self):
        self.cliente = Cliente.objects.create(nombre='Renato Díaz')
        self.doc = DocumentoFactura.objects.create(
            cliente=self.cliente,
            tipo_documento='factura',
            numero_documento='F-001',
            fecha_documento=date(2026, 6, 1),
            fecha_vencimiento=date(2026, 6, 30),
            producto='otro',
            subtotal=Decimal('100.00'),
            isv=Decimal('15.00'),
            monto_total=Decimal('115.00'),
        )

    def test_sin_pagos_saldo_igual_total(self):
        self.assertEqual(self.doc.monto_pagado, Decimal('0.00'))
        self.assertEqual(self.doc.saldo_pendiente, Decimal('115.00'))
        self.assertFalse(self.doc.es_pago_parcial)

    def test_pagos_suman_y_saldo_baja(self):
        PagoFactura.objects.create(
            documento=self.doc, fecha_pago=date(2026, 6, 5),
            metodo_pago='efectivo', monto=Decimal('40.00'),
        )
        PagoFactura.objects.create(
            documento=self.doc, fecha_pago=date(2026, 6, 6),
            metodo_pago='transferencia', monto=Decimal('25.00'),
        )
        self.assertEqual(self.doc.monto_pagado, Decimal('65.00'))
        self.assertEqual(self.doc.saldo_pendiente, Decimal('50.00'))
        self.assertTrue(self.doc.es_pago_parcial)

    def test_vence_hoy_y_en_7_dias(self):
        hoy = timezone.localdate()
        self.doc.fecha_vencimiento = hoy
        self.assertTrue(self.doc.vence_hoy)
        self.doc.fecha_vencimiento = hoy + timedelta(days=5)
        self.assertTrue(self.doc.vence_en_7_dias)
        self.assertFalse(self.doc.vence_hoy)


class TarifaClienteTests(TestCase):
    def setUp(self):
        self.cliente = Cliente.objects.create(nombre='Renato Díaz')

    def test_activa_para_devuelve_la_vigente(self):
        TarifaCliente.objects.create(
            cliente=self.cliente, producto='camiseta',
            precio_por_libra=Decimal('32.00'), activa=True,
            fecha_inicio=date(2026, 1, 1),
        )
        TarifaCliente.objects.create(
            cliente=self.cliente, producto='lisa',
            precio_por_libra=Decimal('29.50'), activa=True,
            fecha_inicio=date(2026, 1, 1),
        )
        t = TarifaCliente.activa_para(self.cliente, 'camiseta')
        self.assertIsNotNone(t)
        self.assertEqual(t.precio_por_libra, Decimal('32.00'))

    def test_activa_para_sin_tarifa_devuelve_none(self):
        self.assertIsNone(TarifaCliente.activa_para(self.cliente, 'otro'))

    def test_inactiva_no_se_devuelve(self):
        TarifaCliente.objects.create(
            cliente=self.cliente, producto='camiseta',
            precio_por_libra=Decimal('10.00'), activa=False,
            fecha_inicio=date(2026, 1, 1),
        )
        self.assertIsNone(TarifaCliente.activa_para(self.cliente, 'camiseta'))
```

- [ ] **Step 2: Ejecutar para ver el fallo**

Run: `python manage.py test apps.core.tests_facturas.test_models -v 2`
Expected: FAIL con `ImportError` / `cannot import name 'DocumentoFactura'`.

- [ ] **Step 3: Añadir los modelos**

En `apps/core/models.py`, al final del archivo, añadir:

```python
# ─── MÓDULO FACTURAS ──────────────────────────────────────────────────────────

PRODUCTO_CHOICES = [
    ('camiseta', 'Camiseta'),
    ('lisa', 'Lisa'),
    ('otro', 'Otro'),
]


class TarifaCliente(models.Model):
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name='tarifas')
    producto = models.CharField(max_length=20, choices=PRODUCTO_CHOICES)
    precio_por_libra = models.DecimalField(max_digits=12, decimal_places=2)
    activa = models.BooleanField(default=True)
    fecha_inicio = models.DateField(default=timezone.now)
    fecha_fin = models.DateField(null=True, blank=True)
    notas = models.TextField(blank=True)

    class Meta:
        verbose_name = 'Tarifa de cliente'
        verbose_name_plural = 'Tarifas de cliente'
        ordering = ['cliente', 'producto', '-fecha_inicio']
        constraints = [
            models.UniqueConstraint(
                fields=['cliente', 'producto'],
                condition=models.Q(activa=True),
                name='tarifa_unica_activa_por_cliente_producto',
            ),
        ]

    def __str__(self):
        return f'{self.cliente.nombre} · {self.get_producto_display()} · L {self.precio_por_libra}/lb'

    @classmethod
    def activa_para(cls, cliente, producto):
        """Tarifa activa vigente del cliente para el producto, o None."""
        return cls.objects.filter(
            cliente=cliente, producto=producto, activa=True,
        ).order_by('-fecha_inicio').first()


class DocumentoFactura(models.Model):
    TIPO_CHOICES = [
        ('factura', 'Factura'),
        ('envio', 'Envío'),
    ]
    ESTADO_REVISION_CHOICES = [
        ('pendiente', 'Pendiente'),
        ('revisada', 'Revisada'),
        ('error', 'Error'),
    ]
    ESTADO_PAGO_CHOICES = [
        ('pendiente', 'Pendiente'),
        ('pagada', 'Pagada'),
        ('vencida', 'Vencida'),
        ('anulada', 'Anulada'),
    ]

    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name='documentos')
    archivo_pdf = models.FileField(upload_to='facturas/%Y/%m/', null=True, blank=True)
    tipo_documento = models.CharField(max_length=10, choices=TIPO_CHOICES)
    numero_documento = models.CharField(max_length=60, blank=True)
    fecha_documento = models.DateField(null=True, blank=True)
    fecha_vencimiento = models.DateField(null=True, blank=True)
    producto = models.CharField(max_length=20, choices=PRODUCTO_CHOICES, blank=True)

    total_libras = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    precio_por_libra = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    isv = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='ISV')
    monto_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    texto_extraido = models.TextField(blank=True)
    estado_revision = models.CharField(max_length=12, choices=ESTADO_REVISION_CHOICES, default='pendiente')
    estado_pago = models.CharField(max_length=12, choices=ESTADO_PAGO_CHOICES, default='pendiente')
    notas = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Documento de factura'
        verbose_name_plural = 'Documentos de factura'
        ordering = ['-fecha_documento', '-created_at']
        permissions = [
            ('ver_facturas', 'Puede ver el módulo de facturas'),
            ('gestionar_facturas', 'Puede crear y editar documentos de facturas'),
            ('registrar_pago_factura', 'Puede registrar pagos de facturas'),
            ('anular_factura', 'Puede anular documentos de facturas'),
            ('gestionar_tarifas', 'Puede gestionar tarifas de cliente'),
        ]

    def __str__(self):
        return f'{self.get_tipo_documento_display()} {self.numero_documento or self.pk} · {self.cliente.nombre}'

    @property
    def monto_pagado(self):
        from decimal import Decimal as _D
        total = self.pagos.aggregate(s=models.Sum('monto'))['s']
        return total if total is not None else _D('0.00')

    @property
    def saldo_pendiente(self):
        return (self.monto_total or 0) - self.monto_pagado

    @property
    def es_pago_parcial(self):
        return self.monto_pagado > 0 and self.saldo_pendiente > 0

    @property
    def vence_hoy(self):
        return bool(self.fecha_vencimiento) and self.fecha_vencimiento == timezone.localdate()

    @property
    def vence_en_7_dias(self):
        if not self.fecha_vencimiento:
            return False
        delta = (self.fecha_vencimiento - timezone.localdate()).days
        return 0 <= delta <= 7


class PagoFactura(models.Model):
    METODO_CHOICES = [
        ('efectivo', 'Efectivo'),
        ('transferencia', 'Transferencia'),
        ('deposito', 'Depósito'),
        ('cheque', 'Cheque'),
        ('tarjeta', 'Tarjeta'),
        ('otro', 'Otro'),
    ]
    documento = models.ForeignKey(DocumentoFactura, on_delete=models.CASCADE, related_name='pagos')
    fecha_pago = models.DateField(default=timezone.now)
    metodo_pago = models.CharField(max_length=20, choices=METODO_CHOICES)
    monto = models.DecimalField(max_digits=12, decimal_places=2)
    referencia = models.CharField(max_length=120, blank=True)
    comprobante = models.FileField(upload_to='facturas/pagos/%Y/%m/', null=True, blank=True)
    notas = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Pago de factura'
        verbose_name_plural = 'Pagos de factura'
        ordering = ['-fecha_pago', '-created_at']

    def __str__(self):
        return f'Pago L {self.monto} · {self.documento}'
```

- [ ] **Step 4: Generar la migración**

Run: `python manage.py makemigrations core`
Expected: crea `apps/core/migrations/0018_documentofactura_tarifacliente_pagofactura.py` (o nombre similar). Revisar que incluya los 3 modelos, el `UniqueConstraint` y los `permissions`.

- [ ] **Step 5: Aplicar la migración**

Run: `python manage.py migrate core`
Expected: OK, aplica la nueva migración.

- [ ] **Step 6: Ejecutar los tests de modelo**

Run: `python manage.py test apps.core.tests_facturas.test_models -v 2`
Expected: PASS (todos).

- [ ] **Step 7: Commit**

```bash
git add apps/core/models.py apps/core/migrations/ apps/core/tests_facturas/test_models.py
git commit -m "feat(facturas): modelos DocumentoFactura, TarifaCliente, PagoFactura + permisos"
```

---

## Task 3: status_service — cálculo de estado de pago

**Files:**
- Create: `apps/core/services/facturas/__init__.py`
- Create: `apps/core/services/facturas/status_service.py`
- Test: `apps/core/tests_facturas/test_status_service.py`

**Interfaces:**
- Consumes: `DocumentoFactura` (props `saldo_pendiente`, `fecha_vencimiento`, `estado_pago`).
- Produces: `calcular_estado_pago(documento) -> str` (uno de `pagada`/`vencida`/`pendiente`/`anulada`). NO guarda.
- Produces: `actualizar_estado_pago(documento, *, guardar=True) -> str` — asigna `documento.estado_pago` y, si `guardar`, hace `documento.save(update_fields=['estado_pago', 'updated_at'])`.

- [ ] **Step 1: Escribir los tests (fallan)**

Crear `apps/core/tests_facturas/test_status_service.py`:

```python
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.core.models import Cliente, DocumentoFactura, PagoFactura
from apps.core.services.facturas import status_service


class StatusServiceTests(TestCase):
    def setUp(self):
        self.cliente = Cliente.objects.create(nombre='Cli')
        self.hoy = timezone.localdate()

    def _doc(self, total, venc):
        return DocumentoFactura.objects.create(
            cliente=self.cliente, tipo_documento='factura',
            fecha_documento=self.hoy, fecha_vencimiento=venc,
            monto_total=Decimal(total),
        )

    def test_pendiente_si_no_vencida_y_con_saldo(self):
        doc = self._doc('100.00', self.hoy + timedelta(days=10))
        self.assertEqual(status_service.calcular_estado_pago(doc), 'pendiente')

    def test_vencida_si_pasada_la_fecha_y_con_saldo(self):
        doc = self._doc('100.00', self.hoy - timedelta(days=1))
        self.assertEqual(status_service.calcular_estado_pago(doc), 'vencida')

    def test_pagada_si_saldo_cero(self):
        doc = self._doc('100.00', self.hoy - timedelta(days=1))
        PagoFactura.objects.create(
            documento=doc, fecha_pago=self.hoy, metodo_pago='efectivo',
            monto=Decimal('100.00'),
        )
        self.assertEqual(status_service.calcular_estado_pago(doc), 'pagada')

    def test_anulada_no_se_sobrescribe(self):
        doc = self._doc('100.00', self.hoy - timedelta(days=1))
        doc.estado_pago = 'anulada'
        self.assertEqual(status_service.calcular_estado_pago(doc), 'anulada')

    def test_actualizar_persiste(self):
        doc = self._doc('100.00', self.hoy + timedelta(days=10))
        status_service.actualizar_estado_pago(doc)
        doc.refresh_from_db()
        self.assertEqual(doc.estado_pago, 'pendiente')
```

- [ ] **Step 2: Ejecutar para ver el fallo**

Run: `python manage.py test apps.core.tests_facturas.test_status_service -v 2`
Expected: FAIL con `ModuleNotFoundError: apps.core.services.facturas`.

- [ ] **Step 3: Crear el paquete y el servicio**

Crear `apps/core/services/facturas/__init__.py` (vacío).

Crear `apps/core/services/facturas/status_service.py`:

```python
"""status_service — cálculo del estado de pago de un documento."""
from django.utils import timezone


def calcular_estado_pago(documento):
    """Devuelve el estado de pago calculado SIN guardar.

    Reglas:
      - 'anulada' es manual y nunca se sobrescribe.
      - saldo <= 0            → 'pagada'
      - saldo > 0 y vencido   → 'vencida'
      - saldo > 0 y no vencido→ 'pendiente'
    """
    if documento.estado_pago == 'anulada':
        return 'anulada'

    if documento.saldo_pendiente <= 0:
        return 'pagada'

    venc = documento.fecha_vencimiento
    if venc and timezone.localdate() > venc:
        return 'vencida'
    return 'pendiente'


def actualizar_estado_pago(documento, *, guardar=True):
    """Calcula y asigna el estado; persiste si guardar=True."""
    nuevo = calcular_estado_pago(documento)
    if documento.estado_pago != nuevo:
        documento.estado_pago = nuevo
        if guardar and documento.pk:
            documento.save(update_fields=['estado_pago', 'updated_at'])
    return nuevo
```

- [ ] **Step 4: Ejecutar los tests**

Run: `python manage.py test apps.core.tests_facturas.test_status_service -v 2`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/core/services/facturas/__init__.py apps/core/services/facturas/status_service.py apps/core/tests_facturas/test_status_service.py
git commit -m "feat(facturas): status_service para estado de pago"
```

---

## Task 4: payment_service + signals de recálculo

**Files:**
- Create: `apps/core/services/facturas/payment_service.py`
- Modify: `apps/core/signals.py`
- Test: `apps/core/tests_facturas/test_payment_service.py`

**Interfaces:**
- Consumes: `status_service.actualizar_estado_pago`.
- Produces: `payment_service.registrar_pago(documento, *, fecha_pago, metodo_pago, monto, referencia='', comprobante=None, notas='') -> PagoFactura`. Crea el pago dentro de una transacción y recalcula el estado del documento.
- Produces: signals `post_save`/`post_delete` sobre `PagoFactura` que llaman `status_service.actualizar_estado_pago(pago.documento)`.

- [ ] **Step 1: Escribir los tests (fallan)**

Crear `apps/core/tests_facturas/test_payment_service.py`:

```python
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.core.models import Cliente, DocumentoFactura, PagoFactura
from apps.core.services.facturas import payment_service


class PaymentServiceTests(TestCase):
    def setUp(self):
        self.cliente = Cliente.objects.create(nombre='Cli')
        self.hoy = timezone.localdate()
        self.doc = DocumentoFactura.objects.create(
            cliente=self.cliente, tipo_documento='factura',
            fecha_documento=self.hoy,
            fecha_vencimiento=self.hoy + timedelta(days=10),
            monto_total=Decimal('100.00'),
        )

    def test_registrar_pago_actualiza_estado_a_pendiente_si_parcial(self):
        payment_service.registrar_pago(
            self.doc, fecha_pago=self.hoy, metodo_pago='efectivo',
            monto=Decimal('40.00'),
        )
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.monto_pagado, Decimal('40.00'))
        self.assertEqual(self.doc.estado_pago, 'pendiente')

    def test_pago_total_marca_pagada(self):
        payment_service.registrar_pago(
            self.doc, fecha_pago=self.hoy, metodo_pago='efectivo',
            monto=Decimal('100.00'),
        )
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.estado_pago, 'pagada')

    def test_multiples_pagos_suman_hasta_pagar(self):
        payment_service.registrar_pago(
            self.doc, fecha_pago=self.hoy, metodo_pago='efectivo',
            monto=Decimal('60.00'),
        )
        payment_service.registrar_pago(
            self.doc, fecha_pago=self.hoy, metodo_pago='transferencia',
            monto=Decimal('40.00'),
        )
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.monto_pagado, Decimal('100.00'))
        self.assertEqual(self.doc.estado_pago, 'pagada')

    def test_borrar_pago_recalcula_estado(self):
        p = payment_service.registrar_pago(
            self.doc, fecha_pago=self.hoy, metodo_pago='efectivo',
            monto=Decimal('100.00'),
        )
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.estado_pago, 'pagada')
        p.delete()
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.estado_pago, 'pendiente')
```

- [ ] **Step 2: Ejecutar para ver el fallo**

Run: `python manage.py test apps.core.tests_facturas.test_payment_service -v 2`
Expected: FAIL (`cannot import name 'payment_service'`).

- [ ] **Step 3: Crear payment_service**

Crear `apps/core/services/facturas/payment_service.py`:

```python
"""payment_service — registro de pagos y recálculo del estado del documento."""
from django.db import transaction

from apps.core.models import PagoFactura
from . import status_service


@transaction.atomic
def registrar_pago(documento, *, fecha_pago, metodo_pago, monto,
                   referencia='', comprobante=None, notas=''):
    """Crea un PagoFactura y recalcula el estado del documento."""
    pago = PagoFactura.objects.create(
        documento=documento,
        fecha_pago=fecha_pago,
        metodo_pago=metodo_pago,
        monto=monto,
        referencia=referencia,
        comprobante=comprobante,
        notas=notas,
    )
    # El signal post_save ya recalcula; recargamos para reflejarlo en la instancia.
    documento.refresh_from_db()
    return pago
```

- [ ] **Step 4: Añadir las signals**

En `apps/core/signals.py`, añadir (mirar imports existentes; añadir lo que falte):

```python
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from .models import PagoFactura
from .services.facturas import status_service


@receiver(post_save, sender=PagoFactura)
def _pago_guardado(sender, instance, **kwargs):
    status_service.actualizar_estado_pago(instance.documento)


@receiver(post_delete, sender=PagoFactura)
def _pago_borrado(sender, instance, **kwargs):
    # El documento puede haberse borrado en cascada; protegerse.
    from .models import DocumentoFactura
    if DocumentoFactura.objects.filter(pk=instance.documento_id).exists():
        status_service.actualizar_estado_pago(instance.documento)
```

Verificar que `apps/core/apps.py` importe signals en `ready()` (buscar `import apps.core.signals` o `from . import signals`). Si no existe, añadir en la clase `AppConfig`:

```python
    def ready(self):
        from . import signals  # noqa: F401
```

- [ ] **Step 5: Ejecutar los tests**

Run: `python manage.py test apps.core.tests_facturas.test_payment_service -v 2`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add apps/core/services/facturas/payment_service.py apps/core/signals.py apps/core/apps.py apps/core/tests_facturas/test_payment_service.py
git commit -m "feat(facturas): payment_service + signals de recálculo de estado"
```

---

## Task 5: pdf_service + extractores (base, factura, envío)

**Files:**
- Create: `apps/core/services/facturas/pdf_service.py`
- Create: `apps/core/services/facturas/pdf_extractors/__init__.py`
- Create: `apps/core/services/facturas/pdf_extractors/base_extractor.py`
- Create: `apps/core/services/facturas/pdf_extractors/factura_extractor.py`
- Create: `apps/core/services/facturas/pdf_extractors/envio_extractor.py`
- Test: `apps/core/tests_facturas/test_extractors.py`

**Interfaces:**
- Produces: `pdf_service.extraer_texto(fileobj_o_path) -> str` (usa PyMuPDF).
- Produces: `pdf_service.get_extractor(tipo_documento) -> BaseExtractor` (devuelve `FacturaExtractor` o `EnvioExtractor`).
- Produces: `BaseExtractor.extraer(texto) -> dict`. Las claves posibles: factura → `{'numero_documento','fecha_documento','subtotal','isv','monto_total','cliente'}`; envío → `{'numero_documento','fecha_documento','cliente','total_libras'}`. Solo incluye claves con valor encontrado.
- Produces: helpers `base_extractor.parse_decimal(s) -> Decimal|None`, `base_extractor.parse_fecha(s) -> date|None`.

> Nota: los regex son una primera aproximación. Se afinan en la Task 14 con los PDFs reales de `docs/facturas/samples/`. Los tests usan texto sintético representativo.

- [ ] **Step 1: Escribir los tests (fallan)**

Crear `apps/core/tests_facturas/test_extractors.py`:

```python
from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.core.services.facturas.pdf_extractors.factura_extractor import FacturaExtractor
from apps.core.services.facturas.pdf_extractors.envio_extractor import EnvioExtractor
from apps.core.services.facturas.pdf_extractors import base_extractor


TEXTO_FACTURA = """
EMPRESA TEXTIL S. DE R.L.
Factura No. F-2026-0042
Fecha: 03/06/2026
Cliente: Renato Díaz
Subtotal: L 1,000.00
ISV (15%): L 150.00
Total: L 1,150.00
"""

TEXTO_ENVIO = """
COMPROBANTE DE ENVÍO
Envío No. E-2026-0117
Fecha: 04/06/2026
Cliente: Renato Díaz
Producto: Camiseta
Total Libras: 85.50
"""


class HelpersTests(TestCase):
    def test_parse_decimal_con_separador_miles(self):
        self.assertEqual(base_extractor.parse_decimal('L 1,150.00'), Decimal('1150.00'))

    def test_parse_decimal_invalido(self):
        self.assertIsNone(base_extractor.parse_decimal('—'))

    def test_parse_fecha_dmy(self):
        self.assertEqual(base_extractor.parse_fecha('03/06/2026'), date(2026, 6, 3))


class FacturaExtractorTests(TestCase):
    def test_extrae_campos_clave(self):
        datos = FacturaExtractor().extraer(TEXTO_FACTURA)
        self.assertEqual(datos['numero_documento'], 'F-2026-0042')
        self.assertEqual(datos['fecha_documento'], date(2026, 6, 3))
        self.assertEqual(datos['subtotal'], Decimal('1000.00'))
        self.assertEqual(datos['isv'], Decimal('150.00'))
        self.assertEqual(datos['monto_total'], Decimal('1150.00'))


class EnvioExtractorTests(TestCase):
    def test_extrae_total_libras_y_numero(self):
        datos = EnvioExtractor().extraer(TEXTO_ENVIO)
        self.assertEqual(datos['numero_documento'], 'E-2026-0117')
        self.assertEqual(datos['fecha_documento'], date(2026, 6, 4))
        self.assertEqual(datos['total_libras'], Decimal('85.50'))
```

- [ ] **Step 2: Ejecutar para ver el fallo**

Run: `python manage.py test apps.core.tests_facturas.test_extractors -v 2`
Expected: FAIL (módulos inexistentes).

- [ ] **Step 3: Crear base_extractor**

Crear `apps/core/services/facturas/pdf_extractors/__init__.py` (vacío).

Crear `apps/core/services/facturas/pdf_extractors/base_extractor.py`:

```python
"""base_extractor — interfaz y helpers de parseo para extractores de PDF."""
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation


def parse_decimal(texto):
    """Convierte 'L 1,150.00' / '1150.00' → Decimal; None si no se puede."""
    if texto is None:
        return None
    limpio = re.sub(r'[^\d.,-]', '', str(texto))
    if not limpio:
        return None
    # Asume formato es-HN: ',' miles y '.' decimales.
    limpio = limpio.replace(',', '')
    try:
        return Decimal(limpio)
    except (InvalidOperation, ValueError):
        return None


def parse_fecha(texto):
    """Convierte una fecha en varios formatos comunes → date; None si falla."""
    if not texto:
        return None
    texto = str(texto).strip()
    formatos = ('%d/%m/%Y', '%d-%m-%Y', '%Y-%m-%d', '%d/%m/%y')
    for fmt in formatos:
        try:
            return datetime.strptime(texto, fmt).date()
        except ValueError:
            continue
    return None


class BaseExtractor:
    """Interfaz de extractor. Subclases implementan extraer(texto) -> dict."""

    def extraer(self, texto):
        raise NotImplementedError

    @staticmethod
    def _buscar(patron, texto, grupo=1, flags=re.IGNORECASE):
        m = re.search(patron, texto, flags)
        return m.group(grupo).strip() if m else None
```

- [ ] **Step 4: Crear factura_extractor**

Crear `apps/core/services/facturas/pdf_extractors/factura_extractor.py`:

```python
"""factura_extractor — extrae datos de una Factura desde texto plano."""
from .base_extractor import BaseExtractor, parse_decimal, parse_fecha


class FacturaExtractor(BaseExtractor):
    def extraer(self, texto):
        datos = {}

        numero = self._buscar(r'Factura\s*(?:No\.?|N[º°]\.?|#)?\s*[:]?\s*([A-Z0-9\-]+)', texto)
        if numero:
            datos['numero_documento'] = numero

        fecha = parse_fecha(self._buscar(r'Fecha\s*[:]?\s*([0-9]{1,2}[/\-][0-9]{1,2}[/\-][0-9]{2,4})', texto))
        if fecha:
            datos['fecha_documento'] = fecha

        cliente = self._buscar(r'Cliente\s*[:]?\s*(.+)', texto)
        if cliente:
            datos['cliente'] = cliente

        subtotal = parse_decimal(self._buscar(r'Subtotal\s*[:]?\s*([L$\s\d.,]+)', texto))
        if subtotal is not None:
            datos['subtotal'] = subtotal

        isv = parse_decimal(self._buscar(r'ISV[^:\n]*[:]?\s*([L$\s\d.,]+)', texto))
        if isv is not None:
            datos['isv'] = isv

        total = parse_decimal(self._buscar(r'(?<!Sub)Total\s*[:]?\s*([L$\s\d.,]+)', texto))
        if total is not None:
            datos['monto_total'] = total

        return datos
```

- [ ] **Step 5: Crear envio_extractor**

Crear `apps/core/services/facturas/pdf_extractors/envio_extractor.py`:

```python
"""envio_extractor — extrae datos de un Envío desde texto plano."""
from .base_extractor import BaseExtractor, parse_decimal, parse_fecha


class EnvioExtractor(BaseExtractor):
    def extraer(self, texto):
        datos = {}

        numero = self._buscar(r'Env[íi]o\s*(?:No\.?|N[º°]\.?|#)?\s*[:]?\s*([A-Z0-9\-]+)', texto)
        if numero:
            datos['numero_documento'] = numero

        fecha = parse_fecha(self._buscar(r'Fecha\s*[:]?\s*([0-9]{1,2}[/\-][0-9]{1,2}[/\-][0-9]{2,4})', texto))
        if fecha:
            datos['fecha_documento'] = fecha

        cliente = self._buscar(r'Cliente\s*[:]?\s*(.+)', texto)
        if cliente:
            datos['cliente'] = cliente

        producto = self._buscar(r'Producto\s*[:]?\s*(Camiseta|Lisa|Otro)', texto)
        if producto:
            datos['producto'] = producto.lower()

        libras = parse_decimal(self._buscar(r'(?:Total\s*)?Libras\s*[:]?\s*([\d.,]+)', texto))
        if libras is not None:
            datos['total_libras'] = libras

        return datos
```

- [ ] **Step 6: Crear pdf_service**

Crear `apps/core/services/facturas/pdf_service.py`:

```python
"""pdf_service — extracción de texto de PDFs con PyMuPDF (fitz)."""
import fitz  # PyMuPDF

from .pdf_extractors.factura_extractor import FacturaExtractor
from .pdf_extractors.envio_extractor import EnvioExtractor


def extraer_texto(archivo):
    """Devuelve el texto plano de un PDF.

    `archivo` puede ser una ruta (str/Path) o un objeto file-like con .read().
    """
    data = None
    if hasattr(archivo, 'read'):
        pos = archivo.tell() if hasattr(archivo, 'tell') else None
        data = archivo.read()
        if pos is not None and hasattr(archivo, 'seek'):
            archivo.seek(pos)
        doc = fitz.open(stream=data, filetype='pdf')
    else:
        doc = fitz.open(archivo)

    partes = []
    try:
        for pagina in doc:
            partes.append(pagina.get_text())
    finally:
        doc.close()
    return '\n'.join(partes)


def get_extractor(tipo_documento):
    """Devuelve la instancia de extractor según el tipo de documento."""
    if tipo_documento == 'envio':
        return EnvioExtractor()
    return FacturaExtractor()
```

- [ ] **Step 7: Ejecutar los tests**

Run: `python manage.py test apps.core.tests_facturas.test_extractors -v 2`
Expected: PASS (todos). Si algún regex falla con el texto sintético, ajustar el patrón hasta que pase.

- [ ] **Step 8: Commit**

```bash
git add apps/core/services/facturas/pdf_service.py apps/core/services/facturas/pdf_extractors/ apps/core/tests_facturas/test_extractors.py
git commit -m "feat(facturas): pdf_service + extractores de factura y envío"
```

---

## Task 6: invoice_service — alta de documento desde PDF

**Files:**
- Create: `apps/core/services/facturas/invoice_service.py`
- Test: `apps/core/tests_facturas/test_invoice_service.py`

**Interfaces:**
- Consumes: `pdf_service.extraer_texto`, `pdf_service.get_extractor`, `TarifaCliente.activa_para`, `status_service.actualizar_estado_pago`.
- Produces: `invoice_service.previsualizar(tipo_documento, archivo) -> dict` — extrae texto + datos sin guardar; devuelve `{'texto_extraido': str, 'datos': dict}`.
- Produces: `invoice_service.crear_documento(*, cliente, tipo_documento, archivo=None, producto=None, datos=None, texto_extraido='') -> DocumentoFactura`. Para envío: si `datos['total_libras']` y hay tarifa activa, fija `precio_por_libra` (snapshot) y `monto_total = total_libras * precio_por_libra`. Guarda con `estado_revision='pendiente'` y recalcula `estado_pago`.

- [ ] **Step 1: Escribir los tests (fallan)**

Crear `apps/core/tests_facturas/test_invoice_service.py`:

```python
from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.core.models import Cliente, DocumentoFactura, TarifaCliente
from apps.core.services.facturas import invoice_service


class InvoiceServiceTests(TestCase):
    def setUp(self):
        self.cliente = Cliente.objects.create(nombre='Renato Díaz')

    def test_crear_factura_desde_datos(self):
        doc = invoice_service.crear_documento(
            cliente=self.cliente, tipo_documento='factura',
            datos={
                'numero_documento': 'F-1', 'fecha_documento': date(2026, 6, 1),
                'subtotal': Decimal('100.00'), 'isv': Decimal('15.00'),
                'monto_total': Decimal('115.00'),
            },
            texto_extraido='...',
        )
        self.assertEqual(doc.tipo_documento, 'factura')
        self.assertEqual(doc.monto_total, Decimal('115.00'))
        self.assertEqual(doc.estado_revision, 'pendiente')
        self.assertEqual(doc.estado_pago, 'pendiente')

    def test_crear_envio_aplica_tarifa_y_calcula_monto(self):
        TarifaCliente.objects.create(
            cliente=self.cliente, producto='camiseta',
            precio_por_libra=Decimal('32.00'), activa=True,
            fecha_inicio=date(2026, 1, 1),
        )
        doc = invoice_service.crear_documento(
            cliente=self.cliente, tipo_documento='envio', producto='camiseta',
            datos={'numero_documento': 'E-1', 'total_libras': Decimal('10.00')},
        )
        self.assertEqual(doc.precio_por_libra, Decimal('32.00'))
        self.assertEqual(doc.monto_total, Decimal('320.00'))

    def test_envio_sin_tarifa_deja_monto_cero(self):
        doc = invoice_service.crear_documento(
            cliente=self.cliente, tipo_documento='envio', producto='otro',
            datos={'total_libras': Decimal('10.00')},
        )
        self.assertIsNone(doc.precio_por_libra)
        self.assertEqual(doc.monto_total, Decimal('0.00') if doc.monto_total == 0 else doc.monto_total)
        self.assertEqual(doc.monto_total, Decimal('0'))
```

- [ ] **Step 2: Ejecutar para ver el fallo**

Run: `python manage.py test apps.core.tests_facturas.test_invoice_service -v 2`
Expected: FAIL (`cannot import name 'invoice_service'`).

- [ ] **Step 3: Crear invoice_service**

Crear `apps/core/services/facturas/invoice_service.py`:

```python
"""invoice_service — alta de documentos (Factura/Envío) desde PDF o datos."""
from decimal import Decimal

from django.db import transaction

from apps.core.models import DocumentoFactura, TarifaCliente
from . import pdf_service, status_service


# Campos que un extractor puede aportar y que se copian directo al documento.
_CAMPOS_DIRECTOS = (
    'numero_documento', 'fecha_documento', 'subtotal', 'isv',
    'monto_total', 'total_libras', 'producto',
)


def previsualizar(tipo_documento, archivo):
    """Extrae texto y datos del PDF sin guardar nada."""
    texto = pdf_service.extraer_texto(archivo)
    datos = pdf_service.get_extractor(tipo_documento).extraer(texto)
    return {'texto_extraido': texto, 'datos': datos}


@transaction.atomic
def crear_documento(*, cliente, tipo_documento, archivo=None, producto=None,
                    datos=None, texto_extraido=''):
    """Crea un DocumentoFactura. Para envío aplica tarifa activa (snapshot)."""
    datos = dict(datos or {})

    doc = DocumentoFactura(
        cliente=cliente,
        tipo_documento=tipo_documento,
        texto_extraido=texto_extraido,
        estado_revision='pendiente',
    )
    if archivo is not None:
        doc.archivo_pdf = archivo
    if producto:
        doc.producto = producto

    for campo in _CAMPOS_DIRECTOS:
        if campo in datos and datos[campo] is not None:
            setattr(doc, campo, datos[campo])

    if tipo_documento == 'envio':
        prod = producto or doc.producto
        tarifa = TarifaCliente.activa_para(cliente, prod) if prod else None
        if tarifa and doc.total_libras is not None:
            doc.precio_por_libra = tarifa.precio_por_libra
            doc.monto_total = (doc.total_libras * tarifa.precio_por_libra).quantize(Decimal('0.01'))

    doc.save()
    status_service.actualizar_estado_pago(doc)
    return doc
```

- [ ] **Step 4: Ejecutar los tests**

Run: `python manage.py test apps.core.tests_facturas.test_invoice_service -v 2`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/core/services/facturas/invoice_service.py apps/core/tests_facturas/test_invoice_service.py
git commit -m "feat(facturas): invoice_service para alta desde PDF/datos con tarifa"
```

---

## Task 7: Formularios

**Files:**
- Modify: `apps/core/forms.py`
- Test: (cubierto por test_views en Task 9; sin test propio)

**Interfaces:**
- Produces: `DocumentoUploadForm` — `cliente`, `tipo_documento`, `producto`, `archivo_pdf`.
- Produces: `DocumentoEditarForm` — ModelForm de `DocumentoFactura` con campos editables.
- Produces: `PagoFacturaForm` — ModelForm de `PagoFactura` (sin `documento`).
- Produces: `TarifaClienteForm` — ModelForm de `TarifaCliente` (sin `cliente`).

- [ ] **Step 1: Añadir los formularios**

En `apps/core/forms.py`, añadir al final (mirar el patrón `widgets`/`Meta` de los forms existentes y mantener estilo Bootstrap con `class='form-control'`/`'form-select'`):

```python
from .models import DocumentoFactura, TarifaCliente, PagoFactura


class DocumentoUploadForm(forms.Form):
    cliente = forms.ModelChoiceField(
        queryset=Cliente.objects.filter(activo=True).order_by('nombre'),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    tipo_documento = forms.ChoiceField(
        choices=DocumentoFactura.TIPO_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    producto = forms.ChoiceField(
        choices=[('', '—')] + list(DocumentoFactura._meta.get_field('producto').choices),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    archivo_pdf = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': 'application/pdf'}),
    )


class DocumentoEditarForm(forms.ModelForm):
    class Meta:
        model = DocumentoFactura
        fields = [
            'cliente', 'tipo_documento', 'numero_documento', 'fecha_documento',
            'fecha_vencimiento', 'producto', 'total_libras', 'precio_por_libra',
            'subtotal', 'isv', 'monto_total', 'estado_revision', 'notas',
        ]
        widgets = {
            'cliente': forms.Select(attrs={'class': 'form-select'}),
            'tipo_documento': forms.Select(attrs={'class': 'form-select'}),
            'numero_documento': forms.TextInput(attrs={'class': 'form-control'}),
            'fecha_documento': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'fecha_vencimiento': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'producto': forms.Select(attrs={'class': 'form-select'}),
            'total_libras': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'precio_por_libra': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'subtotal': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'isv': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'monto_total': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'estado_revision': forms.Select(attrs={'class': 'form-select'}),
            'notas': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }


class PagoFacturaForm(forms.ModelForm):
    class Meta:
        model = PagoFactura
        fields = ['fecha_pago', 'metodo_pago', 'monto', 'referencia', 'comprobante', 'notas']
        widgets = {
            'fecha_pago': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'metodo_pago': forms.Select(attrs={'class': 'form-select'}),
            'monto': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'referencia': forms.TextInput(attrs={'class': 'form-control'}),
            'comprobante': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'notas': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }


class TarifaClienteForm(forms.ModelForm):
    class Meta:
        model = TarifaCliente
        fields = ['producto', 'precio_por_libra', 'activa', 'fecha_inicio', 'fecha_fin', 'notas']
        widgets = {
            'producto': forms.Select(attrs={'class': 'form-select'}),
            'precio_por_libra': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'activa': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'fecha_inicio': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'fecha_fin': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'notas': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }
```

Verificar al inicio de `forms.py` que `import` de `forms` y `Cliente` ya existan (lo usan los forms actuales). Si `Cliente` no está importado, añadirlo al import de modelos existente.

- [ ] **Step 2: Verificar que importa sin error**

Run: `python manage.py shell -c "from apps.core.forms import DocumentoUploadForm, DocumentoEditarForm, PagoFacturaForm, TarifaClienteForm; print('ok')"`
Expected: imprime `ok`.

- [ ] **Step 3: Commit**

```bash
git add apps/core/forms.py
git commit -m "feat(facturas): formularios de upload, edición, pago y tarifa"
```

---

## Task 8: Vistas principales (dashboard, lista, detalle, upload, editar, anular, revisar) + URLs + admin

**Files:**
- Create: `apps/core/views/facturas.py`
- Modify: `apps/core/views/__init__.py`
- Modify: `apps/core/urls.py`
- Modify: `apps/core/admin.py`
- Test: `apps/core/tests_facturas/test_views.py` (ampliar)

**Interfaces:**
- Consumes: `facturas_enabled`, `_perm`, `invoice_service`, `status_service`, forms de Task 7.
- Produces (nombres de URL): `facturas_dashboard`, `facturas_lista`, `factura_detalle`, `factura_upload`, `factura_editar`, `factura_anular`, `factura_revisar`.

- [ ] **Step 1: Escribir tests de acceso y flujo (fallan)**

Ampliar `apps/core/tests_facturas/test_views.py` añadiendo:

```python
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, Permission, User
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Cliente, DocumentoFactura


@override_settings(FACTURAS_MODULE_ENABLED=True, ALLOWED_HOSTS=['testserver', 'localhost'])
class FacturasVistasTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='admin', password='pass12345')
        perms = Permission.objects.filter(codename__in=[
            'ver_facturas', 'gestionar_facturas', 'registrar_pago_factura',
            'anular_factura', 'gestionar_tarifas',
        ])
        for p in perms:
            self.admin.user_permissions.add(p)
        self.operador = User.objects.create_user(username='oper', password='pass12345')
        self.cliente = Cliente.objects.create(nombre='Renato Díaz')

    def test_dashboard_requiere_permiso(self):
        self.client.login(username='oper', password='pass12345')
        resp = self.client.get(reverse('facturas_dashboard'))
        self.assertEqual(resp.status_code, 403)

    def test_dashboard_admin_ok(self):
        self.client.login(username='admin', password='pass12345')
        resp = self.client.get(reverse('facturas_dashboard'))
        self.assertEqual(resp.status_code, 200)

    @override_settings(FACTURAS_MODULE_ENABLED=False)
    def test_apagado_devuelve_404(self):
        self.client.login(username='admin', password='pass12345')
        resp = self.client.get(reverse('facturas_dashboard'))
        self.assertEqual(resp.status_code, 404)

    def test_anular_marca_estado(self):
        self.client.login(username='admin', password='pass12345')
        doc = DocumentoFactura.objects.create(
            cliente=self.cliente, tipo_documento='factura',
            fecha_documento=timezone.localdate(), monto_total=Decimal('50.00'),
        )
        resp = self.client.post(reverse('factura_anular', args=[doc.pk]))
        self.assertEqual(resp.status_code, 302)
        doc.refresh_from_db()
        self.assertEqual(doc.estado_pago, 'anulada')
```

- [ ] **Step 2: Ejecutar para ver el fallo**

Run: `python manage.py test apps.core.tests_facturas.test_views -v 2`
Expected: FAIL (`Reverse for 'facturas_dashboard' not found`).

- [ ] **Step 3: Crear views/facturas.py**

Crear `apps/core/views/facturas.py`:

```python
"""facturas.py — Vistas del módulo Facturas (dashboard, listado, detalle, alta)."""
from .common import *  # noqa: F401,F403

from ..models import DocumentoFactura, TarifaCliente, PagoFactura
from ..forms import DocumentoUploadForm, DocumentoEditarForm
from ..services.facturas import invoice_service, status_service


@login_required
@permission_required(_perm('ver_facturas'), raise_exception=True)
@facturas_enabled
def facturas_dashboard(request):
    hoy = timezone.localdate()
    inicio_mes = hoy.replace(day=1)
    docs_mes = DocumentoFactura.objects.filter(fecha_documento__gte=inicio_mes)
    activos = DocumentoFactura.objects.exclude(estado_pago='anulada')

    total_facturado = sum((d.monto_total for d in activos), Decimal('0'))
    total_cobrado = sum((d.monto_pagado for d in activos), Decimal('0'))
    ctx = {
        'total_docs_mes': docs_mes.count(),
        'total_facturado': total_facturado,
        'total_cobrado': total_cobrado,
        'total_pendiente': total_facturado - total_cobrado,
        'total_vencido': sum((d.saldo_pendiente for d in activos.filter(estado_pago='vencida')), Decimal('0')),
        'facturas_pendientes': activos.filter(tipo_documento='factura', estado_pago__in=['pendiente', 'vencida']).count(),
        'envios_pendientes': activos.filter(tipo_documento='envio', estado_pago__in=['pendiente', 'vencida']).count(),
    }
    return render(request, 'facturas/dashboard.html', ctx)


@login_required
@permission_required(_perm('ver_facturas'), raise_exception=True)
@facturas_enabled
def facturas_lista(request):
    qs = DocumentoFactura.objects.select_related('cliente').all()
    tipo = request.GET.get('tipo', '')
    cliente_id = request.GET.get('cliente', '')
    producto = request.GET.get('producto', '')
    estado = request.GET.get('estado', '')
    desde = request.GET.get('desde', '')
    hasta = request.GET.get('hasta', '')

    if tipo:
        qs = qs.filter(tipo_documento=tipo)
    if cliente_id:
        qs = qs.filter(cliente_id=cliente_id)
    if producto:
        qs = qs.filter(producto=producto)
    if estado:
        qs = qs.filter(estado_pago=estado)
    if desde:
        qs = qs.filter(fecha_documento__gte=desde)
    if hasta:
        qs = qs.filter(fecha_documento__lte=hasta)

    ctx = {
        'documentos': qs,
        'clientes': Cliente.objects.order_by('nombre'),
        'filtros': {
            'tipo': tipo, 'cliente': cliente_id, 'producto': producto,
            'estado': estado, 'desde': desde, 'hasta': hasta,
        },
        'tipo_choices': DocumentoFactura.TIPO_CHOICES,
        'estado_choices': DocumentoFactura.ESTADO_PAGO_CHOICES,
        'producto_choices': DocumentoFactura._meta.get_field('producto').choices,
    }
    return render(request, 'facturas/lista.html', ctx)


@login_required
@permission_required(_perm('ver_facturas'), raise_exception=True)
@facturas_enabled
def factura_detalle(request, pk):
    doc = get_object_or_404(DocumentoFactura.objects.select_related('cliente'), pk=pk)
    return render(request, 'facturas/detalle.html', {
        'doc': doc,
        'pagos': doc.pagos.all(),
    })


@login_required
@permission_required(_perm('gestionar_facturas'), raise_exception=True)
@facturas_enabled
def factura_upload(request):
    datos_previos = None
    texto_extraido = ''
    if request.method == 'POST':
        form = DocumentoUploadForm(request.POST, request.FILES)
        if form.is_valid():
            cliente = form.cleaned_data['cliente']
            tipo = form.cleaned_data['tipo_documento']
            producto = form.cleaned_data['producto']
            archivo = form.cleaned_data['archivo_pdf']

            datos = {}
            if archivo:
                prev = invoice_service.previsualizar(tipo, archivo)
                datos = prev['datos']
                texto_extraido = prev['texto_extraido']

            doc = invoice_service.crear_documento(
                cliente=cliente, tipo_documento=tipo, archivo=archivo,
                producto=producto or datos.get('producto'),
                datos=datos, texto_extraido=texto_extraido,
            )
            messages.success(request, 'Documento creado. Revisá y editá los campos.')
            return redirect('factura_editar', pk=doc.pk)
    else:
        form = DocumentoUploadForm()
    return render(request, 'facturas/form_upload.html', {'form': form})


@login_required
@permission_required(_perm('gestionar_facturas'), raise_exception=True)
@facturas_enabled
def factura_editar(request, pk):
    doc = get_object_or_404(DocumentoFactura, pk=pk)
    if request.method == 'POST':
        form = DocumentoEditarForm(request.POST, instance=doc)
        if form.is_valid():
            doc = form.save()
            status_service.actualizar_estado_pago(doc)
            messages.success(request, 'Documento actualizado.')
            return redirect('factura_detalle', pk=doc.pk)
    else:
        form = DocumentoEditarForm(instance=doc)
    return render(request, 'facturas/form_editar.html', {'form': form, 'doc': doc})


@login_required
@permission_required(_perm('gestionar_facturas'), raise_exception=True)
@facturas_enabled
@require_POST
def factura_revisar(request, pk):
    doc = get_object_or_404(DocumentoFactura, pk=pk)
    doc.estado_revision = 'revisada'
    doc.save(update_fields=['estado_revision', 'updated_at'])
    messages.success(request, 'Documento marcado como revisado.')
    return redirect('factura_detalle', pk=doc.pk)


@login_required
@permission_required(_perm('anular_factura'), raise_exception=True)
@facturas_enabled
@require_POST
def factura_anular(request, pk):
    doc = get_object_or_404(DocumentoFactura, pk=pk)
    doc.estado_pago = 'anulada'
    doc.save(update_fields=['estado_pago', 'updated_at'])
    messages.success(request, 'Documento anulado.')
    return redirect('factura_detalle', pk=doc.pk)
```

- [ ] **Step 4: Registrar el módulo en el barrel de vistas**

En `apps/core/views/__init__.py`, tras `from .admin_ops import *`, añadir:

```python
from .facturas import *           # noqa: F401,F403
```

- [ ] **Step 5: Añadir las rutas**

En `apps/core/urls.py`, dentro de `urlpatterns`, añadir un bloque (respetar la convención: segmentos fijos antes de `<int:pk>`):

```python
    # ── Facturas ──────────────────────────────────────────────────────────────
    path('facturas/', views.facturas_dashboard, name='facturas_dashboard'),
    path('facturas/documentos/', views.facturas_lista, name='facturas_lista'),
    path('facturas/documentos/nuevo/', views.factura_upload, name='factura_upload'),
    path('facturas/documentos/<int:pk>/', views.factura_detalle, name='factura_detalle'),
    path('facturas/documentos/<int:pk>/editar/', views.factura_editar, name='factura_editar'),
    path('facturas/documentos/<int:pk>/revisar/', views.factura_revisar, name='factura_revisar'),
    path('facturas/documentos/<int:pk>/anular/', views.factura_anular, name='factura_anular'),
```

- [ ] **Step 6: Registrar en admin**

En `apps/core/admin.py`, añadir:

```python
from .models import DocumentoFactura, TarifaCliente, PagoFactura


@admin.register(DocumentoFactura)
class DocumentoFacturaAdmin(admin.ModelAdmin):
    list_display = ('id', 'tipo_documento', 'cliente', 'numero_documento',
                    'fecha_documento', 'monto_total', 'estado_pago', 'estado_revision')
    list_filter = ('tipo_documento', 'estado_pago', 'estado_revision', 'producto')
    search_fields = ('numero_documento', 'cliente__nombre')


@admin.register(TarifaCliente)
class TarifaClienteAdmin(admin.ModelAdmin):
    list_display = ('cliente', 'producto', 'precio_por_libra', 'activa', 'fecha_inicio')
    list_filter = ('producto', 'activa')
    search_fields = ('cliente__nombre',)


@admin.register(PagoFactura)
class PagoFacturaAdmin(admin.ModelAdmin):
    list_display = ('documento', 'fecha_pago', 'metodo_pago', 'monto')
    list_filter = ('metodo_pago',)
```

- [ ] **Step 7: Crear plantillas mínimas para que las vistas rendericen**

Para que los tests de vista pasen, crear plantillas con contenido real (se enriquecen en Task 12). Crear ahora versiones funcionales mínimas:

`templates/facturas/dashboard.html`:

```django
{% extends "base.html" %}
{% block title %}Facturas{% endblock %}
{% block content %}
<div class="page-header"><h1><i class="bi bi-receipt me-2"></i>Facturas</h1></div>
<div class="row g-3">
  <div class="col-6 col-md-3"><div class="card"><div class="card-body"><small>Documentos del mes</small><div class="fs-2">{{ total_docs_mes }}</div></div></div></div>
  <div class="col-6 col-md-3"><div class="card"><div class="card-body"><small>Facturado</small><div class="fs-2">L {{ total_facturado }}</div></div></div></div>
  <div class="col-6 col-md-3"><div class="card"><div class="card-body"><small>Cobrado</small><div class="fs-2">L {{ total_cobrado }}</div></div></div></div>
  <div class="col-6 col-md-3"><div class="card"><div class="card-body"><small>Pendiente</small><div class="fs-2">L {{ total_pendiente }}</div></div></div></div>
  <div class="col-6 col-md-3"><div class="card"><div class="card-body"><small>Vencido</small><div class="fs-2">L {{ total_vencido }}</div></div></div></div>
  <div class="col-6 col-md-3"><div class="card"><div class="card-body"><small>Facturas pendientes</small><div class="fs-2">{{ facturas_pendientes }}</div></div></div></div>
  <div class="col-6 col-md-3"><div class="card"><div class="card-body"><small>Envíos pendientes</small><div class="fs-2">{{ envios_pendientes }}</div></div></div></div>
</div>
<a href="{% url 'facturas_lista' %}" class="btn btn-primary mt-3">Ver documentos</a>
<a href="{% url 'factura_upload' %}" class="btn btn-success mt-3">Subir PDF</a>
{% endblock %}
```

`templates/facturas/lista.html`, `templates/facturas/detalle.html`, `templates/facturas/form_upload.html`, `templates/facturas/form_editar.html`: crear versiones mínimas que extiendan `base.html` y muestren los datos clave (se completan en Task 12). Ejemplo mínimo para `form_upload.html`:

```django
{% extends "base.html" %}
{% block title %}Subir documento{% endblock %}
{% block content %}
<h1>Subir documento</h1>
<form method="post" enctype="multipart/form-data">{% csrf_token %}
  {{ form.as_p }}
  <button class="btn btn-primary" type="submit">Continuar</button>
</form>
{% endblock %}
```

(Repetir el patrón mínimo para `lista.html`, `detalle.html`, `form_editar.html` mostrando `{{ documentos }}`, `{{ doc }}`/`{{ form }}` respectivamente.)

- [ ] **Step 8: Ejecutar los tests de vista**

Run: `python manage.py test apps.core.tests_facturas.test_views -v 2`
Expected: PASS (incluyendo los 2 del decorador de Task 1).

- [ ] **Step 9: Commit**

```bash
git add apps/core/views/facturas.py apps/core/views/__init__.py apps/core/urls.py apps/core/admin.py templates/facturas/ apps/core/tests_facturas/test_views.py
git commit -m "feat(facturas): vistas dashboard/lista/detalle/upload/editar/anular/revisar + admin"
```

---

## Task 9: Vistas de pagos

**Files:**
- Create: `apps/core/views/facturas_pagos.py`
- Modify: `apps/core/views/__init__.py`
- Modify: `apps/core/urls.py`
- Create: `templates/facturas/form_pago.html`
- Test: `apps/core/tests_facturas/test_views.py` (ampliar)

**Interfaces:**
- Consumes: `payment_service.registrar_pago`, `PagoFacturaForm`.
- Produces (URL): `factura_pago_nuevo` (`facturas/documentos/<pk>/pago/`), `factura_pago_borrar` (`facturas/pagos/<pk>/borrar/`).

- [ ] **Step 1: Escribir test (falla)**

Ampliar `apps/core/tests_facturas/test_views.py` con:

```python
class FacturasPagoTests(TestCase):
    def setUp(self):
        from apps.core.models import DocumentoFactura
        self.admin = User.objects.create_user(username='admin2', password='pass12345')
        for p in Permission.objects.filter(codename__in=['ver_facturas', 'registrar_pago_factura']):
            self.admin.user_permissions.add(p)
        self.cliente = Cliente.objects.create(nombre='Cli')
        self.doc = DocumentoFactura.objects.create(
            cliente=self.cliente, tipo_documento='factura',
            fecha_documento=timezone.localdate(), monto_total=Decimal('100.00'),
        )

    @override_settings(FACTURAS_MODULE_ENABLED=True)
    def test_registrar_pago_via_vista(self):
        self.client.login(username='admin2', password='pass12345')
        resp = self.client.post(reverse('factura_pago_nuevo', args=[self.doc.pk]), {
            'fecha_pago': timezone.localdate().isoformat(),
            'metodo_pago': 'efectivo', 'monto': '100.00', 'referencia': '', 'notas': '',
        })
        self.assertEqual(resp.status_code, 302)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.estado_pago, 'pagada')
```

(Asegurar que `FacturasPagoTests` herede de `TestCase` con `override_settings` a nivel clase o método y los imports `Decimal`, `timezone`, `Permission`, `User`, `Cliente`, `reverse` ya presentes en el archivo.)

- [ ] **Step 2: Ejecutar para ver el fallo**

Run: `python manage.py test apps.core.tests_facturas.test_views.FacturasPagoTests -v 2`
Expected: FAIL (`Reverse for 'factura_pago_nuevo' not found`).

- [ ] **Step 3: Crear la vista de pagos**

Crear `apps/core/views/facturas_pagos.py`:

```python
"""facturas_pagos.py — Registro y borrado de pagos."""
from .common import *  # noqa: F401,F403

from ..models import DocumentoFactura, PagoFactura
from ..forms import PagoFacturaForm
from ..services.facturas import payment_service


@login_required
@permission_required(_perm('registrar_pago_factura'), raise_exception=True)
@facturas_enabled
def factura_pago_nuevo(request, pk):
    doc = get_object_or_404(DocumentoFactura, pk=pk)
    if request.method == 'POST':
        form = PagoFacturaForm(request.POST, request.FILES)
        if form.is_valid():
            cd = form.cleaned_data
            payment_service.registrar_pago(
                doc,
                fecha_pago=cd['fecha_pago'],
                metodo_pago=cd['metodo_pago'],
                monto=cd['monto'],
                referencia=cd.get('referencia', ''),
                comprobante=cd.get('comprobante'),
                notas=cd.get('notas', ''),
            )
            messages.success(request, 'Pago registrado.')
            return redirect('factura_detalle', pk=doc.pk)
    else:
        form = PagoFacturaForm(initial={'fecha_pago': timezone.localdate()})
    return render(request, 'facturas/form_pago.html', {'form': form, 'doc': doc})


@login_required
@permission_required(_perm('registrar_pago_factura'), raise_exception=True)
@facturas_enabled
@require_POST
def factura_pago_borrar(request, pk):
    pago = get_object_or_404(PagoFactura, pk=pk)
    doc_pk = pago.documento_id
    pago.delete()  # el signal post_delete recalcula el estado
    messages.success(request, 'Pago eliminado.')
    return redirect('factura_detalle', pk=doc_pk)
```

- [ ] **Step 4: Registrar barrel + URLs + plantilla**

En `apps/core/views/__init__.py` añadir tras `from .facturas import *`:

```python
from .facturas_pagos import *     # noqa: F401,F403
```

En `apps/core/urls.py`, en el bloque Facturas:

```python
    path('facturas/documentos/<int:pk>/pago/', views.factura_pago_nuevo, name='factura_pago_nuevo'),
    path('facturas/pagos/<int:pk>/borrar/', views.factura_pago_borrar, name='factura_pago_borrar'),
```

Crear `templates/facturas/form_pago.html`:

```django
{% extends "base.html" %}
{% block title %}Registrar pago{% endblock %}
{% block content %}
<h1>Registrar pago — {{ doc }}</h1>
<p>Saldo pendiente: <strong>L {{ doc.saldo_pendiente }}</strong></p>
<form method="post" enctype="multipart/form-data">{% csrf_token %}
  {{ form.as_p }}
  <button class="btn btn-primary" type="submit">Guardar pago</button>
  <a href="{% url 'factura_detalle' doc.pk %}" class="btn btn-outline-secondary">Cancelar</a>
</form>
{% endblock %}
```

- [ ] **Step 5: Ejecutar el test**

Run: `python manage.py test apps.core.tests_facturas.test_views.FacturasPagoTests -v 2`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/core/views/facturas_pagos.py apps/core/views/__init__.py apps/core/urls.py templates/facturas/form_pago.html apps/core/tests_facturas/test_views.py
git commit -m "feat(facturas): vistas de registro y borrado de pagos"
```

---

## Task 10: Vistas de tarifas por cliente

**Files:**
- Create: `apps/core/views/facturas_tarifas.py`
- Modify: `apps/core/views/__init__.py`
- Modify: `apps/core/urls.py`
- Create: `templates/facturas/tarifas.html`
- Test: `apps/core/tests_facturas/test_views.py` (ampliar)

**Interfaces:**
- Consumes: `TarifaClienteForm`, `Cliente`, `TarifaCliente`.
- Produces (URL): `cliente_tarifas` (`facturas/clientes/<pk>/tarifas/`), `cliente_tarifa_toggle` (`facturas/tarifas/<pk>/toggle/`).

- [ ] **Step 1: Escribir test (falla)**

Ampliar `test_views.py`:

```python
class FacturasTarifasTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='admin3', password='pass12345')
        for p in Permission.objects.filter(codename__in=['ver_facturas', 'gestionar_tarifas']):
            self.admin.user_permissions.add(p)
        self.cliente = Cliente.objects.create(nombre='Cli')

    @override_settings(FACTURAS_MODULE_ENABLED=True)
    def test_crear_tarifa(self):
        from apps.core.models import TarifaCliente
        self.client.login(username='admin3', password='pass12345')
        resp = self.client.post(reverse('cliente_tarifas', args=[self.cliente.pk]), {
            'producto': 'camiseta', 'precio_por_libra': '32.00', 'activa': 'on',
            'fecha_inicio': timezone.localdate().isoformat(),
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(TarifaCliente.objects.filter(cliente=self.cliente, producto='camiseta').exists())
```

- [ ] **Step 2: Ejecutar para ver el fallo**

Run: `python manage.py test apps.core.tests_facturas.test_views.FacturasTarifasTests -v 2`
Expected: FAIL (`Reverse for 'cliente_tarifas' not found`).

- [ ] **Step 3: Crear la vista de tarifas**

Crear `apps/core/views/facturas_tarifas.py`:

```python
"""facturas_tarifas.py — CRUD de tarifas por cliente."""
from .common import *  # noqa: F401,F403

from ..models import Cliente, TarifaCliente
from ..forms import TarifaClienteForm


@login_required
@permission_required(_perm('gestionar_tarifas'), raise_exception=True)
@facturas_enabled
def cliente_tarifas(request, pk):
    cliente = get_object_or_404(Cliente, pk=pk)
    if request.method == 'POST':
        form = TarifaClienteForm(request.POST)
        if form.is_valid():
            tarifa = form.save(commit=False)
            tarifa.cliente = cliente
            # Si se marca activa, desactivar otras activas del mismo producto.
            if tarifa.activa:
                TarifaCliente.objects.filter(
                    cliente=cliente, producto=tarifa.producto, activa=True,
                ).update(activa=False)
            tarifa.save()
            messages.success(request, 'Tarifa guardada.')
            return redirect('cliente_tarifas', pk=cliente.pk)
    else:
        form = TarifaClienteForm(initial={'fecha_inicio': timezone.localdate()})
    return render(request, 'facturas/tarifas.html', {
        'cliente': cliente,
        'form': form,
        'tarifas': cliente.tarifas.all(),
    })


@login_required
@permission_required(_perm('gestionar_tarifas'), raise_exception=True)
@facturas_enabled
@require_POST
def cliente_tarifa_toggle(request, pk):
    tarifa = get_object_or_404(TarifaCliente, pk=pk)
    if not tarifa.activa:
        TarifaCliente.objects.filter(
            cliente=tarifa.cliente, producto=tarifa.producto, activa=True,
        ).update(activa=False)
    tarifa.activa = not tarifa.activa
    tarifa.save(update_fields=['activa'])
    messages.success(request, 'Tarifa actualizada.')
    return redirect('cliente_tarifas', pk=tarifa.cliente_id)
```

- [ ] **Step 4: Barrel + URLs + plantilla**

En `apps/core/views/__init__.py` tras `from .facturas_pagos import *`:

```python
from .facturas_tarifas import *   # noqa: F401,F403
```

En `apps/core/urls.py`, bloque Facturas:

```python
    path('facturas/clientes/<int:pk>/tarifas/', views.cliente_tarifas, name='cliente_tarifas'),
    path('facturas/tarifas/<int:pk>/toggle/', views.cliente_tarifa_toggle, name='cliente_tarifa_toggle'),
```

Crear `templates/facturas/tarifas.html`:

```django
{% extends "base.html" %}
{% block title %}Tarifas — {{ cliente.nombre }}{% endblock %}
{% block content %}
<h1>Tarifas — {{ cliente.nombre }}</h1>
<form method="post" class="card card-body mb-3">{% csrf_token %}
  {{ form.as_p }}
  <button class="btn btn-primary" type="submit">Guardar tarifa</button>
</form>
<table class="table table-sm">
  <thead><tr><th>Producto</th><th>Precio/lb</th><th>Activa</th><th>Desde</th><th></th></tr></thead>
  <tbody>
  {% for t in tarifas %}
    <tr>
      <td>{{ t.get_producto_display }}</td>
      <td>L {{ t.precio_por_libra }}</td>
      <td>{% if t.activa %}<span class="badge bg-success">Activa</span>{% else %}<span class="badge bg-secondary">Inactiva</span>{% endif %}</td>
      <td>{{ t.fecha_inicio|date:"d/m/Y" }}</td>
      <td>
        <form method="post" action="{% url 'cliente_tarifa_toggle' t.pk %}">{% csrf_token %}
          <button class="btn btn-sm btn-outline-secondary" type="submit">{% if t.activa %}Desactivar{% else %}Activar{% endif %}</button>
        </form>
      </td>
    </tr>
  {% empty %}
    <tr><td colspan="5" class="text-muted">Sin tarifas.</td></tr>
  {% endfor %}
  </tbody>
</table>
{% endblock %}
```

- [ ] **Step 5: Ejecutar el test**

Run: `python manage.py test apps.core.tests_facturas.test_views.FacturasTarifasTests -v 2`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/core/views/facturas_tarifas.py apps/core/views/__init__.py apps/core/urls.py templates/facturas/tarifas.html apps/core/tests_facturas/test_views.py
git commit -m "feat(facturas): CRUD de tarifas por cliente"
```

---

## Task 11: Vista del fragmento AJAX para la tab del cliente

**Files:**
- Create: `apps/core/views/facturas_cliente.py`
- Modify: `apps/core/views/__init__.py`
- Modify: `apps/core/urls.py`
- Create: `templates/facturas/_tab_cliente.html`
- Create: `templates/facturas/_badges.html`
- Test: `apps/core/tests_facturas/test_cliente_tab.py`

**Interfaces:**
- Consumes: `DocumentoFactura`, `Cliente`.
- Produces (URL): `cliente_facturas_fragment` (`facturas/clientes/<pk>/fragmento/`). Devuelve el HTML del fragmento (resumen + tabla filtrable por `?tipo=factura|envio|`).

- [ ] **Step 1: Escribir test (falla)**

Crear `apps/core/tests_facturas/test_cliente_tab.py`:

```python
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import Permission, User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Cliente, DocumentoFactura


@override_settings(FACTURAS_MODULE_ENABLED=True, ALLOWED_HOSTS=['testserver', 'localhost'])
class ClienteTabTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='admin', password='pass12345')
        self.admin.user_permissions.add(Permission.objects.get(codename='ver_facturas'))
        self.cliente = Cliente.objects.create(nombre='Renato Díaz')
        DocumentoFactura.objects.create(
            cliente=self.cliente, tipo_documento='factura',
            numero_documento='F-1', fecha_documento=timezone.localdate(),
            monto_total=Decimal('100.00'),
        )
        DocumentoFactura.objects.create(
            cliente=self.cliente, tipo_documento='envio',
            numero_documento='E-1', fecha_documento=timezone.localdate(),
            monto_total=Decimal('50.00'),
        )

    def test_fragmento_muestra_documentos(self):
        self.client.login(username='admin', password='pass12345')
        resp = self.client.get(reverse('cliente_facturas_fragment', args=[self.cliente.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'F-1')
        self.assertContains(resp, 'E-1')

    def test_filtra_solo_envios(self):
        self.client.login(username='admin', password='pass12345')
        resp = self.client.get(reverse('cliente_facturas_fragment', args=[self.cliente.pk]), {'tipo': 'envio'})
        self.assertContains(resp, 'E-1')
        self.assertNotContains(resp, 'F-1')
```

- [ ] **Step 2: Ejecutar para ver el fallo**

Run: `python manage.py test apps.core.tests_facturas.test_cliente_tab -v 2`
Expected: FAIL (`Reverse for 'cliente_facturas_fragment' not found`).

- [ ] **Step 3: Crear la vista del fragmento**

Crear `apps/core/views/facturas_cliente.py`:

```python
"""facturas_cliente.py — Fragmento AJAX de la tab Facturas en la vista de cliente."""
from .common import *  # noqa: F401,F403

from ..models import Cliente, DocumentoFactura


@login_required
@permission_required(_perm('ver_facturas'), raise_exception=True)
@facturas_enabled
def cliente_facturas_fragment(request, pk):
    cliente = get_object_or_404(Cliente, pk=pk)
    qs = DocumentoFactura.objects.filter(cliente=cliente)

    tipo = request.GET.get('tipo', '')
    if tipo in ('factura', 'envio'):
        qs = qs.filter(tipo_documento=tipo)

    activos = DocumentoFactura.objects.filter(cliente=cliente).exclude(estado_pago='anulada')
    total_facturado = sum((d.monto_total for d in activos), Decimal('0'))
    total_pagado = sum((d.monto_pagado for d in activos), Decimal('0'))
    resumen = {
        'total_facturado': total_facturado,
        'total_pagado': total_pagado,
        'total_pendiente': total_facturado - total_pagado,
        'total_vencido': sum((d.saldo_pendiente for d in activos.filter(estado_pago='vencida')), Decimal('0')),
        'num_facturas': activos.filter(tipo_documento='factura').count(),
        'num_envios': activos.filter(tipo_documento='envio').count(),
    }
    return render(request, 'facturas/_tab_cliente.html', {
        'cliente': cliente,
        'documentos': qs.order_by('-fecha_documento'),
        'resumen': resumen,
        'tipo_filtro': tipo,
    })
```

- [ ] **Step 4: Barrel + URL**

En `apps/core/views/__init__.py` tras `from .facturas_tarifas import *`:

```python
from .facturas_cliente import *   # noqa: F401,F403
```

En `apps/core/urls.py`, bloque Facturas:

```python
    path('facturas/clientes/<int:pk>/fragmento/', views.cliente_facturas_fragment, name='cliente_facturas_fragment'),
```

- [ ] **Step 5: Crear los includes de presentación**

Crear `templates/facturas/_badges.html` (badge de estado reutilizable; espera `doc` en contexto):

```django
{% if doc.estado_pago == 'pagada' %}<span class="badge bg-success">Pagada</span>
{% elif doc.estado_pago == 'anulada' %}<span class="badge bg-dark">Anulada</span>
{% elif doc.estado_pago == 'vencida' %}<span class="badge bg-danger">Vencida</span>
{% elif doc.es_pago_parcial %}<span class="badge bg-warning text-dark">Pago parcial</span>
{% else %}<span class="badge bg-secondary">Pendiente</span>{% endif %}
{% if doc.vence_hoy %}<span class="badge bg-danger">Vence hoy</span>
{% elif doc.vence_en_7_dias %}<span class="badge bg-warning text-dark">Vence pronto</span>{% endif %}
```

Crear `templates/facturas/_tab_cliente.html`:

```django
<div class="d-flex flex-wrap gap-3 mb-3">
  <div class="card flex-fill"><div class="card-body py-2"><small>Facturado</small><div class="fs-5">L {{ resumen.total_facturado }}</div></div></div>
  <div class="card flex-fill"><div class="card-body py-2"><small>Pagado</small><div class="fs-5">L {{ resumen.total_pagado }}</div></div></div>
  <div class="card flex-fill"><div class="card-body py-2"><small>Pendiente</small><div class="fs-5">L {{ resumen.total_pendiente }}</div></div></div>
  <div class="card flex-fill"><div class="card-body py-2"><small>Vencido</small><div class="fs-5">L {{ resumen.total_vencido }}</div></div></div>
  <div class="card flex-fill"><div class="card-body py-2"><small>Facturas</small><div class="fs-5">{{ resumen.num_facturas }}</div></div></div>
  <div class="card flex-fill"><div class="card-body py-2"><small>Envíos</small><div class="fs-5">{{ resumen.num_envios }}</div></div></div>
</div>

<div class="btn-group btn-group-sm mb-2" role="group">
  <button class="btn btn-outline-primary filtro-fac {% if not tipo_filtro %}active{% endif %}" data-tipo="">Todos</button>
  <button class="btn btn-outline-primary filtro-fac {% if tipo_filtro == 'factura' %}active{% endif %}" data-tipo="factura">Facturas</button>
  <button class="btn btn-outline-primary filtro-fac {% if tipo_filtro == 'envio' %}active{% endif %}" data-tipo="envio">Envíos</button>
</div>

<div class="table-responsive">
  <table class="table table-sm table-hover align-middle">
    <thead class="table-light"><tr>
      <th>Tipo</th><th>Número</th><th>Producto</th><th>Fecha</th><th>Vencimiento</th>
      <th class="text-end">Libras</th><th class="text-end">Precio</th><th class="text-end">Total</th>
      <th class="text-end">Pagado</th><th class="text-end">Saldo</th><th>Estado</th><th>PDF</th>
    </tr></thead>
    <tbody>
    {% for doc in documentos %}
      <tr>
        <td>{{ doc.get_tipo_documento_display }}</td>
        <td><a href="{% url 'factura_detalle' doc.pk %}">{{ doc.numero_documento|default:doc.pk }}</a></td>
        <td>{{ doc.get_producto_display|default:"—" }}</td>
        <td>{{ doc.fecha_documento|date:"d/m/Y"|default:"—" }}</td>
        <td>{{ doc.fecha_vencimiento|date:"d/m/Y"|default:"—" }}</td>
        <td class="text-end">{{ doc.total_libras|default:"—" }}</td>
        <td class="text-end">{{ doc.precio_por_libra|default:"—" }}</td>
        <td class="text-end">L {{ doc.monto_total }}</td>
        <td class="text-end">L {{ doc.monto_pagado }}</td>
        <td class="text-end">L {{ doc.saldo_pendiente }}</td>
        <td>{% include "facturas/_badges.html" with doc=doc %}</td>
        <td>{% if doc.archivo_pdf %}<a href="{{ doc.archivo_pdf.url }}" target="_blank"><i class="bi bi-file-earmark-pdf"></i></a>{% endif %}</td>
      </tr>
    {% empty %}
      <tr><td colspan="12" class="text-muted">Sin documentos.</td></tr>
    {% endfor %}
    </tbody>
  </table>
</div>
```

- [ ] **Step 6: Ejecutar el test**

Run: `python manage.py test apps.core.tests_facturas.test_cliente_tab -v 2`
Expected: PASS (2 tests).

- [ ] **Step 7: Commit**

```bash
git add apps/core/views/facturas_cliente.py apps/core/views/__init__.py apps/core/urls.py templates/facturas/_tab_cliente.html templates/facturas/_badges.html apps/core/tests_facturas/test_cliente_tab.py
git commit -m "feat(facturas): fragmento AJAX de la tab Facturas del cliente"
```

---

## Task 12: Tab Bootstrap en la vista del cliente + enlace de menú + plantillas completas

**Files:**
- Modify: `templates/clientes/salidas.html`
- Modify: `templates/includes/nav_menu.html`
- Modify: `templates/facturas/lista.html` (completar), `detalle.html` (completar)
- Test: manual + suite completa.

**Interfaces:**
- Consumes: `cliente_facturas_fragment` (URL), `facturas_enabled` (context var), `perms.core.ver_facturas`.

- [ ] **Step 1: Envolver el contenido actual de salidas.html en tabs**

En `templates/clientes/salidas.html`, justo después del `<div class="page-header ...>...</div>` (cierre del header, ~línea 28) y ANTES del `<div class="card mb-4 filters-card">`, insertar la barra de tabs. Luego envolver TODO el contenido existente desde el `filters-card` hasta el final del bloque content dentro de un panel de tab. El contenido de "Productos llevados" NO se modifica, solo se mueve dentro del `tab-pane`.

Insertar tras el header:

```django
{% if facturas_enabled and perms.core.ver_facturas %}
<ul class="nav nav-tabs mb-3" id="clienteTabs" role="tablist">
  <li class="nav-item" role="presentation">
    <button class="nav-link active" id="tab-productos-btn" data-bs-toggle="tab"
            data-bs-target="#tab-productos" type="button" role="tab">
      <i class="bi bi-box-seam me-1"></i>Productos llevados
    </button>
  </li>
  <li class="nav-item" role="presentation">
    <button class="nav-link" id="tab-facturas-btn" data-bs-toggle="tab"
            data-bs-target="#tab-facturas" type="button" role="tab"
            data-url="{% url 'cliente_facturas_fragment' cliente.pk %}">
      <i class="bi bi-receipt me-1"></i>Facturas
    </button>
  </li>
  <li class="nav-item ms-auto" role="presentation">
    {% if perms.core.gestionar_tarifas %}
    <a class="nav-link" href="{% url 'cliente_tarifas' cliente.pk %}">
      <i class="bi bi-tags me-1"></i>Tarifas
    </a>
    {% endif %}
  </li>
</ul>
<div class="tab-content">
  <div class="tab-pane fade show active" id="tab-productos" role="tabpanel">
{% endif %}
```

Y AL FINAL del `{% block content %}` (antes de `{% endblock %}`), cerrar los contenedores:

```django
{% if facturas_enabled and perms.core.ver_facturas %}
  </div>{# /tab-productos #}
  <div class="tab-pane fade" id="tab-facturas" role="tabpanel">
    <div id="facturas-cont" class="text-center text-muted py-4">
      <span class="spinner-border spinner-border-sm"></span> Cargando facturas…
    </div>
  </div>
</div>{# /tab-content #}
{% endif %}
```

> Nota: el contenido entre la apertura `<div class="tab-pane ... id="tab-productos">` y su cierre es EXACTAMENTE el contenido actual de la página (filtros + tablas), sin cambios.

- [ ] **Step 2: Añadir el JS de carga AJAX de la tab**

En `templates/clientes/salidas.html`, dentro de un bloque `{% block extra_js %}` (o al final del content si no existe ese bloque — revisar `base.html` para el nombre del bloque de scripts), añadir:

```django
{% if facturas_enabled and perms.core.ver_facturas %}
<script>
(function () {
  var btn = document.getElementById('tab-facturas-btn');
  var cont = document.getElementById('facturas-cont');
  var cargado = false;
  function cargar(url) {
    fetch(url, {headers: {'X-Requested-With': 'XMLHttpRequest'}})
      .then(function (r) { return r.text(); })
      .then(function (html) { cont.innerHTML = html; bindFiltros(); })
      .catch(function () { cont.innerHTML = '<div class="alert alert-danger">Error al cargar.</div>'; });
  }
  function bindFiltros() {
    cont.querySelectorAll('.filtro-fac').forEach(function (b) {
      b.addEventListener('click', function () {
        var base = btn.getAttribute('data-url');
        var tipo = b.getAttribute('data-tipo');
        cargar(base + (tipo ? ('?tipo=' + tipo) : ''));
      });
    });
  }
  if (btn) {
    btn.addEventListener('shown.bs.tab', function () {
      if (!cargado) { cargado = true; cargar(btn.getAttribute('data-url')); }
    });
  }
})();
</script>
{% endif %}
```

Verificar el nombre real del bloque de scripts en `base.html` (puede ser `extra_js`, `scripts` o similar) y usar ese.

- [ ] **Step 3: Añadir el enlace del módulo en el menú**

En `templates/includes/nav_menu.html`, tras el bloque de "Catálogos" (o donde corresponda), añadir:

```django
{% if facturas_enabled and perms.core.ver_facturas %}
<span class="sidebar-section">Facturas</span>
<a href="{% url 'facturas_dashboard' %}" class="nav-link {% if 'factura' in request.resolver_match.url_name %}active{% endif %}">
  <i class="bi bi-receipt"></i> Facturas
</a>
{% endif %}
```

- [ ] **Step 4: Completar lista.html y detalle.html**

Reemplazar el contenido mínimo de `templates/facturas/lista.html` por una versión con la barra de filtros (tipo, cliente, producto, estado, rango de fechas) y la tabla con todas las columnas del spec (Tipo, Cliente, Número, Producto, Fecha, Vencimiento, Libras, Precio, Subtotal, ISV, Total, Pagado, Saldo, Estado, PDF), usando `{% include "facturas/_badges.html" with doc=doc %}` para el estado y enlaces a `factura_detalle`, `factura_pago_nuevo`, `factura_editar`, `factura_anular`.

Reemplazar `templates/facturas/detalle.html` por una versión que muestre todos los campos del documento, el texto extraído (en `<pre>`), el historial de pagos (tabla con borrar pago), y botones de acción: registrar pago, editar, marcar revisado, anular, descargar PDF — cada uno condicionado al permiso correspondiente (`perms.core.registrar_pago_factura`, `perms.core.gestionar_facturas`, `perms.core.anular_factura`).

(El contenido HTML sigue el mismo patrón Bootstrap de las plantillas existentes como `clientes/salidas.html`; usar `table table-sm`, `card`, `page-header`.)

- [ ] **Step 5: Verificación manual con el servidor de preview**

Levantar el servidor y verificar: dashboard de facturas, subir un PDF de muestra, ver detalle, registrar un pago, y abrir la tab "Facturas" en la vista de un cliente (que carga por AJAX). Comprobar que con el módulo apagado (`FACTURAS_MODULE_ENABLED=False`) el menú y la tab desaparecen y `/facturas/` da 404.

- [ ] **Step 6: Commit**

```bash
git add templates/clientes/salidas.html templates/includes/nav_menu.html templates/facturas/lista.html templates/facturas/detalle.html
git commit -m "feat(facturas): tab Bootstrap en cliente, enlace de menú y plantillas completas"
```

---

## Task 13: Permisos a Administrador en setup_groups

**Files:**
- Modify: `apps/core/management/commands/setup_groups.py`
- Test: `apps/core/tests_facturas/test_views.py` (test de grupo, opcional)

**Interfaces:**
- Consumes: permisos definidos en Task 2.

- [ ] **Step 1: Añadir los permisos al grupo Administrador**

En `apps/core/management/commands/setup_groups.py`, en la lista de `'Administrador'`, añadir tras `'gestionar_backups',`:

```python
        # Módulo Facturas (exclusivo de Administrador)
        'ver_facturas', 'gestionar_facturas', 'registrar_pago_factura',
        'anular_factura', 'gestionar_tarifas',
```

(NO añadir nada a Supervisor ni Operador.)

- [ ] **Step 2: Ejecutar el comando**

Run: `python manage.py setup_groups`
Expected: `Actualizado: Administrador (N permisos)` con N incrementado en 5.

- [ ] **Step 3: Verificar**

Run: `python manage.py shell -c "from django.contrib.auth.models import Group; g=Group.objects.get(name='Administrador'); print(sorted(p.codename for p in g.permissions.filter(codename__startswith='ver_factur') | g.permissions.filter(codename__endswith='_factura') | g.permissions.filter(codename='gestionar_tarifas')))"`
Expected: lista que incluye `ver_facturas`, `gestionar_facturas`, `registrar_pago_factura`, `anular_factura`, `gestionar_tarifas`.

- [ ] **Step 4: Commit**

```bash
git add apps/core/management/commands/setup_groups.py
git commit -m "feat(facturas): otorgar permisos de facturas solo a Administrador"
```

---

## Task 14: Afinar extractores con PDFs reales

**Files:**
- Modify: `apps/core/services/facturas/pdf_extractors/factura_extractor.py`
- Modify: `apps/core/services/facturas/pdf_extractors/envio_extractor.py`
- Test: `apps/core/tests_facturas/test_extractors.py` (añadir casos reales)

**Interfaces:**
- Consumes: PDFs reales en `docs/facturas/samples/`.

- [ ] **Step 1: Volcar el texto real de los PDFs de muestra**

Run (para cada PDF en `docs/facturas/samples/`):
`python manage.py shell -c "from apps.core.services.facturas import pdf_service; print(pdf_service.extraer_texto('docs/facturas/samples/factura_ejemplo.pdf'))"`
Anotar el texto real de una factura y de un envío.

- [ ] **Step 2: Añadir tests con el texto real**

En `apps/core/tests_facturas/test_extractors.py`, añadir constantes con fragmentos reales (anonimizados) y tests que verifiquen que `FacturaExtractor`/`EnvioExtractor` extraen número, fecha, total/libras correctamente del texto real.

- [ ] **Step 3: Ejecutar (probablemente fallan)**

Run: `python manage.py test apps.core.tests_facturas.test_extractors -v 2`
Expected: posibles FAIL si los regex no calzan con el formato real.

- [ ] **Step 4: Ajustar los regex de los extractores**

Modificar los patrones en `factura_extractor.py` y `envio_extractor.py` hasta que los tests con texto real pasen, sin romper los tests con texto sintético.

- [ ] **Step 5: Ejecutar todos los tests de extractores**

Run: `python manage.py test apps.core.tests_facturas.test_extractors -v 2`
Expected: PASS (sintéticos + reales).

- [ ] **Step 6: Commit**

```bash
git add apps/core/services/facturas/pdf_extractors/ apps/core/tests_facturas/test_extractors.py
git commit -m "feat(facturas): afinar extractores con PDFs reales de muestra"
```

---

## Task 15: Suite completa y verificación final

**Files:** ninguno nuevo.

- [ ] **Step 1: Ejecutar toda la suite de facturas**

Run: `python manage.py test apps.core.tests_facturas -v 2`
Expected: PASS (todos).

- [ ] **Step 2: Ejecutar TODA la suite del proyecto (no romper lo existente)**

Run: `python manage.py test apps.core -v 1`
Expected: PASS — confirmar que los tests previos (`apps/core/tests.py`) siguen verdes y que las signals/admin nuevos no rompen nada.

- [ ] **Step 3: `makemigrations --check`**

Run: `python manage.py makemigrations --check --dry-run`
Expected: "No changes detected" (no quedan migraciones sin crear).

- [ ] **Step 4: Commit final si hubo ajustes**

```bash
git add -A
git commit -m "test(facturas): verificación final de la suite completa"
```

---

## Self-Review (cobertura del spec)

| Requisito del spec | Task |
|---|---|
| App dentro de `core`, modular, activable | 1, 8–11 |
| Modelo DocumentoFactura + props + permisos | 2 |
| Modelo TarifaCliente + `activa_para` | 2 |
| Modelo PagoFactura (múltiples pagos) | 2, 4 |
| Cálculo monto envío = libras × precio (snapshot) | 6 |
| Cálculo saldo / monto pagado | 2 |
| Estado pago automático (pagada/vencida/pendiente) | 3 |
| Estado anulada manual | 3, 8 |
| Carga PDF + PyMuPDF + extractores | 5, 6 |
| Extractor factura / envío | 5, 14 |
| Dashboard | 8 |
| Listado general con filtros y acciones | 8, 12 |
| Detalle con historial de pagos | 8, 12 |
| Registro de pago (recalcula) | 4, 9 |
| Tarifas del cliente | 10 |
| Tab Facturas en cliente (sin tocar Productos llevados) | 11, 12 |
| Alertas/badges | 11 (`_badges.html`) |
| Servicios (pdf/invoice/payment/status/extractors) | 3–6 |
| PyMuPDF; pdfplumber preparado | 1 |
| Permisos solo Administrador | 2, 13 |
| Pruebas (lista completa del spec) | 2–6, 8–11, 14–15 |
| NO tocar inventario / stock / Productos llevados | (constraint global; verificado en 12, 15) |
```
