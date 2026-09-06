// olcWave auth-token vault sidecar (Phase 1).
//
// Keeps per-account Yandex sessions and hands olcWave a fresh Session_id.
// The browser is launched ON-DEMAND (RAM-friendly on a small box) and closed
// after each op; Xvfb+x11vnc+websockify (noVNC) run continuously (light) so an
// interactive login can be driven through the panel. A human logs in via noVNC
// (no bot-detection); only the cookie extraction + keep-warm is automated.
import { chromium } from 'playwright';
import http from 'node:http';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

const DATA = process.env.ACCOUNTS_DIR || '/data/accounts';
const SECRET = process.env.VAULT_SECRET || '';
const PORT = Number(process.env.PORT || 8091);
const LOGIN_TIMEOUT_MS = Number(process.env.LOGIN_TIMEOUT_MS || 10 * 60 * 1000);
const UA =
  'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36';

fs.mkdirSync(DATA, { recursive: true });

let busy = false; // single-browser mutex (only one Chromium op at a time)
let live = null; // { account, context, timer } during an interactive login

const profileDir = (k) => path.join(DATA, k, 'profile');
const log = (m) => console.log('[vault] ' + m);

function clearLocks(dir) {
  try {
    for (const f of fs.readdirSync(dir)) {
      if (f.startsWith('Singleton')) fs.rmSync(path.join(dir, f), { force: true });
    }
  } catch {}
}
function listAccounts() {
  try {
    return fs.readdirSync(DATA).filter((k) => fs.existsSync(profileDir(k)));
  } catch {
    return [];
  }
}
async function openContext(key) {
  const dir = profileDir(key);
  fs.mkdirSync(dir, { recursive: true });
  clearLocks(dir); // an ungraceful kill leaves a SingletonLock that blocks reopen
  const ctx = await chromium.launchPersistentContext(dir, {
    headless: false,
    viewport: { width: 1280, height: 900 },
    userAgent: UA,
    args: ['--no-sandbox', '--disable-blink-features=AutomationControlled', '--start-maximized'],
  });
  await ctx.addInitScript(() => Object.defineProperty(navigator, 'webdriver', { get: () => undefined }));
  return ctx;
}
// The jar can hold several Session_id cookies: the live one on .yandex.ru
// (rotated by Passport on activity) and stale copies on sibling domains such
// as .ya.ru, set once at login and never rotated. Only the .yandex.ru (or, for
// a .com account, .yandex.com) value authenticates against cloud-api; picking
// "the first Session_id" used to hand olcWave the stale .ya.ru copy.
const SID_DOMAINS = ['.yandex.ru', 'yandex.ru', '.yandex.com', 'yandex.com'];
async function sidOf(ctx) {
  const all = (await ctx.cookies()).filter((c) => c.name === 'Session_id');
  for (const d of SID_DOMAINS) {
    const c = all.find((c) => c.domain === d);
    if (c) return c.value;
  }
  return all.length ? all[0].value : null;
}

// startup: clear stale profile locks across all accounts
for (const k of listAccounts()) clearLocks(profileDir(k));

