const CACHE_NAME = 'merco-shell-v1';
const APP_SHELL = [
  '/static/manifest.webmanifest',
  '/static/style.css',
  '/static/luxury.css',
  '/static/theme-refresh.css',
  '/static/preferences.css',
  '/static/page-loader.css',
  '/static/offline.css',
  '/static/install-prompt.css',
  '/static/install-prompt.js'
];

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(APP_SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => Promise.all(keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET' || new URL(event.request.url).origin !== self.location.origin) return;

  event.respondWith(
    fetch(event.request).then(response => {
      const copy = response.clone();
      caches.open(CACHE_NAME).then(cache => cache.put(event.request, copy)).catch(() => {});
      return response;
    }).catch(() => caches.match(event.request).then(cached => cached || caches.match('/market')))
  );
});
