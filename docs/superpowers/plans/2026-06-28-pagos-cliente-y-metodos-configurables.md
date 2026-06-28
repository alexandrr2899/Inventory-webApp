# Pagos a nivel de cliente y métodos de pago configurables — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permitir que los pagos pertenezcan al cliente (no a una sola factura) y se repartan automática-pero-editablemente entre sus facturas, con saldo a favor, y métodos de pago configurables.

**Architecture:** Se introducen tres modelos (`MetodoPago`, `Pago`, `AplicacionPago`). Un `Pago` es del cliente; sus `AplicacionPago` reparten el monto entre facturas. `DocumentoFactura.monto_pagado` pasa a sumar aplicaciones y el estado se recalcula vía signals sobre `AplicacionPago`. Los datos viejos (`PagoFactura`) se migran a la nueva estructura y luego se retira ese modelo.

**Tech Stack:** Django (app `apps.core`), SQLite/Postgres, plantillas Django + Bootstrap, tests con `django.test.TestCase`. **El proyecto corre solo en Docker.**

## Global Constraints

- **Tests / manage.py SIEMPRE vía Docker** (no hay python local). Comando base:
  `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py <cmd>`
- En tests de vistas usar `self.client.force_login(user)` (django-axes rompe `client.login`).
- Las vistas viven en `apps/core/views/<modulo>.py` e importan con `from .common import *`. Usar el helper `_perm('<codename>')` y los decoradores `@login_required`, `@permission_required(..., raise_exception=True)`, `@facturas_enabled`.
- Montos: `DecimalField(max_digits=12, decimal_places=2)`. Comparaciones de dinero con `Decimal`.
- Migraciones de `core`: la última es `0019_cliente_dias_credito`; las nuevas siguen numerando `0020+`. Verificar con `makemigrations --check --dry-run`.
- No romper la suite: cada Task deja `manage.py test apps.core` en verde.

---

### Task 1: Modelo `MetodoPago`

**Files:**
- Modify: `apps/core/models.py` (agregar clase tras `class TarifaCliente`, antes de `DocumentoFactura`)
- Modify: `apps/core/admin.py` (registro)
- Create migration: `apps/core/migrations/0020_metodopago.py` (autogenerada)
- Test: `apps/core/tests_facturas/test_metodo_pago.py`

**Interfaces:**
- Produces: `MetodoPago(nombre, tipo, activo, orden)` con `TIPO_CHOICES`; `MetodoPago.objects` ordenado por `['orden', 'nombre']`; `__str__ → nombre`.

- [ ] **Step 1: Escribir el test que falla**

Create `apps/core/tests_facturas/test_metodo_pago.py`:

```python
from django.test import TestCase

from apps.core.models import MetodoPago


class MetodoPagoTests(TestCase):
    def test_str_es_el_nombre(self):
        m = MetodoPago.objects.create(nombre='Transferencia BAC', tipo='transferencia')
        self.assertEqual(str(m), 'Transferencia BAC')

    def test_defaults(self):
        m = MetodoPago.objects.create(nombre='Efectivo', tipo='efectivo')
        self.assertTrue(m.activo)
        self.assertEqual(m.orden, 0)

    def test_orden_por_orden_luego_nombre(self):
        MetodoPago.objects.create(nombre='B', tipo='otro', orden=1)
        MetodoPago.objects.create(nombre='A', tipo='otro', orden=1)
        MetodoPago.objects.create(nombre='Z', tipo='otro', orden=0)
        nombres = list(MetodoPago.objects.values_list('nombre', flat=True))
        self.assertEqual(nombres, ['Z', 'A', 'B'])
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_facturas.test_metodo_pago -v 2`
Expected: FAIL — `ImportError: cannot import name 'MetodoPago'`.

- [ ] **Step 3: Agregar el modelo**

En `apps/core/models.py`, justo antes de `class DocumentoFactura(models.Model):`:

```python
class MetodoPago(models.Model):
    TIPO_CHOICES = [
        ('efectivo', 'Efectivo'),
        ('transferencia', 'Transferencia'),
        ('deposito', 'Depósito'),
        ('cheque', 'Cheque'),
        ('tarjeta', 'Tarjeta'),
        ('otro', 'Otro'),
    ]
    nombre = models.CharField(max_length=80)
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default='otro')
    activo = models.BooleanField(default=True)
    orden = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'Método de pago'
        verbose_name_plural = 'Métodos de pago'
        ordering = ['orden', 'nombre']
        permissions = [
            ('gestionar_metodos_pago', 'Puede gestionar métodos de pago'),
        ]

    def __str__(self):
        return self.nombre
```

- [ ] **Step 4: Registrar en admin**

En `apps/core/admin.py`, agregar `MetodoPago` al import desde `..models` (línea ~5) y al final del archivo:

```python
@admin.register(MetodoPago)
class MetodoPagoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'tipo', 'activo', 'orden')
    list_filter = ('tipo', 'activo')
    search_fields = ('nombre',)
```

- [ ] **Step 5: Crear migración**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py makemigrations core`
Expected: crea `apps/core/migrations/0020_metodopago.py`.

- [ ] **Step 6: Correr el test y verificar que pasa**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_facturas.test_metodo_pago -v 2`
Expected: PASS (3 tests).

- [ ] **Step 7: Commit**

```bash
git add apps/core/models.py apps/core/admin.py apps/core/migrations/0020_metodopago.py apps/core/tests_facturas/test_metodo_pago.py
git commit -m "feat(facturas): modelo MetodoPago configurable"
```

---

### Task 2: Modelos `Pago` y `AplicacionPago` + propiedades de `Cliente`

**Files:**
- Modify: `apps/core/models.py` (agregar `Pago` y `AplicacionPago` tras `PagoFactura`; agregar 2 propiedades a `Cliente`)
- Modify: `apps/core/admin.py` (registros)
- Create migration: `apps/core/migrations/0021_pago_aplicacionpago.py`
- Test: `apps/core/tests_facturas/test_pago_modelos.py`

**Interfaces:**
- Consumes: `MetodoPago` (Task 1), `Cliente`, `DocumentoFactura`.
- Produces:
  - `Pago(cliente, fecha_pago, metodo_pago, monto, referencia, comprobante, notas, created_at)` con `related_name='pagos'` en cliente.
  - `Pago.monto_aplicado` (Decimal), `Pago.saldo_sin_aplicar` (Decimal).
  - `AplicacionPago(pago, documento, monto, created_at)` con `pago.aplicaciones` y `documento.aplicaciones`.
  - `Cliente.saldo_a_favor` (Decimal), `Cliente.total_adeudado` (Decimal).

- [ ] **Step 1: Escribir el test que falla**

Create `apps/core/tests_facturas/test_pago_modelos.py`:

```python
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.core.models import (
    Cliente, DocumentoFactura, MetodoPago, Pago, AplicacionPago,
)


class PagoModeloTests(TestCase):
    def setUp(self):
        self.cli = Cliente.objects.create(nombre='Cli')
        self.met = MetodoPago.objects.create(nombre='Efectivo', tipo='efectivo')
        self.hoy = timezone.localdate()
        self.doc = DocumentoFactura.objects.create(
            cliente=self.cli, tipo_documento='factura', fecha_documento=self.hoy,
            monto_total=Decimal('100.00'),
        )

    def _pago(self, monto):
        return Pago.objects.create(
            cliente=self.cli, fecha_pago=self.hoy, metodo_pago=self.met, monto=monto,
        )

    def test_monto_aplicado_y_saldo_sin_aplicar(self):
        pago = self._pago(Decimal('100.00'))
        AplicacionPago.objects.create(pago=pago, documento=self.doc, monto=Decimal('40.00'))
        self.assertEqual(pago.monto_aplicado, Decimal('40.00'))
        self.assertEqual(pago.saldo_sin_aplicar, Decimal('60.00'))

    def test_saldo_a_favor_del_cliente(self):
        pago = self._pago(Decimal('100.00'))
        AplicacionPago.objects.create(pago=pago, documento=self.doc, monto=Decimal('30.00'))
        self.assertEqual(self.cli.saldo_a_favor, Decimal('70.00'))

    def test_total_adeudado_del_cliente(self):
        # doc de 100 sin pagos: adeudado = 100
        self.assertEqual(self.cli.total_adeudado, Decimal('100.00'))
        pago = self._pago(Decimal('40.00'))
        AplicacionPago.objects.create(pago=pago, documento=self.doc, monto=Decimal('40.00'))
        self.assertEqual(self.cli.total_adeudado, Decimal('60.00'))
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_facturas.test_pago_modelos -v 2`
Expected: FAIL — `cannot import name 'Pago'`.

