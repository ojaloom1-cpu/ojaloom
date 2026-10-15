// Frontend end-to-end tests:  cd tests && npm install && node frontend_dom.mjs
// Runs the REAL built web app (frontend/build.py output) in jsdom against the REAL Python backend.
// `fetch` is replaced by a browser-faithful one: it does CORS preflights, checks Access-Control-Allow-Origin/-Credentials,
// keeps the cookie jar and only exposes headers the server lists in Access-Control-Expose-Headers.
import { JSDOM, VirtualConsole, ResourceLoader } from 'jsdom';
import { spawn, execFileSync } from 'node:child_process';
import http from 'node:http';
import net from 'node:net';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';

const ROOT = path.resolve(import.meta.dirname, '..');
const ORIGIN = 'http://127.0.0.1:5173';          // where the web app "lives" (matches the backend's default OJALOOM_FRONTEND_URL)
let passed = 0;
const results = [];

const sleep = ms => new Promise(r => setTimeout(r, ms));
const freePort = () => new Promise(res => { const s = net.createServer(); s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => res(p)); }); });
async function waitFor(fn, what, ms = 6000) {
  const t0 = Date.now();
  for (;;) {
    let v; try { v = await fn(); } catch { v = null; }
    if (v) return v;
    if (Date.now() - t0 > ms) throw new Error('timed out waiting for ' + what);
    await sleep(40);
  }
}
async function test(name, fn) {
  if (process.env.VERBOSE) console.log('  ...  ' + name);
  try { await fn(); passed++; results.push(['ok', name]); console.log('  ok   ' + name); }
  catch (e) { results.push(['FAIL', name, e]); console.log('  FAIL ' + name + '\n       ' + String(e.stack || e).split('\n').slice(0, 6).join('\n       ')); }
}

// ------------------------------------------------------------------------------------------ servers
function startBackend(env) {
  return new Promise(async (resolve, reject) => {
    const data = fs.mkdtempSync(path.join(os.tmpdir(), 'oj_dom_'));
    const port = await freePort();
    const clean = Object.fromEntries(Object.entries(process.env).filter(([k]) => !k.startsWith('OJALOOM_')));
    const proc = spawn('python3', [path.join(ROOT, 'backend/ojaloom_server.py'), '--port', String(port), '--no-browser', '--data-dir', data],
      { env: { ...clean, OJALOOM_ENV: 'development', OJALOOM_FRONTEND_URL: ORIGIN, ...env }, stdio: ['ignore', 'pipe', 'pipe'] });
    let out = ''; proc.stdout.on('data', d => out += d); proc.stderr.on('data', d => out += d);
    proc.on('exit', c => { if (c) reject(new Error('backend exited ' + c + '\n' + out)); });
    for (let i = 0; i < 80; i++) {
      try { const r = await fetch(`http://127.0.0.1:${port}/health`); if (r.ok) return resolve({ proc, port, data, base: `http://127.0.0.1:${port}` }); } catch {}
      await sleep(120);
    }
    reject(new Error('backend did not start\n' + out));
  });
}
const stopBackend = b => { b.proc.kill('SIGTERM'); fs.rmSync(b.data, { recursive: true, force: true }); };

function startMockGraph() {
  const calls = [];
  const server = http.createServer((req, res) => {
    const chunks = []; req.on('data', c => chunks.push(c));
    req.on('end', () => {
      const raw = Buffer.concat(chunks); calls.push({ path: req.url, raw, auth: req.headers.authorization });
      res.setHeader('Content-Type', 'application/json');
      if (req.url.endsWith('/media')) return res.end(JSON.stringify({ id: 'MEDIA1' }));
      if (req.url.endsWith('/messages')) return res.end(JSON.stringify({ messages: [{ id: 'wamid.DOM' }] }));
      res.statusCode = 404; res.end('{}');
    });
  });
  return new Promise(r => server.listen(0, '127.0.0.1', () => r({ calls, url: `http://127.0.0.1:${server.address().port}`, close: () => server.close() })));
}

function build(apiBase) {
  const out = fs.mkdtempSync(path.join(os.tmpdir(), 'oj_dist_'));
  execFileSync('python3', [path.join(ROOT, 'frontend/build.py'), '--out', out], { env: { ...process.env, API_BASE: apiBase }, stdio: 'pipe' });
  return out;
}

