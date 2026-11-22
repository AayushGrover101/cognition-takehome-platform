const TABS = [['apps', 'Apps'], ['connectors', 'Connectors'], ['people', 'People'], ['activity', 'Activity'], ['outbox', 'Sent outside']];
let state = null;
let tab = location.hash.slice(1) || 'apps';
let filters = { user: '', app: '', operation: '', record: '', outcome: '' };

const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const label = s => esc(String(s ?? '').replace(/_/g, ' '));
const tag = (text, cls) => `<span class="tag ${esc(cls || text)}">${label(text)}</span>`;
const when = ts => new Date(ts * 1000).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' });
const days = d => { const y = Math.round(d / 365 * 10) / 10; return d >= 365 ? `${y} ${y === 1 ? 'year' : 'years'}` : `${d} days`; };

async function get(action, params) {
  const qs = params ? '?' + new URLSearchParams(Object.entries(params).filter(([, v]) => v)) : '';
  return (await fetch('/admin/api/' + action + qs)).json();
}
async function post(action, body) {
  const r = await (await fetch('/admin/api/' + action, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) })).json();
  toast(r.ok ? (r.message || 'Saved') : r.error);
  return r;
}
function toast(text) {
  const t = document.getElementById('toast');
  t.textContent = text; t.classList.add('on');
  clearTimeout(toast.timer); toast.timer = setTimeout(() => t.classList.remove('on'), 2200);
}

async function load() {
  state = await get('state');
  if (!state.me) { location.href = '/signin?next=/admin'; return; }
  document.getElementById('me').textContent = `${state.me.name} · ${state.me.role}`;
  document.getElementById('tabs').innerHTML = TABS.map(([id, name]) => `<button data-tab="${id}" class="${id === tab ? 'on' : ''}">${name}</button>`).join('');
  await render();
}

async function render() {
  const view = document.getElementById('view');
  if (tab === 'apps') view.innerHTML = appsView();
  if (tab === 'connectors') view.innerHTML = connectorsView();
  if (tab === 'people') view.innerHTML = peopleView();
  if (tab === 'activity') view.innerHTML = await activityView();
  if (tab === 'outbox') view.innerHTML = await outboxView();
}

function appsView() {
  const blocks = state.apps.map(a => `
    <div class="block">
      <header><h2>${esc(a.title)}</h2><code class="muted">${esc(a.name)}</code><span class="grow"></span>
        ${a.status === 'published' ? `<a class="link muted" href="/apps/${esc(a.name)}/">Open</a>` : ''}
        ${tag(a.status === 'published' ? 'published' : 'not published', a.status)}</header>
      <div class="body"><table class="kv">
        <tr><th>Who can open it</th><td>${a.access.map(r => tag(r, 'role')).join(' ') || '<span class="muted">Nobody</span>'}</td></tr>
        <tr><th>Operations it may use</th><td>${a.operations.map(o => `<div><code>${esc(o.name)}</code> ${tag(o.group)}
          <span class="muted small">${o.audit ? (o.audit.enabled ? `audited, kept ${days(o.audit.retention_days)}${o.audit.mask_inputs.length ? ', hides ' + esc(o.audit.mask_inputs.join(', ')) : ''}` : 'not audited') : ''}</span></div>`).join('') || '<span class="muted">None</span>'}</td></tr>
      </table></div>
      ${a.problems.length ? `<div class="note">Refused by policy:<ul>${a.problems.map(p => `<li>${esc(p)}</li>`).join('')}</ul></div>` : ''}
    </div>`).join('');
  return `<div class="head"><div class="grow"><h1>Apps</h1><p class="muted">Every app, who can open it, and the operations it is approved to use.</p></div>
    <button class="btn" data-act="sync">Sync from apps repository</button></div>
    ${blocks || '<div class="block"><div class="empty">No apps yet. Apps appear here when they are merged into the apps repository.</div></div>'}`;
}

function connectorsView() {
  const order = { internal: 0, external: 1, blocked: 2 };
  const blocks = [...state.connectors].sort((x, y) => order[x.group] - order[y.group]).map(c => `
    <div class="block">
      <header><h2>${esc(c.title)}</h2><code class="muted">${esc(c.name)}</code><span class="muted">${esc(c.description)}</span><span class="grow"></span>
        <select data-group="${esc(c.name)}">${['internal', 'external', 'blocked'].map(g => `<option value="${g}" ${g === c.group ? 'selected' : ''}>${g[0].toUpperCase() + g.slice(1)}</option>`).join('')}</select></header>
      <div class="body"><table>
        <tr><th>Operation</th><th>Roles allowed</th><th>Hidden fields</th><th>Rules</th><th>Audit</th><th></th></tr>
        ${c.operations.map(o => `<tr>
          <td><code>${esc(o.name.split('.')[1])}</code> ${o.changes_data ? tag('changes data', 'role') : ''}<div class="muted small">${esc(o.description)}</div></td>
          <td>${o.roles.map(r => tag(r, 'role')).join(' ')}</td>
          <td class="small">${Object.entries(o.masked_fields).map(([f, roles]) => `<div><code>${esc(f)}</code> <span class="muted">full for ${label(roles.join(', '))}</span></div>`).join('') || '<span class="muted">None</span>'}</td>
          <td class="small wrapcell">${o.rules.map(r => `<div>${esc(r)}</div>`).join('') || '<span class="muted">None</span>'}</td>
          <td class="small nowrap">${o.audit.required ? 'Always' : 'Default on'}<div class="muted">min ${days(o.audit.min_retention_days)}</div></td>
          <td class="nowrap"><button class="btn small" data-block="${esc(o.name)}" data-to="${o.blocked ? '' : '1'}">${o.blocked ? 'Unblock' : 'Block'}</button> ${o.blocked ? tag('blocked') : ''}</td>
        </tr>`).join('')}
      </table></div>
    </div>`).join('');
  return `<div class="head"><div class="grow"><h1>Connectors</h1>
    <p class="muted">Each connector is Internal, External or Blocked. An app cannot combine Internal and External connectors. Connectors are written by platform engineers.</p></div></div>${blocks}`;
}