- [ ] **Step 3: Agregar los modelos**

En `apps/core/models.py`, después de `class PagoFactura(...)` (al final de la sección facturas):

```python
class Pago(models.Model):
    """Abono de un cliente; se reparte entre facturas vía AplicacionPago."""
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name='pagos')
    fecha_pago = models.DateField(default=timezone.now)
    metodo_pago = models.ForeignKey('MetodoPago', on_delete=models.PROTECT, related_name='pagos')
    monto = models.DecimalField(max_digits=12, decimal_places=2)
    referencia = models.CharField(max_length=120, blank=True)
    comprobante = models.FileField(upload_to='facturas/pagos/%Y/%m/', null=True, blank=True)
    notas = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Pago'
        verbose_name_plural = 'Pagos'
        ordering = ['-fecha_pago', '-created_at']

    def __str__(self):
        return f'Abono L {self.monto} · {self.cliente.nombre}'

    @property
    def monto_aplicado(self):
        total = self.aplicaciones.aggregate(s=models.Sum('monto'))['s']
        return total if total is not None else Decimal('0.00')

    @property
    def saldo_sin_aplicar(self):
        return self.monto - self.monto_aplicado


class AplicacionPago(models.Model):
    """Porción de un Pago aplicada a una factura concreta."""
    pago = models.ForeignKey(Pago, on_delete=models.CASCADE, related_name='aplicaciones')
    documento = models.ForeignKey(DocumentoFactura, on_delete=models.PROTECT, related_name='aplicaciones')
    monto = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Aplicación de pago'
        verbose_name_plural = 'Aplicaciones de pago'
        ordering = ['-created_at']
        constraints = [
            models.CheckConstraint(check=models.Q(monto__gt=0), name='aplicacion_monto_positivo'),
        ]

    def __str__(self):
        return f'L {self.monto} → {self.documento}'
```

- [ ] **Step 4: Agregar propiedades a `Cliente`**

En `class Cliente(models.Model)` (línea ~129), agregar dentro de la clase (después de los campos, antes/después de cualquier `__str__`):

```python
    @property
    def saldo_a_favor(self):
        from decimal import Decimal as _D
        return sum((p.saldo_sin_aplicar for p in self.pagos.all()), _D('0.00'))

    @property
    def total_adeudado(self):
        from decimal import Decimal as _D
        docs = self.documentos.exclude(estado_pago='anulada')
        return sum((d.saldo_pendiente for d in docs), _D('0.00'))
```

(Nota: `Decimal` ya está importado al tope de `models.py`; el import local solo evita depender del orden. Si `Decimal` está disponible en el módulo, puedes usarlo directamente.)

- [ ] **Step 5: Registrar en admin**

En `apps/core/admin.py`, agregar `Pago, AplicacionPago` al import y:

```python
class AplicacionPagoInline(admin.TabularInline):
    model = AplicacionPago
    extra = 0


@admin.register(Pago)
class PagoAdmin(admin.ModelAdmin):
    list_display = ('cliente', 'fecha_pago', 'metodo_pago', 'monto')
    list_filter = ('metodo_pago', 'fecha_pago')
    inlines = [AplicacionPagoInline]
```

- [ ] **Step 6: Crear migración y correr el test**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py makemigrations core`
Then: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_facturas.test_pago_modelos -v 2`
Expected: PASS (3 tests).

- [ ] **Step 7: Commit**

```bash
git add apps/core/models.py apps/core/admin.py apps/core/migrations/0021_pago_aplicacionpago.py apps/core/tests_facturas/test_pago_modelos.py
git commit -m "feat(facturas): modelos Pago y AplicacionPago + saldo del cliente"
```

---

### Task 3: Migración de datos `PagoFactura` → `Pago` + `AplicacionPago`

**Files:**
- Create migration: `apps/core/migrations/0022_migrar_pagos.py` (a mano, `RunPython`)
- Test: `apps/core/tests_facturas/test_migracion_pagos.py`

**Interfaces:**
- Consumes: `PagoFactura` (existente), modelos de Task 1 y 2.
- Produces: por cada `PagoFactura` un `Pago` + una `AplicacionPago`; un `MetodoPago` por cada `metodo_pago` string distinto. En este punto `DocumentoFactura.monto_pagado` SIGUE leyendo `self.pagos` viejos — sin doble conteo.

- [ ] **Step 1: Escribir el test que falla (verifica la lógica de conversión vía función reutilizable)**

Create `apps/core/tests_facturas/test_migracion_pagos.py`:

```python
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.core.models import (
    Cliente, DocumentoFactura, PagoFactura, Pago, AplicacionPago, MetodoPago,
)
from apps.core.services.facturas import migracion


class MigracionPagosTests(TestCase):
    def setUp(self):
        self.cli = Cliente.objects.create(nombre='Cli')
        self.hoy = timezone.localdate()
        self.doc = DocumentoFactura.objects.create(
            cliente=self.cli, tipo_documento='factura', fecha_documento=self.hoy,
            monto_total=Decimal('100.00'),
        )
        PagoFactura.objects.create(
            documento=self.doc, fecha_pago=self.hoy, metodo_pago='transferencia',
            monto=Decimal('60.00'), referencia='REF1',
        )

    def test_convierte_pagofactura_en_pago_y_aplicacion(self):
        migracion.migrar_pagos_a_abonos(
            PagoFactura, Pago, AplicacionPago, MetodoPago,
        )
        self.assertEqual(Pago.objects.count(), 1)
        self.assertEqual(AplicacionPago.objects.count(), 1)
        pago = Pago.objects.get()
        self.assertEqual(pago.cliente, self.cli)
        self.assertEqual(pago.monto, Decimal('60.00'))
        self.assertEqual(pago.referencia, 'REF1')
        self.assertEqual(pago.metodo_pago.tipo, 'transferencia')
        apl = AplicacionPago.objects.get()
        self.assertEqual(apl.documento, self.doc)
        self.assertEqual(apl.monto, Decimal('60.00'))

    def test_reusa_metodo_existente_por_tipo(self):
        PagoFactura.objects.create(
            documento=self.doc, fecha_pago=self.hoy, metodo_pago='transferencia',
            monto=Decimal('40.00'),
        )
        migracion.migrar_pagos_a_abonos(PagoFactura, Pago, AplicacionPago, MetodoPago)
        # Dos pagos 'transferencia' → un solo MetodoPago
        self.assertEqual(MetodoPago.objects.filter(tipo='transferencia').count(), 1)
        self.assertEqual(Pago.objects.count(), 2)
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_facturas.test_migracion_pagos -v 2`
Expected: FAIL — `No module named 'apps.core.services.facturas.migracion'`.

- [ ] **Step 3: Crear la función de conversión reutilizable**

Create `apps/core/services/facturas/migracion.py`:

```python
"""migracion — convierte PagoFactura viejos en Pago + AplicacionPago.

Recibe las clases como argumentos para poder usarse tanto desde una
data migration (modelos históricos) como desde los tests (modelos reales).
"""

TIPO_LABELS = {
    'efectivo': 'Efectivo',
    'transferencia': 'Transferencia',
    'deposito': 'Depósito',
    'cheque': 'Cheque',
    'tarjeta': 'Tarjeta',
    'otro': 'Otro',
}


def migrar_pagos_a_abonos(PagoFactura, Pago, AplicacionPago, MetodoPago):
    metodos = {}  # tipo string -> instancia MetodoPago

    def metodo_para(tipo):
        tipo = tipo or 'otro'
        if tipo not in metodos:
            obj, _ = MetodoPago.objects.get_or_create(
                tipo=tipo, defaults={'nombre': TIPO_LABELS.get(tipo, tipo.title())},
            )
            metodos[tipo] = obj
        return metodos[tipo]

    for pf in PagoFactura.objects.all().select_related('documento'):
        pago = Pago.objects.create(
            cliente_id=pf.documento.cliente_id,
            fecha_pago=pf.fecha_pago,
            metodo_pago=metodo_para(pf.metodo_pago),
            monto=pf.monto,
            referencia=pf.referencia,
            comprobante=pf.comprobante,
            notas=pf.notas,
        )
        AplicacionPago.objects.create(pago=pago, documento_id=pf.documento_id, monto=pf.monto)
```

- [ ] **Step 4: Correr el test y verificar que pasa**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_facturas.test_migracion_pagos -v 2`
Expected: PASS (2 tests).

- [ ] **Step 5: Crear la data migration que la invoca**

Create `apps/core/migrations/0022_migrar_pagos.py`:

```python
from django.db import migrations


def forwards(apps, schema_editor):
    from apps.core.services.facturas.migracion import migrar_pagos_a_abonos
    PagoFactura = apps.get_model('core', 'PagoFactura')
    Pago = apps.get_model('core', 'Pago')
    AplicacionPago = apps.get_model('core', 'AplicacionPago')
    MetodoPago = apps.get_model('core', 'MetodoPago')
    migrar_pagos_a_abonos(PagoFactura, Pago, AplicacionPago, MetodoPago)


def backwards(apps, schema_editor):
    Pago = apps.get_model('core', 'Pago')
    MetodoPago = apps.get_model('core', 'MetodoPago')
    Pago.objects.all().delete()
    MetodoPago.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0021_pago_aplicacionpago'),
    ]
    operations = [
        migrations.RunPython(forwards, backwards),
    ]
```

- [ ] **Step 6: Verificar migraciones consistentes**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py makemigrations --check --dry-run`
Expected: `No changes detected`.
Then run full app tests: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core -v 1`
Expected: PASS (suite completa sigue verde; `monto_pagado` aún lee `self.pagos` viejos).

- [ ] **Step 7: Commit**

```bash
git add apps/core/services/facturas/migracion.py apps/core/migrations/0022_migrar_pagos.py apps/core/tests_facturas/test_migracion_pagos.py
git commit -m "feat(facturas): migración de datos PagoFactura -> Pago+AplicacionPago"
```

---

### Task 4: Cutover — `monto_pagado`, signals y `payment_service`

**Files:**
- Modify: `apps/core/models.py` (`DocumentoFactura.monto_pagado` → suma `aplicaciones`)
- Modify: `apps/core/signals.py` (signals de `AplicacionPago` en vez de `PagoFactura`)
- Rewrite: `apps/core/services/facturas/payment_service.py`
- Modify: `apps/core/views/facturas_pagos.py` (usar nuevo service)
- Modify: `apps/core/forms.py` (`PagoFacturaForm` → nuevo `PagoFacturaForm` sobre `Pago`/aplicación única)
- Replace tests: `apps/core/tests_facturas/test_payment_service.py`, `test_status_service.py` (ajustar a nuevos modelos)
- Test (nuevo): `apps/core/tests_facturas/test_abono_service.py`

**Interfaces:**
- Consumes: `Pago`, `AplicacionPago`, `MetodoPago`, `status_service`.
- Produces:
  - `DocumentoFactura.monto_pagado` suma `self.aplicaciones`.
  - `payment_service.registrar_abono(cliente, *, fecha_pago, metodo_pago, monto, referencia='', comprobante=None, notas='', aplicaciones=None) -> Pago` donde `aplicaciones` es lista de `(documento, monto_Decimal)`; si es `None`, auto-reparte por antigüedad.
  - `payment_service.proponer_reparto(cliente, monto) -> list[(DocumentoFactura, Decimal)]` (sin persistir).
  - `payment_service.aplicar_saldo_a_favor(documento) -> Decimal` (monto aplicado desde crédito).
  - `payment_service.liberar_aplicaciones(documento) -> None`.

- [ ] **Step 1: Escribir los tests que fallan (nuevo service)**

Create `apps/core/tests_facturas/test_abono_service.py`:

```python
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.core.models import Cliente, DocumentoFactura, MetodoPago, AplicacionPago
from apps.core.services.facturas import payment_service


class AbonoServiceTests(TestCase):
    def setUp(self):
        self.cli = Cliente.objects.create(nombre='Cli')
        self.met = MetodoPago.objects.create(nombre='Efectivo', tipo='efectivo')
        self.hoy = timezone.localdate()
        # Dos facturas: la más vieja primero
        self.f1 = DocumentoFactura.objects.create(
            cliente=self.cli, tipo_documento='factura',
            fecha_documento=self.hoy - timedelta(days=10), monto_total=Decimal('100.00'),
        )
        self.f2 = DocumentoFactura.objects.create(
            cliente=self.cli, tipo_documento='factura',
            fecha_documento=self.hoy - timedelta(days=5), monto_total=Decimal('100.00'),
        )

    def _abono(self, monto, aplicaciones=None):
        return payment_service.registrar_abono(
            self.cli, fecha_pago=self.hoy, metodo_pago=self.met,
            monto=Decimal(monto), aplicaciones=aplicaciones,
        )

    def test_auto_reparto_por_antiguedad_llena_f1_y_pasa_a_f2(self):
        self._abono('150.00')
        self.f1.refresh_from_db(); self.f2.refresh_from_db()
        self.assertEqual(self.f1.monto_pagado, Decimal('100.00'))
        self.assertEqual(self.f1.estado_pago, 'pagada')
        self.assertEqual(self.f2.monto_pagado, Decimal('50.00'))
        self.assertEqual(self.f2.estado_pago, 'pendiente')

    def test_excedente_queda_como_saldo_a_favor(self):
        self._abono('250.00')
        self.assertEqual(self.cli.saldo_a_favor, Decimal('50.00'))

    def test_reparto_editado_respeta_montos_dados(self):
        self._abono('80.00', aplicaciones=[(self.f2, Decimal('80.00'))])
        self.f1.refresh_from_db(); self.f2.refresh_from_db()
        self.assertEqual(self.f1.monto_pagado, Decimal('0.00'))
        self.assertEqual(self.f2.monto_pagado, Decimal('80.00'))

    def test_proponer_reparto_no_persiste(self):
        reparto = payment_service.proponer_reparto(self.cli, Decimal('120.00'))
        self.assertEqual([(d.pk, m) for d, m in reparto],
                         [(self.f1.pk, Decimal('100.00')), (self.f2.pk, Decimal('20.00'))])
        self.assertEqual(AplicacionPago.objects.count(), 0)

    def test_aplicar_saldo_a_favor_a_factura_nueva(self):
        self._abono('250.00')  # 50 de crédito
        nueva = DocumentoFactura.objects.create(
            cliente=self.cli, tipo_documento='factura',
            fecha_documento=self.hoy, monto_total=Decimal('30.00'),
        )
        aplicado = payment_service.aplicar_saldo_a_favor(nueva)
        nueva.refresh_from_db()
        self.assertEqual(aplicado, Decimal('30.00'))
        self.assertEqual(nueva.estado_pago, 'pagada')

    def test_liberar_aplicaciones_devuelve_a_saldo_a_favor(self):
        self._abono('100.00')  # cubre f1
        self.f1.refresh_from_db()
        self.assertEqual(self.f1.estado_pago, 'pagada')
        payment_service.liberar_aplicaciones(self.f1)
        self.f1.refresh_from_db()
        self.assertEqual(self.f1.monto_pagado, Decimal('0.00'))
        self.assertEqual(self.cli.saldo_a_favor, Decimal('100.00'))
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_facturas.test_abono_service -v 2`
Expected: FAIL — `module 'payment_service' has no attribute 'registrar_abono'`.

- [ ] **Step 3: Cambiar `monto_pagado` a sumar aplicaciones**

En `apps/core/models.py`, en `DocumentoFactura.monto_pagado`:

```python
    @property
    def monto_pagado(self):
        total = self.aplicaciones.aggregate(s=models.Sum('monto'))['s']
        return total if total is not None else Decimal('0.00')
