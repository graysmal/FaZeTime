import type { ReactElement } from 'react';
import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { bannerFor, LOSS_BANNER_TEXT, type StreamSnapshot } from '@fazetime/contracts';
import { loadSnapshotFixture, SNAPSHOT_FIXTURE_NAMES, type SnapshotFixtureName } from '../src/mock/fixtures';
import { bannerCopy, MarketCard } from '../src/ui/MarketCard';
import { Panel, clampPanelHeight, CHAT_MIN_PX, PANEL_MIN_PX, TopUpDialog, WalletTab } from '../src/ui/Panel';
import { Overlay } from '../src/ui/Overlay';
import { EnvContext, type UiEnv } from '../src/ui/hooks';
import { initialPanelState, PanelController, type PanelState } from '../src/state/controller';

function envWith(state: Partial<PanelState>, mode: 'mock' | 'live' = 'mock'): UiEnv {
  const controller = new PanelController({} as never, { get: async () => null, set: async () => undefined, remove: async () => undefined });
  (controller as unknown as { state: PanelState }).state = { ...initialPanelState(), ...state };
  return {
    controller,
    kv: { get: async () => null, set: async () => undefined, remove: async () => undefined },
    watch: () => () => undefined,
    channel: 'somechannel',
    doc: document,
    mode,
    requestPanelOpen: () => undefined,
    onPanelOpenRequest: () => () => undefined,
  };
}

const render = (env: UiEnv, node: ReactElement) => renderToStaticMarkup(<EnvContext.Provider value={env}>{node}</EnvContext.Provider>);
// Shift to now, exactly as the MOCK adapter does, so open markets are still open.
const snap = (name: string): StreamSnapshot => loadSnapshotFixture(name as SnapshotFixtureName, Date.now());

describe('terminal banners (CONTRACTS 9.14 mapping)', () => {
  const expected: Record<string, RegExp | null> = {
    settled_win: /You won!/,
    settled_loss: new RegExp(LOSS_BANNER_TEXT.replace(/[!]/g, '!')),
    settled_no_position: /Result: RedFox won/,
    void_one_sided: /Market voided, stake refunded/,
    void_empty: /Market voided/,
    void_source_gap: /Market voided, stake refunded/,
    void_resolution_timeout: /Unresolved, stake refunded/,
    void_unresolvable: /Unresolved, stake refunded/,
  };
  it.each([...SNAPSHOT_FIXTURE_NAMES])('%s renders the right banner (or none)', (name) => {
    const s = snap(name);
    const html = render(envWith({ snapshot: s }), <MarketCard surface="panel" />);
    const banners = html.match(/ft-banner--/g) ?? [];
    const want = expected[name] ?? null;
    if (want) {
      expect(banners).toHaveLength(1);
      expect(html).toMatch(want);
      expect(bannerCopy(s.market!, s.my_position)?.banner).toBe(bannerFor(s.market, s.my_position));
    } else {
      expect(banners).toHaveLength(0);
    }
  });

  it('the loss banner uses the exact copy', () => {
    expect(bannerCopy(snap('settled_loss').market!, snap('settled_loss').my_position)?.title).toBe('Ooohhh, so close!!');
  });

  it('the win banner shows the gross payout including stake', () => {
    expect(bannerCopy(snap('settled_win').market!, snap('settled_win').my_position)?.detail).toContain('Paid $12.50 including your $5.00 stake');
  });
});

describe('market card content', () => {
  it('shows question, named sides, pool total, countdown, estimate label and default 500 stake', () => {
    const s = snap('open_no_position');
    const html = render(envWith({ snapshot: s, offsetMs: 0 }), <MarketCard surface="panel" />);
    for (const text of ['Will RedFox win the first Minecraft duel against BlueJay?', 'RedFox', 'BlueJay', 'Total pool', '$40.00', 'Closes in', 'simulated bot stakes', 'Canned fixture'])
      expect(html).toContain(text);
    expect(html).toContain('value="5"'); // Default stake 500 from snapshot.limits.
    expect(html).toContain('Pick a side');
  });

  it('labels the empty/one-sided void risk and the stale source pause', () => {
    expect(render(envWith({ snapshot: snap('open_empty_pool') }), <MarketCard surface="panel" />)).toContain('voided and every stake is refunded');
    expect(render(envWith({ snapshot: snap('open_source_stale') }), <MarketCard surface="panel" />)).toContain('Betting paused: stream source not live');
  });
});

