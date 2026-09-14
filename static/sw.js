const CACHE_NAME = 'merco-shell-v2';
const APP_SHELL = [
  '/static/manifest.webmanifest',
  '/static/style.css',
  '/static/luxury.css',
  '/static/theme-refresh.css',
  '/static/preferences.css',
  '/static/page-loader.css',
  '/static/offline.css',
  '/static/pwa-install.css',
  '/static/pwa-install.js'
];

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(APP_SHELL).catch(() => {})).then(() => self.skipWaiting()));
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => Promise.all(keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('push', event => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (_) { data = {body: event.data?.text() || ''}; }
  const title = data.title || 'Merco';
  const options = {
    body: data.body || 'You have a new notification from Merco.',
    icon: data.icon || '/static/icons/icon-192.svg',
    badge: data.badge || '/static/icons/icon-192.svg',
    tag: `merco-${data.kind || 'general'}`,
    renotify: true,
    data: {url: data.url || '/market'}
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  const target = new URL(event.notification.data?.url || '/market', self.location.origin).href;
  event.waitUntil(
    self.clients.matchAll({type: 'window', includeUncontrolled: true}).then(clients => {
      const existing = clients.find(client => client.url.startsWith(self.location.origin));
      if (existing) {
        existing.focus();
        return existing.navigate(target);
      }
      return self.clients.openWindow(target);
    })
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
