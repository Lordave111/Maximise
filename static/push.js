/* Merco phone notifications.
   Shows a branded permission sheet to every signed-in buyer/seller whose
   browser has not made a notification decision yet. The native browser
   permission dialog is requested only after the user taps Enable.
*/
(function () {
  const supported = 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
  let registration = null;
  const promptSeenKey = 'merco-push-prompt-seen-v2';

  function urlBase64ToUint8Array(base64String) {
    const padding = '='.repeat((4 - base64String.length % 4) % 4);
    const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
    const rawData = atob(base64);
    return Uint8Array.from([...rawData].map(char => char.charCodeAt(0)));
  }

  function status(message, kind = 'info') {
    const box = document.getElementById('mercoPushStatus');
    if (!box) return;
    box.hidden = !message;
    box.className = `merco-push-status is-${kind}`;
    box.textContent = message || '';
  }

  async function getConfig() {
    const response = await fetch('/push/config', { credentials: 'same-origin', cache: 'no-store' });
    if (!response.ok) throw new Error('Merco notification service is unavailable.');
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
    const permission = forcePermission ? await Notification.requestPermission() : Notification.permission;
    if (permission !== 'granted') {
      throw new Error(permission === 'denied'
        ? 'Notifications are blocked for Merco. Open your browser site settings and allow notifications.'
        : 'Notification permission was not granted.');
    }

    const config = await getConfig();
    if (!config.enabled || !config.public_key) {
      throw new Error('Your phone permission is enabled, but Merco phone alerts are not connected yet. The administrator needs to add the VAPID keys in Render.');
    }

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
    if (!response.ok) {
      let message = 'Could not save this phone for notifications.';
      try { message = (await response.json()).error || message; } catch (_) {}
      throw new Error(message);
    }
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
      if (Notification.permission === 'granted') {
        const config = await getConfig();
        if (config.enabled && config.public_key) {
          await subscribe(false);
          button.innerHTML = '<i class="ri-notification-3-fill"></i> Phone alerts enabled';
          button.classList.add('is-enabled');
        } else {
          button.innerHTML = '<i class="ri-notification-3-line"></i> Finish phone alert setup';
        }
      } else if (Notification.permission === 'denied') {
        button.innerHTML = '<i class="ri-notification-off-line"></i> Allow phone notifications';
      } else {
        button.innerHTML = '<i class="ri-notification-3-line"></i> Enable phone alerts';
      }
      button.disabled = false;
    } catch (_) {
      button.disabled = false;
      button.innerHTML = '<i class="ri-notification-3-line"></i> Enable phone alerts';
    }
  }

  function maybeShowPermissionPrompt() {
    if (!supported || Notification.permission !== 'default') return;
    const userFlag = document.querySelector('[data-merco-push-user]')?.dataset.mercoPushUser;
    if (userFlag !== '1') return;
    if (sessionStorage.getItem(promptSeenKey) === '1') return;
    sessionStorage.setItem(promptSeenKey, '1');
    window.setTimeout(openPrompt, 700);
  }

  async function handleEnable(button) {
    if (!button) return;
    button.disabled = true;
    button.innerHTML = '<i class="ri-loader-4-line ri-spin"></i> Connecting...';
    status('', 'info');
    try {
      await subscribe(true);
      closePrompt();
      status('Phone notifications are enabled on this device.', 'success');
      button.innerHTML = '<i class="ri-notification-3-fill"></i> Phone alerts enabled';
      button.classList.add('is-enabled');
      button.disabled = false;
      const settingsButton = document.querySelector('[data-merco-push-enable]');
      if (settingsButton) {
        settingsButton.innerHTML = '<i class="ri-notification-3-fill"></i> Phone alerts enabled';
        settingsButton.classList.add('is-enabled');
        settingsButton.disabled = false;
      }
    } catch (error) {
      button.innerHTML = '<i class="ri-notification-3-line"></i> Enable notifications';
      button.disabled = false;
      status(error?.message || 'We could not enable phone notifications.', 'error');
    }
  }

  async function init() {
    if (!supported) return;
    try { await registerServiceWorker(); } catch (_) {}
    const button = document.querySelector('[data-merco-push-enable]');
    await refreshButton(button);
    const enable = document.getElementById('mercoPushEnable');
    const later = document.getElementById('mercoPushLater');
    if (later) later.addEventListener('click', closePrompt);
    if (enable) enable.addEventListener('click', () => handleEnable(enable));
    if (button) button.addEventListener('click', () => handleEnable(button));
    maybeShowPermissionPrompt();
  }

  window.MercoPush = { enable: () => subscribe(true), register: registerServiceWorker, openPermissionPrompt: openPrompt };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
  else init();
})();
