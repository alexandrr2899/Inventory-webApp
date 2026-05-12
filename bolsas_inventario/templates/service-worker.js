/* ═══════════════════════════════════════════════════════════════════════
   Service Worker — Inventario Bolsas
   Estrategia:
   - Archivos estáticos  → Cache First  (arranque rápido)
   - Páginas HTML/Django → Network First (datos frescos), fallback en cache
   - CDN externo         → Cache First  (Bootstrap, icons)
   ═══════════════════════════════════════════════════════════════════════ */

const CACHE_APP    = 'bolsas-app-v1';
const CACHE_STATIC = 'bolsas-static-v1';
const CACHE_CDN    = 'bolsas-cdn-v1';

// Assets CDN que se cachean al instalar
const PRECACHE_CDN = [
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js',
  'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css',
];

// ─── INSTALL ──────────────────────────────────────────────────────────────────
self.addEventListener('install', event => {
  event.waitUntil(
    Promise.allSettled([
      // Pre-cachear CDN
      caches.open(CACHE_CDN).then(cache =>
        Promise.allSettled(PRECACHE_CDN.map(url =>
          cache.add(url).catch(() => null)
        ))
      ),
    ])
  );
  self.skipWaiting();
});

// ─── ACTIVATE ─────────────────────────────────────────────────────────────────
self.addEventListener('activate', event => {
  const VALID_CACHES = [CACHE_APP, CACHE_STATIC, CACHE_CDN];
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys
          .filter(k => !VALID_CACHES.includes(k))
          .map(k => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

// ─── FETCH ────────────────────────────────────────────────────────────────────
self.addEventListener('fetch', event => {
  const req = event.request;
  const url = new URL(req.url);

  // Solo interceptar GET (nunca cachear POST/formularios Django)
  if (req.method !== 'GET') return;

  // ── CDN externo: Cache First ─────────────────────────────────────────
  if (url.hostname.includes('jsdelivr.net') || url.hostname.includes('bootstrapcdn.com')) {
    event.respondWith(
      caches.open(CACHE_CDN).then(cache =>
        cache.match(req).then(cached => {
          if (cached) return cached;
          return fetch(req).then(res => {
            if (res.ok) cache.put(req, res.clone());
            return res;
          }).catch(() => cached);
        })
      )
    );
    return;
  }

  // Solo manejar requests a este mismo origen
  if (url.origin !== self.location.origin) return;

  // ── Archivos estáticos (/static/...): Cache First ────────────────────
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.open(CACHE_STATIC).then(cache =>
        cache.match(req).then(cached => {
          if (cached) return cached;
          return fetch(req).then(res => {
            if (res.ok) cache.put(req, res.clone());
            return res;
          }).catch(() => cached);
        })
      )
    );
    return;
  }

  // ── Páginas Django autenticadas: siempre red, sin cache de HTML ──────
  event.respondWith(
    fetch(req, { credentials: 'include' })
      .catch(() => offlinePage())
  );
});

// ─── PÁGINA OFFLINE ───────────────────────────────────────────────────────────
function offlinePage() {
  return new Response(
    `<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Sin conexión – Inventario Bolsas</title>
  <style>
    *{box-sizing:border-box;margin:0;padding:0}
    body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
      background:#f4f6f9;display:flex;align-items:center;justify-content:center;
      min-height:100vh;padding:2rem;text-align:center}
    .card{background:#fff;border-radius:16px;padding:2.5rem;max-width:360px;
      box-shadow:0 4px 24px rgba(0,0,0,.1)}
    .icon{font-size:4rem;margin-bottom:1rem}
    h1{color:#1a1a2e;font-size:1.4rem;margin-bottom:.75rem}
    p{color:#6c757d;font-size:.95rem;line-height:1.5;margin-bottom:1.5rem}
    button{background:#0d6efd;color:#fff;border:none;border-radius:10px;
      padding:.75rem 2rem;font-size:1rem;cursor:pointer;width:100%}
    button:active{opacity:.85}
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">📦</div>
    <h1>Sin conexión</h1>
    <p>No se pudo cargar la página.<br>
       Verificá tu conexión a la red o al servidor.</p>
    <button onclick="location.reload()">Reintentar</button>
  </div>
</body>
</html>`,
    {
      status: 200,
      headers: { 'Content-Type': 'text/html; charset=utf-8' },
    }
  );
}
