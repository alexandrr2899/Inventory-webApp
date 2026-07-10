# CRUD de abonos y reorden de tabs del cliente — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convertir los abonos en un CRUD completo (agregar editar y eliminar el `Pago` completo) desde la ficha del cliente, y mostrar la tab de Facturas primero (activa por defecto) antes de Productos llevados.

**Architecture:** Se agrega `editar_abono` al `payment_service` (reutilizando un helper de reparto extraído de `registrar_abono`), dos vistas nuevas (`cliente_abono_editar`, `cliente_abono_borrar`) sobre el modelo `Pago`, se generaliza `form_abono.html` para crear/editar, se añaden acciones a la tabla de abonos y se reordenan las tabs en `salidas.html`. No hay cambios de modelo ni migraciones.

**Tech Stack:** Django (server-rendered templates + Bootstrap 5), corre **solo en Docker**.

## Global Constraints

- **Tests y manage.py corren solo en Docker** (no hay `python` local). Comando de test:
  `docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web manage.py test <ruta> --noinput -v 1`
- En tests, **usar `self.client.force_login(user)`** (nunca `client.login`; django-axes rompe el login por formulario).
- Las vistas de facturas requieren `@login_required`, `@permission_required(_perm('...'), raise_exception=True)` y `@facturas_enabled`. El permiso para abonos es `registrar_pago_factura`.
- Los tests que renderizan plantillas de facturas requieren `@override_settings(FACTURAS_MODULE_ENABLED=True, ALLOWED_HOSTS=['testserver', 'localhost'])`.
- Las señales de `AplicacionPago` (`post_save`/`post_delete`) recalculan el estado de pago de las facturas automáticamente; no recalcular a mano.
- No pedir commit/push global al usuario en cada paso: los commits del plan son locales por tarea (el usuario ya autorizó el flujo del plan).

---

### Task 1: Servicio `editar_abono` + helper de reparto

**Files:**
- Modify: `apps/core/services/facturas/payment_service.py`
- Test: `apps/core/tests_facturas/test_abono_service.py`

**Interfaces:**
- Consumes: `proponer_reparto(cliente, monto)`, `_facturas_pendientes(cliente)`, modelos `Pago`, `AplicacionPago` (ya existen en el módulo).
- Produces:
  - `_aplicar_reparto(pago, aplicaciones)` — crea las `AplicacionPago` de `pago`; si `aplicaciones` es `None`, auto-reparte por antigüedad. Sin retorno.
  - `editar_abono(pago, *, fecha_pago, metodo_pago, monto, referencia='', comprobante=None, notas='', aplicaciones=None) -> Pago` — actualiza el `Pago`, borra sus aplicaciones y las rehace. Si `comprobante is None`, no toca el comprobante existente.
  - `registrar_abono(...)` mantiene la misma firma y comportamiento (ahora delega el reparto en `_aplicar_reparto`).

- [ ] **Step 1: Escribir los tests que fallan**

Agregar al final de la clase `AbonoServiceTests` en `apps/core/tests_facturas/test_abono_service.py`. Añadir el import al inicio del archivo:

```python
from django.core.files.uploadedfile import SimpleUploadedFile
```

Métodos nuevos dentro de `AbonoServiceTests`:

