(() => {
  const bell = document.querySelector('[data-notification-bell]');
  const menu = document.querySelector('[data-notification-menu]');
  const badge = document.querySelector('[data-notification-count]');
  const list = document.querySelector('[data-notification-list]');
  if (!bell || !menu || !badge || !list) return;

  const escapeHtml = value => String(value ?? '').replace(/[&<>\"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#039;'}[c]));
  const render = data => {
    badge.textContent = data.unread > 99 ? '99+' : data.unread;
    badge.hidden = !data.unread;
    list.innerHTML = data.notifications.length ? data.notifications.slice(0, 8).map(n => `
      <a class="merco-notification-item ${n.is_read ? '' : 'is-unread'}" href="/notifications/open/${n.id}">
        <span class="merco-notification-icon">${n.kind === 'new_product' ? '✦' : n.kind === 'new_follower' ? '♡' : n.kind === 'payment_success' ? '✓' : '•'}</span>
        <span><strong>${escapeHtml(n.title)}</strong><small>${escapeHtml(n.message)}</small><time>${new Date(n.created_at).toLocaleString()}</time></span>
      </a>`).join('') : '<div class="merco-notification-empty">You’re all caught up.</div>';
  };
  const load = async () => { try { const r = await fetch('/api/notifications',{headers:{Accept:'application/json'}}); if(r.ok) render(await r.json()); } catch(e) {} };
  bell.addEventListener('click', e => { e.stopPropagation(); menu.hidden = !menu.hidden; if(!menu.hidden) load(); });
  document.addEventListener('click', e => { if(!menu.contains(e.target) && !bell.contains(e.target)) menu.hidden = true; });
  load();
  setInterval(load, 20000);
})();
