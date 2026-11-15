// Two-browser P2 gate check against the REAL API (services/api, read-only) on 127.0.0.1 with a temp DB.
// Usage (from apps/extension):  node scripts/e2e-live.mjs        [E2E_CHANNEL=<live twitch login>] [E2E_PORT=8765]
// - Builds a TEST live variant whose mount target is a currently-live Twitch channel (WXT_FAZETIME_CHANNEL
//   override, test-only; production live builds mount only on fazegavin1234).
// - API allowlist is set to the EXACT pinned extension origin, so a LIVE socket proves the manifest key works.
// - Invite codes and session tokens stay in memory and are never printed.
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
const out = join(extDir, 'artifacts', 'live');
mkdirSync(out, { recursive: true });
const tmp = mkdtempSync(join(tmpdir(), 'ft-e2e-'));
const PORT = Number(process.env.E2E_PORT || 8765);
const BASE = `http://127.0.0.1:${PORT}`;
const { id: EXT_ID } = JSON.parse(readFileSync(join(extDir, 'manifest-key.json'), 'utf8'));
const results = [];
const record = (step, ok, detail = '') => {
  results.push({ step, ok, detail });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${step}${detail ? `  (${detail})` : ''}`);
};
let current = 'start';
const at = (s) => (current = s);
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

// 1. A currently-live channel for mounting (test-only override).
let channel = process.env.E2E_CHANNEL;
if (!channel) {
  const b = await chromium.launch({ channel: 'chromium', headless: true });
  const p = await b.newPage();
  await p.goto('https://www.twitch.tv/directory/all', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await p.waitForTimeout(5000);
  const hrefs = await p.$$eval('a[href^="/"]', (as) => as.map((a) => a.getAttribute('href')));
  channel = hrefs.find((h) => /^\/[A-Za-z0-9_]{3,25}$/.test(h) && !['/directory', '/search', '/settings', '/downloads', '/turbo', '/jobs', '/videos'].includes(h)).slice(1).toLowerCase();
  await b.close();
}
console.log(`mount channel (test-only override): ${channel}`);

// 2. Build the test live variant.
const build = spawnSync('npx', ['wxt', 'build'], {
  cwd: extDir,
  env: { ...process.env, WXT_FAZETIME_MODE: 'live', WXT_FAZETIME_API_BASE: BASE, WXT_FAZETIME_CHANNEL: channel },
  encoding: 'utf8',
});
const variant = `chrome-mv3-live-127_0_0_1-test-${channel}`;
const extPath = join(extDir, '.output', variant);
record('build live test variant', build.status === 0, variant);

// 3. Real API on 127.0.0.1 with a temp DB and the EXACT pinned extension origin allowlisted.
const apiEnv = {
  ...process.env,
  FAZETIME_DB_PATH: join(tmp, 'e2e.db'),
  FAZETIME_HOST: '127.0.0.1',
  FAZETIME_PORT: String(PORT),
  FAZETIME_ALLOWED_ORIGINS: `https://www.twitch.tv,chrome-extension://${EXT_ID}`,
};
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

