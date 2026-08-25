/* Merco phone notifications.
   A signed-in user who has not chosen a notification permission gets a branded
   Merco prompt automatically. The browser's native permission dialog is
   requested only from the user's tap on "Enable notifications" because modern
   browsers require a user gesture for notification permission requests.
*/
(function () {
  'use strict';

  const supported = 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
  let registration = null;
  let busy = false;
  const qs = (selector) => document.querySelector(selector);

  function setButton(button, html, disabled = false, enabled = false) {
    if (!button) return;
    button.innerHTML = html;
    button.disabled = disabled;
    button.classList.toggle('is-enabled', enabled);
    button.setAttribute('aria-busy', disabled ? 'true' : 'false');
  }

  function status(message, kind = 'info') {
    const box = qs('#mercoPushStatus');
    if (!box) return;
    box.hidden = !message;
    box.className = `merco-push-status is-${kind}`;
    box.textContent = message || '';
  }

  function openPrompt() {
    const modal = qs('#mercoPushPermission');
    if (!modal) return;
    modal.hidden = false;
    document.body.classList.add('merco-push-open');
    window.setTimeout(() => qs('#mercoPushEnable')?.focus(), 80);
  }

  function closePrompt() {
    const modal = qs('#mercoPushPermission');
    if (!modal) return;
    modal.hidden = true;
    document.body.classList.remove('merco-push-open');
  }

  function urlBase64ToUint8Array(value) {
    const padding = '='.repeat((4 - value.length % 4) % 4);
    const base64 = (value + padding).replace(/-/g, '+').replace(/_/g, '/');
    const raw = atob(base64);
    const output = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i += 1) output[i] = raw.charCodeAt(i);
    return output;
  }

  async function getConfig() {
    const response = await fetch('/push/config', { credentials: 'same-origin', cache: 'no-store', headers: { Accept: 'application/json' } });
    if (!response.ok) throw new Error('Merco notification service is unavailable right now.');
    const data = await response.json();
    if (!data.public_key) throw new Error('Phone alerts are not configured on Merco yet. The administrator needs to add the VAPID keys in Render.');
    return data;
  }

  async function registerServiceWorker() {
    if (!supported) throw new Error('This browser does not support phone notifications.');
    if (registration) return registration;
    registration = await navigator.serviceWorker.register('/static/sw.js', { scope: '/' });
    return await navigator.serviceWorker.ready;
  }

  async function subscribeFromPermission(permission) {
    if (permission !== 'granted') {
      throw new Error(permission === 'denied'
        ? 'Notifications are blocked for Merco. Allow notifications in your browser/site settings and try again.'
        : 'Notification permission was not granted.');
    }

    const config = await getConfig();
    const reg = await registerServiceWorker();
    let subscription = await reg.pushManager.getSubscription();
    if (!subscription) {
      subscription = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlBase64ToUint8Array(config.public_key) });
    }

    const response = await fetch('/push/subscribe', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify(subscription.toJSON())
    });
    if (!response.ok) {
      let message = 'Merco could not save this device for notifications.';
      try { const data = await response.json(); if (data.error) message = data.error; } catch (_) {}
      throw new Error(message);
    }
    return subscription;
  }

  async function enable(button) {
    if (busy || !supported || !button) return;
    busy = true;
    setButton(button, '<i class="ri-loader-4-line ri-spin"></i> Connecting…', true);
    status('', 'info');

    try {
      // Must stay in the click path: browsers require a user gesture for this prompt.
      let permission = Notification.permission;
      if (permission !== 'granted') permission = await Notification.requestPermission();
      await subscribeFromPermission(permission);
      closePrompt();
      status('Phone notifications are enabled on this device.', 'success');
      setButton(button, '<i class="ri-notification-3-fill"></i> Phone alerts enabled', false, true);
      const settingsButton = qs('[data-merco-push-enable]');
      if (settingsButton && settingsButton !== button) setButton(settingsButton, '<i class="ri-notification-3-fill"></i> Phone alerts enabled', false, true);
    } catch (error) {
      console.error('[Merco Push]', error);
      setButton(button, '<i class="ri-notification-3-line"></i> Enable notifications', false, false);
      status(error?.message || 'We could not enable phone notifications. Please try again.', 'error');
    } finally {
      busy = false;
    }
  }

  async function syncGrantedState(button) {
    if (!button || !supported) return;
    if (Notification.permission === 'granted') {
      try {
        await subscribeFromPermission('granted');
        setButton(button, '<i class="ri-notification-3-fill"></i> Phone alerts enabled', false, true);
      } catch (error) {
        console.warn('[Merco Push] Existing permission could not be synced:', error);
        setButton(button, '<i class="ri-notification-3-line"></i> Enable phone alerts', false, false);
      }
      return;
    }
    if (Notification.permission === 'denied') setButton(button, '<i class="ri-notification-off-line"></i> Notifications blocked');
    else setButton(button, '<i class="ri-notification-3-line"></i> Enable phone alerts');
  }

  function showPermissionPromptForSignedInUser() {
    const modal = qs('#mercoPushPermission');
    if (!modal || !supported || modal.dataset.mercoPushUser !== '1') return;
    if (Notification.permission !== 'default') return;
    // Show the branded explanation automatically after login/page load.
    // The native browser prompt still waits for the user's tap.
    window.setTimeout(openPrompt, 500);
  }

  function init() {
    const modal = qs('#mercoPushPermission');
    const enableButton = qs('#mercoPushEnable');
    const settingsButton = qs('[data-merco-push-enable]');
    const laterButton = qs('#mercoPushLater');
    if (!modal || modal.dataset.mercoPushUser !== '1') return;

    if (!supported) {
      if (settingsButton) setButton(settingsButton, '<i class="ri-notification-off-line"></i> Notifications unavailable', true);
      return;
    }

    // No service-worker registration or network calls before the user asks.
    syncGrantedState(settingsButton);

    if (enableButton) enableButton.addEventListener('click', (event) => { event.preventDefault(); enable(enableButton); });
    if (settingsButton) settingsButton.addEventListener('click', (event) => {
      event.preventDefault();
      if (Notification.permission === 'denied') {
        status('Notifications are blocked by your browser. Open site permissions and allow Merco notifications.', 'error');
        openPrompt();
        return;
      }
      enable(settingsButton);
    });
    if (laterButton) laterButton.addEventListener('click', (event) => { event.preventDefault(); closePrompt(); });

    showPermissionPromptForSignedInUser();
  }

  window.MercoPush = {
    enable: () => enable(qs('#mercoPushEnable')),
    register: registerServiceWorker,
    openPermissionPrompt: openPrompt
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
  else init();
})();
