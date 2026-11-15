(() => {
'use strict';
const $ = (s, r = document) => r.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const S = { user: undefined, meta: null, lang: localStorage.getItem('zp_lang') || 'en' };
const t = k => (I18N[S.lang] && I18N[S.lang][k]) || I18N.en[k] || k;
const ic = (n, c = '') => `<svg class="ic ${c}" viewBox="0 0 24 24" aria-hidden="true">${ICONS[n] || ''}</svg>`;
const inr = p => '₹' + ((p || 0) / 100).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fd = ts => ts ? new Date(ts * 1000).toLocaleString() : '—';
const badge = s => `<span class="badge b-${esc(s)}">${esc(s)}</span>`;
const FINAL = ['paid', 'expired', 'cancelled', 'failed', 'mismatch'];
const app = $('#app');
const PERMS = ['users', 'payments', 'tickets', 'announce', 'subscriptions', 'reports'];

function csrf() { return (document.cookie.match(/zp_csrf=([^;]+)/) || [])[1] || ''; }
async function api(path, o = {}) {
  const opt = { method: o.method || 'GET', headers: { Accept: 'application/json' }, credentials: 'same-origin' };
  if (o.body !== undefined) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(o.body); }
  if (opt.method !== 'GET') opt.headers['X-CSRF-Token'] = csrf();
  const r = await fetch('/api' + path, opt);
  let d = {}; try { d = await r.json(); } catch (e) {}
  if (!r.ok) {
    const det = d.detail;
    const e = new Error(typeof det === 'string' ? det : (det && det[0] && det[0].msg) || 'Request failed');
    e.status = r.status; throw e;
  }
  return d;
}
function toast(msg, type = 'ok') {
  const d = document.createElement('div'); d.className = 'toast ' + type;
  d.innerHTML = ic(type === 'ok' ? 'check' : 'alert') + `<span>${esc(msg)}</span>`;
  $('#toasts').appendChild(d); setTimeout(() => d.classList.add('out'), 3800); setTimeout(() => d.remove(), 4300);
}
async function act(btn, fn) {
  if (btn) btn.disabled = true;
  try { return await fn(); }
  catch (e) {
    if (e.message === 'reauth_required') { toast('Owner session locked. Re-enter your password.', 'err'); go('/owner'); return; }
    toast(e.message || 'Error', 'err');
    if (e.status === 401 && S.user) { S.user = null; go('/login'); }
  } finally { if (btn) btn.disabled = false; }
}
const form = f => Object.fromEntries(new FormData(f).entries());
const copy = async txt => { try { await navigator.clipboard.writeText(txt); toast('Copied'); } catch (e) { toast('Copy failed', 'err'); } };
function go(p) { history.pushState({}, '', p); render(); }
function modal(html) {
  const m = document.createElement('div'); m.className = 'modal';
  m.innerHTML = `<div class="card">${html}<div class="mt"><button class="btn ghost sm" data-close>${ic('x')} Close</button></div></div>`;
  m.addEventListener('click', e => { if (e.target === m || e.target.closest('[data-close]')) m.remove(); });
  document.body.appendChild(m); return m;
}
const tbl = (heads, rows) => `<div class="tw"><table><thead><tr>${heads.map(h => `<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.length ? rows.join('') : `<tr><td colspan="${heads.length}" class="muted c">${t('empty')}</td></tr>`}</tbody></table></div>`;
const logo = `<span class="logo"><svg class="ic" viewBox="0 0 24 24"><path d="M6 7h12L6 17h12"/></svg></span>`;
const field = (l, n, type = 'text', extra = '') => `<label>${l}</label><input name="${n}" type="${type}" ${extra}>`;

/* ---------- theme / language / brand ---------- */
function applyBrand() {
  document.documentElement.style.setProperty('--b1', S.meta.color);
  document.documentElement.lang = S.lang;
  document.documentElement.dir = RTL.includes(S.lang) ? 'rtl' : 'ltr';
}
function langSelect() { return `<select id="lang" style="width:auto" aria-label="${t('language')}">${Object.entries(LANG_NAMES).map(([k, v]) => `<option value="${k}" ${k === S.lang ? 'selected' : ''}>${v}</option>`).join('')}</select>`; }
function bindTop() {
  const l = $('#lang'); if (l) l.onchange = () => { S.lang = l.value; localStorage.setItem('zp_lang', S.lang); applyBrand(); render(); };
  const th = $('#theme'); if (th) th.onclick = () => { const n = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'; document.documentElement.dataset.theme = n; localStorage.setItem('zp_theme', n); th.innerHTML = ic(n === 'dark' ? 'sun' : 'moon'); };
}
const themeBtn = () => `<button class="icon-btn" id="theme" aria-label="Theme">${ic(document.documentElement.dataset.theme === 'dark' ? 'sun' : 'moon')}</button>`;

/* ---------- shell ---------- */
function shell(path) {
  const u = S.user;
  const nav = [['dashboard', '/dashboard', 'home'], ['order', '/order', 'plus'], ['qr', '/qr', 'qr'], ['connect', '/connect', 'plug'], ['verify', '/verify', 'shield'], ['links', '/links', 'link'], ['transactions', '/transactions', 'list'], ['subscription', '/subscription', 'card'], ['support', '/support', 'life'], ['notifications', '/notifications', 'bell'], ['activity', '/activity', 'activity'], ['profile', '/profile', 'user']];
  if (['admin', 'owner'].includes(u.role)) nav.push(['admin', '/admin', 'users']);
  if (u.role === 'owner') nav.push(['owner', '/owner', 'crown']);
  const item = n => `<a class="nav ${path === n[1] ? 'on' : ''}" href="${n[1]}" data-link>${ic(n[2])}<span>${t(n[0])}</span></a>`;
  const mob = ['dashboard', 'order', 'qr', 'connect', 'profile'].map(k => nav.find(n => n[0] === k));
  app.innerHTML = `<div class="shell"><aside class="side glass"><div class="brand">${logo}<span>${esc(S.meta.brand)}</span></div>${nav.map(item).join('')}</aside>
  <div class="main"><header class="top glass"><div class="row"><span class="badge">${esc(u.role)}</span><strong>${esc(u.name)}</strong></div><div class="row">${langSelect()}${themeBtn()}<button class="icon-btn" id="out" aria-label="${t('logout')}">${ic('logout')}</button></div></header><main id="view"></main></div>
  <nav class="bottom glass">${mob.map(item).join('')}</nav></div>`;
  bindTop();
  $('#out').onclick = () => act(null, async () => { await api('/auth/logout', { method: 'POST', body: {} }); S.user = null; go('/login'); });
  return $('#view');
}

/* ---------- public pages ---------- */
function publicWrap(inner) { app.innerHTML = `<div class="auth"><div style="width:min(440px,100%)"><div class="row sp" style="margin-bottom:10px"><a href="/" data-link class="brand">${logo}<span>${esc(S.meta.brand)}</span></a><div class="row">${langSelect()}${themeBtn()}</div></div>${inner}</div></div>`; bindTop(); }
function landing() {
  app.innerHTML = `<div class="hero"><div class="row sp"><div class="brand">${logo}<span>${esc(S.meta.brand)}</span></div><div class="row">${langSelect()}${themeBtn()}</div></div>
  <h1>${t('hero')}</h1><p class="muted">${t('hero2')}</p>
  <div class="row" style="justify-content:center;margin:18px 0"><a class="btn" href="/register" data-link>${ic('user')} ${t('register')}</a><a class="btn ghost" href="/login" data-link>${ic('lock')} ${t('login')}</a></div>
  <div class="grid g2" style="text-align:start;margin-top:30px">
  <div class="card">${ic('shield')}<h2>Provider-verified</h2><p class="muted">Payments turn green only after the gateway's server API confirms the amount, currency and order.</p></div>
  <div class="card">${ic('qr')}<h2>QR & links</h2><p class="muted">Create hosted checkout links and scannable QR codes that work with PhonePe, FamPay and every UPI app.</p></div>
  <div class="card">${ic('lock')}<h2>High security</h2><p class="muted">Hashed passwords, encrypted keys, signed webhooks, idempotency, audit logs and role-based access.</p></div>
  <div class="card">${ic('globe')}<h2>Your gateway URL</h2><div class="url"><span class="mono">${esc(S.meta.base_url)}</span></div></div></div></div>`;
  bindTop();
}
function loginPg() {
  const p = new URLSearchParams(location.search);
  publicWrap(`<div class="card"><h1>${t('login')}</h1><form id="f">${field(t('email'), 'email', 'email', 'required autocomplete="username"')}${field(t('password'), 'password', 'password', 'required autocomplete="current-password"')}
  <div class="row sp mt"><button class="btn">${ic('lock')} ${t('login')}</button><a href="/forgot" data-link>${t('forgot')}</a></div></form><p class="muted">${S.meta.registration_open ? `<a href="/register" data-link>${t('register')}</a>` : ''}</p></div>`);
  if (p.get('verified') === '1') toast('Email verified. Please log in.'); if (p.get('verified') === '0') toast('Verification link invalid or expired.', 'err');
  $('#f').onsubmit = e => { e.preventDefault(); act(e.submitter, async () => { const d = await api('/auth/login', { method: 'POST', body: form(e.target) }); S.user = d.user; go(d.user.ecosystem ? '/dashboard' : '/onboarding'); }); };
}
function registerPg() {
  publicWrap(`<div class="card"><h1>${t('register')}</h1><form id="f">${field(t('name'), 'name', 'text', 'required minlength=2')}${field(t('email'), 'email', 'email', 'required')}${field(t('phone'), 'phone', 'tel', 'inputmode="numeric"')}${field(t('password'), 'password', 'password', 'required minlength=8 autocomplete="new-password"')}
  <p class="note mt">${ic('lock')} We never ask for Google/FamPay/PhonePe passwords, UPI PIN or OTP.</p><button class="btn mt">${ic('check')} ${t('register')}</button></form><p><a href="/login" data-link>${t('login')}</a></p></div>`);
  $('#f').onsubmit = e => { e.preventDefault(); act(e.submitter, async () => { const b = form(e.target); b.lang = S.lang; const d = await api('/auth/register', { method: 'POST', body: b }); toast(d.message); go('/login'); }); };
}
function forgotPg() {
  publicWrap(`<div class="card"><h1>${t('forgot')}</h1><form id="f">${field(t('email'), 'email', 'email', 'required')}<button class="btn mt">${ic('send')} Send link</button></form><p><a href="/login" data-link>${t('login')}</a></p></div>`);
  $('#f').onsubmit = e => { e.preventDefault(); act(e.submitter, async () => { const d = await api('/auth/forgot', { method: 'POST', body: form(e.target) }); toast(d.message); }); };
}
function resetPg() {
  const token = new URLSearchParams(location.search).get('token') || '';
  publicWrap(`<div class="card"><h1>Reset password</h1><form id="f">${field('New password', 'password', 'password', 'required minlength=8 autocomplete="new-password"')}<button class="btn mt">${ic('check')} ${t('save')}</button></form></div>`);
  $('#f').onsubmit = e => { e.preventDefault(); act(e.submitter, async () => { const d = await api('/auth/reset', { method: 'POST', body: { token, password: form(e.target).password } }); toast(d.message); go('/login'); }); };
}
function onboarding() {
  const opts = [['fampay', 'FamPay'], ['phonepe', 'PhonePe'], ['other', 'Other supported provider']];
  let sel = '';
  publicWrap(`<div class="card"><h1>${t('welcome')}, ${esc(S.user.name)}</h1><p class="muted">${t('choose_eco')}</p>${opts.map(o => `<div class="opt" data-v="${o[0]}">${ic('wallet')}<span>${o[1]}</span></div>`).join('')}
  <p class="note">Used only for personalisation. We never request passwords, UPI PIN or OTP.</p><button class="btn mt" id="go" disabled>${t('continue')}</button></div>`);
  app.querySelectorAll('.opt').forEach(el => el.onclick = () => { sel = el.dataset.v; app.querySelectorAll('.opt').forEach(x => x.classList.toggle('on', x === el)); $('#go').disabled = false; });
  $('#go').onclick = e => act(e.target, async () => { const d = await api('/user/profile', { method: 'PUT', body: { ecosystem: sel } }); S.user = d.user; go('/dashboard'); });
}

/* ---------- payments ---------- */
function statusCard(o) {
  const wait = !FINAL.includes(o.status);
  return `<div class="row sp"><div><div class="muted">Order</div><div class="mono">${esc(o.id)}</div></div>${badge(o.status)}</div>
  <h2>${inr(o.amount)} <span class="muted" style="font-size:.8rem">${esc(o.currency)} ${o.mode === 'test' ? badge('test') : ''}</span></h2><p class="muted">${esc(o.description)}</p>
  <p class="muted">Expires: ${fd(o.expires_at)}</p>
  ${o.status === 'paid' ? `<p class="note">${ic('shield')} Verified with the payment provider on ${fd(o.paid_at)}.</p>` : ''}
  ${o.status === 'mismatch' ? `<p class="note warn">Amount mismatch reported by provider. Contact support. ${esc(o.error || '')}</p>` : ''}
  ${wait && o.pay_url ? `<div class="row"><a class="btn" target="_blank" rel="noopener noreferrer" href="${esc(o.pay_url)}">${ic('external')} Pay now</a><button class="btn ghost" data-copy="${esc(o.pay_url)}">${ic('copy')} ${t('copy')}</button></div><p class="muted">${ic('clock')} Waiting for provider confirmation… this updates automatically.</p>` : ''}`;
}
function watch(id, el, onDone) {
  let n = 0;
  const tick = async () => {
    if (!document.body.contains(el)) return;
    try {
      const r = await api('/payment/verify', { method: 'POST', body: { order_id: id } });
      el.innerHTML = statusCard(r.order);
      if (FINAL.includes(r.order.status)) { if (r.order.status === 'paid') toast('Payment verified by provider'); if (onDone) onDone(r.order); return; }
    } catch (e) { if (e.status === 401) return; }
    if (++n < 360) setTimeout(tick, 5000);
  };
  setTimeout(tick, 2500);
}
document.addEventListener('click', e => { const b = e.target.closest('[data-copy]'); if (b) copy(b.dataset.copy); const a = e.target.closest('a[data-link]'); if (a) { e.preventDefault(); go(a.getAttribute('href')); } });

async function connectedProviders() { return (await api('/connect')).items.filter(c => c.status === 'connected'); }
function orderForm(kind, conns) {
  if (!conns.length) return `<div class="card"><p class="note warn">${ic('plug')} No payment provider connected yet. <a href="/connect" data-link>Open Connect</a> and add your gateway keys first.</p></div>`;
  return `<form id="f" class="card"><h2>${kind === 'qr' ? 'Create QR' : 'Create order'}</h2>${field(t('amount') + ' (₹)', 'amount', 'number', 'required min="1" step="0.01" inputmode="decimal"')}${field(t('description'), 'description', 'text', 'required maxlength=200')}
  <label>Provider</label><select name="provider">${conns.map(c => `<option value="${c.provider}">${c.provider} (${c.mode})</option>`).join('')}</select>
  ${field('Customer name (optional)', 'customer_name')}${field('Customer phone (required for Cashfree)', 'customer_phone', 'tel')}${field('Customer email (optional)', 'customer_email', 'email')}
  <label>Expires in</label><select name="expires_minutes"><option value="15">15 minutes</option><option value="60" selected>1 hour</option><option value="1440">24 hours</option><option value="10080">7 days</option></select>
  <button class="btn mt">${ic(kind === 'qr' ? 'qr' : 'plus')} ${t('create')}</button></form>`;
}
function orderBody(f) { const b = form(f); b.amount = parseFloat(b.amount); b.expires_minutes = parseInt(b.expires_minutes, 10); b.idempotency_key = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random()); Object.keys(b).forEach(k => b[k] === '' && delete b[k]); return b; }

async function orderPg(v) {
  const conns = await connectedProviders();
  v.innerHTML = `<h1>${t('order')}</h1><div class="grid g2"><div>${orderForm('order', conns)}</div><div id="res"></div></div><div class="card"><h2>${t('transactions')}</h2><div id="list"></div></div>`;
  const list = async () => { const d = await api('/orders'); $('#list').innerHTML = tbl(['ID', t('amount'), t('description'), t('status'), 'Created', ''], d.items.map(o => `<tr><td class="mono">${esc(o.id)}</td><td>${inr(o.amount)}</td><td>${esc(o.description)}</td><td>${badge(o.status)}</td><td>${fd(o.created_at)}</td><td><a class="btn sm ghost" href="/verify?order=${esc(o.id)}" data-link>${t('verify')}</a></td></tr>`)); };
  list();
  const f = $('#f'); if (f) f.onsubmit = e => { e.preventDefault(); act(e.submitter, async () => { const d = await api('/order/create', { method: 'POST', body: orderBody(f) }); const r = $('#res'); r.className = 'card'; r.innerHTML = statusCard(d.order); watch(d.order.id, r, list); list(); f.reset(); }); };
}
async function verifyPg(v) {
  const pre = new URLSearchParams(location.search).get('order') || '';
  v.innerHTML = `<h1>${t('verify')}</h1><form id="f" class="card">${field('Order ID', 'order_id', 'text', `required value="${esc(pre)}" placeholder="ZP…"`)}<p class="note">${ic('shield')} Status is fetched from the payment provider's server API. Screenshots or reference numbers are never accepted as proof.</p><button class="btn mt">${ic('shield')} ${t('verify')}</button></form><div id="res"></div>`;
  const run = id => act($('#f button'), async () => { const r = await api('/payment/verify', { method: 'POST', body: { order_id: id.trim() } }); const el = $('#res'); el.className = 'card'; el.innerHTML = statusCard(r.order); if (!FINAL.includes(r.order.status)) watch(r.order.id, el); });
  $('#f').onsubmit = e => { e.preventDefault(); run(form(e.target).order_id); };
  if (pre) run(pre);
}
async function qrPg(v) {
  const conns = await connectedProviders();
  v.innerHTML = `<h1>${t('qr')}</h1><div class="grid g2"><div>${orderForm('qr', conns)}</div><div class="card"><p class="note">${ic('qr')} The QR opens the provider-hosted UPI checkout. Scan it with PhonePe, FamPay, GPay, Paytm or any UPI app. QR expires with the order.</p></div></div><div id="list" class="grid g2"></div>`;
  let polls = 0;
  const load = async () => {
    const d = await api('/qr');
    $('#list').innerHTML = d.items.map(q => `<div class="card c"><img class="qrimg" alt="QR" src="data:image/svg+xml;utf8,${encodeURIComponent(q.svg)}"><h2>${inr(q.amount)} ${badge(q.status)}</h2><div class="mono">${esc(q.order_id)}</div><p class="muted">${esc(q.description)}<br>Expires ${fd(q.expires_at)}</p>
    <div class="row" style="justify-content:center"><a class="btn sm ghost" href="/api/qr/${esc(q.id)}.svg">${ic('download')} SVG</a><button class="btn sm ghost" data-png="${esc(q.id)}">${ic('download')} PNG</button><button class="btn sm ghost" data-copy="${esc(q.pay_url)}">${ic('copy')} ${t('copy')}</button></div></div>`).join('') || `<p class="muted">${t('empty')}</p>`;
    $('#list').querySelectorAll('[data-png]').forEach((b, i) => b.onclick = () => { const q = d.items[i]; const img = new Image(); img.onload = () => { const c = document.createElement('canvas'); c.width = c.height = 800; const x = c.getContext('2d'); x.fillStyle = '#fff'; x.fillRect(0, 0, 800, 800); x.drawImage(img, 0, 0, 800, 800); const a = document.createElement('a'); a.href = c.toDataURL('image/png'); a.download = `zadpay-${q.order_id}.png`; a.click(); }; img.src = 'data:image/svg+xml;utf8,' + encodeURIComponent(q.svg); });
    const pend = d.items.filter(q => !FINAL.includes(q.status));
    if (pend.length && polls++ < 120 && document.body.contains($('#list'))) { await Promise.all(pend.map(q => api('/payment/verify', { method: 'POST', body: { order_id: q.order_id } }).catch(() => 0))); setTimeout(load, 6000); }
  };
  load();
  const f = $('#f'); if (f) f.onsubmit = e => { e.preventDefault(); act(e.submitter, async () => { await api('/qr/create', { method: 'POST', body: orderBody(f) }); toast('QR created'); f.reset(); polls = 0; load(); }); };
}
async function linksPg(v) {
  const d = await api('/orders');
  v.innerHTML = `<h1>${t('links')}</h1><div class="card">${tbl(['ID', t('amount'), t('status'), 'Link', ''], d.items.filter(o => o.pay_url).map(o => `<tr><td class="mono">${esc(o.id)}</td><td>${inr(o.amount)}</td><td>${badge(o.status)}</td><td><button class="btn sm ghost" data-copy="${esc(o.pay_url)}">${ic('copy')} ${t('copy')}</button> <a class="btn sm ghost" target="_blank" rel="noopener noreferrer" href="${esc(o.pay_url)}">${ic('external')}</a></td><td>${['created', 'pending'].includes(o.status) ? `<button class="btn sm danger" data-cancel="${esc(o.id)}">Cancel</button>` : ''}</td></tr>`))}</div>`;
  v.querySelectorAll('[data-cancel]').forEach(b => b.onclick = () => act(b, async () => { await api(`/order/${b.dataset.cancel}/cancel`, { method: 'POST', body: {} }); toast('Order cancelled'); linksPg(v); }));
}
async function txnPg(v) {
  const d = await api('/transactions');
  v.innerHTML = `<h1>${t('transactions')}</h1><div class="card">${tbl(['ID', 'Order', 'Provider', t('amount'), t('status'), 'Date'], d.items.map(x => `<tr><td class="mono">${esc(x.id)}</td><td class="mono">${esc(x.order_id)}</td><td>${esc(x.provider)} ${x.mode === 'test' ? badge('test') : ''}</td><td>${inr(x.amount)}</td><td>${badge(x.status)}</td><td>${fd(x.created_at)}</td></tr>`))}</div>`;
}
async function connectPg(v) {
  const d = await api('/connect'); const by = Object.fromEntries(d.items.map(i => [i.provider, i]));
  const eco = { fampay: 'FamPay has no public merchant API. Customers can still pay with FamPay by scanning your UPI QR from the gateway below.', phonepe: 'Customers can pay from PhonePe via the hosted UPI checkout of your gateway.', other: '' }[S.user.ecosystem] || '';
  v.innerHTML = `<h1>${t('connect')}</h1>${eco ? `<p class="note">${ic('wallet')} ${esc(eco)}</p>` : ''}<p class="note mt">${ic('lock')} Keys are encrypted at rest and never sent back to the browser. Use <b>test</b> mode for sandbox keys: no real money moves and orders are labelled TEST.</p><div class="grid g2 mt">${S.meta.providers.map(p => {
    const c = by[p.id];
    return `<div class="card"><div class="row sp"><h2>${esc(p.name)}</h2>${c ? badge(c.status) : badge('inactive')}</div><p class="muted">${esc(p.note)}</p>
    ${c ? `<p class="muted">Key ${esc(c.key_id)} · ${esc(c.mode)} · checked ${fd(c.last_check)} ${c.last_error ? `<br><span style="color:var(--err)">${esc(c.last_error)}</span>` : ''}</p>
    <label>Webhook URL (paste in ${esc(p.name)} dashboard)</label><div class="url"><span class="mono">${esc(c.webhook_url)}</span><button class="btn sm ghost" data-copy="${esc(c.webhook_url)}">${ic('copy')}</button></div><p class="muted">Events: ${esc(p.webhook_events)}${p.needs_webhook_secret ? (c.webhook_secret_set ? '' : '<br><b>Webhook secret not set - add it below to enable instant webhooks.</b>') : ''}</p>
    <div class="row"><button class="btn sm ghost" data-check="${p.id}">${ic('refresh')} ${t('check')}</button><button class="btn sm danger" data-del="${p.id}">${ic('trash')} ${t('disconnect')}</button></div><hr style="border-color:var(--line)">` : ''}
    <form data-prov="${p.id}">${field(p.key_label, 'key_id', 'text', 'required autocomplete="off"')}${field(p.secret_label, 'key_secret', 'password', 'required autocomplete="off"')}${p.needs_webhook_secret ? field('Webhook secret (set the same in Razorpay)', 'webhook_secret', 'password', 'autocomplete="off"') : ''}
    <label>Mode</label><select name="mode"><option value="test">test (sandbox)</option><option value="live">live (real money)</option></select><button class="btn mt">${ic('plug')} ${c ? 'Update' : t('connect')}</button></form></div>`;
  }).join('')}</div>`;
  v.querySelectorAll('form[data-prov]').forEach(f => f.onsubmit = e => { e.preventDefault(); act(e.submitter, async () => { const b = form(f); b.provider = f.dataset.prov; await api('/connect', { method: 'POST', body: b }); toast('Provider connected and credentials verified'); connectPg(v); }); });
  v.querySelectorAll('[data-check]').forEach(b => b.onclick = () => act(b, async () => { const r = await api(`/connect/${b.dataset.check}/check`, { method: 'POST', body: {} }); toast(r.item.status === 'connected' ? 'Healthy' : (r.item.last_error || 'Unhealthy'), r.item.status === 'connected' ? 'ok' : 'err'); connectPg(v); }));
  v.querySelectorAll('[data-del]').forEach(b => b.onclick = () => { if (confirm('Disconnect this provider? Pending orders can no longer be verified.')) act(b, async () => { await api('/connect/' + b.dataset.del, { method: 'DELETE' }); connectPg(v); }); });
}