describe('panel chrome', () => {
  it('always shows the MOCK badge and the three independent mode labels; no card or phone fields', () => {
    const html = render(envWith({ snapshot: snap('open_no_position'), adapterMode: 'MOCK', hasFixtures: true }), (
      <Panel host={document.createElement('div')} placement="chat" notice={null} retryAttach={() => undefined} />
    ));
    expect(html).toContain('MOCK');
    expect(html).toMatch(/Media: <b>TEST FIXTURE/);
    expect(html).toMatch(/Model: <b>FIXTURE/);
    expect(html).toMatch(/Funds: <b>MOCK/);
    expect(html).toContain('Fixture ▾');
    expect(html).toContain('role="separator"');
    expect(html).not.toMatch(/card number|cvc|cvv|phone/i);
  });

  it('the top-up dialog is MOCK-labelled, uses limits presets, and says "FaZe Up!"', () => {
    const html = render(
      envWith({ snapshot: snap('open_low_balance'), topUp: { ...initialPanelState().topUp, open: true, reason: 'insufficient', neededMinor: 200 } }),
      <Panel host={document.createElement('div')} placement="chat" notice={null} retryAttach={() => undefined} />,
    );
    expect(html).toContain('FaZe Up!');
    expect(html).toContain('MOCK · no payment');
    for (const preset of ['$5', '$10', '$50', 'Custom']) expect(html).toContain(preset);
    expect(html).toContain('may close before you are back');
    expect(html).not.toMatch(/card number|cvc|cvv|expiry/i);
  });

  it('clamps the resize split so chat keeps a minimum height', () => {
    expect(clampPanelHeight(5000, 600)).toBe(600 - CHAT_MIN_PX);
    expect(clampPanelHeight(10, 600)).toBe(PANEL_MIN_PX);
    expect(clampPanelHeight(300, 600)).toBe(300);
  });
});

describe('D31: live builds look like a product (no MOCK/DEMO badges or mode chips)', () => {
  const live = (name: string): StreamSnapshot => ({ ...snap(name), modes: { ai_mode: 'OFF', payment_mode: 'UNAVAILABLE', media_source_kind: null } });
  const panel = (state: Partial<PanelState>) =>
    render(envWith(state, 'live'), <Panel host={document.createElement('div')} placement="chat" notice={null} retryAttach={() => undefined} />);

  it('panel header and body carry no badge, chips, fixture menu or fixture-origin label', () => {
    const html = panel({ snapshot: live('open_no_position'), adapterMode: 'LIVE', hasFixtures: false });
    expect(html).not.toMatch(/MOCK|DEMO|TEST MONEY|ft-modes|Fixture ▾|Canned fixture|Operator fixture|LIVE API/);
    expect(html).toContain('Fa<b>Ze</b>Time');
    expect(html).toContain('Will RedFox win the first Minecraft duel against BlueJay?');
  });

  it('the over-video pill has no badge', () => {
    const host = document.createElement('div');
    document.createElement('div').appendChild(host);
    const html = render(envWith({ snapshot: live('open_no_position') }, 'live'), <Overlay host={host} />);
    expect(html).not.toMatch(/MOCK|DEMO/);
    expect(html).toContain('ft-pill-brand');
  });

  it('exactly one unobtrusive test-credits note in the Wallet tab and the top-up dialog', () => {
    const wallet = render(envWith({ snapshot: live('open_no_position') }, 'live'), <WalletTab />);
    expect(wallet.match(/Balances are test credits\./g)).toHaveLength(1);
    expect(wallet).not.toMatch(/MOCK|DEMO|phase 6/);
    expect(wallet).toContain("Top-ups aren&#x27;t available yet");
    const dialog = render(
      envWith({ snapshot: live('open_low_balance'), topUp: { ...initialPanelState().topUp, open: true, reason: 'insufficient', neededMinor: 200 } }, 'live'),
      <TopUpDialog />,
    );
    expect(dialog.match(/Balances are test credits\./g)).toHaveLength(1);
    expect(dialog).not.toMatch(/MOCK|DEMO|FaZe Up!/); // Nothing chargeable is offered while top-ups are unavailable.
  });

  it('AI-origin markets read as "AI suggested", never as fixtures', () => {
    const html = render(envWith({ snapshot: live('open_source_stale') }, 'live'), <MarketCard surface="panel" />);
    expect(html).toContain('AI suggested');
    expect(html).not.toMatch(/fixture/i);
  });

  it('mock builds keep their dev labels', () => {
    const html = render(envWith({ snapshot: snap('open_no_position'), adapterMode: 'MOCK', hasFixtures: true }), (
      <Panel host={document.createElement('div')} placement="chat" notice={null} retryAttach={() => undefined} />
    ));
    expect(html).toContain('MOCK');
    expect(html).toContain('ft-modes');
  });
});