```

- [ ] **Step 4: Mover signals a `AplicacionPago`**

Reescribir `apps/core/signals.py` (la sección de pagos):

```python
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import AplicacionPago
from .services.facturas import status_service


@receiver(post_save, sender=AplicacionPago)
def _aplicacion_guardada(sender, instance, **kwargs):
    status_service.actualizar_estado_pago(instance.documento)


@receiver(post_delete, sender=AplicacionPago)
def _aplicacion_borrada(sender, instance, **kwargs):
    from .models import DocumentoFactura
    if DocumentoFactura.objects.filter(pk=instance.documento_id).exists():
        status_service.actualizar_estado_pago(instance.documento)
```

(Mantener cualquier otro receiver no relacionado a pagos que ya exista en el archivo.)

- [ ] **Step 5: Reescribir `payment_service`**

Replace `apps/core/services/facturas/payment_service.py`:

```python
"""payment_service — registro de abonos y reparto entre facturas."""
from decimal import Decimal

from django.db import transaction

from apps.core.models import Pago, AplicacionPago
from . import status_service


def _facturas_pendientes(cliente):
    """Facturas no anuladas con saldo, de la más vieja a la más nueva."""
    docs = (cliente.documentos
            .exclude(estado_pago='anulada')
            .order_by('fecha_documento', 'created_at'))
    return [d for d in docs if d.saldo_pendiente > 0]


def proponer_reparto(cliente, monto):
    """Reparto sugerido por antigüedad SIN persistir: lista de (documento, monto)."""
    restante = Decimal(monto)
    reparto = []
    for doc in _facturas_pendientes(cliente):
        if restante <= 0:
            break
        aplicar = min(doc.saldo_pendiente, restante)
        if aplicar > 0:
            reparto.append((doc, aplicar))
            restante -= aplicar
    return reparto


@transaction.atomic
def registrar_abono(cliente, *, fecha_pago, metodo_pago, monto,
                    referencia='', comprobante=None, notas='', aplicaciones=None):
    """Crea un Pago y reparte su monto entre facturas.

    `aplicaciones`: lista opcional de (documento, monto). Si es None se auto-reparte
    por antigüedad. El remanente queda como saldo a favor.
    """
    pago = Pago.objects.create(
        cliente=cliente, fecha_pago=fecha_pago, metodo_pago=metodo_pago,
        monto=Decimal(monto), referencia=referencia, comprobante=comprobante, notas=notas,
    )
    if aplicaciones is None:
        aplicaciones = proponer_reparto(cliente, monto)
    for documento, monto_aplicar in aplicaciones:
        monto_aplicar = Decimal(monto_aplicar)
        if monto_aplicar > 0:
            AplicacionPago.objects.create(pago=pago, documento=documento, monto=monto_aplicar)
    return pago


@transaction.atomic
def aplicar_saldo_a_favor(documento):
    """Aplica crédito disponible del cliente a `documento` (pagos más viejos primero).

    Devuelve el monto total aplicado.
    """
    aplicado = Decimal('0.00')
    if documento.estado_pago == 'anulada':
        return aplicado
    pagos = documento.cliente.pagos.order_by('fecha_pago', 'created_at')
    for pago in pagos:
        saldo_doc = documento.saldo_pendiente
        if saldo_doc <= 0:
            break
        disponible = pago.saldo_sin_aplicar
        if disponible <= 0:
            continue
        usar = min(disponible, saldo_doc)
        AplicacionPago.objects.create(pago=pago, documento=documento, monto=usar)
        aplicado += usar
    return aplicado


@transaction.atomic
def liberar_aplicaciones(documento):
    """Elimina las aplicaciones de una factura; el dinero vuelve a saldo a favor."""
    documento.aplicaciones.all().delete()
```

- [ ] **Step 6: Actualizar el form y la vista de pago por factura**

En `apps/core/forms.py`, reemplazar `PagoFacturaForm` por un form que sirva para registrar un pago contra UNA factura (crea Pago + 1 aplicación). Renombrar a `PagoFacturaForm` manteniendo el nombre para mínima fricción:

```python
class PagoFacturaForm(forms.Form):
    fecha_pago = forms.DateField(
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'))
    metodo_pago = forms.ModelChoiceField(
        queryset=MetodoPago.objects.filter(activo=True),
        widget=forms.Select(attrs={'class': 'form-select'}))
    monto = forms.DecimalField(
        max_digits=12, decimal_places=2,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}))
    referencia = forms.CharField(
        required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    comprobante = forms.FileField(
        required=False, widget=forms.ClearableFileInput(attrs={'class': 'form-control'}))
    notas = forms.CharField(
        required=False, widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2}))
```

Asegurar que `MetodoPago` está importado en `forms.py` (`from .models import ..., MetodoPago`).

En `apps/core/views/facturas_pagos.py`, actualizar `factura_pago_nuevo` para usar el nuevo service con una sola aplicación:

```python
from ..models import DocumentoFactura, Pago, AplicacionPago
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
            payment_service.registrar_abono(
                doc.cliente,
                fecha_pago=cd['fecha_pago'], metodo_pago=cd['metodo_pago'],
                monto=cd['monto'], referencia=cd.get('referencia', ''),
                comprobante=cd.get('comprobante'), notas=cd.get('notas', ''),
                aplicaciones=[(doc, cd['monto'])],
            )
            messages.success(request, 'Pago registrado.')
            return redirect('factura_detalle', pk=doc.pk)
    else:
        form = PagoFacturaForm(initial={'fecha_pago': timezone.localdate()})
    return render(request, 'facturas/form_pago.html', {'form': form, 'doc': doc})
```

Y `factura_pago_borrar` ahora borra una `AplicacionPago` (o el `Pago`). Para el flujo por-factura, borrar la aplicación:

```python
@login_required
@permission_required(_perm('registrar_pago_factura'), raise_exception=True)
@facturas_enabled
@require_POST
def factura_pago_borrar(request, pk):
    apl = get_object_or_404(AplicacionPago, pk=pk)
    doc_pk = apl.documento_id
    pago = apl.pago
    apl.delete()  # signal recalcula estado
    if not pago.aplicaciones.exists() and pago.monto == pago.saldo_sin_aplicar:
        # pago quedó totalmente sin aplicar y sin uso: eliminarlo también
        pago.delete()
    messages.success(request, 'Pago eliminado.')
    return redirect('factura_detalle', pk=doc_pk)
```

(La URL `factura_pago_borrar` ahora recibe el `pk` de la `AplicacionPago`. Verificar que la plantilla `detalle.html` pase el id correcto en Task 7.)

- [ ] **Step 7: Reescribir tests viejos que usaban PagoFactura/registrar_pago**

Reemplazar `apps/core/tests_facturas/test_payment_service.py` para usar `registrar_abono` y `MetodoPago`. Ejemplo de los casos equivalentes:

```python
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.core.models import Cliente, DocumentoFactura, MetodoPago
from apps.core.services.facturas import payment_service