/* ---------- dashboard & user pages ---------- */
async function dashPg(v) {
  const d = await api('/dashboard');
  const st = (l, n, i) => `<div class="card stat"><div class="l">${ic(i)} ${l}</div><div class="n">${n}</div></div>`;
  v.innerHTML = `<h1>${t('dashboard')}</h1><div class="grid g4">${st(t('total'), d.total, 'list')}${st(t('paid'), d.paid, 'check')}${st(t('pending'), d.pending, 'clock')}${st(t('failed'), d.failed, 'x')}</div>
  <div class="grid g2"><div class="card"><div class="l muted">Received (verified)</div><div class="n" style="font-size:1.8rem;font-weight:800">${inr(d.received)}</div><p class="muted">${t('subscription')}: <b>${esc(d.plan)}</b> ${d.plan_expires ? '· until ' + fd(d.plan_expires) : ''}</p>${d.providers.length ? d.providers.map(p => `<span class="badge b-${p.status}">${esc(p.provider)} ${esc(p.mode)}</span> `).join('') : `<a class="btn sm" href="/connect" data-link>${ic('plug')} ${t('connect')}</a>`}</div>
  <div class="card"><h2>${ic('globe')} Gateway URL</h2><div class="url"><span class="mono">${esc(S.meta.base_url)}</span><button class="btn sm ghost" data-copy="${esc(S.meta.base_url)}">${ic('copy')}</button></div><p class="muted">Detected automatically from your hosting. Webhook base: <span class="mono">${esc(S.meta.webhook_base)}&lt;id&gt;</span></p></div></div>
  <div class="card"><div class="row sp"><h2>Recent</h2><a href="/order" data-link class="btn sm">${ic('plus')} ${t('order')}</a></div>${tbl(['ID', t('amount'), t('status'), 'Date'], d.recent.map(o => `<tr><td class="mono">${esc(o.id)}</td><td>${inr(o.amount)}</td><td>${badge(o.status)}</td><td>${fd(o.created_at)}</td></tr>`))}</div>`;
}
async function subPg(v) {
  const d = await api('/subscription');
  v.innerHTML = `<h1>${t('subscription')}</h1><p class="note">Current plan: <b>${esc(d.plan)}</b> ${d.expires_at ? '· expires ' + fd(d.expires_at) : ''}${d.custom_price !== null && d.custom_price !== undefined ? ` · your custom price ${inr(d.custom_price)}` : ''}. No automatic deductions - you pay manually each period.</p>
  ${d.payments_ready ? '' : `<p class="note warn mt">Paid plans are unavailable until the owner connects a payment gateway.</p>`}
  <div class="grid g2 mt">${d.plans.map(p => `<div class="card plan"><div class="row sp"><h2>${esc(p.name)}</h2>${p.code === d.plan_code ? badge('active') : ''}</div><div class="p">${inr(d.custom_price !== null && d.custom_price !== undefined && p.code !== 'free' ? d.custom_price : p.price)}<span class="muted" style="font-size:.8rem"> / ${p.days} days</span></div><ul>${p.features.map(f => `<li>${esc(f)}</li>`).join('')}</ul>
  ${p.code !== 'free' ? `<form data-plan="${esc(p.code)}"><input name="code" placeholder="Discount code (optional)" maxlength="30"><button class="btn mt">${ic('card')} Subscribe</button></form>` : ''}</div>`).join('')}</div>
  <div class="card"><h2>History</h2>${tbl(['Plan', t('status'), 'Price', 'Source', 'Expires'], d.history.map(h => `<tr><td>${esc(h.plan)}</td><td>${badge(h.status)}</td><td>${inr(h.price)}</td><td>${esc(h.source)}</td><td>${fd(h.expires_at)}</td></tr>`))}</div>`;
  v.querySelectorAll('form[data-plan]').forEach(f => f.onsubmit = e => { e.preventDefault(); act(e.submitter, async () => { const r = await api('/subscription/checkout', { method: 'POST', body: { plan: f.dataset.plan, code: form(f).code || null } }); if (r.activated) { toast('Plan activated'); subPg(v); } else location.href = r.order.pay_url; }); });
}
async function supportPg(v) {
  const d = await api('/tickets');
  v.innerHTML = `<h1>${t('support')}</h1><div class="grid g2"><form id="f" class="card"><h2>New ticket</h2>${field('Subject', 'subject', 'text', 'required minlength=3 maxlength=120')}<label>Message</label><textarea name="body" rows="4" required minlength=3 maxlength=3000></textarea><button class="btn mt">${ic('send')} Send</button></form>
  <div class="card"><h2>Tickets</h2>${tbl(['ID', 'Subject', t('status'), ''], d.items.map(x => `<tr><td class="mono">${esc(x.id)}</td><td>${esc(x.subject)}</td><td>${badge(x.status)}</td><td><button class="btn sm ghost" data-t="${esc(x.id)}">${t('open')}</button></td></tr>`))}</div></div>`;
  $('#f').onsubmit = e => { e.preventDefault(); act(e.submitter, async () => { await api('/tickets', { method: 'POST', body: form(e.target) }); toast('Ticket sent'); supportPg(v); }); };
  v.querySelectorAll('[data-t]').forEach(b => b.onclick = () => ticketView(b.dataset.t, '/tickets/', '/tickets/'));
}
async function ticketView(id, getP, postP, after) {
  const d = await api(getP + id);
  const m = modal(`<h2>${esc(d.ticket.subject)}</h2><div id="msgs">${d.messages.map(x => `<p class="${x.is_staff ? 'note' : ''}"><b>${x.is_staff ? 'Support' : 'User'}</b> · <span class="muted">${fd(x.created_at)}</span><br>${esc(x.body).replace(/\n/g, '<br>')}</p>`).join('')}</div>
  <form id="rf"><textarea name="body" rows="3" maxlength="3000" placeholder="Reply…"></textarea>${postP.includes('admin') ? `<label>Status</label><select name="status"><option>answered</option><option>open</option><option>closed</option></select>` : ''}<button class="btn mt">${ic('send')} Reply</button></form>`);
  $('#rf', m).onsubmit = e => { e.preventDefault(); act(e.submitter, async () => { await api(postP + id + '/reply', { method: 'POST', body: form(e.target) }); toast('Sent'); m.remove(); if (after) after(); else ticketView(id, getP, postP, after); }); };
}
async function notifPg(v) {
  const d = await api('/notifications'); api('/notifications/read', { method: 'POST', body: {} }).catch(() => 0);
  v.innerHTML = `<h1>${t('notifications')}</h1>${d.items.map(n => `<div class="card"><b>${esc(n.title)}</b> ${n.read ? '' : badge('new')}<p class="muted">${esc(n.body)}</p><small class="muted">${fd(n.created_at)}</small></div>`).join('') || `<p class="muted">${t('empty')}</p>`}`;
}
async function activityPg(v) {
  const d = await api('/activity');
  v.innerHTML = `<h1>${t('activity')}</h1><div class="card">${tbl(['Action', 'Target', 'IP', 'Time'], d.items.map(a => `<tr><td>${esc(a.action)}</td><td>${esc(a.target)}</td><td class="mono">${esc(a.ip)}</td><td>${fd(a.created_at)}</td></tr>`))}</div>`;
}
async function profilePg(v) {
  const [pr, ss, ks] = await Promise.all([api('/user/profile'), api('/user/sessions'), api('/keys')]); const u = pr.user;
  v.innerHTML = `<h1>${t('profile')}</h1><div class="grid g2"><form id="pf" class="card"><h2>${t('profile')}</h2>${field(t('name'), 'name', 'text', `value="${esc(u.name)}" required minlength=2`)}${field(t('phone'), 'phone', 'tel', `value="${esc(u.phone || '')}"`)}<label>${t('email')}</label><input value="${esc(u.email)}" disabled>
  <label>Payment ecosystem</label><select name="ecosystem">${[['fampay', 'FamPay'], ['phonepe', 'PhonePe'], ['other', 'Other']].map(o => `<option value="${o[0]}" ${u.ecosystem === o[0] ? 'selected' : ''}>${o[1]}</option>`).join('')}</select><p class="muted">Plan: ${esc(pr.plan)}</p><button class="btn mt">${ic('check')} ${t('save')}</button></form>
  <form id="pw" class="card"><h2>${t('password')}</h2>${field('Current password', 'current', 'password', 'required autocomplete="current-password"')}${field('New password', 'new', 'password', 'required minlength=8 autocomplete="new-password"')}<button class="btn mt">${ic('lock')} ${t('save')}</button></form></div>
  <div class="card"><h2>Sessions</h2>${tbl(['Device', 'IP', 'Started', ''], ss.sessions.map(s => `<tr><td>${esc((s.ua || '').slice(0, 50))}</td><td class="mono">${esc(s.ip)}</td><td>${fd(s.created_at)}</td><td>${s.current ? badge('active') : `<button class="btn sm danger" data-s="${s.id}">${t('disconnect')}</button>`}</td></tr>`))}</div>
  <div class="card"><h2>API keys</h2><p class="muted">Use <span class="mono">Authorization: Bearer zk_…</span> with /api/order/create, /api/order/{id}, /api/orders, /api/transactions, /api/payment/verify.</p><form id="kf" class="row"><input name="name" placeholder="Key name" required minlength=2 style="max-width:240px"><button class="btn">${ic('plus')} ${t('create')}</button></form>
  ${tbl(['Name', 'Prefix', t('status'), 'Last used', ''], ks.items.map(k => `<tr><td>${esc(k.name)}</td><td class="mono">${esc(k.prefix)}…</td><td>${badge(k.revoked ? 'cancelled' : 'active')}</td><td>${fd(k.last_used)}</td><td>${k.revoked ? '' : `<button class="btn sm danger" data-k="${esc(k.id)}">${ic('trash')}</button>`}</td></tr>`))}</div>`;
  $('#pf').onsubmit = e => { e.preventDefault(); act(e.submitter, async () => { const r = await api('/user/profile', { method: 'PUT', body: form(e.target) }); S.user = r.user; toast('Saved'); }); };
  $('#pw').onsubmit = e => { e.preventDefault(); act(e.submitter, async () => { await api('/user/password', { method: 'POST', body: form(e.target) }); toast('Password changed'); e.target.reset(); }); };
  $('#kf').onsubmit = e => { e.preventDefault(); act(e.submitter, async () => { const r = await api('/keys', { method: 'POST', body: form(e.target) }); modal(`<h2>Your API key</h2><p class="note warn">${esc(r.note)}</p><div class="url"><span class="mono">${esc(r.key)}</span><button class="btn sm ghost" data-copy="${esc(r.key)}">${ic('copy')}</button></div>`); profilePg(v); }); };
  v.querySelectorAll('[data-s]').forEach(b => b.onclick = () => act(b, async () => { await api('/user/sessions/' + b.dataset.s, { method: 'DELETE' }); profilePg(v); }));
  v.querySelectorAll('[data-k]').forEach(b => b.onclick = () => act(b, async () => { await api('/keys/' + b.dataset.k, { method: 'DELETE' }); profilePg(v); }));
}