```python
    def test_editar_sube_monto_y_rehace_reparto(self):
        pago = self._abono('100.00')  # auto: cubre f1
        self.f1.refresh_from_db()
        self.assertEqual(self.f1.estado_pago, 'pagada')
        payment_service.editar_abono(
            pago, fecha_pago=self.hoy, metodo_pago=self.met,
            monto=Decimal('200.00'), aplicaciones=None)
        self.f1.refresh_from_db(); self.f2.refresh_from_db()
        self.assertEqual(self.f1.monto_pagado, Decimal('100.00'))
        self.assertEqual(self.f2.monto_pagado, Decimal('100.00'))

    def test_editar_baja_monto_libera_saldo(self):
        pago = self._abono('200.00')  # auto: cubre f1 y f2
        self.f2.refresh_from_db()
        self.assertEqual(self.f2.estado_pago, 'pagada')
        payment_service.editar_abono(
            pago, fecha_pago=self.hoy, metodo_pago=self.met,
            monto=Decimal('50.00'), aplicaciones=None)
        self.f1.refresh_from_db(); self.f2.refresh_from_db()
        self.assertEqual(self.f1.monto_pagado, Decimal('50.00'))
        self.assertEqual(self.f2.monto_pagado, Decimal('0.00'))
        self.assertEqual(self.f2.estado_pago, 'pendiente')

    def test_editar_con_reparto_explicito(self):
        pago = self._abono('100.00')  # auto: cubre f1
        payment_service.editar_abono(
            pago, fecha_pago=self.hoy, metodo_pago=self.met,
            monto=Decimal('100.00'), aplicaciones=[(self.f2, Decimal('100.00'))])
        self.f1.refresh_from_db(); self.f2.refresh_from_db()
        self.assertEqual(self.f1.monto_pagado, Decimal('0.00'))
        self.assertEqual(self.f2.monto_pagado, Decimal('100.00'))

    def test_editar_conserva_comprobante_si_no_se_envia_uno(self):
        comp = SimpleUploadedFile('c.pdf', b'x', content_type='application/pdf')
        pago = payment_service.registrar_abono(
            self.cli, fecha_pago=self.hoy, metodo_pago=self.met,
            monto=Decimal('100.00'), comprobante=comp)
        nombre = pago.comprobante.name
        self.assertTrue(nombre)
        payment_service.editar_abono(
            pago, fecha_pago=self.hoy, metodo_pago=self.met,
            monto=Decimal('120.00'), comprobante=None)
        pago.refresh_from_db()
        self.assertEqual(pago.comprobante.name, nombre)
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run:
```bash
docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web \
  manage.py test apps.core.tests_facturas.test_abono_service --noinput -v 1
```
Expected: FAIL con `AttributeError: module 'payment_service' has no attribute 'editar_abono'`.

- [ ] **Step 3: Implementar helper + `editar_abono` y refactorizar `registrar_abono`**

En `apps/core/services/facturas/payment_service.py`, reemplazar el cuerpo de `registrar_abono` (líneas 32-57) por esta versión y agregar `_aplicar_reparto` y `editar_abono` justo después:

```python
def _aplicar_reparto(pago, aplicaciones):
    """Crea las AplicacionPago de `pago` según `aplicaciones` (lista de (doc, monto)).

    Si `aplicaciones` es None, auto-reparte por antigüedad. Cada aplicación se
    topa al saldo de la factura y a lo que resta del pago; el remanente queda
    como saldo a favor del cliente.
    """
    if aplicaciones is None:
        aplicaciones = proponer_reparto(pago.cliente, pago.monto)
    restante = pago.monto
    for documento, monto_aplicar in aplicaciones:
        if restante <= 0:
            break
        monto_aplicar = min(Decimal(monto_aplicar), documento.saldo_pendiente, restante)
        if monto_aplicar > 0:
            AplicacionPago.objects.create(pago=pago, documento=documento, monto=monto_aplicar)
            restante -= monto_aplicar


@transaction.atomic
def registrar_abono(cliente, *, fecha_pago, metodo_pago, monto,
                    referencia='', comprobante=None, notas='', aplicaciones=None):
    """Crea un Pago y reparte su monto entre facturas.

    `aplicaciones`: lista opcional de (documento, monto). Si es None se auto-reparte
    por antigüedad.
    """
    pago = Pago.objects.create(
        cliente=cliente, fecha_pago=fecha_pago, metodo_pago=metodo_pago,
        monto=Decimal(monto), referencia=referencia, comprobante=comprobante, notas=notas,
    )
    _aplicar_reparto(pago, aplicaciones)
    return pago


