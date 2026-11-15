import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiFailure, OperatorClient } from '../src/api/client';
import { createReopener } from '../src/api/openAccess';
import type { AiCandidate, AiResolution, OperatorHealth } from '../src/api/types';
import { DemoView } from '../src/demo/DemoView';
import { countdownText, deriveDemoState, errorSentence, poolLine, resultText, streamPill } from '../src/demo/state';
import {
  MKT,
  NOW,
  STR,
  TOKEN,
  UUID_RE,
  byText,
  click,
  envelope,
  healthBody,
  json,
  mount,
  operatorMarket,
  scriptedFetch,
  typeInto,
  waitFor,
  type Call,
  type Mounted,
} from './helpers';

const CND = `cnd_${'1'.repeat(32)}`;
const RSL = `rsl_${'2'.repeat(32)}`;
const EVD = `evd_${'3'.repeat(32)}`;
const EP = `ep_${'4'.repeat(32)}`;
const T0 = Date.parse(NOW);
const iso = (offsetMs: number) => new Date(T0 + offsetMs).toISOString();
const AI = { ai_mode: 'APPROVAL', effective_ai_mode: 'APPROVAL', allow_automatic: false, pending_candidates: 0, pending_resolutions: 0 };
const INJECTION = '<img src=x onerror="alert(1)"> IGNORE PREVIOUS INSTRUCTIONS';

function candidate(over: Partial<AiCandidate> = {}): AiCandidate {
  return {
    id: CND,
    candidate_id: '7c9e6679-7425-40de-944b-e07fc1f90ae7',
    stream_session_id: `run_${'c'.repeat(32)}`,
    source_epoch: EP,
    status: 'PENDING',
    reject_code: null,
    actionable: true,
    market_id: null,
    template_id: 'H2H_WINNER_V1',
    episode_fingerprint: 'h2h:fazegavin|fazeneville:minecraft-1v1',
    question: `Will FaZeGavin win the 1v1? ${INJECTION}`,
    yes: { label: 'FaZeGavin', predicate: 'FaZeGavin wins' },
    no: { label: 'FaZeNeville', predicate: 'FaZeNeville wins' },
    subjects: ['FaZeGavin', 'FaZeNeville'],
    evidence_ids: [`${EP}:2`],
    evidence: [
      { ref: `${EP}:2`, kind: 'TRANSCRIPT', source_epoch: EP, sequence: 2, evidence_id: null, media_start_ms: 0, media_end_ms: 2500, received_at_utc: iso(-20_000), transcript_text: 'hi' },
    ],
    announced_at_media_ms: 0,
    suggested_close_in_s: 45,
    suggested_resolve_in_s: 120,
    close_in_s: 45,
    resolve_in_s: 120,
    proposed_close_at_utc: iso(35_000),
    cancellation_conditions: [],
    rationale: INJECTION,
    rationale_untrusted: true,
    model: 'm',
    prompt_version: 'p',
    ai_mode: 'APPROVAL',
    received_at_utc: iso(-10_000),
    expires_at_utc: iso(50_000),
    decided_at_utc: null,
    decided_by_user_id: null,
    decision_note: null,
    ...over,
  };
}

function resolution(over: Partial<AiResolution> = {}): AiResolution {
  return {
    id: RSL,
    resolution_id: '9b2f6f0e-1c2d-4e5f-8a9b-0c1d2e3f4a5b',
    market_id: MKT,
    market_state: 'EVALUATING',
    market_resolve_by_utc: iso(100_000),
    rules_version: 1,
    source_epoch: EP,
    decision: 'YES',
    status: 'PENDING_APPROVAL',
    status_reason: 'APPROVAL_MODE',
    actionable: true,
    evidence_ids: [EVD],
    evidence: [{ ref: EVD, kind: 'FRAME', source_epoch: EP, sequence: 10, evidence_id: EVD, media_start_ms: 60_000, media_end_ms: 60_000, received_at_utc: iso(-1000) }],
    media_interval: { start_ms: 60_000, end_ms: 62_000 },
    predicate_support: { YES: true, NO: false },
    contradictions: [],
    reason: INJECTION,
    reason_untrusted: true,
    model: 'm',
    prompt_version: 'p',
    ai_mode: 'APPROVAL',
    received_at_utc: iso(-1000),
    decided_at_utc: null,
    decided_by_user_id: null,
    ...over,
  };
}