/* ---------- admin ---------- */
function tabs(v, list, load) {
  v.querySelector('.tabs').innerHTML = list.map(([k, l]) => `<button class="btn ghost sm" data-tab="${k}">${l}</button>`).join('');
  const sel = k => { v.querySelectorAll('[data-tab]').forEach(b => b.style.background = b.dataset.tab === k ? 'rgba(20,86,240,.15)' : ''); const box = v.querySelector('.pane'); box.innerHTML = '<div class="boot" style="height:120px"><div class="spin"></div></div>'; act(null, () => load(k, box)); };
  v.querySelectorAll('[data-tab]').forEach(b => b.onclick = () => sel(b.dataset.tab)); sel(list[0][0]);
}
async function adminPg(v) {
  v.innerHTML = `<h1>${t('admin')}</h1><div class="tabs"></div><div class="pane"></div>`;
  tabs(v, [['users', 'Users'], ['orders', 'Orders'], ['txns', 'Transactions'], ['prov', 'Providers'], ['tickets', 'Tickets'], ['announce', 'Announce'], ['logs', 'Activity logs'], ['export', 'Reports']], async (k, box) => {
    if (k === 'users') {
      box.innerHTML = `<form id="sf" class="row"><input name="search" placeholder="Search email / name / ID" style="max-width:300px"><select name="status" style="width:auto"><option value="">All</option><option>active</option><option>suspended</option><option>blocked</option><option>inactive</option></select><button class="btn">${ic('search')}</button></form><div id="ul" class="card mt"></div>`;
      const load = async () => { const f = form($('#sf')); const d = await api(`/admin/users?search=${encodeURIComponent(f.search)}&status=${f.status}`); $('#ul').innerHTML = tbl(['Name', t('email'), 'Role', t('status'), 'Plan', 'Joined', ''], d.items.map(u => `<tr><td>${esc(u.name)}</td><td>${esc(u.email)}</td><td>${badge(u.role)}</td><td>${badge(u.status)}</td><td>${esc(u.plan)}</td><td>${fd(u.created_at)}</td><td><button class="btn sm ghost" data-u="${esc(u.id)}">Manage</button></td></tr>`)); $('#ul').querySelectorAll('[data-u]').forEach(b => b.onclick = () => manageUser(b.dataset.u, load)); };
      $('#sf').onsubmit = e => { e.preventDefault(); act(null, load); }; load();
    } else if (k === 'orders') {
      box.innerHTML = `<form id="sf" class="row"><input name="search" placeholder="Order ID / email" style="max-width:260px"><select name="status" style="width:auto"><option value="">All</option><option value="failed,expired,cancelled,mismatch">Failed</option><option>paid</option><option value="created,pending">Pending</option></select><button class="btn">${ic('search')}</button></form><div id="ol" class="card mt"></div>`;
      const load = async () => { const f = form($('#sf')); const d = await api(`/admin/orders?search=${encodeURIComponent(f.search)}&status=${encodeURIComponent(f.status)}`); $('#ol').innerHTML = tbl(['ID', 'User', t('amount'), t('status'), 'Provider', 'Purpose', 'Date'], d.items.map(o => `<tr><td class="mono">${esc(o.id)}</td><td>${esc(o.email)}</td><td>${inr(o.amount)}</td><td>${badge(o.status)}</td><td>${esc(o.provider)} ${esc(o.mode)}</td><td>${esc(o.purpose)}</td><td>${fd(o.created_at)}</td></tr>`)); };
      $('#sf').onsubmit = e => { e.preventDefault(); act(null, load); }; load();
    } else if (k === 'txns') {
      box.innerHTML = `<form id="sf" class="row"><input name="search" placeholder="Transaction / order / payment ID" style="max-width:320px"><button class="btn">${ic('search')}</button></form><div id="tl" class="card mt"></div>`;
      const load = async () => { const d = await api('/admin/transactions?search=' + encodeURIComponent(form($('#sf')).search)); $('#tl').innerHTML = tbl(['ID', 'Order', 'User', 'Provider payment', t('amount'), t('status'), 'Date'], d.items.map(x => `<tr><td class="mono">${esc(x.id)}</td><td class="mono">${esc(x.order_id)}</td><td>${esc(x.email)}</td><td class="mono">${esc(x.provider_payment_id)}</td><td>${inr(x.amount)}</td><td>${badge(x.status)}</td><td>${fd(x.created_at)}</td></tr>`)); };
      $('#sf').onsubmit = e => { e.preventDefault(); act(null, load); }; load();
    } else if (k === 'prov') {
      const d = await api('/admin/providers'); box.innerHTML = `<div class="card">${tbl(['User', 'Provider', 'Mode', 'Health', 'Last check', 'Error'], d.items.map(p => `<tr><td>${esc(p.email)}</td><td>${esc(p.provider)}</td><td>${esc(p.mode)}</td><td>${badge(p.status)}</td><td>${fd(p.last_check)}</td><td>${esc(p.last_error || '')}</td></tr>`))}</div>`;
    } else if (k === 'tickets') {
      const load = async () => { const d = await api('/admin/tickets'); box.innerHTML = `<div class="card">${tbl(['ID', 'User', 'Subject', t('status'), 'Updated', ''], d.items.map(x => `<tr><td class="mono">${esc(x.id)}</td><td>${esc(x.email)}</td><td>${esc(x.subject)}</td><td>${badge(x.status)}</td><td>${fd(x.updated_at)}</td><td><button class="btn sm ghost" data-t="${esc(x.id)}">${t('open')}</button></td></tr>`))}</div>`; box.querySelectorAll('[data-t]').forEach(b => b.onclick = () => ticketView(b.dataset.t, '/admin/tickets/', '/admin/tickets/', load)); };
      await load();
    } else if (k === 'announce') {
      box.innerHTML = `<form id="af" class="card">${field('Title', 'title', 'text', 'required maxlength=120')}<label>Message</label><textarea name="body" rows="4" required maxlength=600></textarea><button class="btn mt">${ic('bell')} Send to all active users</button></form>`;
      $('#af').onsubmit = e => { e.preventDefault(); act(e.submitter, async () => { await api('/admin/announce', { method: 'POST', body: form(e.target) }); toast('Announcement sent'); e.target.reset(); }); };
    } else if (k === 'logs') {
      const d = await api('/admin/logs'); box.innerHTML = `<div class="card">${tbl(['Who', 'Action', 'Target', 'Detail', 'IP', 'Time'], d.items.map(l => `<tr><td>${esc(l.actor || 'system')}</td><td>${esc(l.action)}</td><td>${esc(l.target)}</td><td>${esc(l.detail)}</td><td class="mono">${esc(l.ip)}</td><td>${fd(l.created_at)}</td></tr>`))}</div>`;
    } else if (k === 'export') {
      box.innerHTML = `<div class="card row">${['users', 'orders', 'transactions'].map(x => `<a class="btn" href="/api/admin/export/${x}">${ic('download')} ${x}.csv</a>`).join('')}</div>`;
    }
  });
}
async function manageUser(id, reload) {
  const d = await api('/admin/users/' + id); const u = d.user; const own = S.user.role === 'owner';
  const plans = S.meta.plans.filter(p => p.code !== 'free');
  const m = modal(`<h2>${esc(u.name)} ${badge(u.role)} ${badge(u.status)}</h2><p class="muted">${esc(u.email)} · ${esc(u.phone || 'no phone')} · ecosystem ${esc(u.ecosystem || '—')}<br>Orders ${d.orders} (paid ${d.paid}) · Plan ${esc(d.plan)} ${d.plan_expires ? 'until ' + fd(d.plan_expires) : ''}<br>Providers: ${d.providers.map(p => esc(p.provider) + ' ' + esc(p.status)).join(', ') || 'none'}</p>
  ${u.role === 'owner' ? '<p class="note">Owner accounts cannot be modified.</p>' : `<div class="row">${u.status === 'blocked' ? `<button class="btn sm" data-a="unblock">Unblock</button>` : `<button class="btn sm danger" data-a="block">Block</button>`}<button class="btn sm ghost" data-a="s-suspended">Suspend</button><button class="btn sm ghost" data-a="s-inactive">Deactivate</button><button class="btn sm ghost" data-a="s-active">Activate</button><button class="btn sm ghost" data-a="reset">Reset link</button></div>
  <h3 class="mt">Subscription</h3><div class="row"><select id="sp" style="width:auto">${plans.map(p => `<option value="${p.code}">${esc(p.name)}</option>`).join('')}</select><input id="sd" type="number" value="30" min="1" style="width:90px"><button class="btn sm" data-a="grant">Grant free</button><button class="btn sm ghost" data-a="extend">Extend</button><button class="btn sm danger" data-a="cancel">Cancel</button></div>
  ${own ? `<h3 class="mt">Owner controls</h3><div class="row"><input id="cp" type="number" step="0.01" min="0" placeholder="Custom monthly ₹ (blank = default)" style="max-width:260px" value="${u.custom_price !== null && u.custom_price !== undefined ? u.custom_price / 100 : ''}"><button class="btn sm" data-a="price">Set price</button></div>
  <div class="row mt">${PERMS.map(p => `<label style="margin:0"><input type="checkbox" class="pm" value="${p}" style="width:auto" ${(u.perms || '').split(',').includes(p) || u.role !== 'admin' ? 'checked' : ''}> ${p}</label>`).join('')}</div><div class="row mt">${u.role === 'admin' ? `<button class="btn sm" data-a="perms">Save permissions</button><button class="btn sm danger" data-a="demote">Demote to user</button>` : `<button class="btn sm" data-a="promote">Promote to admin</button>`}</div>` : ''}`}`);
  m.addEventListener('click', e => { const b = e.target.closest('[data-a]'); if (!b) return; const a = b.dataset.a; const perms = [...m.querySelectorAll('.pm:checked')].map(x => x.value);
    act(b, async () => {
      const P = (p, body = {}) => api(`/admin/users/${id}${p}`, { method: 'POST', body });
      if (a === 'block') await P('/block'); else if (a === 'unblock') await P('/unblock'); else if (a.startsWith('s-')) await P('/status', { status: a.slice(2) });
      else if (a === 'reset') { const r = await P('/reset-link'); modal(`<h2>Reset link</h2><div class="url"><span class="mono">${esc(r.link)}</span><button class="btn sm ghost" data-copy="${esc(r.link)}">${ic('copy')}</button></div><p class="muted">${esc(r.note)}</p>`); return; }
      else if (['grant', 'extend'].includes(a)) await P('/subscription', { action: a, plan: $('#sp', m).value, days: parseInt($('#sd', m).value, 10) || 30 }); else if (a === 'cancel') await P('/subscription', { action: 'cancel' });
      else if (a === 'price') await api(`/owner/users/${id}/price`, { method: 'POST', body: { price: $('#cp', m).value === '' ? null : parseFloat($('#cp', m).value) } });
      else if (a === 'promote') await api(`/owner/users/${id}/promote`, { method: 'POST', body: { perms } }); else if (a === 'demote') await api(`/owner/users/${id}/demote`, { method: 'POST', body: {} }); else if (a === 'perms') await api(`/owner/users/${id}/perms`, { method: 'POST', body: { perms } });
      toast('Done'); m.remove(); reload();
    }); });
}

