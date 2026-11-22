// The gateway's top bar for app pages: brand, app name, who is signed in, Sign out.
(function () {
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const initials = (name) => name.split(/\s+/).slice(0, 2).map((w) => w[0] || '').join('').toUpperCase();
  const logo = '<svg width="22" height="22" viewBox="0 0 22 22" aria-hidden="true"><rect width="22" height="22" rx="6" fill="#111"/>'
    + '<path d="M7 15.5V6.5M11 15.5V9.5M15 15.5V12" stroke="#fff" stroke-width="2" stroke-linecap="round"/></svg>';

  const bar = document.createElement('header');
  bar.className = 'top';
  bar.innerHTML = `<a class="brand" href="/">${logo}Internal tools</a><span class="crumb">/</span><span class="here"></span>`;
  document.body.prepend(bar);

  gateway.me().then((me) => {
    const here = encodeURIComponent(location.pathname);
    bar.querySelector('.here').textContent = me.app.title;
    bar.insertAdjacentHTML('beforeend', `<span class="spacer"></span>
      <div class="who"><span class="avatar">${esc(initials(me.user.name))}</span><span class="name">${esc(me.user.name)}</span>
      <span class="role">${esc(me.user.title)}</span></div><span class="divider"></span>
      <a class="btn ghost" href="/signout?next=${here}">Sign out</a>`);
  }).catch(() => {});
})();