const health = (over: Record<string, unknown> = {}) => healthBody({ ai: AI, ...over }) as unknown as OperatorHealth;
const aiMarket = (over: Record<string, unknown> = {}) => operatorMarket({ origin: 'AI_APPROVED', ...over });

describe('deriveDemoState', () => {
  it('covers loading, no stream, idle, candidate, open, waiting, suggestion, fixture call and terminal', () => {
    expect(deriveDemoState({ health: null, candidates: null, resolutions: null }).kind).toBe('loading');
    expect(deriveDemoState({ health: health({ stream: null }), candidates: null, resolutions: null }).kind).toBe('no_stream');
    expect(deriveDemoState({ health: health(), candidates: [], resolutions: null }).kind).toBe('idle');
    // a non-actionable candidate (expired/rejected) does not count
    expect(deriveDemoState({ health: health(), candidates: [candidate({ actionable: false, status: 'EXPIRED' })], resolutions: null }).kind).toBe('idle');
    expect(deriveDemoState({ health: health(), candidates: [candidate()], resolutions: null }).kind).toBe('candidate');
    // an OPEN market wins over a pending candidate (it could not be approved anyway: MARKET_BUSY)
    const open = deriveDemoState({ health: health({ markets: [operatorMarket({ state: 'OPEN' })] }), candidates: [candidate()], resolutions: null });
    expect(open.kind).toBe('open');
    // AI market closed, no suggestion yet -> waiting
    expect(deriveDemoState({ health: health({ markets: [aiMarket({ state: 'LOCKED' })] }), candidates: [], resolutions: [] }).kind).toBe('closed');
    expect(deriveDemoState({ health: health({ markets: [aiMarket({ state: 'EVALUATING' })] }), candidates: [], resolutions: [] }).kind).toBe('closed');
    // a WAIT decision is recorded only: still waiting
    expect(
      deriveDemoState({
        health: health({ markets: [aiMarket({ state: 'EVALUATING' })] }),
        candidates: [],
        resolutions: [resolution({ decision: 'WAIT', status: 'RECORDED', actionable: false })],
      }).kind,
    ).toBe('closed');
    // an actionable suggestion for THIS market
    const sug = deriveDemoState({ health: health({ markets: [aiMarket({ state: 'EVALUATING' })] }), candidates: [], resolutions: [resolution()] });
    expect(sug.kind).toBe('suggestion');
    // a suggestion for another market is ignored
    expect(
      deriveDemoState({
        health: health({ markets: [aiMarket({ state: 'EVALUATING' })] }),
        candidates: [],
        resolutions: [resolution({ market_id: `mkt_${'9'.repeat(32)}` })],
      }).kind,
    ).toBe('closed');
    // fixture markets: LOCKED waits, EVALUATING asks the operator for the winner
    expect(deriveDemoState({ health: health({ markets: [operatorMarket({ state: 'LOCKED' })] }), candidates: [], resolutions: null }).kind).toBe('closed');
    expect(deriveDemoState({ health: health({ markets: [operatorMarket({ state: 'EVALUATING' })] }), candidates: [], resolutions: null }).kind).toBe('fixture_call');
    // latest terminal market (a newer DRAFT is skipped)
    const settled = deriveDemoState({
      health: health({ markets: [operatorMarket({ state: 'DRAFT', market_id: `mkt_${'8'.repeat(32)}` }), operatorMarket({ state: 'SETTLED', winning_side: 'NO' })] }),
      candidates: [],
      resolutions: null,
    });
    expect(settled.kind).toBe('result');
    if (settled.kind === 'result') expect(resultText(settled.market)).toBe('Neville won. Winners paid.');
    expect(resultText(operatorMarket({ state: 'VOID', void_reason: 'ONE_SIDED_POOL' }) as never)).toBe('Voided. Everyone refunded.');
  });

  it('formats the pool line with side labels, and countdowns without going negative', () => {
    expect(poolLine(operatorMarket() as never)).toBe('Gavin $5.00 · Neville $7.00 · 2 bets');
    expect(poolLine(operatorMarket({ pool: { yes_minor: 100, no_minor: 0, total_minor: 100, simulated_minor: 0, wager_count: 1 } }) as never)).toBe(
      'Gavin $1.00 · Neville $0.00 · 1 bet',
    );
    expect(countdownText(65_000)).toBe('1:05');
    expect(countdownText(8_200)).toBe('0:09');
    expect(countdownText(-3_000)).toBe('0:00');
    expect(countdownText(null)).toBe('–:––');
  });
});

