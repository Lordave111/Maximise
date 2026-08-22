/* Merco PWA phone notifications. A branded permission sheet is shown to authenticated
   users when notification permission is still undecided. The native browser prompt is
   triggered only from the user's Enable button click. */
(function () {
  const supported = 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
  let registration = null;
  const promptSeenKey = 'merco-push-prompt-seen';

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
    if (permission !== 'granted') throw new Error(permission === 'denied' ? 'Notifications are blocked. You can enable them in your browser site settings.' : 'Notification permission was not granted.');
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

  function closePrompt() {
    const modal = document.getElementById('mercoPushPermission');
    if (!modal) return;
    modal.hidden = true;
    document.body.classList.remove('merco-push-open');
  }

  function openPrompt() {
    const modal = document.getElementById('mercoPushPermission');
    if (!modal) return;
    modal.hidden = false;
    document.body.classList.add('merco-push-open');
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

  async function maybeShowPermissionPrompt() {
    if (!supported || Notification.permission !== 'default') return;
    const userFlag = document.querySelector('[data-merco-push-user]')?.dataset.mercoPushUser;
    if (userFlag !== '1') return;
    if (sessionStorage.getItem(promptSeenKey) === '1') return;
    try {
      const config = await getConfig();
      if (!config.enabled || !config.public_key) return;
      sessionStorage.setItem(promptSeenKey, '1');
      window.setTimeout(openPrompt, 650);
    } catch (_) {}
  }

  async function init() {
    if (!supported) return;
    try {
      await registerServiceWorker();
      const button = document.querySelector('[data-merco-push-enable]');
      await refreshButton(button);

      const enable = document.getElementById('mercoPushEnable');
      const later = document.getElementById('mercoPushLater');
      if (later) later.addEventListener('click', closePrompt);

      if (enable) {
        enable.addEventListener('click', async () => {
          enable.disabled = true;
          enable.innerHTML = '<i class="ri-loader-4-line ri-spin"></i> Connecting...';
          try {
            await subscribe(true);
            closePrompt();
            if (button) {
              button.innerHTML = '<i class="ri-notification-3-fill"></i> Phone alerts enabled';
              button.classList.add('is-enabled');
              button.disabled = false;
            }
          } catch (error) {
            enable.innerHTML = '<i class="ri-notification-3-line"></i> Enable notifications';
            enable.disabled = false;
            if (error?.message) alert(error.message);
          }
        });
      }

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
            if (error?.message) alert(error.message);
          }
        });
      }

      await maybeShowPermissionPrompt();
    } catch (_) {}
  }

  window.MercoPush = { enable: () => subscribe(true), register: registerServiceWorker, openPermissionPrompt: openPrompt };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
  else init();
})();
