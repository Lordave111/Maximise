/* Merco PWA phone notifications. Permission is requested only after the user
   explicitly clicks the Enable button; previously granted permission is reused. */
(function () {
  const supported = 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
  let registration = null;

  function urlBase64ToUint8Array(base64String) {
    const padding = '='.repeat((4 - base64String.length % 4) % 4);
    const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
    const rawData = atob(base64);
    return Uint8Array.from([...rawData].map(char => char.charCodeAt(0)));
  }

  async function getConfig() {
    const response = await fetch('/push/config', { credentials: 'same-origin', cache: 'no-store' });
    if (!response.ok) throw new Error('Push configuration unavailable');
    return response.json();
  }

  async function registerServiceWorker() {
    if (!supported) return null;
    registration = await navigator.serviceWorker.register('/static/sw.js', { scope: '/' });
    await navigator.serviceWorker.ready;
    return registration;
  }

  async function subscribe(forcePermission) {
    if (!supported) throw new Error('This browser does not support phone notifications.');
    const config = await getConfig();
    if (!config.enabled || !config.public_key) throw new Error('Phone notifications are not configured yet.');
    const permission = forcePermission ? await Notification.requestPermission() : Notification.permission;
    if (permission !== 'granted') throw new Error('Notification permission was not granted.');
    const reg = registration || await registerServiceWorker();
    let subscription = await reg.pushManager.getSubscription();
    if (!subscription) {
      subscription = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(config.public_key),
      });
    }
    const response = await fetch('/push/subscribe', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(subscription.toJSON()),
    });
    if (!response.ok) throw new Error('Could not save the notification subscription.');
    return subscription;
  }

  async function refreshButton(button) {
    if (!button) return;
    if (!supported) {
      button.disabled = true;
      button.innerHTML = '<i class="ri-notification-off-line"></i> Phone alerts unavailable';
      return;
    }
    try {
      const config = await getConfig();
      if (!config.enabled) {
        button.disabled = true;
        button.innerHTML = '<i class="ri-notification-off-line"></i> Phone alerts not configured';
        return;
      }
      if (Notification.permission === 'granted') {
        await subscribe(false);
        button.innerHTML = '<i class="ri-notification-3-fill"></i> Phone alerts enabled';
        button.classList.add('is-enabled');
      } else if (Notification.permission === 'denied') {
        button.innerHTML = '<i class="ri-notification-off-line"></i> Notifications blocked';
      }
    } catch (_) {}
  }

  async function init() {
    if (!supported) return;
    try {
      await registerServiceWorker();
      const button = document.querySelector('[data-merco-push-enable]');
      await refreshButton(button);
      if (button) {
        button.addEventListener('click', async () => {
          button.disabled = true;
          button.innerHTML = '<i class="ri-loader-4-line ri-spin"></i> Enabling...';
          try {
            await subscribe(true);
            button.innerHTML = '<i class="ri-notification-3-fill"></i> Phone alerts enabled';
            button.classList.add('is-enabled');
          } catch (error) {
            button.innerHTML = '<i class="ri-notification-3-line"></i> Enable phone alerts';
            button.disabled = false;
            if (error && error.message) alert(error.message);
          }
        });
      }
    } catch (_) {}
  }

  window.MercoPush = { enable: () => subscribe(true), register: registerServiceWorker };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
  else init();
})();