class PaymentServiceTests(TestCase):
    def setUp(self):
        self.cliente = Cliente.objects.create(nombre='Cli')
        self.met = MetodoPago.objects.create(nombre='Efectivo', tipo='efectivo')
        self.hoy = timezone.localdate()
        self.doc = DocumentoFactura.objects.create(
            cliente=self.cliente, tipo_documento='factura', fecha_documento=self.hoy,
            fecha_vencimiento=self.hoy + timedelta(days=10), monto_total=Decimal('100.00'),
        )

    def _abono(self, monto):
        return payment_service.registrar_abono(
            self.cliente, fecha_pago=self.hoy, metodo_pago=self.met,
            monto=Decimal(monto), aplicaciones=[(self.doc, Decimal(monto))],
        )

    def test_pago_parcial_queda_pendiente(self):
        self._abono('40.00')
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.monto_pagado, Decimal('40.00'))
        self.assertEqual(self.doc.estado_pago, 'pendiente')

    def test_pago_total_marca_pagada(self):
        self._abono('100.00')
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.estado_pago, 'pagada')

    def test_borrar_aplicacion_recalcula_estado(self):
        self._abono('100.00')
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.estado_pago, 'pagada')
        self.doc.aplicaciones.all().delete()
        self.doc.refresh_from_db()
        self.assertNotEqual(self.doc.estado_pago, 'pagada')
```

Revisar `test_status_service.py` y `test_models.py`: si crean `PagoFactura` directamente, cambiarlos a crear `Pago` + `AplicacionPago` (o usar `registrar_abono`). Buscar usos:
`grep -rn "PagoFactura\|registrar_pago\b" apps/core/tests_facturas/` y ajustar cada uno.

- [ ] **Step 8: Correr toda la suite**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core -v 1`
Expected: PASS (incluye `test_abono_service` y los tests ajustados).

- [ ] **Step 9: Commit**

```bash
git add apps/core/models.py apps/core/signals.py apps/core/services/facturas/payment_service.py apps/core/views/facturas_pagos.py apps/core/forms.py apps/core/tests_facturas/
git commit -m "feat(facturas): cutover a pagos por cliente (monto_pagado, signals, service)"
```

---

### Task 5: Hooks de anulación y de factura nueva

**Files:**
- Modify: `apps/core/views/facturas.py` (`factura_anular` → liberar; creación/registro de factura → aplicar saldo a favor)
- Test: `apps/core/tests_facturas/test_hooks_saldo.py`

**Interfaces:**
- Consumes: `payment_service.liberar_aplicaciones`, `payment_service.aplicar_saldo_a_favor` (Task 4).
- Produces: anular libera aplicaciones; al crear/confirmar una factura se aplica saldo a favor disponible.

- [ ] **Step 1: Escribir el test que falla**

Create `apps/core/tests_facturas/test_hooks_saldo.py`:

```python
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User, Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Cliente, DocumentoFactura, MetodoPago
from apps.core.services.facturas import payment_service


class HooksSaldoTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u', password='x')
        self.user.user_permissions.add(
            Permission.objects.get(codename='anular_factura'),
            Permission.objects.get(codename='ver_facturas'),
        )
        self.client.force_login(self.user)
        self.cli = Cliente.objects.create(nombre='Cli')
        self.met = MetodoPago.objects.create(nombre='Efectivo', tipo='efectivo')
        self.hoy = timezone.localdate()

    def test_anular_factura_libera_aplicaciones_a_saldo_a_favor(self):
        doc = DocumentoFactura.objects.create(
            cliente=self.cli, tipo_documento='factura', fecha_documento=self.hoy,
            monto_total=Decimal('100.00'))
        payment_service.registrar_abono(
            self.cli, fecha_pago=self.hoy, metodo_pago=self.met,
            monto=Decimal('100.00'), aplicaciones=[(doc, Decimal('100.00'))])
        self.client.post(reverse('factura_anular', args=[doc.pk]))
        doc.refresh_from_db()
        self.assertEqual(doc.estado_pago, 'anulada')
        self.assertEqual(doc.monto_pagado, Decimal('0.00'))
        self.assertEqual(self.cli.saldo_a_favor, Decimal('100.00'))
```

(Si `factura_anular` requiere otro permiso o método GET/POST, ajustar el test al patrón real de la vista — revisar `apps/core/views/facturas.py:226`.)

- [ ] **Step 2: Correr y verificar que falla**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_facturas.test_hooks_saldo -v 2`
Expected: FAIL — `monto_pagado` sigue siendo 100 tras anular.

- [ ] **Step 3: Anular libera aplicaciones**

En `apps/core/views/facturas.py`, `factura_anular`:

```python
def factura_anular(request, pk):
    doc = get_object_or_404(DocumentoFactura, pk=pk)
    doc.estado_pago = 'anulada'
    doc.save(update_fields=['estado_pago', 'updated_at'])
    payment_service.liberar_aplicaciones(doc)
    messages.success(request, 'Documento anulado.')
    return redirect('factura_detalle', pk=doc.pk)
```

Asegurar `from ..services.facturas import payment_service` está en el módulo.

- [ ] **Step 4: Aplicar saldo a favor al crear/confirmar factura**

Localizar dónde se crean facturas que deben absorber crédito: `factura_upload` (creación individual) y `factura_lote_confirmar` (lote). Tras crear cada `DocumentoFactura` con `monto_total > 0`, llamar:

```python
from ..services.facturas import payment_service
# ...después de crear/guardar el documento con monto_total definido:
payment_service.aplicar_saldo_a_favor(documento)
```

Agregar un test que cubra esto si la creación es accesible por servicio (opcional pero recomendado). Mínimo: cubrir `aplicar_saldo_a_favor` directamente (ya cubierto en Task 4) y la anulación (Step 1).

- [ ] **Step 5: Correr la suite**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core -v 1`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/core/views/facturas.py apps/core/tests_facturas/test_hooks_saldo.py
git commit -m "feat(facturas): liberar pagos al anular y aplicar saldo a favor a facturas nuevas"
```

---

### Task 6: CRUD de `MetodoPago` (UI + permiso + nav)

**Files:**
- Create: `apps/core/views/metodos_pago.py`
- Modify: `apps/core/views/__init__.py` (exportar las vistas)
- Modify: `apps/core/forms.py` (`MetodoPagoForm`)
- Modify: `apps/core/urls.py` (4 rutas)
- Create: `templates/metodos_pago/lista.html`, `templates/metodos_pago/form.html`
- Modify: plantilla de navegación (`templates/.../nav_menu.html`) — agregar enlace
- Test: `apps/core/tests_facturas/test_metodos_pago_views.py`

**Interfaces:**
- Consumes: `MetodoPago`, permiso `gestionar_metodos_pago`.
- Produces: URLs `metodo_pago_lista`, `metodo_pago_crear`, `metodo_pago_editar`, `metodo_pago_toggle_activo`.

- [ ] **Step 1: Escribir el test que falla**

Create `apps/core/tests_facturas/test_metodos_pago_views.py`:

```python
from django.contrib.auth.models import User, Permission
from django.test import TestCase
from django.urls import reverse

from apps.core.models import MetodoPago


class MetodosPagoViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u', password='x')
        self.user.user_permissions.add(
            Permission.objects.get(codename='gestionar_metodos_pago'))
        self.client.force_login(self.user)

    def test_crear_metodo(self):
        resp = self.client.post(reverse('metodo_pago_crear'), {
            'nombre': 'Transferencia BAC', 'tipo': 'transferencia', 'orden': 0})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(MetodoPago.objects.filter(nombre='Transferencia BAC').exists())

    def test_toggle_activo(self):
        m = MetodoPago.objects.create(nombre='Efectivo', tipo='efectivo')
        self.client.post(reverse('metodo_pago_toggle_activo', args=[m.pk]))
        m.refresh_from_db()
        self.assertFalse(m.activo)

    def test_sin_permiso_prohibido(self):
        User.objects.create_user('u2', password='x')
        self.client.logout(); self.client.force_login(User.objects.get(username='u2'))
        resp = self.client.get(reverse('metodo_pago_lista'))
        self.assertEqual(resp.status_code, 403)
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_facturas.test_metodos_pago_views -v 2`
Expected: FAIL — `Reverse for 'metodo_pago_crear' not found`.

- [ ] **Step 3: Form**

En `apps/core/forms.py`:

```python
class MetodoPagoForm(forms.ModelForm):
    class Meta:
        model = MetodoPago
        fields = ['nombre', 'tipo', 'activo', 'orden']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'tipo': forms.Select(attrs={'class': 'form-select'}),
            'activo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'orden': forms.NumberInput(attrs={'class': 'form-control'}),
        }