// ------------------------------------------------------------------------------------------ a browser-faithful fetch
const SAFE_HEADERS = ['cache-control', 'content-language', 'content-length', 'content-type', 'expires', 'last-modified', 'pragma'];
function makeFetch(jar, getWin, log = []) {
  const rawRequest = (url, method, headers, body) => new Promise((resolve, reject) => {
    const u = new URL(url);
    const req = http.request({ host: u.hostname, port: u.port, path: u.pathname + u.search, method, headers }, res => {
      const chunks = []; res.on('data', c => chunks.push(c));
      res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, setCookie: [].concat(res.headers['set-cookie'] || []), body: Buffer.concat(chunks) }));
    });
    req.on('error', reject); if (body) req.write(body); req.end();
  });
  const counted = fn => async (url, init) => { log.pending = (log.pending || 0) + 1; try { return await fn(url, init); } finally { log.pending--; } };
  return counted(async function browserFetch(url, init = {}) {
    const u = new URL(url, ORIGIN);
    const method = (init.method || 'GET').toUpperCase();
    const hdrs = Object.fromEntries(Object.entries(init.headers || {}).map(([k, v]) => [k.toLowerCase(), String(v)]));
    const cross = u.origin !== ORIGIN;
    const creds = init.credentials === 'include' || (init.credentials !== 'omit' && !cross);
    const simpleCT = !hdrs['content-type'] || /^(text\/plain|application\/x-www-form-urlencoded|multipart\/form-data)/i.test(hdrs['content-type']);
    const extra = Object.keys(hdrs).filter(h => !['accept', 'accept-language', 'content-language'].includes(h) && !(h === 'content-type' && simpleCT));
    const simple = ['GET', 'HEAD', 'POST'].includes(method) && extra.length === 0;
    const fail = why => { log.push({ url: u.href, method, blocked: why }); throw new TypeError('Failed to fetch (' + why + ')'); };
    if (cross && !simple) {   // CORS preflight
      const pf = await rawRequest(u.href, 'OPTIONS', { Origin: ORIGIN, 'Access-Control-Request-Method': method, 'Access-Control-Request-Headers': extra.sort().join(',') }).catch(() => fail('network'));
      const h = pf.headers;
      if (pf.status < 200 || pf.status > 299) fail('preflight status ' + pf.status);
      if (h['access-control-allow-origin'] !== ORIGIN) fail('preflight: origin not allowed');
      if (creds && h['access-control-allow-credentials'] !== 'true') fail('preflight: credentials not allowed');
      const okMethods = (h['access-control-allow-methods'] || '').toUpperCase().split(/\s*,\s*/);
      if (!['GET', 'HEAD', 'POST'].includes(method) && !okMethods.includes(method)) fail('preflight: method not allowed');
      const okHeaders = (h['access-control-allow-headers'] || '').toLowerCase().split(/\s*,\s*/);
      for (const x of extra) if (!okHeaders.includes(x)) fail('preflight: header not allowed: ' + x);
    }
    const send = { ...hdrs };
    if (cross || method === 'POST') send.origin = ORIGIN;
    if (creds && jar.size) send.cookie = [...jar].map(([k, v]) => k + '=' + v).join('; ');
    let body = init.body; if (body != null && typeof body !== 'string') body = Buffer.from(body);
    if (body != null) send['content-length'] = Buffer.byteLength(body);
    const r = await rawRequest(u.href, method, send, body).catch(() => fail('network'));
    log.push({ url: u.href, method, status: r.status });
    if (cross) {
      if (r.headers['access-control-allow-origin'] !== ORIGIN) fail('response: origin not allowed');
      if (creds && r.headers['access-control-allow-credentials'] !== 'true') fail('response: credentials not allowed');
    }
    if (creds) for (const c of r.setCookie) { const [kv] = c.split(';'); const i = kv.indexOf('='); jar.set(kv.slice(0, i), kv.slice(i + 1)); }
    const exposed = (r.headers['access-control-expose-headers'] || '').toLowerCase().split(/\s*,\s*/);
    const visible = Object.fromEntries(Object.entries(r.headers).filter(([k]) => !cross || SAFE_HEADERS.includes(k) || exposed.includes(k)));
    const ctype = r.headers['content-type'] || '';
    return {
      ok: r.status >= 200 && r.status < 300, status: r.status, url: u.href,
      headers: { get: n => visible[String(n).toLowerCase()] ?? null },
      json: async () => JSON.parse(r.body.toString('utf8')),
      text: async () => r.body.toString('utf8'),
      blob: async () => new (getWin() ? getWin().Blob : Blob)([r.body], { type: ctype }),
    };
  });
}