describe('streamPill', () => {
  it('maps source health to LIVE / Connecting… / OFFLINE', () => {
    const sh = (state: string) => health({ source_health: { state, source_kind: 'TWITCH_STREAMLINK', source_epoch: null, last_media_at_utc: null, last_transcript_at_utc: null, updated_at_utc: NOW } });
    expect(streamPill(sh('LIVE'), false)).toEqual({ text: 'LIVE', tone: 'live' });
    for (const s of ['CONNECTING', 'STALE', 'GAP']) expect(streamPill(sh(s), false)).toEqual({ text: 'Connecting…', tone: 'connecting' });
    expect(streamPill(sh('STOPPED'), false)).toEqual({ text: 'OFFLINE', tone: 'offline' });
    expect(streamPill(health({ source_health: null }), false)).toEqual({ text: 'OFFLINE', tone: 'offline' });
    // no health yet, or health gone stale: never a stale LIVE
    expect(streamPill(null, true).text).toBe('Connecting…');
    expect(streamPill(sh('LIVE'), true).text).toBe('Connecting…');
  });
});

describe('errorSentence', () => {
  it('gives one short human sentence, never the envelope', () => {
    const f = (status: number, code: string, details: unknown = null, extra: Partial<ConstructorParameters<typeof ApiFailure>[0]> = {}) =>
      new ApiFailure({
        kind: 'envelope',
        status,
        info: { code, message: 'raw server text', retryable: false, retry_after_ms: null, request_id: 'req_x', operation_id: null, details },
        message: 'raw server text',
        ...extra,
      });
    expect(errorSentence(f(409, 'MARKET_CLOSED', { reason: 'DEADLINE', reject_code: 'EXPIRED' }))).toBe('Too late to approve: it expired.');
    expect(errorSentence(f(409, 'STALE_MARKET', { reject_code: 'MARKET_BUSY' }))).toBe('Another bet is still running. Finish it first.');
    expect(errorSentence(f(403, 'FORBIDDEN', { ai_mode: 'OFF' }))).toBe('AI is set to OFF. Switch it to APPROVAL under Advanced.');
    expect(errorSentence(f(500, 'INTERNAL_ERROR', null, { outcomeUnknown: true }))).toMatch(/may or may not have gone through/);
    expect(errorSentence(new ApiFailure({ kind: 'network', status: null, info: null, message: 'x' }))).toBe("Can't reach the server.");
    for (const s of [errorSentence(f(422, 'VALIDATION_FAILED')), errorSentence(f(418, 'SOMETHING_NEW'))]) {
      expect(s).not.toContain('raw server text');
      expect(s).not.toMatch(/[A-Z]{3,}_[A-Z]+/);
    }
  });
});

// ---- the view and its buttons ---------------------------------------------------------------------------------

let mounted: Mounted | null = null;
afterEach(() => {
  mounted?.unmount();
  mounted = null;
  vi.unstubAllGlobals();
});

/** A scripted API: GETs come from `world`, POSTs echo a receipt carrying the request's operation_id. */
function api(world: { health: unknown; candidates?: AiCandidate[]; resolutions?: AiResolution[]; post?: (call: Call) => Response | null }) {
  const f = scriptedFetch((call) => {
    if (call.method === 'POST') {
      const custom = world.post?.(call);
      if (custom) return custom;
      return json(200, {
        schema_version: 1,
        operation_id: call.body?.operation_id,
        replayed: false,
        market: operatorMarket({ state: 'OPEN' }),
        candidate: candidate({ status: 'OPENED', actionable: false }),
        resolution: resolution({ status: 'SETTLED', actionable: false }),
        archived_stream_session_id: `run_${'c'.repeat(32)}`,
        stream_session_id: `run_${'7'.repeat(32)}`,
        voided_market_id: null,
        stream: healthBody().stream,
      });
    }
    if (call.url === '/v1/operator/health') return json(200, world.health);
    if (call.url.startsWith('/v1/operator/candidates')) return json(200, { schema_version: 1, server_time_utc: NOW, candidates: world.candidates ?? [] });
    if (call.url.startsWith('/v1/operator/resolutions')) return json(200, { schema_version: 1, server_time_utc: NOW, market_id: MKT, resolutions: world.resolutions ?? [] });
    if (call.url.startsWith('/v1/operator/evidence/')) {
      return new Response(new Blob([new Uint8Array([0xff, 0xd8, 0xff, 0xd9])], { type: 'image/jpeg' }), { status: 200 });
    }
    return json(404, envelope('NOT_FOUND'));
  });
  return { client: new OperatorClient({ getToken: () => TOKEN, fetchImpl: f.fetchImpl }), calls: f.calls };
}
const posts = (calls: Call[]) => calls.filter((c) => c.method === 'POST');
const card = (c: HTMLElement) => c.querySelector('[data-testid="demo-card"]') as HTMLElement | null;

