// CONTRACTS 9.20 item 2 in the viewer MarketCard: "AI is watching for the result…" once an AI market is LOCKED or
// EVALUATING and expected_result_at_utc has passed by the server-time estimate (local clock + offset), no result yet.
import type { ReactElement } from 'react';
import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import type { StreamSnapshot } from '@fazetime/contracts';
import { loadSnapshotFixture } from '../src/mock/fixtures';
import { awaitsExpectedResult, expectedResultAtMs, resultPending, type EtaMarket } from '../src/lib/time';
import { MarketCard } from '../src/ui/MarketCard';
import { EnvContext, type UiEnv } from '../src/ui/hooks';
import { initialPanelState, PanelController, type PanelState } from '../src/state/controller';

const WATCHING = 'AI is watching for the result…';

function envWith(state: Partial<PanelState>, mode: 'mock' | 'live' = 'live'): UiEnv {
  const controller = new PanelController({} as never, { get: async () => null, set: async () => undefined, remove: async () => undefined });
  (controller as unknown as { state: PanelState }).state = { ...initialPanelState(), ...state };
  return {
    controller,
    kv: { get: async () => null, set: async () => undefined, remove: async () => undefined },
    watch: () => () => undefined,
    channel: 'fazegavin1234',
    doc: document,
    mode,
    requestPanelOpen: () => undefined,
    onPanelOpenRequest: () => () => undefined,
  };
}

const render = (env: UiEnv, node: ReactElement) => renderToStaticMarkup(<EnvContext.Provider value={env}>{node}</EnvContext.Provider>);

/** A fixture market (shifted to now) turned into an AI market with the given overrides. */
function aiSnap(name: 'locked' | 'evaluating' | 'open_no_position', over: Record<string, unknown>): StreamSnapshot {
  const s = loadSnapshotFixture(name, Date.now());
  return { ...s, market: { ...s.market!, origin: 'AI_APPROVED', ...over } as StreamSnapshot['market'] };
}

const at = (offsetMs: number) => new Date(Date.now() + offsetMs).toISOString();
const card = (s: StreamSnapshot, offsetMs = 0, mode: 'mock' | 'live' = 'live', surface: 'panel' | 'overlay' = 'panel') =>
  render(envWith({ snapshot: s, offsetMs }, mode), <MarketCard surface={surface} />);

describe('MarketCard: result pending (CONTRACTS 9.20 item 2)', () => {
  it('LOCKED past the expected result time: the waiting hint becomes "AI is watching for the result…" with dots', () => {
    const html = card(aiSnap('locked', { expected_result_at_utc: at(-5_000) }));
    expect(html).toContain(WATCHING);
    expect(html).toMatch(/<p class="ft-hint ft-hint--watching" role="status"><span class="ft-watch" aria-hidden="true"><span><\/span><span><\/span><span><\/span><\/span>/);
    expect(html).not.toContain('Betting closed. Waiting for the result.');
    expect(html.match(/class="ft-hint/g)).toHaveLength(1); // the same one line: no extra overlay space
  });

  it('EVALUATING past the time: same signal, keeping the refund-not-guess note on that line', () => {
    const html = card(aiSnap('evaluating', { expected_result_at_utc: at(-1_000) }));
    expect(html).toContain(`${WATCHING} Unclear results are refunded, never guessed.`);
    expect(html).not.toContain('Determining the outcome from the stream.');
  });

  it('before the expected time, the existing locked / evaluating hints stay as they are', () => {
    const locked = card(aiSnap('locked', { expected_result_at_utc: at(60_000) }));
    expect(locked).toContain('Betting closed. Waiting for the result.');
    expect(locked).not.toContain(WATCHING);
    const evaluating = card(aiSnap('evaluating', { expected_result_at_utc: at(60_000) }));
    expect(evaluating).toContain('Determining the outcome from the stream. Unclear results are refunded, never guessed.');
    expect(evaluating).not.toContain(WATCHING);
  });

  it('uses the server-time offset, not the raw local clock', () => {
    // Local clock says 60 s to go, but the server is 2 minutes ahead: the time has passed.
    expect(card(aiSnap('locked', { expected_result_at_utc: at(60_000) }), 120_000)).toContain(WATCHING);
    // Local clock says 5 s ago, but the server is 1 minute behind: not yet.
    expect(card(aiSnap('locked', { expected_result_at_utc: at(-5_000) }), -60_000)).not.toContain(WATCHING);
  });

  it('a null, absent or unreadable expected time changes nothing', () => {
    for (const over of [{ expected_result_at_utc: null }, {}, { expected_result_at_utc: 'later' }, { expected_result_at_utc: 42 }]) {
      const html = card(aiSnap('locked', over));
      expect(html).toContain('Betting closed. Waiting for the result.');
      expect(html).not.toContain(WATCHING);
      expect(html).not.toContain('ft-watch');
    }
  });

  it('an OPEN market keeps its countdown; a fixture market never claims the AI is watching', () => {
    const open = card(aiSnap('open_no_position', { expected_result_at_utc: at(-5_000) }));
    expect(open).toContain('Closes in');
    expect(open).not.toContain(WATCHING);
    expect(card(aiSnap('locked', { origin: 'CANNED_FIXTURE', expected_result_at_utc: at(-5_000) }))).not.toContain(WATCHING);
  });

  it('also in the over-video dropdown card, and live builds add no MOCK / DEMO wording (D31)', () => {
    const html = card(aiSnap('locked', { expected_result_at_utc: at(-5_000) }), 0, 'live', 'overlay');
    expect(html).toContain(WATCHING);
    const line = /<p class="ft-hint ft-hint--watching"[^>]*>.*?<\/p>/.exec(html)![0];
    expect(line).not.toMatch(/mock|demo|fixture/i);
  });
});

describe('resultPending / awaitsExpectedResult (pure)', () => {
  const m = (over: Partial<EtaMarket>): EtaMarket => ({ state: 'LOCKED', origin: 'AI_AUTOMATIC', winning_side: null, void_reason: null, ...over });
  const T = Date.parse('2026-11-15T04:00:00.000Z');
  it('compares local time plus offset with the expected time, only for LOCKED / EVALUATING AI markets with no result', () => {
    const eta = '2026-11-15T04:00:10.000Z';
    expect(expectedResultAtMs(m({ expected_result_at_utc: eta }))).toBe(T + 10_000);
    expect(resultPending(m({ expected_result_at_utc: eta }), T + 9_999, 0)).toBe(false);
    expect(resultPending(m({ expected_result_at_utc: eta }), T + 10_000, 0)).toBe(true);
    expect(resultPending(m({ expected_result_at_utc: eta }), T, 10_000)).toBe(true);
    expect(resultPending(m({ state: 'EVALUATING', expected_result_at_utc: eta }), T + 20_000, 0)).toBe(true);
    for (const state of ['OPEN', 'SETTLED', 'VOID']) expect(resultPending(m({ state, expected_result_at_utc: eta }), T + 20_000, 0)).toBe(false);
    expect(resultPending(m({ void_reason: 'UNRESOLVABLE', expected_result_at_utc: eta }), T + 20_000, 0)).toBe(false);
    expect(resultPending(null, T, 0)).toBe(false);
    // The card's clock ticks only while such a market waits (or while OPEN).
    expect(awaitsExpectedResult(m({ expected_result_at_utc: eta }))).toBe(true);
    expect(awaitsExpectedResult(m({ expected_result_at_utc: null }))).toBe(false);
    expect(awaitsExpectedResult(m({ state: 'SETTLED', expected_result_at_utc: eta }))).toBe(false);
  });
});
