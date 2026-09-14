(function () {
  'use strict';

  let deferredPrompt = null;
  const STORAGE_KEY = 'merco-install-prompt-seen';
  const INSTALL_KEY = 'merco-installed';
  const DISMISS_DAYS = 7;

  function isStandalone() {
    return window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
  }

  function recentlyDismissed() {
    try {
      const seen = Number(localStorage.getItem(STORAGE_KEY) || 0);
      return seen && (Date.now() - seen) < DISMISS_DAYS * 86400000;
    } catch (_) {
      return false;
    }
  }

  function markSeen() {
    try { localStorage.setItem(STORAGE_KEY, String(Date.now())); } catch (_) {}
  }

  function markInstalled() {
    try { localStorage.setItem(INSTALL_KEY, '1'); } catch (_) {}
  }

  function isIOS() {
    return /iphone|ipad|ipod/i.test(window.navigator.userAgent) && !window.MSStream;
  }

  function createPrompt() {
    if (document.getElementById('mercoInstallPrompt')) return document.getElementById('mercoInstallPrompt');

    const wrap = document.createElement('aside');
    wrap.id = 'mercoInstallPrompt';
    wrap.className = 'merco-install';
    wrap.setAttribute('role', 'dialog');
    wrap.setAttribute('aria-label', 'Install Merco');
    wrap.innerHTML = `
      <div class="merco-install__glow"></div>
      <button class="merco-install__close" type="button" aria-label="Close install prompt"><i class="ri-close-line"></i></button>
      <div class="merco-install__icon"><i class="ri-sparkling-2-fill"></i></div>
      <div class="merco-install__body">
        <span class="merco-install__eyebrow">MAKE MERCO YOURS</span>
        <h3>Install Merco ✨</h3>
        <p>Get the full marketplace experience with one tap — faster access, app-like browsing and no need to type the website again.</p>
        <div class="merco-install__actions">
          <button class="merco-install__button" id="mercoInstallNow" type="button"><i class="ri-download-cloud-2-line"></i><span>Install Merco</span></button>
          <button class="merco-install__later" id="mercoInstallLater" type="button">Maybe later</button>
        </div>
        <p class="merco-install__ios" id="mercoInstallIOS"><i class="ri-share-forward-line"></i> Tap <strong>Share</strong>, then choose <strong>Add to Home Screen</strong>.</p>
      </div>`;
    document.body.appendChild(wrap);

    wrap.querySelector('.merco-install__close').addEventListener('click', dismiss);
    wrap.querySelector('#mercoInstallLater').addEventListener('click', dismiss);
    wrap.querySelector('#mercoInstallNow').addEventListener('click', install);
    return wrap;
  }

  function showPrompt(mode) {
    if (isStandalone()) return;
    const prompt = createPrompt();
    const iosHelp = prompt.querySelector('#mercoInstallIOS');
    const installButton = prompt.querySelector('#mercoInstallNow');

    if (mode === 'ios') {
      installButton.style.display = 'none';
      iosHelp.style.display = 'block';
    } else {
      installButton.style.display = 'inline-flex';
      iosHelp.style.display = 'none';
    }

    requestAnimationFrame(() => prompt.classList.add('is-visible'));
  }

  function dismiss() {
    markSeen();
    const prompt = document.getElementById('mercoInstallPrompt');
    if (prompt) prompt.classList.remove('is-visible');
  }

  async function install() {
    if (!deferredPrompt) {
      if (isIOS()) showPrompt('ios');
      return;
    }
    deferredPrompt.prompt();
    const result = await deferredPrompt.userChoice;
    deferredPrompt = null;
    if (result && result.outcome === 'accepted') markInstalled();
    dismiss();
  }

  window.addEventListener('beforeinstallprompt', function (event) {
    event.preventDefault();
    deferredPrompt = event;
    if (!recentlyDismissed()) {
      setTimeout(() => showPrompt('android'), 1800);
    }
  });

  window.addEventListener('appinstalled', function () {
    markInstalled();
    const prompt = document.getElementById('mercoInstallPrompt');
    if (prompt) prompt.classList.remove('is-visible');
  });

  window.addEventListener('load', function () {
    if (isStandalone() || recentlyDismissed()) return;
    if (isIOS()) setTimeout(() => showPrompt('ios'), 2200);
  });

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', function () {
      navigator.serviceWorker.register('/static/sw.js').catch(function () {});
    });
  }
})();