describe('DemoView', () => {
  it('idle: only "FaZeTime" and the pill on top, no IDs or disclaimers; the test bet creates AND opens', async () => {
    const { client, calls } = api({ health: healthBody({ ai: AI }) });
    mounted = await mount(<DemoView client={client} />);
    const c = mounted.container;
    await waitFor(() => c.textContent?.includes('Waiting for the AI to spot a bet'));
    expect(c.querySelector('header')!.textContent).toBe('FaZeTimeOFFLINEFΘ');
    expect(c.textContent).not.toMatch(/mkt_|run_|str_|ep_|DEMO|test money|OPERATOR_FIXTURE/);
    expect(c.querySelector('[data-testid="advanced-link"]')!.getAttribute('href')).toBe('#advanced');
    expect(byText(c, 'button', 'Sign out')).toBeNull();
    await click(byText(c, 'button', 'test bet'));
    const form = c.querySelector('[data-testid="test-bet"]')!;
    const inputs = form.querySelectorAll('input');
    await typeInto(inputs[0], 'Will Gavin win?');
    await typeInto(inputs[1], 'Gavin');
    await typeInto(inputs[2], 'Neville');
    await typeInto(inputs[3], '45');
    await click(byText(c, 'button', 'Open bet'));
    await waitFor(() => posts(calls).length === 2);
    const [create, open] = posts(calls);
    expect(create.url).toBe('/v1/operator/markets');
    expect(create.body).toMatchObject({ question: 'Will Gavin win?', yes_label: 'Gavin', no_label: 'Neville', close_in_s: 45, resolve_in_s: 300 });
    expect(open.url).toBe(`/v1/operator/markets/${MKT}/open`);
    expect(create.body?.operation_id).toMatch(UUID_RE);
    expect(open.body?.operation_id).toMatch(UUID_RE);
    expect(create.body?.operation_id).not.toBe(open.body?.operation_id);
  });

  it('candidate: question and labels as text, a big countdown, Approve and one-click Reject (fixed reason, no form)', async () => {
    const { client, calls } = api({
      health: healthBody({ ai: AI, server_time_utc: NOW }),
      candidates: [candidate()],
      post: (call) =>
        call.url.endsWith('/approve') && posts(calls).length === 1
          ? json(409, envelope('MARKET_CLOSED', 'raw', { details: { reason: 'DEADLINE', reject_code: 'EXPIRED' } }))
          : null,
    });
    mounted = await mount(<DemoView client={client} />);
    const c = mounted.container;
    await waitFor(() => card(c)?.dataset.state === 'candidate');
    expect(c.querySelector('[data-testid="demo-question"]')!.textContent).toContain(INJECTION);
    expect(c.querySelector('img[src="x"]')).toBeNull();
    expect(c.textContent).toContain('FaZeGavin');
    expect(c.textContent).toContain('FaZeNeville');
    expect(c.querySelector('[data-testid="demo-countdown"]')!.textContent).toMatch(/^0:0[0-5]$/); // LEAD binds: ~5 s
    await click(byText(c, 'button', 'Approve'));
    await waitFor(() => c.querySelector('[data-testid="demo-error"]'));
    expect(c.querySelector('[data-testid="demo-error"]')!.textContent).toBe('Too late to approve: it expired.');
    expect(c.textContent).not.toContain('MARKET_CLOSED');
    await click(byText(c, 'button', 'Reject'));
    await waitFor(() => posts(calls).length === 2);
    const [approve, reject] = posts(calls);
    expect(approve.url).toBe(`/v1/operator/candidates/${CND}/approve`);
    expect(approve.body).toEqual({ operation_id: approve.body?.operation_id });
    expect(reject.url).toBe(`/v1/operator/candidates/${CND}/reject`);
    expect(reject.body).toMatchObject({ reason: 'rejected by operator' });
    expect(reject.body?.operation_id).not.toBe(approve.body?.operation_id);
    expect(c.querySelector('textarea, input')).toBeNull();
  });

  it('open: question, "Yes $X · No $Y · N bets" and a countdown to close', async () => {
    const { client } = api({ health: healthBody({ ai: AI, markets: [operatorMarket({ state: 'OPEN' })] }) });
    mounted = await mount(<DemoView client={client} />);
    const c = mounted.container;
    await waitFor(() => card(c)?.dataset.state === 'open');
    expect(c.querySelector('[data-testid="demo-pool"]')!.textContent).toBe('Gavin $5.00 · Neville $7.00 · 2 bets');
    expect(c.querySelector('[data-testid="demo-countdown"]')!.textContent).toMatch(/^[01]:\d\d$/);
  });

  it('waiting: an AI market after close with no suggestion yet', async () => {
    const { client } = api({ health: healthBody({ ai: AI, markets: [aiMarket({ state: 'EVALUATING' })] }), resolutions: [] });
    mounted = await mount(<DemoView client={client} />);
    const c = mounted.container;
    await waitFor(() => card(c)?.dataset.state === 'closed');
    expect(c.textContent).toContain('Betting closed. Waiting for the result.');
  });

  it('suggestion: "AI says: <label> won", one authenticated thumbnail, Approve result and Void & refund', async () => {
    const { client, calls } = api({ health: healthBody({ ai: AI, markets: [aiMarket({ state: 'EVALUATING' })] }), resolutions: [resolution()] });
    mounted = await mount(<DemoView client={client} />);
    const c = mounted.container;
    await waitFor(() => card(c)?.dataset.state === 'suggestion');
    expect(c.querySelector('[data-testid="demo-verdict"]')!.textContent).toBe('AI says: Gavin won');
    expect(c.textContent).not.toContain(INJECTION); // the model's reason stays in Advanced
    await waitFor(() => c.querySelector('[data-testid="demo-evidence"] img'));
    const img = calls.find((x) => x.url === `/v1/operator/evidence/${EVD}`)!;
    expect(img.headers.Authorization).toBe(`Bearer ${TOKEN}`);
    await click(byText(c, 'button', 'Approve result'));
    await waitFor(() => posts(calls).length === 1);
    expect(posts(calls)[0].url).toBe(`/v1/operator/resolutions/${RSL}/approve`);
    mounted.unmount();
    const second = api({ health: healthBody({ ai: AI, markets: [aiMarket({ state: 'EVALUATING' })] }), resolutions: [resolution()] });
    mounted = await mount(<DemoView client={second.client} />);
    const c2 = mounted.container;
    await waitFor(() => card(c2)?.dataset.state === 'suggestion');
    await click(byText(c2, 'button', 'Void & refund'));
    await waitFor(() => posts(second.calls).length === 1);
    expect(posts(second.calls)[0].url).toBe(`/v1/operator/markets/${MKT}/void`);
    expect(posts(second.calls)[0].body).toMatchObject({ note: 'voided by operator' });
  });

  it('fixture call: "<label> won" buttons settle that side', async () => {
    const { client, calls } = api({ health: healthBody({ ai: AI, markets: [operatorMarket({ state: 'EVALUATING' })] }) });
    mounted = await mount(<DemoView client={client} />);
    const c = mounted.container;
    await waitFor(() => card(c)?.dataset.state === 'fixture_call');
    await click(byText(c, 'button', 'Neville won'));
    await waitFor(() => posts(calls).length === 1);
    expect(posts(calls)[0].url).toBe(`/v1/operator/markets/${MKT}/settle`);
    expect(posts(calls)[0].body).toMatchObject({ winning_side: 'NO', note: 'called by operator' });
  });

  it('terminal: shows the result line; Reset for next take needs one confirm', async () => {
    const { client, calls } = api({ health: healthBody({ ai: AI, markets: [operatorMarket({ state: 'SETTLED', winning_side: 'YES' })] }) });
    mounted = await mount(<DemoView client={client} />);
    const c = mounted.container;
    await waitFor(() => card(c)?.dataset.state === 'result');
    expect(c.querySelector('[data-testid="demo-result"]')!.textContent).toBe('Gavin won. Winners paid.');
    await click(byText(c, 'button', 'Reset for next take'));
    expect(posts(calls)).toHaveLength(0);
    await click(byText(c.querySelector('[data-testid="reset-confirm"]')!, 'button', 'Reset'));
    await waitFor(() => posts(calls).length === 1);
    expect(posts(calls)[0].url).toBe('/v1/operator/runs/reset');
    expect(posts(calls)[0].body).toEqual({ stream_id: STR, operation_id: posts(calls)[0].body?.operation_id });
  });

  it('an unknown outcome offers "Try again", which re-sends the SAME operation_id', async () => {
    let n = 0;
    const { client, calls } = api({
      health: healthBody({ ai: AI, markets: [operatorMarket({ state: 'EVALUATING' })] }),
      post: () => (++n === 1 ? json(503, envelope('INTERNAL_ERROR')) : null),
    });
    mounted = await mount(<DemoView client={client} />);
    const c = mounted.container;
    await waitFor(() => card(c)?.dataset.state === 'fixture_call');
    await click(byText(c, 'button', 'Gavin won'));
    await waitFor(() => c.querySelector('[data-testid="demo-error"]'));
    expect(c.querySelector('[data-testid="demo-error"]')!.textContent).toContain('may or may not have gone through');
    await click(byText(c, 'button', 'Try again'));
    await waitFor(() => posts(calls).length === 2);
    expect(posts(calls)[1].body).toEqual(posts(calls)[0].body);
  });
});