/* ---------- owner ---------- */
async function ownerPg(v) {
  const st = await api('/owner/state');
  if (!st.elevated) {
    v.innerHTML = `<h1>${t('owner')}</h1><form id="f" class="card" style="max-width:420px"><h2>${ic('lock')} Owner Control Center</h2><p class="muted">Re-enter your password to unlock for 10 minutes. Every action is audit-logged.</p>${field(t('password'), 'password', 'password', 'required autocomplete="current-password"')}<button class="btn mt">${ic('lock')} Unlock</button></form>`;
    $('#f').onsubmit = e => { e.preventDefault(); act(e.submitter, async () => { await api('/owner/unlock', { method: 'POST', body: form(e.target) }); ownerPg(v); }); }; return;
  }
  v.innerHTML = `<h1>${t('owner')}</h1><div class="tabs"></div><div class="pane"></div>`;
  tabs(v, [['analytics', 'Analytics'], ['health', 'System health'], ['plans', 'Plans & pricing'], ['discounts', 'Discounts'], ['admins', 'Admins'], ['settings', 'Settings'], ['audit', 'Audit logs'], ['keys', 'API access']], async (k, box) => {
    if (k === 'analytics') {
      const d = await api('/owner/analytics'); const n = s => (d.orders.find(o => o.status === s) || { n: 0 }).n;
      const mx = Math.max(1, ...d.series.map(s => s.s));
      box.innerHTML = `<div class="grid g4">${[['Users', d.users], ['Admins', d.admins], ['Paid orders', n('paid')], ['Failed', n('failed') + n('expired') + n('cancelled') + n('mismatch')], ['Merchant volume', inr(d.volume)], ['Subscription revenue', inr(d.subscription_revenue)], ['Active subs', d.active_subs]].map(x => `<div class="card stat"><div class="l">${x[0]}</div><div class="n">${x[1]}</div></div>`).join('')}</div>
      <div class="card"><h2>Paid volume, last 14 days</h2>${d.series.map(s => `<div class="row" style="flex-wrap:nowrap"><span class="mono" style="width:90px">${esc(s.d)}</span><div style="flex:1;background:var(--bg2);border-radius:8px"><div style="width:${Math.max(3, s.s / mx * 100)}%;background:var(--grad);height:14px;border-radius:8px"></div></div><span>${inr(s.s)}</span></div>`).join('') || `<p class="muted">${t('empty')}</p>`}</div>`;
    } else if (k === 'health') {
      const d = await api('/owner/health');
      box.innerHTML = `<div class="card"><p>Gateway URL (auto-detected): <span class="mono">${esc(d.base_url)}</span></p><p>Uptime ${Math.floor(d.uptime_s / 60)} min · Python ${esc(d.python)} · DB ${d.db_ok ? badge('active') : badge('error')} ${(d.db_size / 1024).toFixed(0)} KB · Email ${d.email_enabled ? badge('active') : badge('inactive')} · Providers connected ${d.providers_connected}</p><p class="muted">Data dir: ${esc(d.data_dir)}</p>${d.warnings.map(w => `<p class="note warn">${ic('alert')} ${esc(w)}</p>`).join('') || `<p class="note">${ic('check')} No warnings.</p>`}<p><a href="/api/docs" target="_blank" rel="noopener">API documentation</a></p></div>`;
    } else if (k === 'plans') {
      const d = await api('/owner/plans');
      const pf = p => `<form class="card" data-code="${esc(p.code)}"><h2>${esc(p.code)}</h2><div class="grid g2"><div>${field('Name', 'name', 'text', `value="${esc(p.name)}" required`)}${field('Price per period (₹)', 'price', 'number', `value="${p.price / 100}" min="0" step="0.01" required`)}${field('Days', 'days', 'number', `value="${p.days}" min="1"`)}</div><div>${field('Order limit (blank = unlimited)', 'order_limit', 'number', `value="${p.order_limit || ''}" min="0"`)}${field('Features (comma separated)', 'features', 'text', `value="${esc(p.features.join(', '))}"`)}<label><input type="checkbox" name="enabled" style="width:auto" ${p.enabled ? 'checked' : ''}> Enabled</label></div></div><button class="btn mt">${ic('check')} ${t('save')}</button></form>`;
      box.innerHTML = d.items.map(pf).join('') + pf({ code: '', name: '', price: 0, days: 30, order_limit: '', features: [], enabled: true }).replace(`<h2></h2>`, `<h2>New plan</h2><input name="newcode" placeholder="code e.g. gold" pattern="[a-z0-9_]{2,20}" required>`);
      box.querySelectorAll('form[data-code]').forEach(f => f.onsubmit = e => { e.preventDefault(); act(e.submitter, async () => { const x = new FormData(f); const code = f.dataset.code || x.get('newcode'); await api('/owner/plans/' + code, { method: 'PUT', body: { name: x.get('name'), price: parseFloat(x.get('price')), days: parseInt(x.get('days'), 10) || 30, enabled: x.get('enabled') === 'on', order_limit: x.get('order_limit') ? parseInt(x.get('order_limit'), 10) : null, features: String(x.get('features') || '').split(',').map(s => s.trim()).filter(Boolean) } }); toast('Plan saved'); S.meta = await api('/meta'); });
      });
    } else if (k === 'discounts') {
      const load = async () => { const d = await api('/owner/discounts'); box.innerHTML = `<form id="df" class="card row">${field('Code', 'code', 'text', 'required maxlength=30')}${field('Percent off', 'percent', 'number', 'min=0 max=100 value=0')}${field('Flat off (₹)', 'flat', 'number', 'min=0 step=0.01 value=0')}${field('Max uses (0 = unlimited)', 'max_uses', 'number', 'min=0 value=0')}<button class="btn">${ic('plus')} ${t('create')}</button></form><div class="card">${tbl(['Code', '%', 'Flat', 'Used', t('status'), ''], d.items.map(x => `<tr><td>${esc(x.code)}</td><td>${x.percent}</td><td>${inr(x.flat)}</td><td>${x.used}/${x.max_uses || '∞'}</td><td>${badge(x.active ? 'active' : 'inactive')}</td><td><button class="btn sm ghost" data-tg="${esc(x.code)}">Toggle</button></td></tr>`))}</div>`;
        $('#df').onsubmit = e => { e.preventDefault(); act(e.submitter, async () => { const b = form(e.target); await api('/owner/discounts', { method: 'POST', body: { code: b.code, percent: +b.percent, flat: +b.flat, max_uses: +b.max_uses } }); load(); }); };
        box.querySelectorAll('[data-tg]').forEach(b => b.onclick = () => act(b, async () => { await api(`/owner/discounts/${b.dataset.tg}/toggle`, { method: 'POST', body: {} }); load(); })); };
      await load();
    } else if (k === 'admins') {
      const load = async () => { const d = await api('/admin/users?role=admin'); box.innerHTML = `<form id="cf" class="card"><h2>Create admin</h2><div class="grid g2"><div>${field(t('name'), 'name', 'text', 'required')}${field(t('email'), 'email', 'email', 'required')}${field(t('password'), 'password', 'password', 'required minlength=8')}</div><div><label>Permissions</label>${PERMS.map(p => `<label style="margin:2px 0"><input type="checkbox" class="pm" value="${p}" style="width:auto" checked> ${p}</label>`).join('')}</div></div><button class="btn mt">${ic('plus')} ${t('create')}</button></form><div class="card"><h2>Admins</h2>${tbl([t('name'), t('email'), 'Permissions', t('status'), ''], d.items.map(a => `<tr><td>${esc(a.name)}</td><td>${esc(a.email)}</td><td>${esc(a.perms)}</td><td>${badge(a.status)}</td><td><button class="btn sm ghost" data-u="${esc(a.id)}">Manage</button></td></tr>`))}<p class="muted">To promote an existing user, open them in Admin → Users → Manage.</p></div>`;
        $('#cf').onsubmit = e => { e.preventDefault(); act(e.submitter, async () => { const b = form(e.target); b.perms = [...box.querySelectorAll('.pm:checked')].map(x => x.value); await api('/owner/admins', { method: 'POST', body: b }); toast('Admin created'); load(); }); };
        box.querySelectorAll('[data-u]').forEach(b => b.onclick = () => manageUser(b.dataset.u, load)); };
      await load();
    } else if (k === 'settings') {
      const { settings: s } = await api('/owner/settings');
      box.innerHTML = `<form id="sf" class="card"><h2>Branding & platform</h2><div class="grid g2"><div>${field('Brand name', 'brand_name', 'text', `value="${esc(s.brand_name)}"`)}${field('Tagline', 'tagline', 'text', `value="${esc(s.tagline)}"`)}${field('Primary color', 'primary_color', 'color', `value="${esc(s.primary_color)}"`)}${field('Min transaction (₹)', 'min_txn', 'number', `value="${s.min_txn}" min="1" step="0.01"`)}${field('Max transaction (₹)', 'max_txn', 'number', `value="${s.max_txn}" min="1" step="0.01"`)}</div>
      <div><label><input type="checkbox" name="maintenance" style="width:auto" ${s.maintenance === '1' ? 'checked' : ''}> Maintenance mode (users blocked, staff allowed, webhooks keep working)</label>${field('Maintenance message', 'maintenance_message', 'text', `value="${esc(s.maintenance_message)}"`)}<label><input type="checkbox" name="registration_open" style="width:auto" ${s.registration_open === '1' ? 'checked' : ''}> Registrations open</label>${field('Welcome notification template', 'tpl_welcome', 'text', `value="${esc(s.tpl_welcome)}"`)}${field('Payment success template', 'tpl_payment_success', 'text', `value="${esc(s.tpl_payment_success)}"`)}</div></div><button class="btn mt">${ic('check')} ${t('save')}</button></form><p class="note">Your own payment gateway (used for subscription payments) is connected on the <a href="/connect" data-link>Connect</a> page with the owner account.</p>`;
      $('#sf').onsubmit = e => { e.preventDefault(); act(e.submitter, async () => { const f = e.target; const val = n => f.elements[n].value; const values = { brand_name: val('brand_name'), tagline: val('tagline'), primary_color: val('primary_color'), maintenance: f.elements.maintenance.checked ? '1' : '0', maintenance_message: val('maintenance_message'), registration_open: f.elements.registration_open.checked ? '1' : '0', tpl_welcome: val('tpl_welcome'), tpl_payment_success: val('tpl_payment_success') }; await api('/owner/settings', { method: 'PUT', body: { values, min_txn: parseFloat(val('min_txn')), max_txn: parseFloat(val('max_txn')) } }); S.meta = await api('/meta'); applyBrand(); toast('Settings saved'); }); };
    } else if (k === 'audit') {
      box.innerHTML = `<form id="sf" class="row"><input name="search" placeholder="Filter action / target / user" style="max-width:300px"><button class="btn">${ic('search')}</button></form><div id="al" class="card mt"></div>`;
      const load = async () => { const d = await api('/owner/audit?search=' + encodeURIComponent(form($('#sf')).search)); $('#al').innerHTML = tbl(['#', 'Who', 'Role', 'Action', 'Target', 'Detail', 'IP', 'Time'], d.items.map(l => `<tr><td>${l.id}</td><td>${esc(l.actor || 'system')}</td><td>${esc(l.actor_role)}</td><td>${esc(l.action)}</td><td>${esc(l.target)}</td><td>${esc(l.detail)}</td><td class="mono">${esc(l.ip)}</td><td>${fd(l.created_at)}</td></tr>`)); };
      $('#sf').onsubmit = e => { e.preventDefault(); act(null, load); }; load();
    } else if (k === 'keys') {
      const load = async () => { const d = await api('/owner/keys'); box.innerHTML = `<div class="card">${tbl(['User', 'Name', 'Prefix', t('status'), 'Last used', ''], d.items.map(x => `<tr><td>${esc(x.email)}</td><td>${esc(x.name)}</td><td class="mono">${esc(x.prefix)}…</td><td>${badge(x.revoked ? 'cancelled' : 'active')}</td><td>${fd(x.last_used)}</td><td>${x.revoked ? '' : `<button class="btn sm danger" data-k="${esc(x.id)}">Revoke</button>`}</td></tr>`))}</div>`; box.querySelectorAll('[data-k]').forEach(b => b.onclick = () => act(b, async () => { await api('/owner/keys/' + b.dataset.k, { method: 'DELETE' }); load(); })); };
      await load();
    }
  });
}

