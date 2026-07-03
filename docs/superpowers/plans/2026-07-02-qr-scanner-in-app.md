# Escáner QR in-app — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Añadir un escáner QR integrado (PWA) que, desde la navbar abre la ficha del ítem, y dentro de entrada/salida agrega el ítem escaneado a la lista del movimiento.

**Architecture:** Un componente compartido (modal Bootstrap + `qr-scanner.js` sobre la librería `html5-qrcode`) que decodifica el QR, extrae el ID del ítem del path (`/inventario/<id>/`) y lo entrega a un handler configurable. Cada contexto (navbar, entrada, salida) registra su propio handler: navegar, o agregar a la lista.

**Tech Stack:** Django templates, Bootstrap 5.3.3, `html5-qrcode@2.3.8` (CDN jsdelivr), tom-select (ya presente), JS vanilla.

## Global Constraints

- **Permiso navbar:** el botón de escaneo en la navbar se renderiza solo con `perms.core.ver_inventario`. El modal del escáner se incluye para cualquier usuario autenticado.
- **Contexto seguro:** la cámara solo funciona en HTTPS o `localhost` (`window.isSecureContext`). Fuera de eso, mostrar aviso, no intentar iniciar.
- **Librería por CDN:** `https://cdn.jsdelivr.net/npm/html5-qrcode@2.3.8/html5-qrcode.min.js` (global `Html5Qrcode`). No se toca `requirements.txt`.
- **Patrón del path del ítem:** `/inventario/<id>/` (coincide con `item_detalle`, `path('inventario/<int:pk>/', ...)`). El host del QR se ignora; se opera sobre el origen actual.
- **Sin permisos nuevos.** Reutiliza los existentes.
- **Idioma:** textos de UI en español, tono consistente con el resto de la app.
- **No romper flujos existentes:** `agregarFila`, `agregarFilaPT`, `selectedPtPks`, pestañas de salida y validaciones de envío deben seguir funcionando igual.

---

## Estructura de archivos

- **Crear** `static/js/qr-scanner.js` — módulo `window.QRScanner` (API `open`, `close`, `notify`, `flash`, `parseItemId`). Toda la lógica de cámara/decodificación/parseo vive aquí.
- **Crear** `templates/includes/qr_scanner.html` — el modal Bootstrap (contenedor de cámara + zona de avisos). Sin lógica.
- **Modificar** `templates/base.html` — cargar CDN + `qr-scanner.js`, incluir el modal (autenticados), botón de cámara en la navbar (con `ver_inventario`).
- **Modificar** `static/css/app.css` — animación `.qr-flash` para resaltar la fila existente.
- **Modificar** `templates/movimientos/entrada.html` — botón "Escanear" + handler (agrega a la única tabla).
- **Modificar** `templates/movimientos/salida.html` — botón "Escanear" + handler (enruta por pestaña).
- **Crear** `apps/core/tests_inventario/test_qr_scanner_render.py` — test de render/permiso del botón navbar.

---

### Task 1: Componente de escaneo compartido + flujo navbar (ir al ítem)

Entrega: desde cualquier pantalla, el botón de la navbar abre el modal, escanea un QR de ítem y navega a su ficha. Test automatizado del render/permiso del botón.

**Files:**
- Create: `static/js/qr-scanner.js`
- Create: `templates/includes/qr_scanner.html`
- Modify: `templates/base.html`
- Modify: `static/css/app.css`
- Create: `apps/core/tests_inventario/test_qr_scanner_render.py`

**Interfaces:**
- Produces (consumido por Tasks 2 y 3):
  - `window.QRScanner.open({ mode, onItem })` — `mode`: `'single'` | `'continuous'`; `onItem: (itemId: string) => void`. Abre el modal e inicia la cámara.
  - `window.QRScanner.close()` — detiene la cámara y cierra el modal.
  - `window.QRScanner.notify(message: string, type?: 'info'|'success'|'warning'|'danger')` — muestra un aviso inline dentro del modal.
  - `window.QRScanner.flash(el: HTMLElement)` — resalta brevemente un elemento (agrega/quita clase `qr-flash`).
  - `window.QRScanner.parseItemId(text: string) => string | null` — función pura: devuelve el `<id>` si el texto contiene `/inventario/<id>/`, si no `null`.
  - Elementos DOM del modal: `#qrScannerModal`, `#qr-reader`, `#qr-notify`. Botón navbar: `#btnQrScan`.

