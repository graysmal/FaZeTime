// Real-browser smoke test on live twitch.tv (logged out) with the built unpacked extension.
// Usage: npx wxt build && node scripts/smoke.mjs   (screenshots + summary.json in artifacts/)
// Uses Playwright's bundled Chromium (channel "chromium"), which still honours --load-extension.
import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const here = dirname(fileURLToPath(import.meta.url));
const extPath = join(here, '..', '.output', 'chrome-mv3');
const out = join(here, '..', 'artifacts');
mkdirSync(out, { recursive: true });
const results = [];
const record = (step, ok, detail = '') => {
  results.push({ step, ok, detail });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${step}${detail ? `  (${detail})` : ''}`);
};
let current = 'start';
const at = (label) => {
  current = label;
};
const shot = (page, name) => page.screenshot({ path: join(out, `${name}.png`) });

const ctx = await chromium.launchPersistentContext(mkdtempSync(join(tmpdir(), 'ft-smoke-')), {
  channel: 'chromium',
  headless: process.env.HEADED ? false : true,
  viewport: { width: 1600, height: 900 },
  args: [`--disable-extensions-except=${extPath}`, `--load-extension=${extPath}`],
});
const page = ctx.pages()[0] ?? (await ctx.newPage());
const panelHosts = () => page.locator('[data-fazetime-host="panel"]').count();
const overlayHosts = () => page.locator('[data-fazetime-host="overlay"]').count();
const panel = page.locator('[data-fazetime-host="panel"] .ft-panel');

async function pickFixture(name) {
  await panel.locator('.ft-chip-btn', { hasText: 'Fixture' }).click();
  await panel.locator('.ft-menu-item[role="menuitemradio"]', { hasText: new RegExp(`[●○] ${name}$`) }).click();
  await page.waitForTimeout(700);
}

try {
  let sw = ctx.serviceWorkers()[0];
  if (!sw) sw = await ctx.waitForEvent('serviceworker', { timeout: 15000 });
  record('extension service worker started', Boolean(sw), sw?.url());

  await page.goto('https://www.twitch.tv/directory/all', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(5000);
  await page.getByRole('button', { name: 'Proceed' }).click({ timeout: 3000 }).catch(() => {});
  const reserved = new Set(['/directory', '/search', '/settings', '/downloads', '/turbo', '/jobs', '/p', '/videos']);
  const channels = (await page.$$eval('a[href^="/"]', (as) => as.map((a) => a.getAttribute('href')))).filter(
    (h, i, all) => /^\/[A-Za-z0-9_]{3,25}$/.test(h) && !reserved.has(h) && all.indexOf(h) === i,
  );
  const first = channels[0];
  await page.goto(`https://www.twitch.tv${first}`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.locator('[data-fazetime-host="panel"]').waitFor({ timeout: 30000 });
  await page.waitForTimeout(4000);
  record('mounts exactly once on a channel page', (await panelHosts()) === 1 && (await overlayHosts()) <= 1, `${first}: panel=${await panelHosts()} overlay=${await overlayHosts()}`);
  const placement = await page.locator('[data-fazetime-host="panel"]').getAttribute('data-fazetime-placement');
  record('panel placed above chat (not floating)', placement === 'chat', `placement=${placement}`);
  await page.waitForTimeout(3000);
  record('no duplicates after 7 s of live page churn', (await panelHosts()) === 1 && (await overlayHosts()) <= 1);
  await shot(page, '01-channel-mounted');

  // SPA navigation through an in-page link.
  await page.evaluate(() => {
    window.__ftNoReload = true;
    document.querySelector('[data-fazetime-host="panel"]').__ftOld = true;
  });
  const target = await page.$$eval(
    'a[href^="/"]',
    (as, current) =>
      as
        .map((a) => a.getAttribute('href'))
        .find((h) => /^\/[A-Za-z0-9_]{3,25}$/.test(h) && h.toLowerCase() !== current.toLowerCase() && !['/directory', '/search', '/settings', '/videos'].includes(h)),
    first,
  );
  await page.locator(`a[href="${target}"]`).first().click();
  await page.waitForURL((u) => u.pathname.toLowerCase() === target.toLowerCase(), { timeout: 20000 });
  await page.waitForFunction(() => {
    const h = document.querySelector('[data-fazetime-host="panel"]');
    return h && !h.__ftOld;
  }, null, { timeout: 30000 });
  await page.waitForTimeout(4000);
  const noReload = await page.evaluate(() => window.__ftNoReload === true);
  record('SPA navigation without reload', noReload, `${first} -> ${target}`);
  record('remounted exactly once after SPA navigation', (await panelHosts()) === 1 && (await overlayHosts()) <= 1, `panel=${await panelHosts()} overlay=${await overlayHosts()}`);
  await shot(page, '02-after-spa-navigation');

  // Labels.
  const hiddenBy = await page.evaluate(() => document.querySelector('[data-fazetime-host="panel"]').closest('[aria-hidden="true"]')?.tagName ?? 'none');
  console.log(`diagnostic: aria-hidden ancestor of panel host = ${hiddenBy}`);
  const header = await panel.locator('.ft-head').innerText();
  const modes = await panel.locator('.ft-modes').innerText();
  record('MOCK badge and three mode labels visible', /MOCK/.test(header) && /Media/.test(modes) && /Model/.test(modes) && /Funds/.test(modes), modes.replace(/\s+/g, ' '));

  // Mock wager on the default fixture.
  at('pick open_no_position');
  await pickFixture('open_no_position');
  at('select side');
  await panel.locator('.ft-choice').first().click();
  at('click Place Bet');
  await panel.locator('.ft-primary', { hasText: /^Place Bet/ }).click();
  at('wait for Bet accepted');
  await panel.getByText('Bet accepted').waitFor({ timeout: 10000 });
  record('mock wager accepted with receipt', true, await panel.locator('.ft-status').innerText());
  await shot(page, '03-mock-wager-accepted');

  // Insufficient funds -> top-up dialog.
  at('insufficient funds flow');
  await pickFixture('open_low_balance');
  await panel.locator('.ft-choice').first().click();
  await panel.locator('.ft-primary', { hasText: 'Top up to bet' }).click();
  await panel.locator('.ft-dialog').waitFor({ timeout: 5000 });
  const dialog = await panel.locator('.ft-dialog').innerText();
  record('insufficient funds opens MOCK top-up dialog with FaZe Up!', /FaZe Up!/.test(dialog) && /MOCK/.test(dialog), dialog.split('\n')[0]);
  await shot(page, '04-insufficient-funds-topup');
  await panel.locator('.ft-primary', { hasText: 'FaZe Up!' }).click();
  await panel.getByText(/Added \$5\.00 of MOCK demo funds/).waitFor({ timeout: 5000 });
  record('MOCK top-up credited', true);
  await panel.locator('.ft-secondary', { hasText: 'Done' }).click();

  // Terminal states.
  at('terminal states');
  for (const [name, text] of [
    ['settled_win', 'You won!'],
    ['settled_loss', 'Ooohhh, so close!!'],
    ['void_one_sided', 'Market voided, stake refunded'],
    ['void_unresolvable', 'Unresolved, stake refunded'],
    ['settled_no_position', 'Result:'],
  ]) {
    await pickFixture(name);
    const ok = (await panel.locator('.ft-banner').count()) === 1 && (await panel.locator('.ft-banner').innerText()).includes(text);
    record(`terminal banner ${name}`, ok);
    await shot(page, `05-banner-${name}`);
  }
  await pickFixture('open_no_position');

  // Close / reopen.
  at('close/reopen');
  await panel.locator('button[aria-label="Close the FaZeTime panel"]').click();
  await page.waitForTimeout(300);
  const closedH = await page.locator('[data-fazetime-host="panel"]').evaluate((h) => h.getBoundingClientRect().height);
  await shot(page, '06-panel-closed');
  await panel.locator('button[aria-label="Open the FaZeTime panel"]').click();
  await page.waitForTimeout(300);
  const openH = await page.locator('[data-fazetime-host="panel"]').evaluate((h) => h.getBoundingClientRect().height);
  record('close and reopen', closedH < 60 && openH > closedH, `closed=${Math.round(closedH)}px open=${Math.round(openH)}px`);

  // Keyboard resize (no focus trap: Tab moves on).
  at('keyboard resize');
  const chatBefore = await page.locator('section.chat-room').first().evaluate((e) => e.getBoundingClientRect().height);
  await panel.locator('.ft-resize').focus();
  for (let i = 0; i < 5; i++) await page.keyboard.press('ArrowDown');
  await page.waitForTimeout(300);
  const resizedH = await page.locator('[data-fazetime-host="panel"]').evaluate((h) => h.getBoundingClientRect().height);
  const chatAfter = await page.locator('section.chat-room').first().evaluate((e) => e.getBoundingClientRect().height);
  record('keyboard resize grows panel and shrinks chat', resizedH > openH && chatAfter < chatBefore, `panel ${Math.round(openH)}->${Math.round(resizedH)} chat ${Math.round(chatBefore)}->${Math.round(chatAfter)}`);
  await page.keyboard.press('Tab');
  const focusLeft = await page.evaluate(() => {
    const sr = document.querySelector('[data-fazetime-host="panel"]')?.shadowRoot;
    return !(sr?.activeElement?.classList.contains('ft-resize'));
  });
  record('Tab leaves the resize handle (no trap)', focusLeft);
  await shot(page, '07-resized');

  // Over-video dropdown clears the player controls.
  at('over-video dropdown');
  if ((await overlayHosts()) === 1) {
    const overlay = page.locator('[data-fazetime-host="overlay"]');
    await overlay.locator('.ft-pill').click();
    await page.waitForTimeout(500);
    const drop = await overlay.evaluate((h) => h.getBoundingClientRect().bottom);
    const controls = await page.locator('[data-a-target="player-controls"]').first().boundingBox();
    const player = await page.locator('[data-a-target="video-player"]').first().boundingBox();
    const controlsTop = controls && controls.height > 0 ? controls.y : (player ? player.y + player.height - 50 : Infinity);
    record('over-video dropdown stays above the player controls', drop <= controlsTop, `dropdown bottom=${Math.round(drop)} controls top=${Math.round(controlsTop)}`);
    await shot(page, '08-over-video-dropdown');
    await overlay.locator('.ft-pill').click();
  } else record('over-video dropdown mounted', false, 'no player anchor found');

  const single = async () => (await panelHosts()) === 1 && (await overlayHosts()) <= 1;
  const playerWidth = async () => Math.round((await page.locator('[data-a-target="video-player"]').first().boundingBox())?.width ?? 0);
  const blur = () => page.evaluate(() => (document.activeElement instanceof HTMLElement ? document.activeElement.blur() : undefined));

  // Theater mode (Alt+T), with the player's theatre button as a fallback.
  at('theater mode');
  const w0 = await playerWidth();
  await blur();
  await page.keyboard.press('Alt+t');
  await page.waitForTimeout(1500);
  let w1 = await playerWidth();
  let how = 'Alt+T';
  if (Math.abs(w1 - w0) < 40) {
    await page.locator('[data-a-target="video-player"]').first().hover();
    await page.locator('button[aria-label*="heat" i]').first().click({ timeout: 5000 }).catch(() => {});
    await page.waitForTimeout(1500);
    w1 = await playerWidth();
    how = 'theatre button';
  }
  const theaterOn = Math.abs(w1 - w0) >= 40;
  await page.waitForTimeout(1500);
  record('theater mode on: single mount', theaterOn && (await single()), `${how}: player width ${w0} -> ${w1}; panel=${await panelHosts()} overlay=${await overlayHosts()}`);
  await shot(page, '09-theater-mode');
  await blur();
  await page.keyboard.press('Alt+t');
  await page.waitForTimeout(1500);
  if (Math.abs((await playerWidth()) - w0) >= 40) {
    await page.locator('[data-a-target="video-player"]').first().hover();
    await page.locator('button[aria-label*="heat" i]').first().click({ timeout: 5000 }).catch(() => {});
    await page.waitForTimeout(1500);
  }
  await page.waitForTimeout(1000);
  record('theater mode off: single mount, panel back above chat', (await single()) && (await page.locator('[data-fazetime-host="panel"]').getAttribute('data-fazetime-placement')) === 'chat', `player width ${await playerWidth()}`);

  // Chat collapse / expand.
  at('chat collapse');
  await page.locator('[data-a-target="right-column__toggle-collapse-btn"]').first().click();
  await page.waitForTimeout(2500);
  const floating = await page.locator('[data-fazetime-placement="floating"]').count();
  const visiblePanel = await page.locator('[data-fazetime-host="panel"]').evaluate((h) => h.getBoundingClientRect().height > 0).catch(() => false);
  record('chat collapsed: no floating fallback, no duplicate, pill still mounted', floating === 0 && (await panelHosts()) <= 1 && (await overlayHosts()) === 1, `panel hosts=${await panelHosts()} visible=${visiblePanel}`);
  await shot(page, '10-chat-collapsed');
  at('chat expand');
  const expand = page.locator('[data-a-target="right-column__toggle-collapse-btn"]').first();
  if (await expand.count()) await expand.click();
  else await page.getByRole('button', { name: /expand/i }).first().click();
  await page.locator('[data-fazetime-host="panel"][data-fazetime-placement="chat"]').waitFor({ timeout: 15000 });
  await page.waitForTimeout(1500);
  const restored = await page.locator('[data-fazetime-host="panel"]').evaluate((h) => ({ h: Math.round(h.getBoundingClientRect().height), afterHeader: h.nextElementSibling?.classList.contains('stream-chat-header') }));
  record('chat expanded: panel restored above chat exactly once', (await single()) && restored.h > 0 && restored.afterHeader === true, JSON.stringify(restored));
  await shot(page, '11-chat-expanded');

  // Full-screen via the player's button (a trusted click), then exit.
  at('full-screen');
  await page.locator('[data-a-target="video-player"]').first().hover();
  await page.locator('[data-a-target="player-fullscreen-button"]').first().click({ timeout: 5000 }).catch(() => {});
  await page.waitForTimeout(1500);
  const fsOn = await page.evaluate(() => Boolean(document.fullscreenElement));
  const pillsInFs = await page.evaluate(() => document.querySelector('[data-fazetime-host="overlay"]')?.shadowRoot?.querySelectorAll('.ft-pill').length ?? -1);
  if (!fsOn) record('full-screen entered (headless)', false, 'document.fullscreenElement stayed null: not verifiable headless');
  else record('full-screen: over-video pill hidden, single mount', pillsInFs === 0 && (await single()), `pills=${pillsInFs}`);
  await shot(page, '12-fullscreen');
  await page.evaluate(() => (document.fullscreenElement ? document.exitFullscreen() : undefined)).catch(() => {});
  await page.waitForTimeout(1500);
  const pillsAfter = await page.evaluate(() => document.querySelector('[data-fazetime-host="overlay"]')?.shadowRoot?.querySelectorAll('.ft-pill').length ?? -1);
  record('full-screen exit: pill back, single mount', !(await page.evaluate(() => Boolean(document.fullscreenElement))) && pillsAfter === 1 && (await single()), `pills=${pillsAfter}`);
} catch (err) {
  record(`smoke run (step: ${current})`, false, String(err?.message ?? err).split('\n').slice(0, 8).join(' | '));
  await shot(page, 'zz-failure').catch(() => {});
} finally {
  writeFileSync(join(out, 'summary.json'), JSON.stringify({ at: new Date().toISOString(), results }, null, 2));
  await ctx.close();
}
const failed = results.filter((r) => !r.ok).length;
console.log(`\n${results.length - failed}/${results.length} checks passed. Artifacts: ${out}`);
process.exit(failed ? 1 : 0);
