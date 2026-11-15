import type { ReactElement } from 'react';
import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { bannerFor, LOSS_BANNER_TEXT, type StreamSnapshot } from '@fazetime/contracts';
import { loadSnapshotFixture, SNAPSHOT_FIXTURE_NAMES, type SnapshotFixtureName } from '../src/mock/fixtures';
import { bannerCopy, MarketCard } from '../src/ui/MarketCard';
import { Panel, clampPanelHeight, CHAT_MIN_PX, PANEL_MIN_PX } from '../src/ui/Panel';
import { EnvContext, type UiEnv } from '../src/ui/hooks';
import { initialPanelState, PanelController, type PanelState } from '../src/state/controller';

function envWith(state: Partial<PanelState>): UiEnv {
  const controller = new PanelController({} as never, { get: async () => null, set: async () => undefined, remove: async () => undefined });
  (controller as unknown as { state: PanelState }).state = { ...initialPanelState(), ...state };
  return {
    controller,
    kv: { get: async () => null, set: async () => undefined, remove: async () => undefined },
    watch: () => () => undefined,
    channel: 'somechannel',
    doc: document,
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