// ---- §9.19 generic candidates (D37/D39) ------------------------------------------------------------------------

const CUES = { success_cue: 'SUCCESS_CUE_MODEL_TEXT level cleared', failure_cue: 'FAILURE_CUE_MODEL_TEXT try again' };
const YES_RULE = 'YES if the level in progress when betting opened ends with a visible result showing the streamer cleared it.';
const NO_RULE = 'NO if it ends with a visible result showing the streamer does not.';

/** A pending GENERIC_BINARY_V1 candidate: received 10 s ago with close_in_s 35, so its receipt-anchored lead is gone. */
function genericCandidate(over: Partial<AiCandidate> = {}): AiCandidate {
  return candidate({
    template_id: 'GENERIC_BINARY_V1',
    generic: { spec_version: 'gen-1', kind: 'EPISODE_OUTCOME', unit: 'level', params: { win_verb: 'clear' }, episode_start_media_ms: 120_000, ...CUES },
    episode_fingerprint: `gen:${EP}:120000:episode_outcome`,
    question: 'Will the streamer clear this level?',
    yes: { label: 'Yes', predicate: YES_RULE },
    no: { label: 'No', predicate: NO_RULE },
    subjects: [],
    suggested_close_in_s: 35,
    suggested_resolve_in_s: 335,
    close_in_s: 35,
    resolve_in_s: 335,
    proposed_close_at_utc: iso(25_000),
    rationale: 'model rationale',
    ...over,
  });
}