/* ---------- router ---------- */
const PUBLIC = { '/': landing, '/login': loginPg, '/register': registerPg, '/forgot': forgotPg, '/reset': resetPg };
const PRIVATE = { '/dashboard': dashPg, '/order': orderPg, '/connect': connectPg, '/verify': verifyPg, '/qr': qrPg, '/links': linksPg, '/transactions': txnPg, '/subscription': subPg, '/support': supportPg, '/notifications': notifPg, '/activity': activityPg, '/profile': profilePg, '/admin': adminPg, '/owner': ownerPg };
async function render() {
  try {
    const path = location.pathname.replace(/\/+$/, '') || '/';
    if (!S.meta) { S.meta = await api('/meta'); applyBrand(); }
    if (S.user === undefined) { try { S.user = (await api('/user/profile')).user; } catch (e) { S.user = null; if (e.status === 503) { S.maint = e.message; } } }
    if (S.maint && !S.user) { app.innerHTML = `<div class="auth"><div class="card c">${ic('settings')}<h1>Maintenance</h1><p class="muted">${esc(S.meta.maintenance_message)}</p></div></div>`; if (path !== '/login') return; }
    if (PUBLIC[path]) { if (S.user && path !== '/' && path !== '/reset') return go('/dashboard'); return PUBLIC[path](); }
    if (!S.user) return go('/login');
    if (!S.user.ecosystem && path !== '/onboarding') return go('/onboarding');
    if (path === '/onboarding') return onboarding();
    const fn = PRIVATE[path]; if (!fn) return go('/dashboard');
    if ((path === '/admin' && !['admin', 'owner'].includes(S.user.role)) || (path === '/owner' && S.user.role !== 'owner')) return go('/dashboard');
    const v = shell(path); await act(null, () => fn(v));
  } catch (e) { app.innerHTML = `<div class="auth"><div class="card c"><h1>Connection problem</h1><p class="muted">${esc(e.message)}</p><button class="btn" onclick="location.reload()">Retry</button></div></div>`; }
}
window.addEventListener('popstate', render);
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
render();
})();