@transaction.atomic
def editar_abono(pago, *, fecha_pago, metodo_pago, monto,
                 referencia='', comprobante=None, notas='', aplicaciones=None):
    """Actualiza un Pago y rehace su reparto entre facturas.

    Borra las AplicacionPago existentes y las vuelve a crear con la misma lógica
    de `registrar_abono`. El comprobante solo se reemplaza si `comprobante` no es
    None (para no borrar el archivo existente al editar sin subir uno nuevo).
    """
    pago.fecha_pago = fecha_pago
    pago.metodo_pago = metodo_pago
    pago.monto = Decimal(monto)
    pago.referencia = referencia
    pago.notas = notas
    if comprobante is not None:
        pago.comprobante = comprobante
    pago.save()
    pago.aplicaciones.all().delete()
    _aplicar_reparto(pago, aplicaciones)
    return pago
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run:
```bash
docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web \
  manage.py test apps.core.tests_facturas.test_abono_service --noinput -v 1
```
Expected: PASS (todos los tests de la clase, incluidos los previos de `registrar_abono`).

- [ ] **Step 5: Commit**

```bash
git add apps/core/services/facturas/payment_service.py apps/core/tests_facturas/test_abono_service.py
git commit -m "feat(facturas): editar_abono rehace el reparto entre facturas"
```

---

### Task 2: Vistas editar/borrar abono + URLs + form generalizado

**Files:**
- Modify: `apps/core/views/facturas_cliente.py`
- Modify: `apps/core/urls.py:102`
- Modify: `templates/facturas/form_abono.html`
- Test: `apps/core/tests_facturas/test_abono_view.py`

**Interfaces:**
- Consumes: `payment_service.editar_abono`, `payment_service._facturas_pendientes`, `AbonoClienteForm`, modelos `Pago`, `AplicacionPago`. La plantilla `form_abono.html` ahora recibe `pendientes` como lista de dicts `{'doc': <DocumentoFactura>, 'aplicado': <Decimal|None>}` y las claves de contexto `action_url`, `titulo`, `submit_label`, `modo_edicion`, `pago`.
- Produces:
  - Vista `cliente_abono_editar(request, pk)` — `pk` = id del `Pago`. URL name `cliente_abono_editar`.
  - Vista `cliente_abono_borrar(request, pk)` — `@require_POST`, `pk` = id del `Pago`. URL name `cliente_abono_borrar`.
  - `cliente_abono_nuevo` ahora pasa el mismo contexto (`pendientes` como dicts, `action_url`, etc.).

- [ ] **Step 1: Escribir los tests que fallan**

Agregar a `apps/core/tests_facturas/test_abono_view.py`. Añadir imports al inicio:

```python
from apps.core.models import Pago
from apps.core.services.facturas import payment_service
```

Y estos métodos dentro de `AbonoViewTests`:

```python
    def _pago(self, monto, aplicaciones=None):
        return payment_service.registrar_abono(
            self.cli, fecha_pago=self.hoy, metodo_pago=self.met,
            monto=Decimal(monto), aplicaciones=aplicaciones)

    def test_editar_get_precarga_formulario(self):
        pago = self._pago('100.00')
        resp = self.client.get(reverse('cliente_abono_editar', args=[pago.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Editar abono')
        # La factura ya saldada por este pago aparece en el reparto para redistribuir.
        self.assertContains(resp, f'aplicar_{self.f1.pk}')

    def test_editar_post_actualiza_monto(self):
        pago = self._pago('100.00')  # cubre f1
        resp = self.client.post(reverse('cliente_abono_editar', args=[pago.pk]), {
            'fecha_pago': self.hoy.isoformat(), 'metodo_pago': self.met.pk,
            'monto': '200.00'})
        self.assertEqual(resp.status_code, 302)
        self.f1.refresh_from_db(); self.f2.refresh_from_db()
        self.assertEqual(self.f1.monto_pagado, Decimal('100.00'))
        self.assertEqual(self.f2.monto_pagado, Decimal('100.00'))

    def test_borrar_elimina_pago_y_recalcula(self):
        pago = self._pago('100.00')  # cubre f1
        self.f1.refresh_from_db()
        self.assertEqual(self.f1.estado_pago, 'pagada')
        resp = self.client.post(reverse('cliente_abono_borrar', args=[pago.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Pago.objects.filter(pk=pago.pk).exists())
        self.f1.refresh_from_db()
        self.assertEqual(self.f1.monto_pagado, Decimal('0.00'))
        self.assertEqual(self.f1.estado_pago, 'pendiente')

    def test_editar_sin_permiso_403(self):
        otro = User.objects.create_user('sinperm', password='x')
        otro.user_permissions.add(Permission.objects.get(codename='ver_facturas'))
        self.client.force_login(otro)
        pago = self._pago('100.00')
        resp = self.client.get(reverse('cliente_abono_editar', args=[pago.pk]))
        self.assertEqual(resp.status_code, 403)
```