describe('DemoView: §9.19 generic candidates', () => {
  it('approves a generic candidate with its clamped close_in_s (from approval), and H2H still without one', async () => {
    const gen = api({ health: healthBody({ ai: AI, server_time_utc: NOW }), candidates: [genericCandidate()] });
    mounted = await mount(<DemoView client={gen.client} />);
    const c = mounted.container;
    await waitFor(() => card(c)?.dataset.state === 'candidate');
    // The receipt-anchored lead (close at +25 s, minus 30 s) would already be gone; counted from approval it does
    // not apply, so the window is the candidate expiry (50 s).
    expect(c.querySelector('[data-testid="demo-countdown"]')!.textContent).toMatch(/^0:(4\d|50)$/);
    const approve = byText(c, 'button', 'Approve') as HTMLButtonElement;
    expect(approve.disabled).toBe(false);
    await click(approve);
    await waitFor(() => posts(gen.calls).length === 1);
    const [g] = posts(gen.calls);
    expect(g.url).toBe(`/v1/operator/candidates/${CND}/approve`);
    expect(g.body).toEqual({ close_in_s: 35, operation_id: g.body?.operation_id });
    expect(g.body?.operation_id).toMatch(UUID_RE);
    mounted.unmount();

    const h2h = api({ health: healthBody({ ai: AI, server_time_utc: NOW }), candidates: [candidate({ proposed_close_at_utc: iso(45_000) })] });
    mounted = await mount(<DemoView client={h2h.client} />);
    const c2 = mounted.container;
    await waitFor(() => card(c2)?.dataset.state === 'candidate');
    expect(c2.querySelector('[data-testid="demo-countdown"]')!.textContent).toMatch(/^0:1[0-5]$/); // LEAD still binds
    expect(c2.querySelector('[data-testid="demo-kind"]')).toBeNull();
    expect(c2.querySelector('[data-testid="demo-rules"]')).toBeNull();
    await click(byText(c2, 'button', 'Approve'));
    await waitFor(() => posts(h2h.calls).length === 1);
    const [h] = posts(h2h.calls);
    expect(h.body).toEqual({ operation_id: h.body?.operation_id });
    expect(h.body).not.toHaveProperty('close_in_s');
  });

  it('shows no kind line above the question, only the YES / NO rules; tolerates no subjects and never shows the cues', async () => {
    const kinds: [string, string, Record<string, unknown>][] = [
      ['EPISODE_OUTCOME', 'Outcome', { win_verb: 'clear' }],
      ['END_VALUE_AT_LEAST', 'Number', { label: 'time left', threshold: 30 }],
      ['SAY_PHRASE', 'Heard on stream', { phrase: 'rush' }],
      ['DURATION_OVER', 'Duration', { duration_s: 90 }],
    ];
    for (const [kind, , params] of kinds) {
      const g = genericCandidate({
        generic: { spec_version: 'gen-1', kind, unit: 'round', params, episode_start_media_ms: 5_000, ...CUES },
        subjects: kind === 'SAY_PHRASE' ? ['FaZeGavin'] : [],
      });
      const { client } = api({ health: healthBody({ ai: AI, server_time_utc: NOW }), candidates: [g] });
      mounted = await mount(<DemoView client={client} />);
      const c = mounted.container;
      await waitFor(() => card(c)?.dataset.state === 'candidate');
      expect(c.querySelector('[data-testid="demo-kind"]')).toBeNull();
      expect(c.textContent).not.toMatch(/^Number/);
      const rules = c.querySelector('[data-testid="demo-rules"]')!;
      expect(rules.querySelector('.demo-rule.yes')!.textContent).toBe(YES_RULE); // already says YES: no repeated label
      expect(rules.querySelector('.demo-rule.no')!.textContent).toBe(NO_RULE);
      expect(c.querySelector('.demo-chip')).toBeNull();
      expect(c.textContent).not.toMatch(/SUCCESS_CUE|FAILURE_CUE|model rationale|GENERIC_BINARY_V1|gen:/);
      mounted.unmount();
      mounted = null;
    }
  });

  it('labels a rule that does not name its side, and shows no kind line without a generic object', async () => {
    const g = genericCandidate({
      generic: null,
      yes: { label: 'Yes', predicate: 'The streamer clears the level.' },
      no: { label: 'No', predicate: 'The level ends without a clear.' },
    });
    const { client, calls } = api({ health: healthBody({ ai: AI, server_time_utc: NOW }), candidates: [g] });
    mounted = await mount(<DemoView client={client} />);
    const c = mounted.container;
    await waitFor(() => card(c)?.dataset.state === 'candidate');
    expect(c.querySelector('[data-testid="demo-kind"]')).toBeNull();
    expect(c.querySelector('.demo-rule.yes')!.textContent).toBe('Yes: The streamer clears the level.');
    expect(c.querySelector('.demo-rule.no')!.textContent).toBe('No: The level ends without a clear.');
    await click(byText(c, 'button', 'Approve'));
    await waitFor(() => posts(calls).length === 1);
    expect(posts(calls)[0].body).toMatchObject({ close_in_s: 35 });
  });
});