describe('P6-E live Stripe test top-ups (D31 wording, no card fields)', () => {
  const stripe = (name: string): StreamSnapshot => ({ ...snap(name), modes: { ai_mode: 'OFF', payment_mode: 'STRIPE_TEST', media_source_kind: null } });
  const tracking = (over: Record<string, unknown> = {}) =>
    ({
      payment_mode: 'STRIPE_TEST',
      topup_id: `top_${'a'.repeat(32)}`,
      operation_id: '00000000-0000-4000-8000-000000000020',
      amount_minor: 1000,
      status: 'PENDING',
      checkout_opened: true,
      checkout_blocked: false,
      previous_run: false,
      watching: true,
      updated_at_ms: Date.now(),
      ...over,
    }) as PanelState['pendingTopUp'];
  const dialogState = (over: Partial<PanelState> = {}): Partial<PanelState> => ({
    snapshot: stripe('open_low_balance'),
    topUp: { ...initialPanelState().topUp, open: true, reason: 'insufficient', neededMinor: 200 },
    ...over,
  });

  it('the Wallet tab offers "Add funds" with exactly one test-credits note', () => {
    const html = render(envWith({ snapshot: stripe('open_no_position') }, 'live'), <WalletTab />);
    expect(html).toMatch(/<button type="button" class="ft-primary">Add funds<\/button>/);
    expect(html.match(/Balances are test credits\./g)).toHaveLength(1);
    expect(html).not.toMatch(/MOCK|DEMO|aren&#x27;t available/);
  });

  it('the dialog keeps "FaZe Up!", the presets and one note, with no card fields and no mock wording', () => {
    const html = render(envWith(dialogState(), 'live'), <TopUpDialog />);
    expect(html).toContain('FaZe Up!');
    for (const preset of ['$5', '$10', '$50', 'Custom']) expect(html).toContain(preset);
    expect(html.match(/Balances are test credits\./g)).toHaveLength(1);
    expect(html).toContain('may close before you are back');
    expect(html).toContain('Card details are entered only there');
    expect(html).not.toMatch(/<input[^>]*(card|cvc|cvv|expiry|exp-date|cc-)/i);
    expect(html).not.toMatch(/MOCK|DEMO|no payment/);
  });

  it('pending: waits for Stripe and offers to reopen checkout; the button says it is not credited yet', () => {
    const html = render(envWith(dialogState({ pendingTopUp: tracking() }), 'live'), <TopUpDialog />);
    expect(html).toContain('Finish paying $10.00 in the Stripe tab. Credits appear here once Stripe confirms.');
    expect(html).toContain('Open checkout');
    expect(html).not.toContain('Test credits added');
  });

  it('credited: "Test credits added: $X" and a reminder that the bet was not placed', () => {
    const html = render(envWith(dialogState({ pendingTopUp: tracking({ status: 'CREDITED', watching: false }) }), 'live'), <TopUpDialog />);
    expect(html).toContain('Test credits added: $10.00');
    expect(html).toContain('Your bet was not placed. Check the market and confirm it again.');
    expect(html).toContain('>Done<');
  });

  it('failed, expired and archived-run results read honestly', () => {
    const one = (over: Record<string, unknown>) =>
      render(envWith({ snapshot: stripe('open_no_position'), pendingTopUp: tracking(over) }, 'live'), (
        <Panel host={document.createElement('div')} placement="chat" notice={null} retryAttach={() => undefined} />
      ));
    expect(one({ status: 'FAILED', watching: false })).toContain('payment didn&#x27;t go through. No credits were added.');
    expect(one({ status: 'EXPIRED', watching: false })).toContain('checkout expired. No credits were added.');
    expect(one({ status: 'CREDITED', watching: false, previous_run: true })).toContain('Test credits added: $10.00, credited to the previous demo run.');
  });

  it('pending notice has a hide (×) that only hides it; a finished result shows again', () => {
    const panel = (over: Record<string, unknown>, hidden: boolean) =>
      render(envWith({ snapshot: stripe('open_no_position'), pendingTopUp: tracking(over), hiddenTopUpFor: hidden ? (tracking(over) as { topup_id: string }).topup_id : null }, 'live'), (
        <Panel host={document.createElement('div')} placement="chat" notice={null} retryAttach={() => undefined} />
      ));
    const shown = panel({}, false);
    expect(shown).toContain('Finish paying $10.00 in the Stripe tab.');
    expect(shown).toContain('aria-label="Hide this top-up notice"');
    expect(panel({}, true)).not.toContain('Finish paying');
    const done = panel({ status: 'CREDITED', watching: false }, true);
    expect(done).toContain('Test credits added: $10.00');
    expect(done).not.toContain('Hide this top-up notice');
  });

  it('the available balance is marked as money (green)', () => {
    const html = render(envWith({ snapshot: stripe('open_no_position') }, 'live'), <WalletTab />);
    expect(html).toMatch(/<span>Available<\/span><b class="ft-money">\$/);
  });

  it('the market card shows "Add funds" (not demo wording) and a fresh estimate', () => {
    const html = render(envWith({ snapshot: stripe('open_no_position') }, 'live'), <MarketCard surface="panel" />);
    expect(html).toContain('Add funds');
    expect(html).not.toContain('Add demo funds');
  });
});

describe('profile card (owner request 2026-11-15)', () => {
  it('builds initials from the display name', async () => {
    const { initialsFor } = await import('../src/ui/Panel');
    expect(initialsFor('Faze Gavin')).toBe('FG');
    expect(initialsFor('gavin')).toBe('GA');
    expect(initialsFor('faze_neville')).toBe('FN');
    expect(initialsFor('')).toBe('?');
    expect(initialsFor(null)).toBe('?');
  });

  const stripe = (name: string): StreamSnapshot => ({ ...snap(name), modes: { ai_mode: 'OFF', payment_mode: 'STRIPE_TEST', media_source_kind: null } });
  const liveStatus = (enrolled: boolean) => ({
    mode: 'LIVE' as const, link: 'WS' as never, enrolled, reenroll: false, displayName: enrolled ? 'Faze Gavin' : null,
    role: enrolled ? 'VIEWER' : null, apiBase: 'http://fazetime:8000', channel: 'fazegavin1234', message: null,
  });

  it('not verified: tag, the "verify before betting" note, a Verify button, and Add funds disabled', async () => {
    const { ProfileCard, VERIFY_NOTE } = await import('../src/ui/Panel');
    const html = render(envWith({ backend: liveStatus(false), snapshot: stripe('open_no_position') }, 'live'), <ProfileCard onClose={() => undefined} />);
    expect(html).toMatch(/data-testid="profile-verified">Not verified</);
    expect(html).toContain(VERIFY_NOTE.replace(/'/g, '&#x27;'));
    expect(html).toMatch(/<button type="button" class="ft-primary">Verify<\/button>/);
    expect(html).toMatch(/<button type="button" class="ft-primary ft-profile-add" disabled="">Add funds<\/button>/);
    expect(html).not.toMatch(/password/i);
  });

  it('verified: tag with a check, green available balance, and an enabled Add funds; no Verify button', async () => {
    const { ProfileCard } = await import('../src/ui/Panel');
    const html = render(envWith({ backend: liveStatus(true), snapshot: stripe('open_no_position') }, 'live'), <ProfileCard onClose={() => undefined} />);
    expect(html).toMatch(/data-testid="profile-verified"><svg[^]*<\/svg>Verified</);
    expect(html).toMatch(/class="ft-money ft-profile-balance" data-testid="profile-available">\$/);
    expect(html).toMatch(/<button type="button" class="ft-primary ft-profile-add">Add funds<\/button>/);
    expect(html).not.toContain('>Verify<');
    expect(html).toContain('FG');
  });

  it('Add funds goes to the Wallet tab when the panel provides it', async () => {
    const { ProfileCard } = await import('../src/ui/Panel');
    const html = render(envWith({ backend: liveStatus(true), snapshot: stripe('open_no_position') }, 'live'), (
      <ProfileCard onClose={() => undefined} onAddFunds={() => undefined} top={48} />
    ));
    expect(html).toContain('style="top:48px;max-height:calc(100% - 60px)"');
  });

  it('the panel header has a profile (person) button', () => {
    const html = render(envWith({}, 'live'), <Panel host={document.createElement('div')} placement="chat" notice={null} retryAttach={() => undefined} />);
    expect(html).toContain('aria-label="Your FaZeTime profile"');
  });
});

describe('CALM / ENRAGE theme (owner request 2026-11-15)', () => {
  it('the panel defaults to CALM (FaZe) and carries the switch', () => {
    const html = render(envWith({}, 'live'), <Panel host={document.createElement('div')} placement="chat" notice={null} retryAttach={() => undefined} />);
    expect(html).toContain('data-theme="faze"');
    expect(html).toMatch(/role="radiogroup" aria-label="Theme" data-value="calm"/);
    expect(html).toMatch(/aria-checked="true" class="ft-theme-opt"[^>]*>F</);
    expect(html).toContain('<span class="omega">Θ</span>');
    expect(html).not.toContain('ft-sky');
  });

  it('maps the stored choice to the odyssey attribute', async () => {
    const { themeAttr } = await import('../src/ui/theme');
    expect(themeAttr('enrage')).toBe('odyssey');
    expect(themeAttr('calm')).toBe('faze');
    expect(themeAttr(null)).toBe('faze');
  });
});

describe('Redeem journey map (owner request 2026-11-15)', () => {
  const items = [
    { item_id: 'c', title: 'Hoodie', description: 'x', price_minor: 2500 },
    { item_id: 'a', title: 'Sticker', description: 'x', price_minor: 500 },
    { item_id: 'b', title: 'Emote', description: 'x', price_minor: 1000 },
  ];
  it('orders stops cheapest first and locks what the balance cannot reach, with the amount still needed', async () => {
    const { redeemMap } = await import('../src/ui/Panel');
    const stops = redeemMap(items, 1200, false);
    expect(stops.map((s) => s.item.item_id)).toEqual(['a', 'b', 'c']);
    expect(stops.map((s) => s.locked)).toEqual([false, false, true]);
    expect(stops[2]!.needMinor).toBe(1300);
  });
  it('locks every stop while rewards are unavailable, and while the balance is unknown', async () => {
    const { redeemMap } = await import('../src/ui/Panel');
    expect(redeemMap(items, 99_999, true).every((s) => s.locked && s.needMinor === 0)).toBe(true);
    expect(redeemMap(items, null, false).every((s) => s.locked)).toBe(true);
  });
});

describe('Redeem voyage ship (owner request 2026-11-15)', () => {
  const items = [
    { item_id: 'a', title: 'A', description: 'x', price_minor: 500 },
    { item_id: 'b', title: 'B', description: 'x', price_minor: 1000 },
    { item_id: 'c', title: 'C', description: 'x', price_minor: 2500 },
  ];
  it('sails on the leg into the first locked stop, as far as the balance reaches', async () => {
    const { redeemMap, shipPosition } = await import('../src/ui/Panel');
    const at = (bal: number | null, unavailable = false) => shipPosition(redeemMap(items, bal, unavailable), bal, unavailable);
    expect(at(2000)).toEqual({ leg: 2, t: (2000 - 1000) / 1500 });
    expect(at(200)).toEqual({ leg: 0, t: 0.4 });
    expect(at(5000)).toEqual({ leg: 2, t: 0.92 }); // all reached: docked at the last stop
    expect(at(2000, true)).toEqual({ leg: 0, t: 0.12 }); // rewards unavailable: just leaving port
    expect(shipPosition([], 100, false)).toBeNull();
  });
});