// ------------------------------------------------------------------------------------------ open the app in a "browser"
async function openApp({ dist, jar, hash = '', share = null, capture = {} }) {
  const errors = [], fetchLog = [], opened = [], clicks = [], blobs = [], shares = [];
  const vc = new VirtualConsole();
  vc.on('jsdomError', e => { if (!/Not implemented: (navigation|window\.open)/.test(e.message)) errors.push(e.message); });
  vc.on('error', (...a) => errors.push(a.join(' ')));
  let win = null;
  class Loader extends ResourceLoader {
    fetch(url) {
      const u = new URL(url);
      if (u.origin !== ORIGIN) return null;
      return Promise.resolve(fs.readFileSync(path.join(dist, u.pathname === '/' ? 'index.html' : u.pathname.slice(1))));
    }
  }
  const dom = new JSDOM(fs.readFileSync(path.join(dist, 'index.html'), 'utf8'), {
    url: ORIGIN + '/' + hash, runScripts: 'dangerously', resources: new Loader(), pretendToBeVisual: true, virtualConsole: vc,
    beforeParse(w) {
      win = w;
      w.fetch = makeFetch(jar, () => win, fetchLog);
      w.matchMedia = w.matchMedia || (q => ({ matches: false, media: q, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }));
      w.scrollTo = () => {}; w.HTMLElement.prototype.scrollIntoView = () => {};
      w.URL.createObjectURL = b => { blobs.push(b); return 'blob:test/' + blobs.length; }; w.URL.revokeObjectURL = () => {};
      w.open = (...a) => { opened.push(a[0]); return { opener: null }; };
      // record every anchor click (mailto:, download, wa.me) instead of letting jsdom try to navigate
      w.addEventListener('click', e => { const a = e.target.closest && e.target.closest('a[href]'); if (a) { clicks.push({ href: a.href, download: a.getAttribute('download') }); if (!/^#/.test(a.getAttribute('href'))) e.preventDefault(); } }, true);
      if (share) {
        Object.defineProperty(w.navigator, 'canShare', { value: d => !!(d && d.files && d.files.length), configurable: true });
        Object.defineProperty(w.navigator, 'share', { value: async d => { shares.push(d); }, configurable: true });
      }
    },
  });
  return { dom, win: dom.window, doc: dom.window.document, errors, fetchLog, opened, clicks, blobs, shares };
}
// let the app finish what it started (in-flight requests, re-renders) before its window is destroyed
async function closeApp(app) {
  let quiet = 0;
  for (let i = 0; i < 120 && quiet < 5; i++) { await sleep(40); quiet = (app.fetchLog.pending || 0) === 0 ? quiet + 1 : 0; }
  app.win.close();
}
const text = el => (el && el.textContent || '').replace(/\s+/g, ' ').trim();

// ------------------------------------------------------------------------------------------ seed a shop through the real API
async function seed(base, jar) {
  const f = makeFetch(jar, () => null);
  const call = async (method, p, body, csrf) => {
    const r = await f(base + p, { method, credentials: 'include', headers: { 'Content-Type': 'application/json', ...(csrf ? { 'X-CSRF-Token': csrf } : {}) }, body: body ? JSON.stringify(body) : undefined });
    return { status: r.status, data: await r.json() };
  };
  const s = await call('POST', '/api/signup', { email: 'dom@example.test', password: 'correct horse battery 42', owner_name: 'Dom Owner', business_name: 'Ada Fabrics', category: 'Fashion & Clothing', phone: '08030000000', accept_terms: '1' });
  assert.ok(s.status < 300, 'signup ' + JSON.stringify(s));
  const csrf = (await call('GET', '/api/me')).data.csrf;
  const p = await call('POST', '/api/products', { name: 'Ankara 6 yards', selling_price: 5000, cost_price: 3000, stock_quantity: 50 }, csrf);
  const c = await call('POST', '/api/customers', { full_name: 'Chioma Obi', phone: '0803 123 4567', email: 'chioma@example.test' }, csrf);
  const o = await call('POST', '/api/orders', { customer_id: c.data.id, items: [{ product_id: p.data.product.id, quantity: 3 }], status: 'pending', payment_method: 'Cash', initial_payment: 5000 }, csrf);
  assert.ok(o.status < 300, 'order ' + JSON.stringify(o));
  const token = (await call('GET', '/api/receipts')).data.items[0].public_token;
  return { csrf, token, customerId: c.data.id };
}

const openSendMenu = async app => {
  const btn = await waitFor(() => app.doc.querySelector('[data-act="send-menu"]'), 'a Send button');
  btn.dispatchEvent(new app.win.MouseEvent('click', { bubbles: true }));
  await waitFor(() => app.doc.querySelector('#ddlayer .dd-menu'), 'the Send menu');
  return btn;
};
const pickMenu = async (app, run) => {
  const item = await waitFor(() => app.doc.querySelector(`#ddlayer [data-run="${run}"]`), 'menu item ' + run);
  item.dispatchEvent(new app.win.MouseEvent('click', { bubbles: true }));
};

// ================================================================================================ run
console.log('\nFrontend tests (real app + real backend, browser-faithful CORS)\n');

// ---- static checks on the built site -------------------------------------------------------------
await test('built index.html: strict CSP, no inline scripts, hashed assets, CSP allows the API origin only', async () => {
  const dist = build('https://api.example.com');
  const html = fs.readFileSync(path.join(dist, 'index.html'), 'utf8');
  const csp = html.match(/Content-Security-Policy" content="([^"]+)"/)[1];
  assert.match(csp, /default-src 'none'/);
  assert.match(csp, /script-src 'self'(;|$)/, 'no unsafe-inline / eval for scripts');
  assert.ok(!/unsafe-eval/.test(csp));
  assert.match(csp, /connect-src 'self' https:\/\/api\.example\.com;/);
  assert.ok(!/<script(?![^>]*\ssrc=)[^>]*>/.test(html), 'every <script> is an external file');
  assert.match(html, /app\.js\?v=[0-9a-f]{10}/);
  assert.match(fs.readFileSync(path.join(dist, 'config.js'), 'utf8'), /"apiBase":"https:\/\/api\.example\.com"/);
  assert.ok(!html.includes('__API_ORIGIN__') && !html.includes('__JS_HASH__'));
});

// ---- the app against a backend with direct WhatsApp delivery switched on ----------------------------
const graph = await startMockGraph();
const full = await startBackend({ OJALOOM_WA_TOKEN: 'wa_dom', OJALOOM_WA_PHONE_ID: '555', OJALOOM_WA_GRAPH_BASE: graph.url });
const distFull = build(full.base);
let seeded; const jarFull = new Map();

await test('logged out: boots from /api/boot over CORS, shows landing page, support button points at WhatsApp 2347074235945', async () => {
  const app = await openApp({ dist: distFull, jar: new Map() });
  await waitFor(() => text(app.doc.querySelector('#root')).length > 100, 'landing page');
  assert.deepEqual(app.fetchLog.filter(l => l.blocked), [], 'no request was blocked by CORS');
  assert.ok(app.fetchLog.some(l => l.url === full.base + '/api/boot' && l.status === 200), 'boot fetched from the API host');
  const fab = app.doc.querySelector('#support');
  assert.equal(fab.hidden, false);
  assert.ok(fab.querySelector('svg'), 'icon drawn');
  assert.match(fab.href, /^https:\/\/wa\.me\/2347074235945\?text=Hello%20Oja%20Loom%20support/);
  assert.equal(fab.getAttribute('target'), '_blank');
  assert.match(fab.getAttribute('rel'), /noopener/);
  const terms = [...app.doc.querySelectorAll('a')].find(a => /Terms of Service/.test(a.textContent));
  assert.equal(terms.href, full.base + '/terms', 'server-rendered pages are linked on the API host');
  assert.deepEqual(app.errors, []);
  await closeApp(app);
});

await test('server unreachable: friendly error with Try again + support chat (no blank page)', async () => {
  const dead = build('http://127.0.0.1:1');
  const app = await openApp({ dist: dead, jar: new Map() });
  const err = await waitFor(() => app.doc.querySelector('.boot-err'), 'the error screen');
  assert.match(text(err), /Cannot reach Oja Loom/);
  assert.ok(err.querySelector('[data-act="reload"]'));
  assert.match(err.querySelector('a[href^="https://wa.me/2347074235945"]').href, /wa\.me/);
  await closeApp(app);
});

await test('signed in: dashboard loads with the cookie sent cross-origin; support message names the shop', async () => {
  seeded = await seed(full.base, jarFull);
  const app = await openApp({ dist: distFull, jar: jarFull });
  await waitFor(() => app.doc.querySelector('.side, .bnav, nav'), 'the signed-in app shell');
  assert.deepEqual(app.fetchLog.filter(l => l.blocked), []);
  const me = app.fetchLog.find(l => l.url === full.base + '/api/me');
  assert.equal(me.status, 200);
  const fab = app.doc.querySelector('#support');
  fab.dispatchEvent(new app.win.MouseEvent('click', { bubbles: true, cancelable: true }));
  assert.match(decodeURIComponent(fab.href), /with my shop "Ada Fabrics"/);
  assert.deepEqual(app.errors, []);
  await closeApp(app);
});

await test('Receipts list: Send button carries ref/email/phone and opens a menu with exactly WhatsApp + Email', async () => {
  const app = await openApp({ dist: distFull, jar: jarFull, hash: '#/receipts' });
  const btn = await openSendMenu(app);
  assert.equal(btn.dataset.kind, 'receipt');
  assert.equal(btn.dataset.ref, seeded.token);
  assert.equal(btn.dataset.email, 'chioma@example.test');
  assert.equal(btn.dataset.phone, '2348031234567');
  assert.match(text(btn), /^Send/);
  const items = [...app.doc.querySelectorAll('#ddlayer .dd-opt')];
  assert.deepEqual(items.map(i => text(i)), ['WhatsApp', 'Email']);
  assert.equal(items[0].dataset.ref, seeded.token, 'the menu items carry the document with them');
  assert.equal(btn.getAttribute('aria-expanded'), 'true');
  await closeApp(app);
});

await test('WhatsApp (direct mode): asks to confirm, then the SERVER delivers the PDF into the customer\'s WhatsApp', async () => {
  graph.calls.length = 0;
  const app = await openApp({ dist: distFull, jar: jarFull, hash: '#/receipts' });
  await openSendMenu(app); await pickMenu(app, 'send-wa');
  const dlg = await waitFor(() => app.doc.querySelector('[data-act="confirm-yes"]'), 'the confirm dialog');
  assert.match(text(app.doc.querySelector('#layers')), /Chioma Obi/);
  assert.match(text(app.doc.querySelector('#layers')), /2348031234567/);
  dlg.dispatchEvent(new app.win.MouseEvent('click', { bubbles: true }));
  await waitFor(() => graph.calls.some(c => c.path.endsWith('/messages')), 'the WhatsApp message to be sent');
  const upload = graph.calls.find(c => c.path.endsWith('/media'));
  assert.ok(upload.raw.includes('%PDF-'), 'the real PDF was uploaded to WhatsApp');
  const msg = JSON.parse(graph.calls.find(c => c.path.endsWith('/messages')).raw.toString());
  assert.equal(msg.to, '2348031234567');
  await waitFor(() => /Sent\. The PDF is in their WhatsApp/.test(text(app.doc.querySelector('#toasts'))), 'success toast');
  assert.equal(app.opened.length, 0, 'no other app / tab was opened');
  assert.equal(app.clicks.filter(c => /^mailto:|wa\.me/.test(c.href)).length, 0);
  assert.deepEqual(app.errors, []);
  await closeApp(app);
});

await test('Email on a device that cannot share files: PDF saved, mail app opens with recipient, subject and body filled in', async () => {
  const app = await openApp({ dist: distFull, jar: jarFull, hash: '#/receipts' });
  await openSendMenu(app); await pickMenu(app, 'send-mail');
  await waitFor(() => app.clicks.some(c => c.href.startsWith('mailto:')), 'the mail app to open');
  const mail = app.clicks.find(c => c.href.startsWith('mailto:'));
  assert.match(mail.href, /^mailto:chioma@example\.test\?subject=Receipt%20/);
  assert.match(decodeURIComponent(mail.href), /from Ada Fabrics&body=Hello Chioma,/);
  const dl = app.clicks.find(c => c.download);
  assert.match(dl.download, /\.pdf$/, 'PDF saved first so it can be attached');
  const buf = await new Promise(res => { const r = new app.win.FileReader(); r.onload = () => res(r.result); r.readAsText(app.blobs[0].slice(0, 8)); });
  assert.match(buf, /^%PDF-/);
  assert.match(text(app.doc.querySelector('#toasts')), /Attach it in the email that just opened/);
  assert.deepEqual(app.errors, []);
  await closeApp(app);
});

await test('Debts: Send button works for a statement (ref = customer id, email present)', async () => {
  const app = await openApp({ dist: distFull, jar: jarFull, hash: '#/debts' });
  const btn = await waitFor(() => app.doc.querySelector('[data-act="send-menu"][data-kind="statement"]'), 'the debt Send button');
  assert.equal(btn.dataset.ref, seeded.customerId);
  assert.equal(btn.dataset.email, 'chioma@example.test');
  assert.match(btn.dataset.pdf, /\/api\/customers\/cus_[0-9a-f]+\/statement$/);
  await closeApp(app);
});

// ---- the app against a backend WITHOUT the WhatsApp Cloud API: the phone's share sheet gets the PDF ------
const bare = await startBackend({});
const distBare = build(bare.base);
const jarBare = new Map(); let seededBare;

await test('share sheet path: WhatsApp choice hands the real PDF FILE to navigator.share (not a link, not another app)', async () => {
  seededBare = await seed(bare.base, jarBare);
  const app = await openApp({ dist: distBare, jar: jarBare, hash: '#/receipts', share: true });
  await openSendMenu(app); await pickMenu(app, 'send-wa');
  await waitFor(() => app.shares.length === 1, 'navigator.share to be called');
  const d = app.shares[0];
  assert.equal(d.files.length, 1);
  assert.equal(d.files[0].type, 'application/pdf');
  assert.ok(d.files[0].size > 1000, 'a real PDF, ' + d.files[0].size + ' bytes');
  assert.match(d.files[0].name, /\.pdf$/, 'filename survived CORS (Content-Disposition is exposed)');
  assert.match(d.text, /Hello Chioma, thank you for your business\. Here is your receipt/);
  assert.equal(app.opened.length, 0);
  assert.equal(app.clicks.filter(c => c.download).length, 0, 'nothing was downloaded to another app');
  assert.deepEqual(app.errors, []);
  await closeApp(app);
});

await test('share sheet path: Email choice shares the PDF with a subject and a written body', async () => {
  const app = await openApp({ dist: distBare, jar: jarBare, hash: '#/receipts', share: true });
  await openSendMenu(app); await pickMenu(app, 'send-mail');
  await waitFor(() => app.shares.length === 1, 'navigator.share to be called');
  const d = app.shares[0];
  assert.equal(d.files[0].type, 'application/pdf');
  assert.match(d.title, /^Receipt .* from Ada Fabrics$/);
  assert.match(d.text, /^Hello Chioma,\n\nThank you for your business\. Your receipt .* is attached\./);
  assert.deepEqual(app.errors, []);
  await closeApp(app);
});

await test('share sheet path: cancelling the sheet is silent (no fallback download, no error toast)', async () => {
  const app = await openApp({ dist: distBare, jar: jarBare, hash: '#/receipts', share: true });
  Object.defineProperty(app.win.navigator, 'share', { configurable: true, value: async () => { const e = new Error('cancelled'); e.name = 'AbortError'; throw e; } });
  await openSendMenu(app); await pickMenu(app, 'send-wa');
  await sleep(600);
  assert.equal(app.clicks.filter(c => c.download).length, 0);
  assert.equal(app.opened.length, 0);
  assert.equal(text(app.doc.querySelector('#toasts')), '');
  await closeApp(app);
});

await test('desktop path: WhatsApp choice saves the PDF then opens the customer\'s chat with the message ready', async () => {
  const app = await openApp({ dist: distBare, jar: jarBare, hash: '#/receipts' });
  await openSendMenu(app); await pickMenu(app, 'send-wa');
  await waitFor(() => app.opened.length === 1, 'WhatsApp chat to open');
  assert.match(app.opened[0], /^https:\/\/wa\.me\/2348031234567\?text=Hello%20Chioma/);
  assert.ok(app.clicks.some(c => /\.pdf$/.test(c.download || '')), 'PDF saved so it can be attached');
  assert.match(text(app.doc.querySelector('#toasts')), /Attach it in the WhatsApp chat/);
  await closeApp(app);
});

stopBackend(full); stopBackend(bare); graph.close();
const failed = results.filter(r => r[0] === 'FAIL').length;
console.log(`\n${passed} passed, ${failed} failed\n`);
process.exit(failed ? 1 : 0);