describe('client: D35 silent re-open', () => {
  it('a 401 on a mutation re-opens once and retries with the same operation_id and the new token', async () => {
    let token = TOKEN;
    const NEW = 'fzs_freshtokenfreshtokenfresh0000';
    const reauthenticate = vi.fn(async () => {
      token = NEW;
      return 'renewed' as const;
    });
    const onUnauthorized = vi.fn();
    const f = scriptedFetch((call) =>
      call.headers.Authorization === `Bearer ${TOKEN}`
        ? json(401, envelope('UNAUTHENTICATED'))
        : json(200, { schema_version: 1, operation_id: call.body?.operation_id, replayed: false, market: operatorMarket() }),
    );
    const client = new OperatorClient({ getToken: () => token, fetchImpl: f.fetchImpl, reauthenticate, onUnauthorized });
    const r = await client.openMarket(MKT);
    expect(reauthenticate).toHaveBeenCalledTimes(1);
    expect(onUnauthorized).not.toHaveBeenCalled();
    expect(f.calls).toHaveLength(2);
    expect(f.calls[1].headers.Authorization).toBe(`Bearer ${NEW}`);
    expect(f.calls[1].body?.operation_id).toBe(f.calls[0].body?.operation_id);
    expect(r.operationId).toBe(f.calls[0].body?.operation_id);
  });

  it('invite mode (404 from the open route) falls back to onUnauthorized; a transient failure does not sign out', async () => {
    const onUnauthorized = vi.fn();
    const f = scriptedFetch(() => json(401, envelope('UNAUTHENTICATED')));
    const invite = new OperatorClient({ getToken: () => TOKEN, fetchImpl: f.fetchImpl, onUnauthorized, reauthenticate: async () => 'invite_mode' });
    await expect(invite.health()).rejects.toBeInstanceOf(ApiFailure);
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
    const transient = new OperatorClient({ getToken: () => TOKEN, fetchImpl: f.fetchImpl, onUnauthorized, reauthenticate: async () => 'failed' });
    await expect(transient.health()).rejects.toBeInstanceOf(ApiFailure);
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });

  it('a 403 refusing a mutation (AI mode OFF) does not drop the session; a 403 on a read does', async () => {
    const onForbidden = vi.fn();
    const f = scriptedFetch(() => json(403, envelope('FORBIDDEN', 'AI mode is OFF; candidates cannot be approved.', { details: { ai_mode: 'OFF' } })));
    const client = new OperatorClient({ getToken: () => TOKEN, fetchImpl: f.fetchImpl, onForbidden });
    await expect(client.approveCandidate(CND, null)).rejects.toBeInstanceOf(ApiFailure);
    expect(onForbidden).not.toHaveBeenCalled();
    await expect(client.health()).rejects.toBeInstanceOf(ApiFailure);
    expect(onForbidden).toHaveBeenCalledTimes(1);
  });

  it('the reopener is single-flight, treats 404 as invite mode, and waits between failed attempts', async () => {
    let clock = 0;
    let mode: 'ok' | 'down' | '404' = 'down';
    const open = vi.fn(async () => {
      if (mode === 'down') throw new ApiFailure({ kind: 'network', status: null, info: null, message: 'down' });
      if (mode === '404') throw new ApiFailure({ kind: 'envelope', status: 404, info: null, message: 'nf' });
      return {
        schema_version: 1 as const,
        session_token: 'fzs_freshtokenfreshtokenfresh0000',
        session_id: `ses_${'e'.repeat(32)}`,
        expires_at_utc: '2099-01-01T00:00:00.000Z',
        me: { user: { user_id: `usr_${'f'.repeat(32)}`, display_name: 'Operator', role: 'OPERATOR' } },
      } as never;
    });
    const onSession = vi.fn();
    const onInviteMode = vi.fn();
    const reopen = createReopener({ open, deviceId: () => crypto.randomUUID(), onSession, onInviteMode, now: () => clock, minGapMs: 3_000 });
    const [a, b] = await Promise.all([reopen(), reopen()]);
    expect([a, b]).toEqual(['failed', 'failed']);
    expect(open).toHaveBeenCalledTimes(1); // concurrent 401s share one call
    mode = 'ok';
    expect(await reopen()).toBe('failed'); // inside the gap: no network call
    expect(open).toHaveBeenCalledTimes(1);
    clock = 3_001;
    expect(await reopen()).toBe('renewed');
    expect(onSession).toHaveBeenCalledTimes(1);
    mode = '404';
    expect(await reopen()).toBe('invite_mode');
    expect(onInviteMode).toHaveBeenCalledTimes(1);
  });
});

