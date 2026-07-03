# Toggle del sidebar en desktop

**Fecha:** 2026-07-03
**Estado:** Aprobado (diseño)

## Problema

En desktop (≥768px) el sidebar de navegación es fijo (`position: fixed`, 220px) y
`.main-content` tiene `margin-left: 220px`. En páginas anchas —sobre todo la de
**facturas**, con su tabla— el contenido no cabe y hay que hacer **scroll horizontal** para
ver los botones de acción. No hay forma de ocultar el sidebar en desktop (la hamburguesa
actual es solo móvil, `d-md-none`, y abre el offcanvas).

## Objetivo

Permitir **ocultar/mostrar el sidebar en desktop** con una hamburguesa, de modo que el
contenido use todo el ancho. La preferencia se **recuerda** entre páginas.

## Decisiones tomadas (brainstorming)

- **Ocultar por completo** (no riel de íconos): el sidebar desaparece y `.main-content`
  pasa a `margin-left: 0`, ancho completo. La hamburguesa lo vuelve a mostrar.
- **Persistente:** el estado (oculto/visible) se guarda en `localStorage` y se aplica en
  cada carga (la app recarga página completa al navegar).
- Solo afecta **desktop** (≥768px). En móvil no cambia nada (el sidebar ya está oculto y se
  usa el offcanvas con su propia hamburguesa).

## Contexto del código actual

- `templates/base.html`: navbar con hamburguesa móvil (`d-md-none` → abre `#menuMobile`),
  toggle de tema (`#themeToggle`), sidebar desktop (`<aside class="sidebar">`) y
  `.main-content`. En el `<head>` hay un `<script>` que aplica el tema **antes** de pintar
  (para evitar flash); al final del `<body>` hay un `<script>` que cablea `#themeToggle` y
  registra el service worker.
- `static/css/app.css`: el sidebar y el margen viven en el bloque
  `@media (min-width: 768px)` (`.sidebar { ... }`, `.main-content { margin-left: 220px; }`).

## Diseño

### 1. Botón hamburguesa de desktop

En la navbar de `base.html`, un `<button id="sidebarToggle">` con icono `bi-list`, visible
solo en desktop (`d-none d-md-inline-flex`), con el mismo estilo que los otros botones de la
navbar (`btn btn-sm btn-outline-light`). Atributos de accesibilidad: `aria-label="Mostrar u
ocultar menú"` y `aria-expanded` (refleja si el sidebar está visible). Se coloca a la
izquierda de la marca (donde se espera una hamburguesa), junto a —pero independiente de— la
hamburguesa móvil existente, que no se toca.

### 2. Mecanismo: clase en `<html>` + localStorage

- La clase `sidebar-hidden` en `<html>` (`document.documentElement`) indica "sidebar
  oculto".
- La preferencia se guarda en `localStorage` con la clave `app-sidebar-hidden`
  (`'1'` = oculto; ausente/otro = visible).
- Se usa `<html>` (no `<body>`) para poder aplicar el estado desde el `<head>` antes de que
  exista `<body>`, evitando el flash.

### 3. CSS (solo desktop)

Dentro del bloque `@media (min-width: 768px)` de `app.css`:

```css
html.sidebar-hidden .sidebar { display: none; }
html.sidebar-hidden .main-content { margin-left: 0; }
```

Y una transición suave del margen en `.main-content`:

```css
.main-content { transition: margin-left .2s ease; }
```

En móvil (<768px) estas reglas no aplican (están dentro del media query), así que el
comportamiento móvil no cambia.

### 4. Sin parpadeo (aplicación temprana)

En el `<script>` del `<head>` que ya aplica el tema, agregar: si
`localStorage.getItem('app-sidebar-hidden') === '1'`, hacer
`document.documentElement.classList.add('sidebar-hidden')`. Así el estado se aplica antes
de pintar y no se ve el sidebar aparecer y desaparecer.

### 5. Cableado del botón

En el `<script>` del final del `<body>` (junto al del `#themeToggle`), cablear
`#sidebarToggle`: al hacer clic, alterna `sidebar-hidden` en `<html>`, actualiza
`localStorage` y el atributo `aria-expanded` del botón. Inicializar `aria-expanded` según el
estado actual al cargar.

## Componentes a modificar

- `templates/base.html` — botón `#sidebarToggle` en la navbar; aplicación temprana en el
  script del `<head>`; cableado en el script del `<body>`.
- `static/css/app.css` — reglas `html.sidebar-hidden ...` dentro del media query desktop y
  la transición de `.main-content`.

## Pruebas

- **Render:** `base.html` incluye `id="sidebarToggle"` para un usuario autenticado (test
  Django con `assertContains` sobre una página simple como `dashboard`).
- **Manual (visual, desktop ≥768px):** al hacer clic se oculta el sidebar y el contenido
  ocupa todo el ancho; al recargar/navegar el estado se mantiene; en la página de facturas
  desaparece el scroll horizontal; en móvil no hay cambios.

## Fuera de alcance (YAGNI)

- Riel de íconos (sidebar angosto en vez de oculto).
- Animar el ancho del sidebar (se oculta con `display: none`).
- Recordar la preferencia por-usuario en el servidor (basta `localStorage`).
- Cambiar la hamburguesa/offcanvas móvil.