> Nota: `AbonoViewTests` no usa `@override_settings`; el `setUp` actual funciona porque las vistas `cliente_abono_*` no dependen de `FACTURAS_MODULE_ENABLED` en test (el decorador `@facturas_enabled` lee `settings.FACTURAS_MODULE_ENABLED`). Si el test da 404, agregar `@override_settings(FACTURAS_MODULE_ENABLED=True)` a la clase e importar `override_settings`. Verificar corriendo el test previo `test_abono_auto_reparte_por_antiguedad`: si hoy pasa, el setting ya está activo en el entorno de test.

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run:
```bash
docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web \
  manage.py test apps.core.tests_facturas.test_abono_view --noinput -v 1
```
Expected: FAIL con `NoReverseMatch: Reverse for 'cliente_abono_editar' not found`.

- [ ] **Step 3: Agregar las URLs**

En `apps/core/urls.py`, después de la línea 102 (`cliente_abono_nuevo`), agregar:

```python
    path('facturas/abonos/<int:pk>/editar/', views.cliente_abono_editar, name='cliente_abono_editar'),
    path('facturas/abonos/<int:pk>/borrar/', views.cliente_abono_borrar, name='cliente_abono_borrar'),
```

- [ ] **Step 4: Implementar las vistas y ajustar `cliente_abono_nuevo`**

En `apps/core/views/facturas_cliente.py`:

(a) Añadir `Pago` al import de modelos (línea 6):

```python
from ..models import Cliente, DocumentoFactura, Pago
```

(b) Reemplazar la vista `cliente_abono_nuevo` (líneas 84-121) por esta versión que arma el contexto compartido:

```python
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
            aplicaciones, tiene_edicion = _leer_reparto(request, pendientes)
            payment_service.registrar_abono(
                cliente, fecha_pago=cd['fecha_pago'], metodo_pago=cd['metodo_pago'],
                monto=cd['monto'], referencia=cd.get('referencia', ''),
                comprobante=cd.get('comprobante'), notas=cd.get('notas', ''),
                aplicaciones=aplicaciones if tiene_edicion else None,
            )
            messages.success(request, 'Abono registrado.')
            return redirect('cliente_salidas', pk=cliente.pk)
    else:
        form = AbonoClienteForm(initial={'fecha_pago': timezone.localdate()})
    return render(request, 'facturas/form_abono.html', {
        'form': form, 'cliente': cliente,
        'pendientes': [{'doc': d, 'aplicado': None} for d in pendientes],
        'modo_edicion': False, 'pago': None,
        'action_url': reverse('cliente_abono_nuevo', args=[cliente.pk]),
        'titulo': 'Registrar abono', 'submit_label': 'Registrar abono',
    })
```

(c) Agregar el helper `_leer_reparto` (extrae la lógica de los campos `aplicar_<pk>`, hoy inline en `cliente_abono_nuevo`) y las dos vistas nuevas, al final del archivo:

```python
def _leer_reparto(request, docs):
    """Construye (aplicaciones, tiene_edicion) desde los campos aplicar_<pk>.

    `docs`: iterable de DocumentoFactura. Devuelve una lista de (doc, monto) para
    los valores válidos > 0, y un flag que indica si hubo algún valor numérico
    (aunque sea 0) — si no hubo ninguno, el llamador auto-reparte.
    """
    aplicaciones = []
    tiene_edicion = False
    for doc in docs:
        raw = request.POST.get(f'aplicar_{doc.pk}')
        if raw in (None, ''):
            continue
        try:
            monto = Decimal(raw)
        except (InvalidOperation, ValueError):
            continue
        tiene_edicion = True
        if monto > 0:
            aplicaciones.append((doc, monto))
    return aplicaciones, tiene_edicion


@login_required
@permission_required(_perm('registrar_pago_factura'), raise_exception=True)
@facturas_enabled
def cliente_abono_editar(request, pk):
    pago = get_object_or_404(Pago, pk=pk)
    cliente = pago.cliente
    # Reparto: facturas pendientes + las ya aplicadas por ESTE pago (aunque este
    # abono las haya dejado en saldo 0), para poder redistribuir hacia ellas.
    aplicado_por_doc = {a.documento_id: a.monto for a in pago.aplicaciones.select_related('documento')}
    docs = {d.pk: d for d in payment_service._facturas_pendientes(cliente)}
    for a in pago.aplicaciones.select_related('documento'):
        docs.setdefault(a.documento_id, a.documento)
    docs = sorted(docs.values(), key=lambda d: (d.fecha_documento, d.created_at))

    if request.method == 'POST':
        form = AbonoClienteForm(request.POST, request.FILES)
        if form.is_valid():
            cd = form.cleaned_data
            aplicaciones, tiene_edicion = _leer_reparto(request, docs)
            payment_service.editar_abono(
                pago, fecha_pago=cd['fecha_pago'], metodo_pago=cd['metodo_pago'],
                monto=cd['monto'], referencia=cd.get('referencia', ''),
                comprobante=cd.get('comprobante'), notas=cd.get('notas', ''),
                aplicaciones=aplicaciones if tiene_edicion else None,
            )
            messages.success(request, 'Abono actualizado.')
            return redirect('cliente_salidas', pk=cliente.pk)
    else:
        form = AbonoClienteForm(initial={
            'fecha_pago': pago.fecha_pago, 'metodo_pago': pago.metodo_pago_id,
            'monto': pago.monto, 'referencia': pago.referencia, 'notas': pago.notas,
        })
    return render(request, 'facturas/form_abono.html', {
        'form': form, 'cliente': cliente,
        'pendientes': [{'doc': d, 'aplicado': aplicado_por_doc.get(d.pk)} for d in docs],
        'modo_edicion': True, 'pago': pago,
        'action_url': reverse('cliente_abono_editar', args=[pago.pk]),
        'titulo': 'Editar abono', 'submit_label': 'Guardar cambios',
    })


@login_required
@permission_required(_perm('registrar_pago_factura'), raise_exception=True)
@facturas_enabled
@require_POST
def cliente_abono_borrar(request, pk):
    pago = get_object_or_404(Pago, pk=pk)
    cliente_pk = pago.cliente_id
    pago.delete()  # cascade borra aplicaciones; señales recalculan facturas
    messages.success(request, 'Abono eliminado.')
    return redirect('cliente_salidas', pk=cliente_pk)
```

Verificar que `InvalidOperation` esté disponible: el archivo ya importa `from decimal import Decimal, InvalidOperation` en la línea 2. `require_POST` viene de `.common import *`.

- [ ] **Step 5: Generalizar `form_abono.html`**

En `templates/facturas/form_abono.html`:

(1) `{% block title %}` (línea 3) →
```html
{% block title %}{{ titulo }} · {{ cliente.nombre }}{% endblock %}
```

(2) Encabezado (línea 7) →
```html
  <h1><i class="bi bi-cash-coin me-2"></i>{{ titulo }} · {{ cliente.nombre }}</h1>
```

(3) `<form>` (línea 17) →
```html
<form method="post" action="{{ action_url }}" enctype="multipart/form-data">
```

(4) Cuerpo de la tabla de reparto (líneas 66-82) — iterar sobre los dicts y precargar el `value`:
```html
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
            <tr>
              <td colspan="4" class="text-muted text-center py-2">
                Sin facturas pendientes — el abono quedará como saldo a favor.
              </td>
            </tr>
            {% endfor %}
```

