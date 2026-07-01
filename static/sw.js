const CACHE_NAME = 'zeropos-v37';
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

  // Navegaciones HTML (mode='navigate'): NO interceptar.
  // Safari lanza "Response served by service worker has redirections" si el SW
  // devuelve una respuesta que siguió un 302 de Flask. La solución correcta es
  // dejar que el browser maneje las navegaciones de forma nativa — incluyendo
  // cualquier redirect a login. Los sub-recursos (CSS/JS) se cachean por separado.
  if (event.request.mode === 'navigate') {
    return;
  }

  // API: NO interceptar
  if (url.pathname.startsWith('/api/')) {
    return;
  }

  // Externos: NO interceptar
  if (url.origin !== self.location.origin) {
    return;
  }

  // Sub-recursos estáticos: cache-first, actualiza caché en background
  event.respondWith(
    caches.match(event.request).then(cached => {
      const networkFetch = fetch(event.request).then(response => {
        if (response.status === 200 && url.pathname.startsWith('/static/')) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
        }
        return response;
      });
      return cached || networkFetch;
    }).catch(() => caches.match(event.request))
  );
});