- [ ] **Step 1: Escribir el test de render/permiso (falla)**

Crear `apps/core/tests_inventario/test_qr_scanner_render.py`:

```python
from django.contrib.auth.models import User, Permission
from django.test import TestCase
from django.urls import reverse


class QrScannerNavbarRenderTests(TestCase):
    def test_boton_visible_con_ver_inventario(self):
        user = User.objects.create_user('scan1', password='x')
        user.user_permissions.add(Permission.objects.get(codename='ver_inventario'))
        self.client.force_login(user)
        resp = self.client.get(reverse('dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="btnQrScan"')

    def test_boton_oculto_sin_ver_inventario(self):
        user = User.objects.create_user('scan2', password='x')
        self.client.force_login(user)
        resp = self.client.get(reverse('dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'id="btnQrScan"')
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run (según memoria del proyecto, tests solo en Docker):
```bash
docker compose run --rm --entrypoint "" web python manage.py test apps.core.tests_inventario.test_qr_scanner_render -v 2
```
Expected: FAIL — `btnQrScan` no existe todavía (AssertionError en `test_boton_visible_con_ver_inventario`).

- [ ] **Step 3: Crear el partial del modal**

Crear `templates/includes/qr_scanner.html`:

```html
{# Modal del escáner QR. Se incluye una vez en base.html para usuarios autenticados. #}
<div class="modal fade" id="qrScannerModal" tabindex="-1" aria-hidden="true">
  <div class="modal-dialog modal-dialog-centered">
    <div class="modal-content">
      <div class="modal-header">
        <h5 class="modal-title"><i class="bi bi-qr-code-scan me-2"></i>Escanear QR</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Cerrar"></button>
      </div>
      <div class="modal-body">
        <div id="qr-reader" style="width:100%"></div>
        <div id="qr-notify" class="mt-2"></div>
        <p class="text-muted small mb-0 mt-2">
          <i class="bi bi-info-circle me-1"></i>Apuntá la cámara al código QR del ítem.
        </p>
      </div>
    </div>
  </div>
</div>
```

- [ ] **Step 4: Crear el módulo del escáner**

Crear `static/js/qr-scanner.js`:

```javascript
/* qr-scanner.js — escáner QR compartido sobre html5-qrcode.
   Expone window.QRScanner. Requiere Html5Qrcode (CDN) y Bootstrap. */
(function () {
  'use strict';

  var reader = null;      // instancia Html5Qrcode
  var running = false;
  var config = { mode: 'single', onItem: null };
  var lastText = '';      // debounce de códigos repetidos
  var lastAt = 0;

  function el(id) { return document.getElementById(id); }

  function parseItemId(text) {
    var path;
    try { path = new URL(text, window.location.origin).pathname; }
    catch (e) { path = String(text); }
    var m = path.match(/\/inventario\/(\d+)\//);
    return m ? m[1] : null;
  }

  function notify(message, type) {
    var box = el('qr-notify');
    if (!box) return;
    type = type || 'info';
    box.innerHTML = '<div class="alert alert-' + type + ' py-2 mb-0">' + message + '</div>';
    if (type === 'success' || type === 'info') {
      setTimeout(function () {
        if (box.firstChild) box.innerHTML = '';
      }, 2500);
    }
  }

  function flash(node) {
    if (!node) return;
    node.classList.remove('qr-flash');
    void node.offsetWidth;           // reinicia la animación
    node.classList.add('qr-flash');
    setTimeout(function () { node.classList.remove('qr-flash'); }, 1400);
  }

  function onDecode(decodedText) {
    var now = Date.now();
    if (decodedText === lastText && now - lastAt < 1500) return; // mismo código en cuadro
    lastText = decodedText;
    lastAt = now;

    var id = parseItemId(decodedText);
    if (!id) { notify('QR no reconocido.', 'warning'); return; }
    if (typeof config.onItem === 'function') config.onItem(id);
    if (config.mode === 'single') stop();  // navbar: detener tras un escaneo válido
  }

  function start() {
    var target = el('qr-reader');
    if (!target) return;
    if (!window.isSecureContext) {
      notify('El escáner requiere HTTPS.', 'danger');
      return;
    }
    if (typeof Html5Qrcode === 'undefined') {
      notify('No se pudo cargar el lector de QR.', 'danger');
      return;
    }
    reader = new Html5Qrcode('qr-reader');
    reader.start(
      { facingMode: 'environment' },
      { fps: 10, qrbox: 250 },
      onDecode,
      function () { /* fallo por cuadro: ignorar */ }
    ).then(function () { running = true; })
     .catch(function () {
       notify('No se pudo acceder a la cámara. Permití el acceso en tu navegador.', 'danger');
     });
  }

  function stop() {
    if (reader && running) {
      running = false;
      reader.stop().then(function () { reader.clear(); reader = null; })
                   .catch(function () { reader = null; });
    }
  }

  function open(opts) {
    config.mode = (opts && opts.mode) || 'single';
    config.onItem = (opts && opts.onItem) || null;
    lastText = ''; lastAt = 0;
    var box = el('qr-notify'); if (box) box.innerHTML = '';
    var modalEl = el('qrScannerModal');
    if (!modalEl) return;
    bootstrap.Modal.getOrCreateInstance(modalEl).show();
  }

  function close() {
    var modalEl = el('qrScannerModal');
    if (modalEl) bootstrap.Modal.getOrCreateInstance(modalEl).hide();
  }

  // Ciclo de vida ligado al modal
  document.addEventListener('DOMContentLoaded', function () {
    var modalEl = el('qrScannerModal');
    if (modalEl) {
      modalEl.addEventListener('shown.bs.modal', start);
      modalEl.addEventListener('hidden.bs.modal', stop);
    }
    var btn = el('btnQrScan');
    if (btn) {
      btn.addEventListener('click', function () {
        open({ mode: 'single', onItem: function (id) {
          window.location.href = '/inventario/' + id + '/';
        }});
      });
    }
  });

  window.QRScanner = {
    open: open, close: close, notify: notify, flash: flash, parseItemId: parseItemId,
  };
})();
```

- [ ] **Step 5: Añadir la animación de resaltado en app.css**

Agregar al final de `static/css/app.css`:

```css
/* Resaltado temporal de una fila existente al escanear un duplicado */
@keyframes qr-flash-kf {
  0%   { background-color: rgba(255, 193, 7, .55); }
  100% { background-color: transparent; }
}
.qr-flash { animation: qr-flash-kf 1.4s ease-out; }
```

- [ ] **Step 6: Cablear base.html — CDN, módulo, modal y botón navbar**

En `templates/base.html`:

6a. Botón de la navbar. Dentro del bloque `{% if user.is_authenticated %}` del área derecha de la navbar (junto al toggle de tema, antes del nombre de usuario), agregar:

```html
{% if perms.core.ver_inventario %}
<button type="button" id="btnQrScan"
        class="btn btn-sm btn-outline-light"
        title="Escanear QR" aria-label="Escanear QR">
  <i class="bi bi-qr-code-scan"></i>
</button>
{% endif %}
```

6b. Incluir el modal para usuarios autenticados. Justo antes del cierre `{% endif %}` del bloque autenticado que contiene el bottom-nav (o inmediatamente después de `</nav>` del bottom-nav, aún dentro de `{% if user.is_authenticated %}`), agregar:

```html
{% include "includes/qr_scanner.html" %}
```

6c. Cargar librería y módulo. Después del `<script>` de tom-select y **antes** de `{% block extra_js %}{% endblock %}`, agregar:

```html
{% if user.is_authenticated %}
<script src="https://cdn.jsdelivr.net/npm/html5-qrcode@2.3.8/html5-qrcode.min.js"></script>
<script src="{% static 'js/qr-scanner.js' %}"></script>
{% endif %}
```

(Verificar que `{% load static %}` ya esté en base.html; se usa para otros assets, así que sí.)

- [ ] **Step 7: Correr el test y verificar que pasa**

Run:
```bash
docker compose run --rm --entrypoint "" web python manage.py test apps.core.tests_inventario.test_qr_scanner_render -v 2
```
Expected: PASS (2 tests OK).

- [ ] **Step 8: Verificación manual (cámara)**

Requiere HTTPS o `localhost` y un dispositivo con cámara. En un navegador:
1. Login con usuario que tenga `ver_inventario`.
2. Clic en el icono QR de la navbar → se abre el modal y pide permiso de cámara.
3. Apuntar a un QR de ítem (generado en la ficha) → navega a `/inventario/<id>/`.
4. Cerrar el modal sin escanear → la cámara se apaga (luz del dispositivo).

Verificar `parseItemId` en la consola del navegador:
```javascript
QRScanner.parseItemId('https://ejemplo.com/inventario/42/');  // "42"
QRScanner.parseItemId('/inventario/7/');                       // "7"
QRScanner.parseItemId('https://otro-host/inventario/9/');      // "9" (ignora host)
QRScanner.parseItemId('https://ejemplo.com/facturas/3/');      // null
QRScanner.parseItemId('texto cualquiera');                     // null
```

- [ ] **Step 9: Commit**

```bash
git add static/js/qr-scanner.js templates/includes/qr_scanner.html templates/base.html static/css/app.css apps/core/tests_inventario/test_qr_scanner_render.py
git commit -m "feat(scanner): escáner QR compartido + acceso navbar (ir al ítem)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Escaneo en Entrada (agregar a la lista)

Entrega: en la pantalla de entrada, un botón "Escanear" abre el escáner en modo continuo; cada QR agrega el ítem a la tabla, evita duplicados (avisa + resalta) y avisa si el ítem no está en el catálogo de la entrada.

**Files:**
- Modify: `templates/movimientos/entrada.html`

**Interfaces:**
- Consumes (de Task 1): `QRScanner.open({mode:'continuous', onItem})`, `QRScanner.notify`, `QRScanner.flash`.
- Consumes (existente en entrada.html): `agregarFila(preItemId, preCant)`, `ITEMS_DATA` (array de `{pk, nombre, codigo, unidad}`), `tbody` (`#cuerpo-tabla`), filas `.fila-item` con `select[name="item[]"]`.

- [ ] **Step 1: Añadir el botón "Escanear" junto a "Agregar ítem"**

En `templates/movimientos/entrada.html`, en el `card-header` de la tabla de ítems (donde está `#btn-agregar`), envolver los botones y agregar el de escanear:

```html
<div class="d-flex gap-2">
  <button type="button" id="btn-escanear" class="btn btn-outline-success btn-sm">
    <i class="bi bi-qr-code-scan me-1"></i>Escanear
  </button>
  <button type="button" id="btn-agregar" class="btn btn-success btn-sm">
    <i class="bi bi-plus-lg me-1"></i>Agregar ítem
  </button>
</div>
```

(Reemplaza el `<button id="btn-agregar">` suelto por este contenedor; mantené el mismo `id="btn-agregar"` para no romper su listener existente.)

- [ ] **Step 2: Añadir el handler de escaneo al final del bloque de script**

En `templates/movimientos/entrada.html`, dentro de `{% block extra_js %}`, después del bloque de inicialización (tras las líneas `if (FILAS_PREVIAS.length > 0) {...} else {...}`), agregar:

```javascript
// ── Escaneo QR: agrega ítems a la tabla ───────────────────────────────────────
const btnEscanear = document.getElementById('btn-escanear');
if (btnEscanear && window.QRScanner) {
  btnEscanear.addEventListener('click', () => {
    QRScanner.open({ mode: 'continuous', onItem: (id) => {
      const it = ITEMS_DATA.find(x => String(x.pk) === String(id));
      if (!it) { QRScanner.notify('Ítem no disponible en esta entrada.', 'warning'); return; }

      const filas = Array.from(tbody.querySelectorAll('.fila-item'));
      const existente = filas.find(tr => {
        const sel = tr.querySelector('select[name="item[]"]');
        return sel && String(sel.value) === String(id);
      });
      if (existente) {
        QRScanner.notify(`"${it.nombre}" ya está en la lista.`, 'info');
        QRScanner.flash(existente);
        return;
      }

      agregarFila(String(id));
      QRScanner.notify(`Agregado: ${it.nombre}`, 'success');
    }});
  });
}
```

- [ ] **Step 3: Verificación manual**

Requiere cámara y HTTPS/localhost:
1. Ir a Nueva Entrada.
2. Clic en "Escanear" → modal en modo continuo.
3. Escanear un QR de ítem → aparece una fila con ese ítem; el modal sigue abierto.
4. Escanear el mismo QR otra vez → aviso "ya está en la lista" + la fila existente parpadea; no se duplica.
5. Escanear un QR válido de la app pero de un ítem que no está en `ITEMS_DATA` (si aplica) → aviso "Ítem no disponible en esta entrada."
6. Escanear varios ítems distintos seguidos → se agregan todos sin cerrar el modal.
7. Cerrar el modal → la cámara se apaga; las filas quedan; completar cantidades y registrar.

- [ ] **Step 4: Commit**

```bash
git add templates/movimientos/entrada.html
git commit -m "feat(scanner): escanear QR para agregar ítems en Entrada

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Escaneo en Salida (agregar a la lista, enrutando por pestaña)

Entrega: en la pantalla de salida, un botón "Escanear" abre el escáner en modo continuo; cada QR localiza el ítem en su catálogo, activa la pestaña correspondiente, agrega la fila, evita duplicados (avisa + resalta) y avisa si el ítem no pertenece a ninguna categoría de la salida.

**Files:**
- Modify: `templates/movimientos/salida.html`

**Interfaces:**
- Consumes (de Task 1): `QRScanner.open({mode:'continuous', onItem})`, `QRScanner.notify`, `QRScanner.flash`.
- Consumes (existente en salida.html): `ITEMS_PRODUCTO`, `ITEMS_REPUESTO`, `ITEMS_CONSUMIBLE`, `ITEMS_OTROS` (arrays `{pk, nombre, codigo, unidad}`), `agregarFilaPT({item_id})`, `agregarFila(panel, {item_id})`, `selectedPtPks` (Set de pks de producto terminado), contenedores `#contenedor-pt` (filas `.fila-pt[data-item-pk]`) y `#contenedor-{rep|con|otros}` (filas `.fila-dinamica` con `select[name="item[]"]`), pestañas `#tab-pt|#tab-rep|#tab-con|#tab-otros` (Bootstrap tabs), y `bootstrap.Tab`.

- [ ] **Step 1: Añadir el botón "Escanear" (visible en todas las pestañas)**

En `templates/movimientos/salida.html`, justo después del `<ul class="nav nav-tabs ...">...</ul>` (cierre de la lista de pestañas, línea ~65) y antes de `<div class="tab-content">`, agregar una barra de acción:

```html
<div class="mb-3">
  <button type="button" id="btn-escanear" class="btn btn-outline-danger btn-sm">
    <i class="bi bi-qr-code-scan me-1"></i>Escanear
  </button>
</div>
```

- [ ] **Step 2: Añadir el handler de escaneo con enrutado por pestaña**

En `templates/movimientos/salida.html`, dentro de `{% block extra_js %}`, al final del script (después del bloque de inicialización que restaura filas previas), agregar:

```javascript
// ── Escaneo QR: agrega ítems enrutando a la pestaña correcta ───────────────────
function handleScanSalida(id) {
  const mapa = [
    { arr: ITEMS_PRODUCTO,   tabId: 'tab-pt',    panel: 'pt'    },
    { arr: ITEMS_REPUESTO,   tabId: 'tab-rep',   panel: 'rep'   },
    { arr: ITEMS_CONSUMIBLE, tabId: 'tab-con',   panel: 'con'   },
    { arr: ITEMS_OTROS,      tabId: 'tab-otros', panel: 'otros' },
  ];
  const grupo = mapa.find(m => m.arr.some(x => String(x.pk) === String(id)));
  if (!grupo) { QRScanner.notify('Ítem no disponible para salida.', 'warning'); return; }
  const it = grupo.arr.find(x => String(x.pk) === String(id));

  // Activar la pestaña de la categoría del ítem
  bootstrap.Tab.getOrCreateInstance(document.getElementById(grupo.tabId)).show();

  if (grupo.panel === 'pt') {
    if (selectedPtPks.has(String(id))) {
      QRScanner.notify(`"${it.nombre}" ya está en la lista.`, 'info');
      QRScanner.flash(document.querySelector(`#contenedor-pt .fila-pt[data-item-pk="${id}"]`));
      return;
    }
    agregarFilaPT({ item_id: String(id) });
  } else {
    const cont = document.getElementById(`contenedor-${grupo.panel}`);
    const filas = Array.from(cont.querySelectorAll('.fila-dinamica'));
    const existente = filas.find(w => {
      const sel = w.querySelector('select[name="item[]"]');
      return sel && String(sel.value) === String(id);
    });
    if (existente) {
      QRScanner.notify(`"${it.nombre}" ya está en la lista.`, 'info');
      QRScanner.flash(existente);
      return;
    }
    agregarFila(grupo.panel, { item_id: String(id) });
  }
  QRScanner.notify(`Agregado: ${it.nombre}`, 'success');
}

