const CACHE_NAME = 'zeropos-v8';
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
  // Archivos estáticos: cache-first
  event.respondWith(
    caches.match(event.request).then(cached => {
      return cached || fetch(event.request).then(response => {
        if (response.ok && url.pathname.startsWith('/static/')) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
        }
        return response;
      });
    })
  );
});
