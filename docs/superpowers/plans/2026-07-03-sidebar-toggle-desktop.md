# Toggle del sidebar en desktop — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agregar una hamburguesa en desktop que oculte/muestre el sidebar (persistente en localStorage), para que el contenido use todo el ancho y desaparezca el scroll horizontal en páginas como facturas.

**Architecture:** Una clase `sidebar-hidden` en `<html>` controla la visibilidad vía CSS (solo en el media query desktop). El estado se guarda en `localStorage['app-sidebar-hidden']`, se aplica temprano en el script del `<head>` (sin flash) y se alterna con un botón `#sidebarToggle` en la navbar cableado en el script del `<body>`.

**Tech Stack:** Django templates (`base.html`), CSS (`app.css`), JS vanilla, Bootstrap 5, bootstrap-icons.

## Global Constraints

- **Solo desktop (≥768px):** las reglas de ocultamiento viven dentro de `@media (min-width: 768px)`; en móvil no cambia nada.
- **Ocultar por completo:** `.sidebar { display: none }` + `.main-content { margin-left: 0 }` cuando `html.sidebar-hidden`.
- **Persistencia:** `localStorage` clave `app-sidebar-hidden`, valor `'1'` = oculto (ausente/otro = visible).
- **Sin flash:** aplicar la clase desde el script del `<head>` antes de pintar, sobre `document.documentElement` (`<html>`).
- **No tocar** la hamburguesa/offcanvas móvil (`d-md-none` → `#menuMobile`) ni el toggle de tema.
- **Botón desktop:** `id="sidebarToggle"`, icono `bi-list`, visible solo en desktop (`d-none d-md-inline-flex`), estilo `btn btn-sm btn-outline-light`, con `aria-label` y `aria-expanded`.
- **Tests solo en Docker, con volumen montado y `--noinput`:**
  `docker compose run --rm --no-deps -v "$(pwd)":/app --entrypoint python web manage.py test <ruta> -v 2 --noinput`

---

## Estructura de archivos

- **Modificar** `templates/base.html` — botón `#sidebarToggle` en la navbar; aplicación temprana en el `<script>` del `<head>`; cableado en el `<script>` del final del `<body>`.
- **Modificar** `static/css/app.css` — reglas `html.sidebar-hidden ...` dentro del media query desktop + transición de `.main-content`.
- **Crear** `apps/core/tests_inventario/test_sidebar_toggle_render.py` — test de render del botón (base.html se renderiza vía `dashboard`).

---

### Task 1: Toggle del sidebar en desktop (botón + CSS + persistencia)

Entrega: en desktop, el botón hamburguesa oculta/muestra el sidebar; el contenido se expande a todo el ancho; el estado persiste entre páginas sin parpadeo. Test de render del botón.

**Files:**
- Modify: `templates/base.html`
- Modify: `static/css/app.css`
- Test: `apps/core/tests_inventario/test_sidebar_toggle_render.py`

**Interfaces:**
- Produces (contrato interno del front):
  - Clase `sidebar-hidden` en `<html>`.
  - `localStorage['app-sidebar-hidden']` = `'1'` (oculto) / ausente (visible).
  - Botón `#sidebarToggle` en la navbar.

- [ ] **Step 1: Escribir el test de render (falla)**

Crear `apps/core/tests_inventario/test_sidebar_toggle_render.py`:

```python
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


class SidebarToggleRenderTests(TestCase):
    def test_boton_desktop_presente_para_autenticado(self):
        user = User.objects.create_user('sb', password='x')
        self.client.force_login(user)
        resp = self.client.get(reverse('dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="sidebarToggle"')
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run:
```bash
docker compose run --rm --no-deps -v "$(pwd)":/app --entrypoint python web manage.py test apps.core.tests_inventario.test_sidebar_toggle_render -v 2 --noinput
```
Expected: FAIL — no aparece `id="sidebarToggle"`.

- [ ] **Step 3: Agregar las reglas CSS en app.css**

En `static/css/app.css`, dentro del bloque `@media (min-width: 768px)` que contiene `.sidebar` y `.main-content` (donde está `.main-content { margin-left: 220px; }`), dejar ese bloque así (agregar la transición a `.main-content` y las dos reglas `html.sidebar-hidden`):

```css
@media (min-width: 768px) {
  .sidebar {
    display: block; position: fixed; top: 56px; left: 0; width: 220px;
    height: calc(100vh - 56px); overflow-y: auto; background: var(--app-sidebar-bg);
    border-right: 1px solid var(--app-sidebar-border); padding: 1rem 0; z-index: 100;
  }
  .main-content { margin-left: 220px; transition: margin-left .2s ease; }
  body { padding-bottom: 0; }

  /* Sidebar oculto por el toggle de desktop */
  html.sidebar-hidden .sidebar { display: none; }
  html.sidebar-hidden .main-content { margin-left: 0; }
}
```

(Es el mismo bloque existente; solo se añade `transition: margin-left .2s ease;` a `.main-content` y las dos reglas nuevas `html.sidebar-hidden ...`.)

- [ ] **Step 4: Aplicar el estado temprano en el script del `<head>`**

En `templates/base.html`, reemplazar el `<script>` del `<head>` que aplica el tema (el que empieza con `// Tema claro/oscuro: aplicar ANTES del render`, líneas ~8-18) por esta versión que además aplica `sidebar-hidden`:

```html
  <!-- Tema y estado del sidebar: aplicar ANTES del render para evitar el flash -->
  <script>
    (function () {
      try {
        var stored = localStorage.getItem('app-theme');
        var theme = stored || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
        document.documentElement.setAttribute('data-bs-theme', theme);
      } catch (e) {
        document.documentElement.setAttribute('data-bs-theme', 'light');
      }
      try {
        if (localStorage.getItem('app-sidebar-hidden') === '1') {
          document.documentElement.classList.add('sidebar-hidden');
        }
      } catch (e) {}
    })();
  </script>
```

- [ ] **Step 5: Agregar el botón hamburguesa de desktop en la navbar**

En `templates/base.html`, la navbar tiene la hamburguesa móvil dentro de `{% if user.is_authenticated %}`:

```html
    {% if user.is_authenticated %}
    <!-- Hamburger (mobile only) -->
    <button class="btn btn-outline-light btn-sm d-md-none me-2 px-2"
            type="button"
            data-bs-toggle="offcanvas"
            data-bs-target="#menuMobile"
            aria-controls="menuMobile"
            aria-label="Abrir menú">
      <i class="bi bi-list fs-5"></i>
    </button>
    {% endif %}
```

Inmediatamente **después** del `{% endif %}` de ese bloque, agregar el botón de desktop:

```html
    {% if user.is_authenticated %}
    <!-- Toggle del sidebar (solo desktop) -->
    <button class="btn btn-outline-light btn-sm d-none d-md-inline-flex align-items-center me-2 px-2"
            type="button"
            id="sidebarToggle"
            aria-label="Mostrar u ocultar menú"
            aria-expanded="true">
      <i class="bi bi-list fs-5"></i>
    </button>
    {% endif %}
```

- [ ] **Step 6: Cablear el botón en el script del final del `<body>`**

En `templates/base.html`, en el `<script>` del final del `<body>` (el que contiene el IIFE `// Toggle de tema claro/oscuro` y el registro del service worker), agregar un IIFE nuevo **después** del IIFE del tema y **antes** del bloque `if ('serviceWorker' in navigator)`:

```html
  // ─── Toggle del sidebar (desktop) ──────────────────────────────────────────
  (function () {
    var btn = document.getElementById('sidebarToggle');
    if (!btn) return;
    var root = document.documentElement;
    function sync() {
      btn.setAttribute('aria-expanded', root.classList.contains('sidebar-hidden') ? 'false' : 'true');
    }
    sync();
    btn.addEventListener('click', function () {
      var oculto = root.classList.toggle('sidebar-hidden');
      try { localStorage.setItem('app-sidebar-hidden', oculto ? '1' : '0'); } catch (e) {}
      sync();
    });
  })();
```

- [ ] **Step 7: Correr el test de render y verificar que pasa**

Run:
```bash
docker compose run --rm --no-deps -v "$(pwd)":/app --entrypoint python web manage.py test apps.core.tests_inventario.test_sidebar_toggle_render -v 2 --noinput
```
Expected: PASS (1 test OK).

- [ ] **Step 8: Verificación manual (desktop ≥768px)**

Con el container en el puerto 8000 (o reconstruyéndolo si es necesario, ya que el servicio no monta el código):
1. Iniciar sesión y abrir cualquier página en una ventana ancha (≥768px).
2. Clic en la hamburguesa de la navbar → el sidebar se oculta y el contenido ocupa todo el ancho, con transición suave.
3. Navegar a otra página / recargar → el sidebar sigue oculto (persistencia, sin parpadeo).
4. Clic de nuevo → el sidebar vuelve a aparecer; recargar → sigue visible.
5. Abrir la lista de **facturas** con el sidebar oculto → ya no hay scroll horizontal para ver los botones de acción.
6. En una ventana angosta (<768px) → nada cambia: la hamburguesa de desktop no se ve y el offcanvas móvil funciona igual.

- [ ] **Step 9: Commit**

```bash
git add templates/base.html static/css/app.css apps/core/tests_inventario/test_sidebar_toggle_render.py
git commit -m "feat(ui): ocultar/mostrar el sidebar en desktop con hamburguesa (persistente)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Notas de verificación global

- El único test automatizado es el de render (el comportamiento visual/persistencia se verifica manualmente; no hay arnés de JS en el repo).
- Correr la suite de core para asegurar que no se rompió ningún render:
  ```bash
  docker compose run --rm --no-deps -v "$(pwd)":/app --entrypoint python web manage.py test apps.core -v 1 --noinput
  ```
- Sin migraciones ni dependencias nuevas.
- Para ver el cambio en el container del puerto 8000 (el servicio no monta el código fuente): `APP_PORT=8000 docker compose up -d --build web`.
- **Autorización de commits:** pedir autorización antes del `git commit` según la preferencia del usuario.