(5) En la tarjeta "Comprobante y notas", antes del input de comprobante (dentro del `<div class="mb-3">` de la línea 92), mostrar el comprobante actual en edición:
```html
      <div class="mb-3">
        <label class="form-label">{{ form.comprobante.label }}</label>
        {% if pago and pago.comprobante %}
        <div class="small mb-1"><a href="{{ pago.comprobante.url }}" target="_blank">Ver comprobante actual</a></div>
        {% endif %}
        {{ form.comprobante }}
        {% if form.comprobante.errors %}<div class="text-danger small">{{ form.comprobante.errors }}</div>{% endif %}
      </div>
```

(6) Botón submit (líneas 106-108) →
```html
    <button type="submit" class="btn btn-primary btn-lg flex-fill flex-md-grow-0">
      <i class="bi bi-check-lg me-2"></i>{{ submit_label }}
    </button>
```

- [ ] **Step 6: Correr los tests y verificar que pasan**

Run:
```bash
docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web \
  manage.py test apps.core.tests_facturas.test_abono_view --noinput -v 1
```
Expected: PASS (nuevos tests + `test_abono_auto_reparte_por_antiguedad`, `test_abono_con_reparto_editado`, `test_abono_con_valor_invalido_no_revienta` siguen pasando).

- [ ] **Step 7: Commit**

```bash
git add apps/core/views/facturas_cliente.py apps/core/urls.py templates/facturas/form_abono.html apps/core/tests_facturas/test_abono_view.py
git commit -m "feat(facturas): editar y borrar abono desde la ficha del cliente"
```

---

### Task 3: Acciones editar/eliminar en la tabla de abonos

**Files:**
- Modify: `templates/facturas/_tab_cliente.html:113-129`
- Test: `apps/core/tests_facturas/test_cliente_tab.py`

**Interfaces:**
- Consumes: `cliente_abono_editar`, `cliente_abono_borrar` (Task 2), la lista `abonos` que ya pasa `cliente_facturas_fragment`, y `perms.core.registrar_pago_factura`.
- Produces: columna "Acciones" en la tabla de abonos con enlace Editar y form POST Eliminar (con `confirm()` y `{% csrf_token %}`), visible solo con permiso.

- [ ] **Step 1: Escribir el test que falla**

Agregar a `apps/core/tests_facturas/test_cliente_tab.py` (dentro de `ClienteTabTests`):

```python
    def test_tabla_abonos_muestra_acciones_con_permiso(self):
        from apps.core.models import MetodoPago
        from apps.core.services.facturas import payment_service
        self.admin.user_permissions.add(Permission.objects.get(codename='registrar_pago_factura'))
        met = MetodoPago.objects.create(nombre='Efectivo', tipo='efectivo')
        pago = payment_service.registrar_abono(
            self.cliente, fecha_pago=timezone.localdate(), metodo_pago=met, monto=Decimal('50.00'))
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('cliente_facturas_fragment', args=[self.cliente.pk]))
        self.assertContains(resp, reverse('cliente_abono_editar', args=[pago.pk]))
        self.assertContains(resp, reverse('cliente_abono_borrar', args=[pago.pk]))

    def test_tabla_abonos_oculta_acciones_sin_permiso(self):
        from apps.core.models import MetodoPago
        from apps.core.services.facturas import payment_service
        met = MetodoPago.objects.create(nombre='Efectivo', tipo='efectivo')
        pago = payment_service.registrar_abono(
            self.cliente, fecha_pago=timezone.localdate(), metodo_pago=met, monto=Decimal('50.00'))
        self.client.force_login(self.admin)  # solo tiene ver_facturas
        resp = self.client.get(reverse('cliente_facturas_fragment', args=[self.cliente.pk]))
        self.assertNotContains(resp, reverse('cliente_abono_borrar', args=[pago.pk]))
```

- [ ] **Step 2: Correr y verificar que falla**

Run:
```bash
docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web \
  manage.py test apps.core.tests_facturas.test_cliente_tab --noinput -v 1
```
Expected: FAIL en `test_tabla_abonos_muestra_acciones_con_permiso` (la URL de editar no aparece).

