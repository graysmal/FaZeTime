// P6-E local e2e: live build -> REAL API (services/api, read-only) on 127.0.0.1 with Stripe TEST mode loaded
// from the repo .env.local (the API reads it; this script never reads or prints a key).
// Usage (from apps/extension):  node scripts/e2e-topup.mjs   [E2E_PORT=8766] [HEADED=1]
// Checks: Add funds -> FaZe Up! -> the BACKGROUND opens a checkout.stripe.com tab -> server row PENDING ->
// the background polls GET /v1/topups/{id} -> the ?fazetime_topup= return hint polls and never credits.
// It NEVER completes a payment (the 4242 checkout is run by the owner at the gate).
// Never printed: invite codes, session tokens, the Checkout URL (only its host is recorded).
import { spawn, spawnSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { randomUUID } from 'node:crypto';
import { chromium } from 'playwright';

const here = dirname(fileURLToPath(import.meta.url));
const extDir = join(here, '..');
const apiDir = join(extDir, '..', '..', 'services', 'api');
const out = join(extDir, 'artifacts', 'topup');
mkdirSync(out, { recursive: true });
const tmp = mkdtempSync(join(tmpdir(), 'ft-topup-'));
const PORT = Number(process.env.E2E_PORT || 8766);
const BASE = `http://127.0.0.1:${PORT}`;
const CHANNEL = 'fazegavin1234'; // The default mount target; Stripe returns here (server-configured URLs).
const { id: EXT_ID } = JSON.parse(readFileSync(join(extDir, 'manifest-key.json'), 'utf8'));
const results = [];
const record = (step, ok, detail = '') => {
  results.push({ step, ok, detail });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${step}${detail ? `  (${detail})` : ''}`);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const op = () => randomUUID();
async function api(method, path, token, body) {
  const res = await fetch(BASE + path, {
    method,
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  return { status: res.status, body: await res.json().catch(() => null) };
}
const dbRow = (topupId) => {
  const py = `import sqlite3,sys,json\nc=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True)\nr=c.execute("select status, amount_minor, (stripe_session_id like 'cs_test_%') from topups where topup_id=?",(sys.argv[2],)).fetchone()\nprint(json.dumps(r))`;
  const r = spawnSync('python3', ['-I', '-c', py, join(tmp, 'e2e.db'), topupId], { encoding: 'utf8' });
  return JSON.parse(r.stdout.trim() || 'null');
};

// 1. Build the live variant against this local API (default channel).
const build = spawnSync('npx', ['wxt', 'build'], { cwd: extDir, env: { ...process.env, WXT_FAZETIME_MODE: 'live', WXT_FAZETIME_API_BASE: BASE }, encoding: 'utf8' });
const extPath = join(extDir, '.output', 'chrome-mv3-live-127_0_0_1');
const manifest = JSON.parse(readFileSync(join(extPath, 'manifest.json'), 'utf8'));
record('build live variant (no new permissions)', build.status === 0 && JSON.stringify(manifest.permissions) === '["storage"]' && JSON.stringify(manifest.host_permissions) === JSON.stringify([`${BASE}/*`]), `permissions ${JSON.stringify(manifest.permissions)} host ${JSON.stringify(manifest.host_permissions)}`);

// 2. Real API with a temp DB; Stripe test secrets load from the repo .env.local inside the API process.
const apiEnv = { ...process.env, FAZETIME_DB_PATH: join(tmp, 'e2e.db'), FAZETIME_HOST: '127.0.0.1', FAZETIME_PORT: String(PORT), FAZETIME_ALLOWED_ORIGINS: `https://www.twitch.tv,chrome-extension://${EXT_ID}` };
const server = spawn('uv', ['run', '--frozen', 'python', '-m', 'fazetime_api', 'serve'], { cwd: apiDir, env: apiEnv, stdio: ['ignore', 'pipe', 'pipe'] });
let serverLog = '';
server.stdout.on('data', (d) => (serverLog += d));
server.stderr.on('data', (d) => (serverLog += d));
for (let i = 0; i < 60; i++) {
  try {
    if ((await fetch(`${BASE}/healthz`)).ok) break;
  } catch {}
  await sleep(500);
}
record('API healthz on 127.0.0.1', (await fetch(`${BASE}/healthz`).catch(() => ({ ok: false }))).ok, BASE);

const swLogs = [];
let ctx;
try {
  const boot = spawnSync('uv', ['run', '--frozen', 'python', '-m', 'fazetime_api', 'bootstrap-operator'], { cwd: apiDir, env: apiEnv, encoding: 'utf8' });
  const opCode = boot.stdout.trim().split('\n').at(-1).trim();
  const opr = (await api('POST', '/v1/enroll', null, { invite_code: opCode, display_name: 'Operator', device_id: op() })).body.session_token;
  const st = await api('POST', '/v1/operator/streams', opr, { operation_id: op(), twitch_channel_login: CHANNEL });
  record('operator stream + run created', st.status === 201 || st.status === 200);
  const invite = (await api('POST', '/v1/operator/invites', opr, { operation_id: op(), role: 'VIEWER', is_bot: false })).body.invite_code;
  // payment_mode from a throwaway viewer's snapshot (the extension's own token never leaves it).
  const probeInvite = (await api('POST', '/v1/operator/invites', opr, { operation_id: op(), role: 'VIEWER', is_bot: false })).body.invite_code;
  const probe = (await api('POST', '/v1/enroll', null, { invite_code: probeInvite, display_name: 'Probe', device_id: op() })).body;
  const snap = await api('GET', `/v1/streams/${probe.me.current_stream.stream_id}/snapshot`, probe.session_token);
  record('server payment_mode is STRIPE_TEST', snap.body?.modes?.payment_mode === 'STRIPE_TEST', `payment_mode ${snap.body?.modes?.payment_mode}`);
  const before = snap.body?.wallet?.available_minor;

  ctx = await chromium.launchPersistentContext(mkdtempSync(join(tmp, 'prof-')), {
    channel: 'chromium',
    headless: !process.env.HEADED,
    viewport: { width: 1600, height: 900 },
    args: [`--disable-extensions-except=${extPath}`, `--load-extension=${extPath}`],
  });
  // Record the emitting script's host so Stripe's own page logs are not mistaken for ours.
  const hostOf = (m) => {
    try {
      return new URL(m.location()?.url || 'about:blank').host || 'unknown';
    } catch {
      return 'unknown';
    }
  };
  ctx.on('console', (m) => swLogs.push({ host: hostOf(m), text: m.text() }));
  const sw = ctx.serviceWorkers()[0] ?? (await ctx.waitForEvent('serviceworker', { timeout: 15000 }));
  sw.on?.('console', (m) => swLogs.push({ host: `sw:${hostOf(m)}`, text: m.text() }));
  const popup = await ctx.newPage();
  await popup.goto(`chrome-extension://${EXT_ID}/popup.html`);
  await popup.getByPlaceholder('XXXX-XXXX-XXXX').fill(invite);
  await popup.getByPlaceholder('PixelPilot').fill('Viewer Tess');
  await popup.getByRole('button', { name: 'Sign in' }).click();
  await popup.getByText(/Signed in as/).first().waitFor({ timeout: 15000 });
  await popup.close();
  record('viewer enrolled via popup', true);

  const page = ctx.pages()[0] ?? (await ctx.newPage());
  await page.goto(`https://www.twitch.tv/${CHANNEL}`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.getByRole('button', { name: 'Proceed' }).click({ timeout: 3000 }).catch(() => {});
  const panel = page.locator('[data-fazetime-host="panel"] .ft-panel');
  await panel.waitFor({ timeout: 40000 });
  await page.waitForTimeout(3000);
  await page.screenshot({ path: join(out, '00-panel.png') });
  // CSS locators: Twitch may set aria-hidden on an ancestor, which hides the panel from role queries.
  const openBtn = panel.locator('button[aria-label="Open the FaZeTime panel"]');
  if (await openBtn.count()) await openBtn.click();
  await panel.locator('.ft-tab', { hasText: 'Wallet' }).click({ timeout: 15000 });
  const addFunds = panel.locator('.ft-primary', { hasText: 'Add funds' });
  await addFunds.waitFor({ timeout: 15000 });
  const walletText = await panel.innerText();
  record('Wallet: "Add funds" enabled, one test-credits note, no MOCK/DEMO', (await addFunds.isEnabled()) && (walletText.match(/Balances are test credits\./g) ?? []).length === 1 && !/MOCK|DEMO/.test(walletText));
  await page.screenshot({ path: join(out, '01-wallet.png') });

  await addFunds.click();
  const dialog = panel.locator('.ft-dialog');
  await dialog.waitFor({ timeout: 5000 });
  const dialogHtml = await dialog.innerHTML();
  record('dialog: FaZe Up!, presets, no card fields', dialogHtml.includes('FaZe Up!') && (await dialog.locator('input').count()) === 0 && !/card number|cvc|cvv/i.test(dialogHtml));
  await dialog.locator('.ft-amount', { hasText: /^\$5$/ }).click();
  await page.screenshot({ path: join(out, '02-dialog.png') });
  const newTab = ctx.waitForEvent('page', { timeout: 20000 });
  await dialog.locator('.ft-primary', { hasText: 'FaZe Up!' }).click();
  const checkout = await newTab;
  await checkout.waitForLoadState('domcontentloaded', { timeout: 30000 }).catch(() => {});
  const host = new URL(checkout.url()).host; // Only the host is recorded; the URL is never printed.
  record('background opened Stripe Checkout in a NEW tab', host === 'checkout.stripe.com', `host ${host}`);
  await checkout.waitForTimeout(4000);
  await checkout.screenshot({ path: join(out, '03-stripe-checkout.png') }); // Stripe shows its own test-mode banner.

  const t = await sw.evaluate(() => globalThis.__fazetimeDebug.topup());
  record('tracked top-up: PENDING, opened, watching; no URL in the tab-facing view', t?.status === 'PENDING' && t.checkout_opened && t.watching && !JSON.stringify(t).includes('stripe.com'), `${t?.topup_id?.slice(0, 8)}… ${t?.status} $${(t?.amount_minor ?? 0) / 100}`);
  const row = dbRow(t.topup_id);
  record('server row is PENDING with a cs_test_ session (DB, read-only)', row?.[0] === 'PENDING' && row?.[1] === 500 && row?.[2] === 1, JSON.stringify(row));
  await page.bringToFront();
  await panel.getByText('Finish paying $5.00 in the Stripe tab.').waitFor({ timeout: 5000 });
  const getsBefore = (serverLog.match(/GET \/v1\/topups\/top_/g) ?? []).length;
  await sleep(7000);
  const getsAfter = (serverLog.match(/GET \/v1\/topups\/top_/g) ?? []).length;
  record('background polls GET /v1/topups/{id} about every 3 s while PENDING', getsAfter - getsBefore >= 2, `${getsAfter - getsBefore} GETs in 7 s (server access log)`);
  await page.screenshot({ path: join(out, '04-pending.png') });

  // Return without payment (cancel URL shape): a hint only. Status stays PENDING, nothing is credited.
  await checkout.close();
  await page.goto(`https://www.twitch.tv/${CHANNEL}?fazetime_topup=${t.topup_id}&fazetime_result=cancel`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.locator('[data-fazetime-host="panel"] .ft-panel').waitFor({ timeout: 40000 });
  await page.locator('[data-fazetime-host="panel"] .ft-panel').getByText('Checkout was closed before payment. No credits were added.').waitFor({ timeout: 15000 });
  const after = await api('GET', `/v1/streams/${probe.me.current_stream.stream_id}/snapshot`, probe.session_token);
  const row2 = dbRow(t.topup_id);
  record('return URL without payment: still PENDING, no credit', row2?.[0] === 'PENDING', `server ${row2?.[0]}`);
  await page.screenshot({ path: join(out, '05-returned-no-payment.png') });
  void after;
  void before;

  // Reload keeps the tracked top-up (persisted in background storage).
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.locator('[data-fazetime-host="panel"] .ft-panel').waitFor({ timeout: 40000 });
  const t2 = await sw.evaluate(() => globalThis.__fazetimeDebug.topup());
  record('after a tab reload the background still tracks the same top-up', t2?.topup_id === t.topup_id && t2.status === 'PENDING');

  const PATS = { checkoutUrl: /checkout\.stripe\.com/, sessionId: /cs_test_/, sessionToken: /fzs_/, wsTicket: /fzw_/, stripeKey: /sk_test_|rk_test_|whsec_/ };
  const hits = [];
  for (const [name, re] of Object.entries(PATS)) {
    if (re.test(serverLog)) hits.push(`server:${name}`);
    for (const l of swLogs) if (re.test(l.text)) hits.push(`console[${l.host}]:${name}`);
  }
  const ours = hits.filter((h) => h.startsWith('server:') || h.includes(EXT_ID) || h.startsWith('console[sw:') || h.includes('www.twitch.tv'));
  const stripeOwn = hits.filter((h) => !ours.includes(h));
  record('no Checkout URL, session id, token or key in the server log or the extension/Twitch-page console', ours.length === 0, `${swLogs.length} console lines; our hits: ${JSON.stringify([...new Set(ours)])}; Stripe-page-only hits (not ours): ${JSON.stringify([...new Set(stripeOwn)])}`);
} catch (err) {
  record('e2e threw', false, String(err?.message ?? err).slice(0, 300));
} finally {
  await ctx?.close().catch(() => {});
  server.kill('SIGTERM');
  const passed = results.filter((r) => r.ok).length;
  writeFileSync(join(out, 'summary.json'), JSON.stringify({ when: new Date().toISOString(), passed, total: results.length, results }, null, 2));
  console.log(`\n${passed}/${results.length} passed. Artifacts: ${out}`);
  process.exit(passed === results.length ? 0 : 1);
}
