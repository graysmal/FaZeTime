// CONTRACTS §9.20 item 2 on the console demo view: "AI is watching for the result…" once an AI market is LOCKED
// or EVALUATING and its expected_result_at_utc has passed by the server clock, with no result yet.
import { afterEach, describe, expect, it } from 'vitest';
import { OperatorClient } from '../src/api/client';
import type { OperatorMarket } from '../src/api/types';
import { DemoView } from '../src/demo/DemoView';
import { isResultPending } from '../src/demo/state';
import { MKT, NOW, TOKEN, envelope, healthBody, json, mount, operatorMarket, scriptedFetch, waitFor, type Mounted } from './helpers';

const T0 = Date.parse(NOW);
const iso = (offsetMs: number) => new Date(T0 + offsetMs).toISOString();
const AI = { ai_mode: 'APPROVAL', effective_ai_mode: 'APPROVAL', allow_automatic: false, pending_candidates: 0, pending_resolutions: 0 };

const aiLocked = (over: Record<string, unknown> = {}) =>
  operatorMarket({ origin: 'AI_APPROVED', state: 'LOCKED', locked_at_utc: iso(-30_000), ...over }) as unknown as OperatorMarket;

let mounted: Mounted | null = null;
afterEach(() => {
  mounted?.unmount();
  mounted = null;
});

describe('isResultPending (§9.20 item 2)', () => {
  it('only LOCKED / EVALUATING AI markets, only after the expected time, only without a result', () => {
    const past = iso(-5_000);
    const future = iso(60_000);
    expect(isResultPending(aiLocked({ expected_result_at_utc: past }), T0)).toBe(true);
    expect(isResultPending(aiLocked({ state: 'EVALUATING', expected_result_at_utc: past }), T0)).toBe(true);
    expect(isResultPending(aiLocked({ origin: 'AI_AUTOMATIC', expected_result_at_utc: past }), T0)).toBe(true);
    // Before the time: unchanged; once the server clock passes it: pending.
    expect(isResultPending(aiLocked({ expected_result_at_utc: future }), T0)).toBe(false);
    expect(isResultPending(aiLocked({ expected_result_at_utc: future }), T0 + 61_000)).toBe(true);
    for (const state of ['OPEN', 'SETTLED', 'VOID', 'DRAFT']) {
      expect(isResultPending(aiLocked({ state, expected_result_at_utc: past }), T0)).toBe(false);
    }
    expect(isResultPending(aiLocked({ expected_result_at_utc: null }), T0)).toBe(false);
    expect(isResultPending(aiLocked(), T0)).toBe(false); // absent: an older server
    expect(isResultPending(aiLocked({ expected_result_at_utc: 'soon' }), T0)).toBe(false);
    expect(isResultPending(aiLocked({ expected_result_at_utc: past }), null)).toBe(false); // no server clock yet
    // "AI is watching" is only claimed for AI markets (the contract sends null for fixtures anyway).
    expect(isResultPending(aiLocked({ origin: 'OPERATOR_FIXTURE', expected_result_at_utc: past }), T0)).toBe(false);
    expect(isResultPending(aiLocked({ winning_side: 'YES', expected_result_at_utc: past }), T0)).toBe(false);
  });
});

/** Health carries one market; the server clock is NOW, so serverNow ≈ NOW. */
function demoApi(market: unknown) {
  const f = scriptedFetch((call) => {
    if (call.url === '/v1/operator/health') return json(200, healthBody({ ai: AI, server_time_utc: NOW, markets: [market] }));
    if (call.url.startsWith('/v1/operator/candidates')) return json(200, { schema_version: 1, server_time_utc: NOW, candidates: [] });
    if (call.url.startsWith('/v1/operator/resolutions')) {
      return json(200, { schema_version: 1, server_time_utc: NOW, market_id: MKT, resolutions: [] });
    }
    return json(404, envelope('NOT_FOUND'));
  });
  return new OperatorClient({ getToken: () => TOKEN, fetchImpl: f.fetchImpl });
}

const card = (c: HTMLElement) => c.querySelector('[data-testid="demo-card"]') as HTMLElement | null;

describe('DemoView: result pending (§9.20 item 2)', () => {
  it('past the expected result time, a LOCKED AI market says "AI is watching for the result…" with decorative dots', async () => {
    mounted = await mount(<DemoView client={demoApi(aiLocked({ expected_result_at_utc: iso(-5_000) }))} />);
    const c = mounted.container;
    await waitFor(() => c.querySelector('[data-testid="demo-watching"]'));
    expect(card(c)!.dataset.state).toBe('closed');
    expect(c.querySelector('[data-testid="demo-watching"]')!.textContent).toBe('AI is watching for the result…');
    expect(c.querySelector('.watch-dots')!.getAttribute('aria-hidden')).toBe('true');
    expect(c.querySelectorAll('.watch-dots > span')).toHaveLength(3);
    expect(c.textContent).not.toContain('Betting closed. Waiting for the result.');
    expect(c.textContent).toContain('Gavin $5.00 · Neville $7.00 · 2 bets'); // the pool line stays
  });

  it('EVALUATING past the expected time shows it too', async () => {
    mounted = await mount(<DemoView client={demoApi(aiLocked({ state: 'EVALUATING', expected_result_at_utc: iso(-1_000) }))} />);
    const c = mounted.container;
    await waitFor(() => c.querySelector('[data-testid="demo-watching"]'));
    expect(c.querySelector('[data-testid="demo-watching"]')!.textContent).toBe('AI is watching for the result…');
  });

  it('before the time, or with a null or absent expected time, the closed card stays as it was', async () => {
    for (const eta of [iso(60_000), null, undefined]) {
      const m = aiLocked(eta === undefined ? {} : { expected_result_at_utc: eta });
      mounted = await mount(<DemoView client={demoApi(m)} />);
      const c = mounted.container;
      await waitFor(() => card(c)?.dataset.state === 'closed');
      expect(c.textContent).toContain('Betting closed. Waiting for the result.');
      expect(c.querySelector('[data-testid="demo-watching"]')).toBeNull();
      expect(c.querySelector('.watch-dots')).toBeNull();
      mounted.unmount();
      mounted = null;
    }
  });

  it('an OPEN market keeps its countdown even if the expected time has passed', async () => {
    mounted = await mount(<DemoView client={demoApi(aiLocked({ state: 'OPEN', expected_result_at_utc: iso(-5_000) }))} />);
    const c = mounted.container;
    await waitFor(() => card(c)?.dataset.state === 'open');
    expect(c.querySelector('[data-testid="demo-countdown"]')).not.toBeNull();
    expect(c.textContent).not.toContain('AI is watching for the result');
  });
});