```

- [ ] **Step 4: Vistas**

Create `apps/core/views/metodos_pago.py`:

```python
"""metodos_pago.py — CRUD de métodos de pago."""
from .common import *  # noqa: F401,F403

from ..models import MetodoPago
from ..forms import MetodoPagoForm


@login_required
@permission_required(_perm('gestionar_metodos_pago'), raise_exception=True)
def metodo_pago_lista(request):
    metodos = MetodoPago.objects.all()
    return render(request, 'metodos_pago/lista.html', {'metodos': metodos})


@login_required
@permission_required(_perm('gestionar_metodos_pago'), raise_exception=True)
def metodo_pago_crear(request):
    if request.method == 'POST':
        form = MetodoPagoForm(request.POST)
        if form.is_valid():
            m = form.save()
            messages.success(request, f'Método "{m.nombre}" creado.')
            return redirect('metodo_pago_lista')
    else:
        form = MetodoPagoForm()
    return render(request, 'metodos_pago/form.html', {'form': form, 'titulo': 'Nuevo método de pago'})


@login_required
@permission_required(_perm('gestionar_metodos_pago'), raise_exception=True)
def metodo_pago_editar(request, pk):
    metodo = get_object_or_404(MetodoPago, pk=pk)
    if request.method == 'POST':
        form = MetodoPagoForm(request.POST, instance=metodo)
        if form.is_valid():
            form.save()
            messages.success(request, f'Método "{metodo.nombre}" actualizado.')
            return redirect('metodo_pago_lista')
    else:
        form = MetodoPagoForm(instance=metodo)
    return render(request, 'metodos_pago/form.html', {
        'form': form, 'titulo': f'Editar: {metodo.nombre}', 'metodo': metodo})


@login_required
@permission_required(_perm('gestionar_metodos_pago'), raise_exception=True)
@require_POST
def metodo_pago_toggle_activo(request, pk):
    metodo = get_object_or_404(MetodoPago, pk=pk)
    metodo.activo = not metodo.activo
    metodo.save(update_fields=['activo'])
    messages.success(request, f'Método "{metodo.nombre}" {"activado" if metodo.activo else "desactivado"}.')
    return redirect('metodo_pago_lista')
```

Exportar en `apps/core/views/__init__.py` (seguir el patrón existente — agregar `from .metodos_pago import *` o las importaciones nombradas que use el archivo).

- [ ] **Step 5: URLs**

En `apps/core/urls.py`, junto a las rutas de facturas:

```python
    path('facturas/metodos-pago/', views.metodo_pago_lista, name='metodo_pago_lista'),
    path('facturas/metodos-pago/nuevo/', views.metodo_pago_crear, name='metodo_pago_crear'),
    path('facturas/metodos-pago/<int:pk>/editar/', views.metodo_pago_editar, name='metodo_pago_editar'),
    path('facturas/metodos-pago/<int:pk>/toggle/', views.metodo_pago_toggle_activo, name='metodo_pago_toggle_activo'),
