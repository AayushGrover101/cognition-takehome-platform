const $ = (s) => document.querySelector(s);
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
let current = null;

async function refresh() {
  try {
    const cases = await gateway.call('kyc.list_cases', { status: 'any' });
    $('#rows').innerHTML = cases.map((c) => `<tr data-id="${esc(c.id)}" class="${c.id === current ? 'on' : ''}">
      <td>${esc(c.id)}</td><td>${esc(c.customer)}</td><td>${esc(c.country)}</td>
      <td><span class="tag">${esc(c.risk)}</span></td><td><span class="tag">${esc(c.status)}</span></td></tr>`).join('');
  } catch (e) {
    $('#rows').innerHTML = `<tr><td colspan="5" class="muted">${esc(e.message)}</td></tr>`;
  }
}

function renderCase(c, message) {
  const taxId = c.tax_id ? esc(c.tax_id) : esc(c.tax_id_last4);
  $('#detail').innerHTML = `<h2>${esc(c.customer)}</h2><p class="muted">${esc(c.id)} · ${esc(c.status)}</p>
    <dl class="fields"><dt>Country</dt><dd>${esc(c.country)}</dd><dt>Risk</dt><dd>${esc(c.risk)}</dd>
    <dt>Tax ID</dt><dd>${taxId}</dd><dt>Decided by</dt><dd>${esc(c.decided_by || '—')}</dd>
    <dt>Reason</dt><dd>${esc(c.decision_reason || '—')}</dd></dl>
    <input id="reason" placeholder="Reason (required for decisions)">
    <div class="buttons">
      <button class="btn" data-act="full">Show full tax ID</button>
      <button class="btn" data-act="escalate">Escalate</button>
      <button class="btn" data-act="approve">Approve</button>
      <button class="btn" data-act="reject">Reject</button>
    </div>${message ? `<div class="result ${message.ok ? 'ok' : 'bad'}">${esc(message.text)}</div>` : ''}`;
}

async function open(id, message) {
  current = id;
  try { renderCase(await gateway.call('kyc.get_case', { case_id: id }), message); }
  catch (e) { $('#detail').innerHTML = `<div class="result bad">${esc(e.message)}</div>`; }
  refresh();
}

async function act(kind) {
  const reason = $('#reason').value.trim();
  try {
    if (kind === 'full') return renderCase(await gateway.call('kyc.get_case_full', { case_id: current }));
    if (kind === 'escalate') await gateway.call('kyc.escalate_case', { case_id: current, reason });
    else await gateway.call('kyc.decide_case', { case_id: current, decision: kind, reason });
    open(current, { ok: true, text: 'Done.' });
  } catch (e) {
    open(current, { ok: false, text: e.message });
  }
}

document.addEventListener('click', (e) => {
  const row = e.target.closest('tr[data-id]');
  if (row) open(row.dataset.id);
  const button = e.target.closest('button[data-act]');
  if (button) act(button.dataset.act);
});

gateway.me().then((me) => {
  $('#who').textContent = `${me.user.name} · ${me.user.role.replace('_', ' ')}`;
  $('#tools').innerHTML = me.tools.map((t) => `<code>${esc(t)}</code>`).join('');
  refresh();
});
