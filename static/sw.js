const CACHE_NAME = 'empty-chair-static-v2';
const STATIC_ASSETS = [
  '/static/style.css',
  '/static/flashy.css',
  '/static/mobile.css',
  '/static/mobile-nav.css',
  '/static/flashy.js',
  '/static/pwa.js',
  '/static/pwa.css',
  '/static/favicon.png',
  '/static/empty-chair-logo.png',
  '/static/icons/ec-icon-192.png',
  '/static/icons/ec-icon-512.svg',
  '/static/icons/ec-icon-512-maskable.svg'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(
      keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
    ))
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(request).then((cached) => {
        const network = fetch(request)
          .then((response) => {
            if (response && response.ok) {
              const clone = response.clone();
              caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
            }
            return response;
          })
          .catch(() => cached);

        return cached || network;
      })
    );
  }
});