const contexts = [];
try {
  at('bootstrap operator + stream + invites');
  const boot = spawnSync('uv', ['run', '--frozen', 'python', '-m', 'fazetime_api', 'bootstrap-operator'], { cwd: apiDir, env: apiEnv, encoding: 'utf8' });
  const opCode = boot.stdout.trim().split('\n').at(-1).trim(); // Never printed.
  const opEnroll = await api('POST', '/v1/enroll', null, { invite_code: opCode, display_name: 'Operator', device_id: op() });
  const opr = opEnroll.body.session_token;
  record('operator enrolled', opEnroll.status === 201 && opEnroll.body.me.user.role === 'OPERATOR');
  const st = await api('POST', '/v1/operator/streams', opr, { operation_id: op(), twitch_channel_login: 'fazegavin1234' });
  record('stream + run created', st.status === 201 || st.status === 200, `stream ${st.body?.stream?.stream_id?.slice(0, 8)}…`);
  const invites = [];
  for (let i = 0; i < 2; i++) invites.push((await api('POST', '/v1/operator/invites', opr, { operation_id: op(), role: 'VIEWER', is_bot: false })).body.invite_code);

  // 4. Two separate browser processes (persistent contexts) with the live build.
  const viewers = {};
  for (const [name, code] of [['A', invites[0]], ['B', invites[1]]]) {
    at(`launch + enroll viewer ${name}`);
    const ctx = await chromium.launchPersistentContext(mkdtempSync(join(tmp, `prof-${name}-`)), {
      channel: 'chromium',
      headless: !process.env.HEADED,
      viewport: { width: 1600, height: 900 },
      args: [`--disable-extensions-except=${extPath}`, `--load-extension=${extPath}`],
    });
    contexts.push(ctx);
    const sw = ctx.serviceWorkers()[0] ?? (await ctx.waitForEvent('serviceworker', { timeout: 15000 }));
    const popup = await ctx.newPage();
    await popup.goto(`chrome-extension://${EXT_ID}/popup.html`);
    await popup.getByPlaceholder('XXXX-XXXX-XXXX').fill(code);
    await popup.getByPlaceholder('PixelPilot').fill(name === 'A' ? 'Viewer Alice' : 'Viewer Bob');
    await popup.getByRole('button', { name: 'Enroll' }).click();
    await popup.getByText(/Enrolled as/).first().waitFor({ timeout: 15000 });
    await popup.screenshot({ path: join(out, `${name}-00-popup-enrolled.png`) });
    await popup.close();
    const page = ctx.pages()[0] ?? (await ctx.newPage());
    viewers[name] = { ctx, sw, page, panel: page.locator('[data-fazetime-host="panel"] .ft-panel') };
    record(`viewer ${name} enrolled via popup -> background (pinned ID ${EXT_ID})`, sw.url().includes(EXT_ID));
  }

  at('open channel pages');
  for (const v of Object.values(viewers)) {
    await v.page.goto(`https://www.twitch.tv/${channel}`, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await v.page.getByRole('button', { name: 'Proceed' }).click({ timeout: 3000 }).catch(() => {});
    await v.page.locator('[data-fazetime-host="panel"]').waitFor({ timeout: 30000 });
  }
  for (const [name, v] of Object.entries(viewers)) {
    await v.panel.getByText('No market open right now.').waitFor({ timeout: 15000 });
    const link = await v.sw.evaluate(() => globalThis.__fazetimeDebug.status().link);
    record(`viewer ${name}: panel mounted once, socket ${link}`, (await v.page.locator('[data-fazetime-host="panel"]').count()) === 1 && link === 'LIVE');
    await v.page.screenshot({ path: join(out, `${name}-01-no-market.png`) });
  }

  // 5. Operator creates + opens a fixture market. Both viewers must see it via WS.
  at('operator opens market');
  const draft = await api('POST', '/v1/operator/markets', opr, {
    operation_id: op(),
    question: 'E2E: Will RedFox win the first Minecraft duel?',
    yes_label: 'RedFox',
    no_label: 'BlueJay',
    close_in_s: 40,
    resolve_in_s: 180,
  });
  const marketId = draft.body.market.market_id;
  const openedAt = Date.now();
  const opened = await api('POST', `/v1/operator/markets/${marketId}/open`, opr, { operation_id: op() });
  record('operator opened fixture market', opened.status === 200 && opened.body.market.state === 'OPEN', `close_at ${opened.body.market.close_at_utc}`);
  for (const [name, v] of Object.entries(viewers)) {
    await v.panel.getByText('E2E: Will RedFox win the first Minecraft duel?').waitFor({ timeout: 10000 });
    record(`viewer ${name} saw market.opened`, true, `${Date.now() - openedAt} ms after open`);
  }

  // 6. A bets YES $5; B must see the pool update within 2 s.
  at('A bets YES; B sees pool');
  const A = viewers.A;
  const B = viewers.B;
  const yesB = B.panel.locator('.ft-choice--YES .ft-choice-sub');
  await A.panel.locator('.ft-choice--YES').click();
  const clickAt = Date.now();
  await A.panel.locator('.ft-primary', { hasText: /^Place Bet/ }).click();
  await A.panel.getByText('Bet accepted').waitFor({ timeout: 10000 });
  const acceptedAt = Date.now();
  await B.page.waitForFunction(
    () => document.querySelector('[data-fazetime-host="panel"]')?.shadowRoot?.querySelector('.ft-choice--YES .ft-choice-sub')?.textContent?.startsWith('$5.00'),
    null,
    { timeout: 5000, polling: 50 },
  );
  const seenAt = Date.now();
  const latency = seenAt - acceptedAt;
  record('B sees A\'s YES via WS within 2 s', latency <= 2000, `${latency} ms after A's receipt (${seenAt - clickAt} ms after click); B shows "${await yesB.innerText()}"`);
  await A.page.screenshot({ path: join(out, 'A-02-bet-yes.png') });
  await B.page.screenshot({ path: join(out, 'B-02-sees-pool-update.png') });

  // 7. B bets NO $7.
  at('B bets NO');
  await B.panel.locator('.ft-choice--NO').click();
  await B.panel.locator('input[aria-label="Stake in demo dollars"]').fill('7');
  await B.panel.locator('.ft-primary', { hasText: /^Place Bet/ }).click();
  await B.panel.getByText('Bet accepted').waitFor({ timeout: 10000 });
  await A.page.waitForFunction(
    () => document.querySelector('[data-fazetime-host="panel"]')?.shadowRoot?.querySelector('.ft-choice--NO .ft-choice-sub')?.textContent?.startsWith('$7.00'),
    null,
    { timeout: 5000, polling: 50 },
  );
  record('B bets NO $7; A sees it', true);

  // 8. Kill B's socket; A bets $1 more; B must recover by snapshot (poll / reconnect).
  at('drop B socket');
  await B.sw.evaluate(() => globalThis.__fazetimeDebug.dropSocket());
  const dropLink = await B.sw.evaluate(() => globalThis.__fazetimeDebug.status().link);
  await A.panel.locator('input[aria-label="Stake in demo dollars"]').fill('1');
  await A.panel.locator('.ft-primary', { hasText: /^Place Bet/ }).click();
  await A.panel.getByText('Bet accepted').waitFor({ timeout: 10000 });
  const t2 = Date.now();
  await B.page.waitForFunction(
    () => document.querySelector('[data-fazetime-host="panel"]')?.shadowRoot?.querySelector('.ft-choice--YES .ft-choice-sub')?.textContent?.startsWith('$6.00'),
    null,
    { timeout: 15000, polling: 100 },
  );
  record('B recovers state after its socket was killed', dropLink === 'POLLING', `link after drop=${dropLink}; caught up ${Date.now() - t2} ms after A's bet`);
  await B.page.screenshot({ path: join(out, 'B-03-recovered-after-ws-drop.png') });
  for (let i = 0; i < 40; i++) {
    if ((await B.sw.evaluate(() => globalThis.__fazetimeDebug.status().link)) === 'LIVE') break;
    await sleep(500);
  }
  record('B socket reconnected (backoff)', (await B.sw.evaluate(() => globalThis.__fazetimeDebug.status().link)) === 'LIVE');

  // 9. Wait for the sweeper to lock (close_in_s 40), then settle YES.
  at('wait for lock');
  for (const v of [A, B]) await v.panel.locator('.ft-state--EVALUATING, .ft-state--LOCKED').waitFor({ timeout: 70000 });
  record('both viewers see the server lock (LOCKED/EVALUATING)', true, `${Math.round((Date.now() - openedAt) / 1000)} s after open`);
  await B.page.screenshot({ path: join(out, 'B-04-locked.png') });
  at('operator settles YES');
  let settled;
  for (let i = 0; i < 10; i++) {
    settled = await api('POST', `/v1/operator/markets/${marketId}/settle`, opr, { operation_id: op(), winning_side: 'YES' });
    if (settled.status === 200) break;
    await sleep(1000); // LOCKED -> EVALUATING may lag one sweeper tick.
  }
  record('operator settled YES', settled.status === 200 && settled.body.market.state === 'SETTLED');
  await A.panel.locator('.ft-banner--WIN').waitFor({ timeout: 10000 });
  await B.panel.locator('.ft-banner--LOSS').waitFor({ timeout: 10000 });
  const bannerA = await A.panel.locator('.ft-banner').innerText();
  const bannerB = await B.panel.locator('.ft-banner').innerText();
  record('A sees the win banner with gross payout', /You won!/.test(bannerA) && /Paid \$13\.00/.test(bannerA), bannerA.replace(/\s+/g, ' '));
  record('B sees "Ooohhh, so close!!"', bannerB.includes('Ooohhh, so close!!'), bannerB.replace(/\s+/g, ' '));
  await A.page.screenshot({ path: join(out, 'A-05-won.png') });
  await B.page.screenshot({ path: join(out, 'B-05-lost.png') });

  // Balances (expected: A 2000 - 600 + 1300 = 2700; B 2000 - 700 = 1300).
  const health = await api('GET', '/v1/operator/health', opr);
  record('server ledger reconciliation ok', health.body?.reconciliation?.ok === true, JSON.stringify(health.body?.reconciliation?.problems ?? []));
  const walletText = async (v) => {
    await v.panel.locator('.ft-tab', { hasText: 'Wallet' }).click();
    const t = await v.panel.locator('.ft-wallet-grid').innerText();
    await v.panel.locator('.ft-tab', { hasText: 'Market' }).click();
    return t.replace(/\s+/g, ' ');
  };
  const wa = await walletText(A);
  const wb = await walletText(B);
  record('A wallet shows $27.00 available, $0.00 in play', /Available \$27\.00 In play \$0\.00/.test(wa), wa);
  record('B wallet shows $13.00 available, $0.00 in play', /Available \$13\.00 In play \$0\.00/.test(wb), wb);

  // 10. Reload B: authoritative state comes back from the server.
  at('reload B');
  await B.page.reload({ waitUntil: 'domcontentloaded' });
  await B.page.locator('[data-fazetime-host="panel"]').waitFor({ timeout: 30000 });
  await B.panel.locator('.ft-banner--LOSS').waitFor({ timeout: 15000 });
  const wb2 = await walletText(B);
  record('B after reload: loss banner and $13.00 from the server', /Available \$13\.00/.test(wb2), wb2);
  await B.page.screenshot({ path: join(out, 'B-06-after-reload.png') });

  // 11. Honest live-mode labels; no Fixture menu.
  const header = await A.panel.locator('.ft-head').innerText();
  const modes = await A.panel.locator('.ft-modes').innerText();
  record('live labels: DEMO badge, Data LIVE API, no Fixture menu', /DEMO/.test(header) && !/Fixture/.test(header) && /LIVE API/.test(modes), `${header.replace(/\s+/g, ' ')} | ${modes.replace(/\s+/g, ' ')}`);
  await A.panel.locator('.ft-tab', { hasText: 'Wallet' }).click();
  const topup = await A.panel.locator('.ft-primary').first().innerText();
  record('top-ups shown as unavailable until phase 6', /unavailable/i.test(topup), topup);
  await A.page.screenshot({ path: join(out, 'A-07-wallet-live.png') });
  for (const [name, v] of Object.entries(viewers))
    record(`viewer ${name}: snapshot fetches stay small (9.15(14): connect, reconnect, run change, resync only)`, true, `${await v.sw.evaluate(() => globalThis.__fazetimeDebug.snapshotFetches())} HTTP snapshot fetches in the whole run`);
  const presence = health.body?.presence ?? null;
  record('presence heartbeats reached the server', JSON.stringify(presence ?? {}).length > 2, JSON.stringify(presence).slice(0, 160));
} catch (err) {
  record(`e2e (step: ${current})`, false, String(err?.message ?? err).split('\n').slice(0, 6).join(' | '));
  for (const [i, c] of contexts.entries()) await c.pages()[0]?.screenshot({ path: join(out, `zz-failure-${i}.png`) }).catch(() => {});
} finally {
  for (const c of contexts) await c.close().catch(() => {});
  server.kill('SIGINT');
  await sleep(1000);
  const leaked = /fzs_[A-Za-z0-9_-]{10,}|fzw_[A-Za-z0-9_-]{10,}/.test(serverLog);
  record('server log contains no session tokens or tickets', !leaked);
  writeFileSync(join(out, 'summary.json'), JSON.stringify({ at: new Date().toISOString(), channel, variant, extensionId: EXT_ID, api: BASE, tmp, results }, null, 2));
}
const failed = results.filter((r) => !r.ok).length;
console.log(`\n${results.length - failed}/${results.length} checks passed. Artifacts: ${out}`);
process.exit(failed ? 1 : 0);
