const CACHE_NAME='merco-shell-v2';

self.addEventListener('install', function(event){
  self.skipWaiting();
});

self.addEventListener('activate', function(event){
  event.waitUntil(self.clients.claim());
});

// Keep navigation network-first so live marketplace data is never replaced by stale cache.
self.addEventListener('fetch', function(event){
  if(event.request.method!=='GET') return;
  if(event.request.mode==='navigate'){
    event.respondWith(fetch(event.request).catch(function(){
      return new Response('<!doctype html><title>Merco</title><meta name="viewport" content="width=device-width,initial-scale=1"><body style="font-family:system-ui;padding:2rem;background:#050505;color:#fff"><h1>You are offline</h1><p>Reconnect to continue using Merco.</p></body>',{headers:{'Content-Type':'text/html;charset=UTF-8'}});
    }));
  }
});

self.addEventListener('push', function(event){
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (_) {
    data = {title:'Merco', body:event.data ? event.data.text() : 'You have a new notification.'};
  }
  const title = data.title || 'Merco';
  const options = {
    body: data.body || 'You have a new notification.',
    icon: data.icon || '/static/icons/icon-192.svg',
    badge: data.badge || '/static/icons/icon-192.svg',
    data: {url: data.url || '/notifications'}
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', function(event){
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || '/notifications';
  event.waitUntil(
    self.clients.matchAll({type:'window', includeUncontrolled:true}).then(function(clients){
      for (const client of clients) {
        if ('focus' in client) {
          if ('navigate' in client) client.navigate(target);
          return client.focus();
        }
      }
      if (self.clients.openWindow) return self.clients.openWindow(target);
    })
  );
});
