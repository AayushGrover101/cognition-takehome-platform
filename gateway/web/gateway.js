// The only way an app talks to company data: gateway.call('connector.tool', { ...inputs }).
// Refusals throw an Error whose message is the reason, ready to show to the person.
(function () {
  const app = location.pathname.split('/')[2];

  async function request(path, options) {
    const response = await fetch(`/api/${app}/${path}`, { credentials: 'same-origin', ...options });
    let body;
    try { body = await response.json(); } catch (e) { throw new Error('The gateway sent an unexpected response'); }
    if (!body.ok) throw new Error(body.error || 'The gateway refused this request');
    return body.data;
  }

  window.gateway = Object.freeze({
    me: () => request('_me'),
    call: (tool, inputs = {}) => request(encodeURIComponent(tool), {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(inputs),
    }),
  });
})();