- [ ] **Step 3: Agregar la columna de acciones**

En `templates/facturas/_tab_cliente.html`, reemplazar el bloque de la tabla de abonos (líneas 113-129) por:

```html
<h2 class="h6 mt-4">Abonos del cliente</h2>
<table class="table table-sm">
  <thead><tr>
    <th>Fecha</th><th>Método</th><th>Monto</th><th>Aplicado</th><th>Sin aplicar</th>
    {% if perms.core.registrar_pago_factura %}<th class="text-end">Acciones</th>{% endif %}
  </tr></thead>
  <tbody>
    {% for p in abonos %}
    <tr>
      <td>{{ p.fecha_pago|date:"d/m/Y" }}</td>
      <td>{{ p.metodo_pago.nombre }}</td>
      <td>L {{ p.monto }}</td>
      <td>L {{ p.monto_aplicado }}</td>
      <td>L {{ p.saldo_sin_aplicar }}</td>
      {% if perms.core.registrar_pago_factura %}
      <td class="text-end text-nowrap">
        <a href="{% url 'cliente_abono_editar' p.pk %}" class="btn btn-sm btn-outline-primary" title="Editar">
          <i class="bi bi-pencil"></i>
        </a>
        <form method="post" action="{% url 'cliente_abono_borrar' p.pk %}" class="d-inline"
              onsubmit="return confirm('¿Eliminar este abono? Se recalcularán las facturas afectadas.');">
          {% csrf_token %}
          <button type="submit" class="btn btn-sm btn-outline-danger" title="Eliminar">
            <i class="bi bi-trash"></i>
          </button>
        </form>
      </td>
      {% endif %}
    </tr>
    {% empty %}
    <tr><td colspan="{% if perms.core.registrar_pago_factura %}6{% else %}5{% endif %}" class="text-muted">Sin abonos.</td></tr>
    {% endfor %}
  </tbody>
</table>
```

- [ ] **Step 4: Correr y verificar que pasa**

Run:
```bash
docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web \
  manage.py test apps.core.tests_facturas.test_cliente_tab --noinput -v 1
```
Expected: PASS (nuevos tests + los previos de la clase).

- [ ] **Step 5: Commit**

```bash
git add templates/facturas/_tab_cliente.html apps/core/tests_facturas/test_cliente_tab.py
git commit -m "feat(facturas): acciones editar/eliminar en la tabla de abonos del cliente"
```

---

### Task 4: Reordenar tabs — Facturas primero y activa

**Files:**
- Modify: `templates/clientes/salidas.html`
- Test: `apps/core/tests_facturas/test_cliente_tab.py`

**Interfaces:**
- Consumes: la carga diferida por AJAX del fragmento de facturas (JS existente en `salidas.html`).
- Produces: la tab **Facturas** aparece primero y activa por defecto; **Productos llevados** segunda. El fragmento de facturas se carga al abrir la página (ya no solo al hacer clic en la tab).

- [ ] **Step 1: Escribir el test que falla**

Agregar a `apps/core/tests_facturas/test_cliente_tab.py` (dentro de `ClienteTabTests`):

```python
    def test_ficha_muestra_facturas_como_primera_tab_activa(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('cliente_salidas', args=[self.cliente.pk]))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        i_fac = html.index('id="tab-facturas-btn"')
        i_prod = html.index('id="tab-productos-btn"')
        self.assertLess(i_fac, i_prod, 'La tab de Facturas debe ir antes que Productos')
        # El botón de Facturas es el activo por defecto.
        fac_btn = html[i_fac - 200:i_fac]
        self.assertIn('active', fac_btn)
```

> Si `cliente_salidas` requiere permisos de inventario además de `ver_facturas`, el test podría dar 403/redirect. Si eso ocurre, agregar en el `setUp`-equivalente del test los permisos necesarios (revisar el decorador de `cliente_salidas` en `apps/core/views/`); el objetivo del assert es el orden de las tabs.

- [ ] **Step 2: Correr y verificar que falla**