function peopleView() {
  return `<div class="head"><div class="grow"><h1>People</h1><p class="muted">Roles decide which apps a person can open and which operations they can run. In production these come from company sign-in groups.</p></div></div>
    <div class="block"><table><tr><th>Person</th><th>Role</th></tr>
    ${state.users.map(u => `<tr><td>${esc(u.name)} <code class="muted">${esc(u.id)}</code></td>
      <td><select data-user="${esc(u.id)}" ${u.id === state.me.id ? 'disabled' : ''}>${state.roles.map(r => `<option value="${esc(r)}" ${r === u.role ? 'selected' : ''}>${label(r)}</option>`).join('')}</select></td></tr>`).join('')}
    </table></div>`;
}

async function activityView() {
  const [{ rows }, check] = await Promise.all([get('audit', filters), get('audit-verify')]);
  const opt = (list, cur, any) => `<option value="">${any}</option>` + list.map(([v, t]) => `<option value="${esc(v)}" ${v === cur ? 'selected' : ''}>${esc(t)}</option>`).join('');
  const ops = state.connectors.flatMap(c => c.operations.map(o => [o.name, o.name]));
  return `<div class="head"><div class="grow"><h1>Activity</h1><p class="muted">One row for every call through the gateway, including refused ones. Rows cannot be edited.</p></div>
      <span class="tag ${check.ok ? 'allowed' : 'refused'}">${check.ok ? `Log intact · ${check.rows} rows verified` : `Log altered at row ${check.broken_at}`}</span></div>
    <div class="filters">
      <select data-filter="user">${opt(state.users.map(u => [u.id, u.name]), filters.user, 'Anyone')}</select>
      <select data-filter="app">${opt(state.apps.map(a => [a.name, a.title]).concat([['admin', 'Admin']]), filters.app, 'Any app')}</select>
      <select data-filter="operation">${opt(ops, filters.operation, 'Any operation')}</select>
      <select data-filter="outcome">${opt([['allowed', 'Allowed'], ['refused', 'Refused']], filters.outcome, 'Any outcome')}</select>
      <input data-filter="record" placeholder="Record, e.g. KYC-1004" value="${esc(filters.record)}">
      <button class="btn" data-act="clear">Clear</button>
    </div>
    <div class="block"><table>
      <tr><th>When</th><th>Who</th><th>App</th><th>Operation</th><th>Record</th><th>Inputs</th><th>Outcome</th><th>Kept for</th></tr>
      ${rows.map(r => `<tr class="${esc(r.outcome)}">
        <td class="nowrap muted">${when(r.ts)}</td>
        <td class="nowrap">${esc(r.user_name)}<div class="muted small">${label(r.role)}</div></td>
        <td>${esc(r.app)}</td><td><code>${esc(r.operation)}</code></td><td class="nowrap">${esc(r.record_id)}</td>
        <td class="small wrapcell">${Object.entries(r.inputs).map(([k, v]) => `<div><span class="muted">${esc(k)}:</span> ${esc(v)}</div>`).join('')}</td>
        <td class="wrapcell">${tag(r.outcome)}<div class="muted small">${esc(r.reason)}</div></td>
        <td class="nowrap muted small">${days(r.retention_days)}</td></tr>`).join('') || '<tr><td colspan="8" class="empty">Nothing matches.</td></tr>'}
    </table></div>`;
}

async function outboxView() {
  const { rows } = await get('outbox');
  return `<div class="head"><div class="grow"><h1>Sent outside</h1><p class="muted">Everything apps have sent to outside services through External connectors. Nothing is really sent in this prototype.</p></div></div>
    <div class="block"><table><tr><th>When</th><th>Service</th><th>To</th><th>Content</th><th>Sent by</th><th>App</th></tr>
    ${rows.map(r => `<tr><td class="nowrap muted">${when(r.ts)}</td><td>${esc(r.service)}</td><td>${esc(r.destination)}</td><td class="wrapcell">${esc(r.content)}</td><td class="nowrap">${esc(r.user_name)}</td><td>${esc(r.app)}</td></tr>`).join('') || '<tr><td colspan="6" class="empty">Nothing has been sent outside.</td></tr>'}
    </table></div>`;
}

document.addEventListener('click', async e => {
  const t = e.target.closest('button'); if (!t) return;
  if (t.dataset.tab) { tab = t.dataset.tab; location.hash = tab; await load(); }
  if (t.dataset.block) { await post('operation-block', { operation: t.dataset.block, blocked: !!t.dataset.to }); await load(); }
  if (t.dataset.act === 'sync') { await post('sync-apps'); await load(); }
  if (t.dataset.act === 'clear') { filters = { user: '', app: '', operation: '', record: '', outcome: '' }; await render(); }
});
document.addEventListener('change', async e => {
  const t = e.target;
  if (t.dataset.group) { await post('connector-group', { connector: t.dataset.group, group: t.value }); await load(); }
  if (t.dataset.user) { await post('user-role', { user: t.dataset.user, role: t.value }); await load(); }
  if (t.dataset.filter) { filters[t.dataset.filter] = t.value.trim(); await render(); }
});
load();