function send(res, code, obj) {
  res.statusCode = code;
  res.setHeader('Content-Type', 'application/json');
  res.end(JSON.stringify(obj));
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://x');
  const p = url.pathname;
  const account = url.searchParams.get('account') || '';

  if (p === '/health') {
    return send(res, 200, { ok: true, busy, live: live?.account || null, accounts: listAccounts() });
  }
  if (SECRET && req.headers['x-vault-secret'] !== SECRET) return send(res, 401, { error: 'unauthorized' });

  try {
    if (p === '/accounts' && req.method === 'GET') {
      return send(res, 200, { accounts: listAccounts() });
    }

    // Start an interactive login: launch a browser on the account's profile and
    // hold it (mutex) until /login/commit or a timeout. User logs in via noVNC.
    if (p === '/login/start' && req.method === 'POST') {
      if (busy) return send(res, 409, { error: 'busy - another browser op in progress' });
      const key = account || 'acc_' + crypto.randomBytes(4).toString('hex');
      busy = true;
      let ctx;
      try {
        ctx = await openContext(key);
        const page = ctx.pages()[0] || (await ctx.newPage());
        await page.goto('https://telemost.yandex.ru/', { waitUntil: 'domcontentloaded' }).catch(() => {});
      } catch (e) {
        try { await ctx?.close(); } catch {}
        busy = false;
        return send(res, 500, { error: String(e) });
      }
      const timer = setTimeout(async () => {
        log('login timeout for ' + key);
        try { await ctx.close(); } catch {}
        live = null;
        busy = false;
      }, LOGIN_TIMEOUT_MS);
      live = { account: key, context: ctx, timer };
      log('login started for ' + key + ' - drive it via noVNC');
      return send(res, 200, { account: key, novnc: '/vnc.html' });
    }

    // Finish the login: read the Session_id, persist (profile already saved),
    // close the browser, release the mutex.
    if (p === '/login/commit' && req.method === 'POST') {
      if (!live) return send(res, 400, { error: 'no login in progress' });
      const key = live.account;
      const sid = await sidOf(live.context);
      if (!sid) return send(res, 400, { error: 'not logged in yet (no Session_id) - finish in noVNC first', account: key });
      clearTimeout(live.timer);
      try { await live.context.close(); } catch {}
      live = null;
      busy = false;
      log('login committed for ' + key + ' (sid len ' + sid.length + ')');
      return send(res, 200, { account: key, ok: true, len: sid.length });
    }

    if (p === '/login/cancel' && req.method === 'POST') {
      if (live) {
        clearTimeout(live.timer);
        try { await live.context.close(); } catch {}
        live = null;
        busy = false;
      }
      return send(res, 200, { ok: true });
    }

    // Non-destructive snapshot of the live login (does NOT close the browser):
    // whether Session_id is present, its length + a hash fingerprint (so a value
    // change is visible without exposing the token), the current URL, and whether
    // the Telemost logged-in marker (create-call-button) is visible.
    if (p === '/login/status' && req.method === 'GET') {
      if (!live) return send(res, 200, { live: null, ready: false });
      const sid = await sidOf(live.context);
      let url = '';
      let marker = false;
      try {
        const page = live.context.pages()[0];
        if (page) {
          url = page.url();
          marker = await page.getByTestId('create-call-button').first().isVisible({ timeout: 500 }).catch(() => false);
        }
      } catch {}
      const sidFp = sid ? crypto.createHash('sha256').update(sid).digest('hex').slice(0, 8) : null;
      return send(res, 200, {
        live: live.account,
        sid: !!sid,
        sidLen: sid ? sid.length : 0,
        sidFp,
        url,
        marker,
        ready: !!sid && marker,
      });
    }

    // Non-interactive refresh+extract: spin up the account's browser, touch
    // Yandex (refreshes the session), read the CURRENT Session_id, close.
    if (p === '/token' && req.method === 'GET') {
      if (!account) return send(res, 400, { error: 'account required' });
      if (!fs.existsSync(profileDir(account))) return send(res, 404, { error: 'no such account' });
      if (busy) return send(res, 503, { error: 'busy - retry shortly' });
      busy = true;
      let ctx;
      try {
        ctx = await openContext(account);
        const page = ctx.pages()[0] || (await ctx.newPage());
        await page.goto('https://telemost.yandex.ru/', { waitUntil: 'domcontentloaded' }).catch(() => {});
        const sid = await sidOf(ctx);
        try { await ctx.close(); } catch {}
        busy = false;
        if (!sid) return send(res, 409, { error: 'session dead - re-seed via login', account });
        return send(res, 200, { account, token: sid }); // RAW token - olcWave consumer only
      } catch (e) {
        try { await ctx?.close(); } catch {}
        busy = false;
        return send(res, 500, { error: String(e) });
      }
    }

    if (p === '/account' && req.method === 'DELETE') {
      if (!account) return send(res, 400, { error: 'account required' });
      if (live?.account === account) return send(res, 409, { error: 'account has a login in progress' });
      fs.rmSync(path.join(DATA, account), { recursive: true, force: true });
      return send(res, 200, { ok: true });
    }

    return send(res, 404, { error: 'not found' });
  } catch (e) {
    return send(res, 500, { error: String(e) });
  }
});

server.listen(PORT, '0.0.0.0', () => log('http api on :' + PORT + (SECRET ? ' (secret required)' : ' (NO secret set)')));

async function shutdown() {
  log('shutting down - closing browser gracefully');
  try { if (live) { clearTimeout(live.timer); await live.context.close(); } } catch {}
  process.exit(0);
}
process.on('SIGTERM', shutdown);
process.on('SIGINT', shutdown);
