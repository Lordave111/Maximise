(() => {
  'use strict';

  const enableButton = document.querySelector('[data-merco-push-enable]');
  const disableButton = document.querySelector('[data-merco-push-disable]');
  const status = document.querySelector('[data-merco-push-status]');
  if (!enableButton && !disableButton) return;

  const setStatus = (text, ok = false) => {
    if (status) {
      status.textContent = text;
      status.dataset.ok = ok ? '1' : '0';
    }
  };

  const base64ToBytes = value => {
    const padding = '='.repeat((4 - value.length % 4) % 4);
    const base64 = (value + padding).replace(/-/g, '+').replace(/_/g, '/');
    const raw = atob(base64);
    return Uint8Array.from([...raw].map(ch => ch.charCodeAt(0)));
  };

  async function getRegistration() {
    if (!('serviceWorker' in navigator)) throw new Error('This browser does not support service workers.');
    await navigator.serviceWorker.register('/static/sw.js');
    return navigator.serviceWorker.ready;
  }

  async function enablePush() {
    if (!window.isSecureContext) throw new Error('Push notifications require HTTPS.');
    if (!('Notification' in window) || !('PushManager' in window)) throw new Error('This browser does not support push notifications.');

    const permission = await Notification.requestPermission();
    if (permission !== 'granted') throw new Error('Notification permission was not granted.');

    const keyResponse = await fetch('/api/push/public-key', {headers: {Accept: 'application/json'}});
    const keyData = await keyResponse.json();
    if (!keyData.configured || !keyData.publicKey) throw new Error('Push notifications are not configured on the server yet.');

    const registration = await getRegistration();
    let subscription = await registration.pushManager.getSubscription();
    if (!subscription) {
      subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: base64ToBytes(keyData.publicKey)
      });
    }

    const response = await fetch('/api/push/subscribe', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', Accept: 'application/json'},
      body: JSON.stringify(subscription.toJSON())
    });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || 'Could not save your push subscription.');
    setStatus('Phone alerts are enabled.', true);
    if (enableButton) enableButton.hidden = true;
    if (disableButton) disableButton.hidden = false;
  }

  async function disablePush() {
    const registration = await getRegistration();
    const subscription = await registration.pushManager.getSubscription();
    if (subscription) {
      await fetch('/api/push/unsubscribe', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', Accept: 'application/json'},
        body: JSON.stringify({endpoint: subscription.endpoint})
      });
      await subscription.unsubscribe();
    }
    setStatus('Phone alerts are disabled.', true);
    if (enableButton) enableButton.hidden = false;
    if (disableButton) disableButton.hidden = true;
  }

  async function refreshStatus() {
    try {
      const response = await fetch('/api/push/status', {headers: {Accept: 'application/json'}});
      if (!response.ok) return;
      const data = await response.json();
      const enabled = data.subscriptions > 0;
      if (enableButton) enableButton.hidden = enabled;
      if (disableButton) disableButton.hidden = !enabled;
      setStatus(enabled ? 'Phone alerts are enabled.' : 'Phone alerts are currently off.', enabled);
    } catch (_) {}
  }

  enableButton?.addEventListener('click', async () => {
    enableButton.disabled = true;
    try { await enablePush(); } catch (error) { setStatus(error.message || 'Could not enable notifications.'); } finally { enableButton.disabled = false; }
  });
  disableButton?.addEventListener('click', async () => {
    disableButton.disabled = true;
    try { await disablePush(); } catch (error) { setStatus(error.message || 'Could not disable notifications.'); } finally { disableButton.disabled = false; }
  });

  refreshStatus();
})();
