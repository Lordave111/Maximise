/* Merco phone notifications + role-aware navigation. */
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
    if (!response.ok) throw new Error(`Merco notification service returned ${response.status}.`);
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
      subscription = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(config.public_key)
      });
    }

    const response = await fetch('/push/subscribe', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify(subscription.toJSON())
    });
    if (!response.ok) {
      let message = `Merco could not save this device (HTTP ${response.status}).`;
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
    window.setTimeout(openPrompt, 500);
  }

  function initPush() {
    const modal = qs('#mercoPushPermission');
    const enableButton = qs('#mercoPushEnable');
    const settingsButton = qs('[data-merco-push-enable]');
    const laterButton = qs('#mercoPushLater');
    if (!modal || modal.dataset.mercoPushUser !== '1') return;

    if (!supported) {
      if (settingsButton) setButton(settingsButton, '<i class="ri-notification-off-line"></i> Notifications unavailable', true);
      return;
    }

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

  /* The base template predates the restored seller/buyer navigation. Build the
     same navigation from a small authenticated JSON endpoint so the links are
     available everywhere without exposing seller/admin links to other roles. */
  async function enhanceNavigation() {
    const nav = document.querySelector('.topbar nav');
    if (!nav) return;
    try {
      const response = await fetch('/api/navigation', { credentials: 'same-origin', cache: 'no-store', headers: { Accept: 'application/json' } });
      if (!response.ok) return;
      const data = await response.json();
      if (!data.authenticated || !Array.isArray(data.items)) return;

      const logout = Array.from(nav.querySelectorAll('a')).find(a => /log out/i.test(a.textContent));
      const existing = new Set(Array.from(nav.querySelectorAll('a')).map(a => a.getAttribute('href')));
      for (const item of data.items) {
        if (existing.has(item.url)) continue;
        const link = document.createElement('a');
        link.href = item.url;
        link.dataset.mercoNav = 'true';
        link.innerHTML = `<i class="${item.icon}"></i><span>${item.label}</span>`;
        if (logout) nav.insertBefore(link, logout); else nav.appendChild(link);
      }
    } catch (error) {
      console.debug('[Merco Navigation]', error);
    }
  }

  window.MercoPush = {
    enable: () => enable(qs('#mercoPushEnable')),
    register: registerServiceWorker,
    openPermissionPrompt: openPrompt
  };

  function init() {
    initPush();
    enhanceNavigation();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
  else init();
})();
