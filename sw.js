const CACHE_NAME='merco-shell-v1';

self.addEventListener('install',function(event){
  self.skipWaiting();
});

self.addEventListener('activate',function(event){
  event.waitUntil(self.clients.claim());
});

// Keep navigation network-first so live marketplace data is never replaced by stale cache.
self.addEventListener('fetch',function(event){
  if(event.request.method!=='GET')return;
  if(event.request.mode==='navigate'){
    event.respondWith(fetch(event.request).catch(function(){
      return new Response('<!doctype html><title>Merco</title><meta name="viewport" content="width=device-width,initial-scale=1"><body style="font-family:system-ui;padding:2rem;background:#050505;color:#fff"><h1>You are offline</h1><p>Reconnect to continue using Merco.</p></body>',{headers:{'Content-Type':'text/html;charset=UTF-8'}});
    }));
  }
});