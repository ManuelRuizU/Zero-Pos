const CACHE_NAME = 'zeropos-v26';
const URLS_TO_CACHE = [
  '/static/pos.html',
  '/static/admin.html',
  '/static/pedidos.html',
  '/static/cliente.html',
  '/static/cocina.html',
  '/static/login.html',
  '/static/inventario.html',
  '/static/meson.html',
  '/static/onboarding.html',
  '/static/js/vendor/qrcode.min.js',
  /* CSS por página */
  '/static/css/pos.css',
  '/static/css/admin.css',
  '/static/css/inventario.css',
  '/static/css/login.css',
  '/static/css/cliente.css',
  '/static/css/meson.css',
  '/static/css/onboarding.css',
  '/static/css/pedidos.css',
  '/static/css/cocina.css',
  /* JS por página */
  '/static/js/pos.js',
  '/static/js/admin.js',
  '/static/js/inventario.js',
  '/static/js/login.js',
  '/static/js/cliente.js',
  '/static/js/meson.js',
  '/static/js/onboarding.js',
  '/static/js/pedidos.js',
  '/static/js/cocina.js',
  '/static/manifest.json',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
];

self.addEventListener('install', event => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(URLS_TO_CACHE))
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  // API: NO interceptar — dejar pasar al browser
  if (url.pathname.startsWith('/api/')) {
    return;
  }
  // Externos: NO interceptar
  if (url.origin !== self.location.origin) {
    return;
  }
  // Network-first con fallback a caché.
  // Safari lanza "Response served by service worker has redirections" si el SW
  // devuelve una respuesta redirigida (302 de Flask → login). Con {redirect:'follow'}
  // el fetch sigue la redirección y response.redirected queda true; en ese caso
  // devolvemos la respuesta sin cachear para que Safari no la rechace.
  event.respondWith(
    fetch(event.request, {redirect: 'follow'})
      .then(response => {
        // NO cachear redirects — Safari los rechaza como respuesta SW
        if (response.redirected || response.type === 'opaqueredirect') {
          return response;
        }
        // Solo cachear respuestas 200 de archivos estáticos
        if (response.status === 200 && url.pathname.startsWith('/static/')) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
        }
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});