const btnEscanear = document.getElementById('btn-escanear');
if (btnEscanear && window.QRScanner) {
  btnEscanear.addEventListener('click', () => {
    QRScanner.open({ mode: 'continuous', onItem: handleScanSalida });
  });
}
```

- [ ] **Step 3: Verificación manual**

Requiere cámara y HTTPS/localhost:
1. Ir a Nueva Salida.
2. Clic en "Escanear" → modal en modo continuo.
3. Escanear un QR de un **producto terminado** → se activa la pestaña "Producto Terminado" y se agrega la fila; el modal sigue abierto.
4. Escanear un QR de un **repuesto** → se activa la pestaña "Repuestos" y se agrega la fila.
5. Repetir con **consumible** y **otros**.
6. Escanear un ítem ya agregado → aviso "ya está en la lista" + la fila parpadea; no se duplica (probar tanto en PT como en un panel dinámico).
7. Escanear un QR válido pero de un ítem que no está en ninguna categoría de salida → aviso "Ítem no disponible para salida."
8. Cerrar el modal → cámara apagada; completar y registrar la salida.

- [ ] **Step 4: Commit**

```bash
git add templates/movimientos/salida.html
git commit -m "feat(scanner): escanear QR para agregar ítems en Salida (enruta por pestaña)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Notas de verificación global

- Correr toda la suite tras Task 1 para asegurar que no se rompió nada de render:
  ```bash
  docker compose run --rm --entrypoint "" web python manage.py test apps.core -v 1
  ```
- La lógica JS de Tasks 2 y 3 no tiene arnés de pruebas automatizadas en este repo (no hay tests JS); se cubre con las verificaciones manuales descritas. `parseItemId` (Task 1) es pura y se valida en consola.
- **Autorización de commits:** según la preferencia del usuario, pedir autorización antes de cada `git commit`.