Run:
```bash
docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web \
  manage.py test apps.core.tests_facturas.test_cliente_tab --noinput -v 1
```
Expected: FAIL en `test_ficha_muestra_facturas_como_primera_tab_activa` (`i_fac` > `i_prod`).

- [ ] **Step 3: Reordenar los `<li>` de las tabs**

En `templates/clientes/salidas.html`, reemplazar el bloque `<ul class="nav nav-tabs">` (líneas 37-58) por (Facturas primero y `active`, Productos sin `active`):

```html
<ul class="nav nav-tabs mb-3" id="clienteTabs" role="tablist">
  <li class="nav-item" role="presentation">
    <button class="nav-link active" id="tab-facturas-btn" data-bs-toggle="tab"
            data-bs-target="#tab-facturas" type="button" role="tab"
            data-url="{% url 'cliente_facturas_fragment' cliente.pk %}">
      <i class="bi bi-receipt me-1"></i>Facturas
    </button>
  </li>
  <li class="nav-item" role="presentation">
    <button class="nav-link" id="tab-productos-btn" data-bs-toggle="tab"
            data-bs-target="#tab-productos" type="button" role="tab">
      <i class="bi bi-box-seam me-1"></i>Productos llevados
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
```

- [ ] **Step 4: Cambiar qué panel está activo por defecto**

En el mismo archivo:

(a) Panel de productos (línea 60): quitar `show active` →
```html
  <div class="tab-pane fade" id="tab-productos" role="tabpanel">
```

(b) Panel de facturas (línea 270): agregar `show active` →
```html
  <div class="tab-pane fade show active" id="tab-facturas" role="tabpanel">
```

- [ ] **Step 5: Cargar el fragmento de facturas al abrir la página**

En el `<script>` de `salidas.html`, dentro del IIFE, reemplazar el bloque final (líneas 341-344):

```js
  btn.addEventListener('shown.bs.tab', function () {
    if (!cargado) { cargado = true; cargar(''); }
  });
```

por:

```js
  btn.addEventListener('shown.bs.tab', function () {
    if (!cargado) { cargado = true; cargar(''); }
  });

  // Facturas es la tab activa por defecto: cargar el fragmento de una.
  if (btn.classList.contains('active') && !cargado) {
    cargado = true;
    cargar('');
  }
```

- [ ] **Step 6: Correr y verificar que pasa**

Run:
```bash
docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web \
  manage.py test apps.core.tests_facturas.test_cliente_tab --noinput -v 1
```
Expected: PASS.

- [ ] **Step 7: Verificación manual en navegador (runserver)**

Levantar el server (puerto 8002) y abrir la ficha de un cliente:
```bash
docker compose run --rm --no-deps -p 8002:8002 -e DEBUG=True -e ALLOWED_HOSTS=localhost,127.0.0.1 \
  -v "$(pwd)":/app --entrypoint python web manage.py runserver 0.0.0.0:8002
```
Confirmar: (1) la tab **Facturas** aparece primera y activa, y su tabla carga sin hacer clic; (2) en la tabla de abonos, **Editar** abre el form precargado y **Eliminar** pide confirmación y recalcula; (3) editar el monto de un abono ajusta el saldo de las facturas.

- [ ] **Step 8: Commit**

```bash
git add templates/clientes/salidas.html apps/core/tests_facturas/test_cliente_tab.py
git commit -m "feat(clientes): mostrar tab Facturas primero y activa en la ficha del cliente"
```

---

### Task 5: Correr toda la suite de facturas

**Files:** ninguno (verificación de regresión).

- [ ] **Step 1: Correr todos los tests de facturas**

Run:
```bash
docker compose run --rm --no-deps --entrypoint python -v "$(pwd)":/app web \
  manage.py test apps.core.tests_facturas --noinput -v 1
```
Expected: PASS (sin regresiones en `test_hooks_saldo`, `test_payment_service`, `test_pago_modelos`, etc.).

- [ ] **Step 2 (si algo falla): depurar y arreglar** siguiendo superpowers:systematic-debugging antes de dar por terminado.