describe('DemoView: CALM / ENRAGE theme switch (owner request 2026-11-15)', () => {
  it('defaults to CALM (FaZe); ENRAGE switches to the Odyssey theme, adds the sky, and is remembered', async () => {
    try {
      window.localStorage.removeItem('fazetime.operator.theme');
    } catch {
      /* storage may be unavailable in the test DOM */
    }
    const { client } = api({ health: healthBody({ ai: AI }) });
    mounted = await mount(<DemoView client={client} />);
    const c = mounted.container;
    await waitFor(() => c.querySelector('[data-testid="theme-switch"]'));
    expect(document.documentElement.dataset.theme).toBe('faze');
    expect(c.querySelector('.ody-sky')).toBeNull();
    const enrage = c.querySelector('button[aria-label="Odyssey theme"]')!;
    expect(enrage.getAttribute('aria-checked')).toBe('false');
    await click(enrage);
    await waitFor(() => document.documentElement.dataset.theme === 'odyssey');
    expect(c.querySelector('.ody-sky')).not.toBeNull();
    expect(c.querySelector('button[aria-label="Odyssey theme"]')!.getAttribute('aria-checked')).toBe('true');
    await click(c.querySelector('button[aria-label="FaZe theme"]') as HTMLElement);
    await waitFor(() => document.documentElement.dataset.theme === 'faze');
    expect(c.querySelector('.ody-sky')).toBeNull();
  });
});