```

- [ ] **Step 6: Plantillas**

Create `templates/metodos_pago/lista.html` (extender la base del proyecto — revisar `templates/maquinas/lista.html` para el `{% extends %}` y bloques correctos):

```html
{% extends "base.html" %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-3">
  <h1 class="h4 mb-0">Métodos de pago</h1>
  <a href="{% url 'metodo_pago_crear' %}" class="btn btn-primary btn-sm">Nuevo método</a>
</div>
<table class="table table-sm align-middle">
  <thead><tr><th>Nombre</th><th>Tipo</th><th>Estado</th><th></th></tr></thead>
  <tbody>
    {% for m in metodos %}
    <tr>
      <td>{{ m.nombre }}</td>
      <td>{{ m.get_tipo_display }}</td>
      <td>{% if m.activo %}<span class="badge bg-success">Activo</span>{% else %}<span class="badge bg-secondary">Inactivo</span>{% endif %}</td>
      <td class="text-end">
        <a href="{% url 'metodo_pago_editar' m.pk %}" class="btn btn-sm btn-outline-secondary">Editar</a>
        <form method="post" action="{% url 'metodo_pago_toggle_activo' m.pk %}" class="d-inline">
          {% csrf_token %}
          <button class="btn btn-sm btn-outline-secondary">{% if m.activo %}Desactivar{% else %}Activar{% endif %}</button>
        </form>
      </td>
    </tr>
    {% empty %}
    <tr><td colspan="4" class="text-muted">Sin métodos de pago.</td></tr>
    {% endfor %}
  </tbody>
</table>
{% endblock %}
```

Create `templates/metodos_pago/form.html` (espejo de `templates/maquinas/form.html`):

```html
{% extends "base.html" %}
{% block content %}
<h1 class="h4 mb-3">{{ titulo }}</h1>
<form method="post" class="col-md-6">
  {% csrf_token %}
  {{ form.as_p }}
  <button class="btn btn-primary">Guardar</button>
  <a href="{% url 'metodo_pago_lista' %}" class="btn btn-link">Cancelar</a>
</form>
{% endblock %}
```

(Ajustar `{% extends %}` y clases al patrón real del proyecto si difiere de `maquinas/`.)

- [ ] **Step 7: Enlace en navegación**

Agregar en el menú (donde están "Máquinas"/"Clientes" o la sección de facturas) un enlace a `{% url 'metodo_pago_lista' %}` con la guarda de permiso:

```html
{% if perms.core.gestionar_metodos_pago %}
<a class="dropdown-item" href="{% url 'metodo_pago_lista' %}">Métodos de pago</a>
{% endif %}
```

- [ ] **Step 8: Correr la suite**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_facturas.test_metodos_pago_views -v 2`
Expected: PASS (3 tests). Luego correr `apps.core` completo en verde.

- [ ] **Step 9: Commit**

```bash
git add apps/core/views/metodos_pago.py apps/core/views/__init__.py apps/core/forms.py apps/core/urls.py templates/metodos_pago/ templates/ apps/core/tests_facturas/test_metodos_pago_views.py
git commit -m "feat(facturas): CRUD de métodos de pago configurables"
```

---

### Task 7: UI "Registrar abono" desde la ficha del cliente (reparto editable)

**Files:**
- Modify: `apps/core/views/facturas_cliente.py` (vista `cliente_abono_nuevo`)
- Modify: `apps/core/forms.py` (`AbonoClienteForm`)
- Modify: `apps/core/urls.py` (ruta `cliente_abono_nuevo`)
- Create: `templates/facturas/form_abono.html`
- Modify: `templates/facturas/_tab_cliente.html` (botón "Registrar abono" + saldo a favor)
- Test: `apps/core/tests_facturas/test_abono_view.py`

**Interfaces:**
- Consumes: `payment_service.registrar_abono`, `payment_service.proponer_reparto`, `MetodoPago`.
- Produces: URL `cliente_abono_nuevo`.

- [ ] **Step 1: Escribir el test que falla**

Create `apps/core/tests_facturas/test_abono_view.py`:

```python
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User, Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Cliente, DocumentoFactura, MetodoPago


class AbonoViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u', password='x')
        self.user.user_permissions.add(
            Permission.objects.get(codename='registrar_pago_factura'),
            Permission.objects.get(codename='ver_facturas'))
        self.client.force_login(self.user)
        self.cli = Cliente.objects.create(nombre='Cli')
        self.met = MetodoPago.objects.create(nombre='Efectivo', tipo='efectivo')
        self.hoy = timezone.localdate()
        self.f1 = DocumentoFactura.objects.create(
            cliente=self.cli, tipo_documento='factura',
            fecha_documento=self.hoy - timedelta(days=5), monto_total=Decimal('100.00'))
        self.f2 = DocumentoFactura.objects.create(
            cliente=self.cli, tipo_documento='factura',
            fecha_documento=self.hoy, monto_total=Decimal('100.00'))

    def test_abono_auto_reparte_por_antiguedad(self):
        resp = self.client.post(reverse('cliente_abono_nuevo', args=[self.cli.pk]), {
            'fecha_pago': self.hoy.isoformat(), 'metodo_pago': self.met.pk,
            'monto': '150.00',
            # sin montos por factura -> auto reparto
        })
        self.assertEqual(resp.status_code, 302)
        self.f1.refresh_from_db(); self.f2.refresh_from_db()
        self.assertEqual(self.f1.monto_pagado, Decimal('100.00'))
        self.assertEqual(self.f2.monto_pagado, Decimal('50.00'))

    def test_abono_con_reparto_editado(self):
        resp = self.client.post(reverse('cliente_abono_nuevo', args=[self.cli.pk]), {
            'fecha_pago': self.hoy.isoformat(), 'metodo_pago': self.met.pk,
            'monto': '100.00',
            f'aplicar_{self.f1.pk}': '0',
            f'aplicar_{self.f2.pk}': '100.00',
        })
        self.assertEqual(resp.status_code, 302)
        self.f1.refresh_from_db(); self.f2.refresh_from_db()
        self.assertEqual(self.f1.monto_pagado, Decimal('0.00'))
        self.assertEqual(self.f2.monto_pagado, Decimal('100.00'))
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_facturas.test_abono_view -v 2`
Expected: FAIL — `Reverse for 'cliente_abono_nuevo' not found`.

- [ ] **Step 3: Form de cabecera del abono**

En `apps/core/forms.py`:

```python
class AbonoClienteForm(forms.Form):
    fecha_pago = forms.DateField(
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'))
    metodo_pago = forms.ModelChoiceField(
        queryset=MetodoPago.objects.filter(activo=True),
        widget=forms.Select(attrs={'class': 'form-select'}))
    monto = forms.DecimalField(
        max_digits=12, decimal_places=2,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}))
    referencia = forms.CharField(
        required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    comprobante = forms.FileField(
        required=False, widget=forms.ClearableFileInput(attrs={'class': 'form-control'}))
    notas = forms.CharField(
        required=False, widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2}))
```

- [ ] **Step 4: Vista**

En `apps/core/views/facturas_cliente.py`:

```python
from decimal import Decimal
from ..forms import AbonoClienteForm
from ..services.facturas import payment_service


@login_required
@permission_required(_perm('registrar_pago_factura'), raise_exception=True)
@facturas_enabled
def cliente_abono_nuevo(request, pk):
    cliente = get_object_or_404(Cliente, pk=pk)
    pendientes = payment_service._facturas_pendientes(cliente)
    if request.method == 'POST':
        form = AbonoClienteForm(request.POST, request.FILES)
        if form.is_valid():
            cd = form.cleaned_data
            # Construir aplicaciones desde los campos aplicar_<pk> si vienen
            aplicaciones = []
            tiene_edicion = False
            for doc in pendientes:
                raw = request.POST.get(f'aplicar_{doc.pk}')
                if raw not in (None, ''):
                    tiene_edicion = True
                    monto = Decimal(raw)
                    if monto > 0:
                        aplicaciones.append((doc, monto))
            payment_service.registrar_abono(
                cliente, fecha_pago=cd['fecha_pago'], metodo_pago=cd['metodo_pago'],
                monto=cd['monto'], referencia=cd.get('referencia', ''),
                comprobante=cd.get('comprobante'), notas=cd.get('notas', ''),
                aplicaciones=aplicaciones if tiene_edicion else None,
            )
            messages.success(request, 'Abono registrado.')
            return redirect('cliente_facturas_fragment', pk=cliente.pk)
    else:
        form = AbonoClienteForm(initial={'fecha_pago': timezone.localdate()})
    return render(request, 'facturas/form_abono.html', {
        'form': form, 'cliente': cliente, 'pendientes': pendientes,
    })
```

Exportar la vista en `apps/core/views/__init__.py` si el archivo usa importaciones nombradas.

- [ ] **Step 5: URL**

En `apps/core/urls.py`:

```python
    path('facturas/clientes/<int:pk>/abono/', views.cliente_abono_nuevo, name='cliente_abono_nuevo'),
```

- [ ] **Step 6: Plantilla con reparto editable**

Create `templates/facturas/form_abono.html`:

```html
{% extends "base.html" %}
{% block content %}
<h1 class="h4 mb-3">Registrar abono · {{ cliente.nombre }}</h1>
<p class="text-muted">Saldo a favor actual: <strong>L {{ cliente.saldo_a_favor }}</strong> ·
   Total adeudado: <strong>L {{ cliente.total_adeudado }}</strong></p>
<form method="post" enctype="multipart/form-data" class="col-lg-8">
  {% csrf_token %}
  <div class="row g-2 mb-3">
    <div class="col-md-3">{{ form.fecha_pago.label_tag }}{{ form.fecha_pago }}</div>
    <div class="col-md-3">{{ form.metodo_pago.label_tag }}{{ form.metodo_pago }}</div>
    <div class="col-md-3">{{ form.monto.label_tag }}{{ form.monto }}</div>
    <div class="col-md-3">{{ form.referencia.label_tag }}{{ form.referencia }}</div>
  </div>
  <h2 class="h6">Reparto entre facturas (editable)</h2>
  <p class="text-muted small">Deja los montos en blanco para repartir automáticamente
     de la más antigua a la más reciente.</p>
  <table class="table table-sm align-middle">
    <thead><tr><th>Factura</th><th>Fecha</th><th>Saldo</th><th>Aplicar</th></tr></thead>
    <tbody>
      {% for doc in pendientes %}
      <tr>
        <td>{{ doc.numero_documento|default:doc.pk }}</td>
        <td>{{ doc.fecha_documento|date:"d/m/Y" }}</td>
        <td>L {{ doc.saldo_pendiente }}</td>
        <td><input type="number" step="0.01" min="0" name="aplicar_{{ doc.pk }}"
                   class="form-control form-control-sm" placeholder="auto"></td>
      </tr>
      {% empty %}
      <tr><td colspan="4" class="text-muted">Sin facturas pendientes (el abono quedará como saldo a favor).</td></tr>
      {% endfor %}
    </tbody>
  </table>
  <div class="mb-3">{{ form.comprobante.label_tag }}{{ form.comprobante }}</div>
  <div class="mb-3">{{ form.notas.label_tag }}{{ form.notas }}</div>
  <button class="btn btn-primary">Registrar abono</button>
  <a href="{% url 'cliente_facturas_fragment' cliente.pk %}" class="btn btn-link">Cancelar</a>
</form>
{% endblock %}
```

(Ajustar `{% extends %}` y nombres de campos al patrón real; revisar `templates/facturas/form_pago.html`.)

- [ ] **Step 7: Botón y saldo en la pestaña del cliente**

En `templates/facturas/_tab_cliente.html`, agregar cerca del resumen un enlace y el saldo a favor:

```html
{% if perms.core.registrar_pago_factura %}
<a href="{% url 'cliente_abono_nuevo' cliente.pk %}" class="btn btn-sm btn-success">Registrar abono</a>
{% endif %}
<span class="ms-2 text-muted">Saldo a favor: <strong>L {{ cliente.saldo_a_favor }}</strong></span>
```

(Verificar que `cliente` está en el contexto de `_tab_cliente.html`; si no, pasarlo desde `cliente_facturas_fragment`.)

- [ ] **Step 8: Correr la suite**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_facturas.test_abono_view -v 2`
Expected: PASS (2 tests). Luego `apps.core` completo en verde.

- [ ] **Step 9: Commit**

```bash
git add apps/core/views/facturas_cliente.py apps/core/views/__init__.py apps/core/forms.py apps/core/urls.py templates/facturas/form_abono.html templates/facturas/_tab_cliente.html apps/core/tests_facturas/test_abono_view.py
git commit -m "feat(facturas): registrar abono por cliente con reparto editable"
```

---

### Task 8: Mostrar saldo a favor y lista de abonos; ajustar detalle de factura

**Files:**
- Modify: `apps/core/views/facturas_cliente.py` (`cliente_facturas_fragment` → pasar `cliente`, `abonos`, `saldo_a_favor`)
- Modify: `templates/facturas/_tab_cliente.html` (lista de abonos del cliente)
- Modify: `templates/facturas/detalle.html` (listar aplicaciones de la factura y arreglar id en "borrar pago")
- Test: `apps/core/tests_facturas/test_cliente_tab.py` (extender)

**Interfaces:**
- Consumes: `Cliente.saldo_a_favor`, `cliente.pagos`, `documento.aplicaciones`.
- Produces: contexto extendido en el fragmento del cliente.

- [ ] **Step 1: Extender el test del tab del cliente**

En `apps/core/tests_facturas/test_cliente_tab.py`, agregar un test que verifique que el saldo a favor aparece en el render:

```python
    def test_fragmento_muestra_saldo_a_favor(self):
        from decimal import Decimal
        from apps.core.models import MetodoPago
        from apps.core.services.facturas import payment_service
        met = MetodoPago.objects.create(nombre='Efectivo', tipo='efectivo')
        # abono mayor al adeudado -> saldo a favor
        payment_service.registrar_abono(
            self.cliente, fecha_pago=self.hoy, metodo_pago=met, monto=Decimal('50.00'))
        resp = self.client.get(reverse('cliente_facturas_fragment', args=[self.cliente.pk]))
        self.assertContains(resp, 'Saldo a favor')
```

(Adaptar `self.cliente` / `self.hoy` a lo que ya define el `setUp` de ese archivo.)

- [ ] **Step 2: Correr y verificar que falla**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core.tests_facturas.test_cliente_tab -v 2`
Expected: FAIL — el texto no aparece (o falta `cliente` en contexto).

- [ ] **Step 3: Pasar contexto extendido**

En `cliente_facturas_fragment` (apps/core/views/facturas_cliente.py), en el `render` final agregar al diccionario:

```python
        'cliente': cliente,
        'abonos': cliente.pagos.all()[:50],
        'saldo_a_favor': cliente.saldo_a_favor,
```

- [ ] **Step 4: Render del saldo y abonos**

En `templates/facturas/_tab_cliente.html`, agregar una sección de abonos:

```html
<h2 class="h6 mt-4">Abonos del cliente</h2>
<table class="table table-sm">
  <thead><tr><th>Fecha</th><th>Método</th><th>Monto</th><th>Aplicado</th><th>Sin aplicar</th></tr></thead>
  <tbody>
    {% for p in abonos %}
    <tr>
      <td>{{ p.fecha_pago|date:"d/m/Y" }}</td>
      <td>{{ p.metodo_pago.nombre }}</td>
      <td>L {{ p.monto }}</td>
      <td>L {{ p.monto_aplicado }}</td>
      <td>L {{ p.saldo_sin_aplicar }}</td>
    </tr>
    {% empty %}
    <tr><td colspan="5" class="text-muted">Sin abonos.</td></tr>
    {% endfor %}
  </tbody>
</table>
```

- [ ] **Step 5: Arreglar "borrar pago" en el detalle de la factura**

En `templates/facturas/detalle.html`, la tabla de pagos ahora debe iterar `doc.aplicaciones` y el botón de borrar debe pasar el `pk` de la **aplicación** (la vista `factura_pago_borrar` ahora recibe `AplicacionPago.pk` — Task 4). Localizar el bloque que recorre `doc.pagos` y cambiarlo a:

```html
{% for apl in doc.aplicaciones.all %}
<tr>
  <td>{{ apl.pago.fecha_pago|date:"d/m/Y" }}</td>
  <td>{{ apl.pago.metodo_pago.nombre }}</td>
  <td>L {{ apl.monto }}</td>
  <td>
    <form method="post" action="{% url 'factura_pago_borrar' apl.pk %}" class="d-inline">
      {% csrf_token %}
      <button class="btn btn-sm btn-outline-danger">Borrar</button>
    </form>
  </td>
</tr>
{% endfor %}
```

(Si `_modal_pago.html` referencia `doc.pagos`, actualizarlo igual a `doc.aplicaciones`.)

- [ ] **Step 6: Correr la suite completa**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core -v 1`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/core/views/facturas_cliente.py templates/facturas/_tab_cliente.html templates/facturas/detalle.html templates/facturas/_modal_pago.html apps/core/tests_facturas/test_cliente_tab.py
git commit -m "feat(facturas): mostrar saldo a favor, abonos del cliente y aplicaciones por factura"
```

---

### Task 9: Retirar el modelo `PagoFactura`

**Files:**
- Modify: `apps/core/models.py` (eliminar `class PagoFactura`)
- Modify: `apps/core/admin.py` (eliminar `PagoFactura` import y `PagoFacturaAdmin`)
- Create migration: `apps/core/migrations/0023_remove_pagofactura.py`
- Grep de seguridad: ninguna referencia restante a `PagoFactura`

**Interfaces:**
- Consumes: nada (la migración de datos de Task 3 ya preservó la información en `Pago`/`AplicacionPago`).
- Produces: el esquema sin la tabla `PagoFactura`.

- [ ] **Step 1: Verificar que no quedan referencias en código de app**

Run: `grep -rn "PagoFactura" apps/ templates/ | grep -v "/migrations/"`
Expected: sin resultados (las migraciones históricas SÍ la referencian y se dejan intactas). Si aparece algo en views/forms/tests/templates, corregirlo antes de continuar.

- [ ] **Step 2: Eliminar el modelo y su admin**

En `apps/core/models.py`, borrar la clase `PagoFactura` completa.
En `apps/core/admin.py`, quitar `PagoFactura` del import y borrar el bloque `@admin.register(PagoFactura)` / `PagoFacturaAdmin`.

- [ ] **Step 3: Crear la migración de eliminación**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py makemigrations core`
Expected: crea `0023_remove_pagofactura.py` con `DeleteModel(name='PagoFactura')`.

- [ ] **Step 4: Verificar migraciones y suite**

Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py makemigrations --check --dry-run`
Expected: `No changes detected`.
Run: `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test apps.core -v 1`
Expected: PASS (suite completa).

- [ ] **Step 5: Commit**

```bash
git add apps/core/models.py apps/core/admin.py apps/core/migrations/0023_remove_pagofactura.py
git commit -m "refactor(facturas): retirar modelo PagoFactura tras migración a abonos"
```

---

## Notas de despliegue

- Las migraciones `0020`–`0023` deben aplicarse **en orden y juntas**: `0022` (data) corre antes de que `0023` borre `PagoFactura`, y el cambio de código de Task 4 (`monto_pagado` por aplicaciones) asume que `0022` ya pobló las aplicaciones. No desplegar el código de Task 4 sin haber aplicado `0022`.
- Tras desplegar, crear los métodos de pago reales del negocio (transferencias a cada cuenta) desde **Facturas → Métodos de pago**.
- Revisar Service Workers / versiones de caché si las plantillas cambian (el proyecto bump-ea versiones de SW en commits previos).
