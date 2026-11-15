// P6-E: live Stripe test top-up handoff in the background adapter (CONTRACTS 9.18, 9.10).
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { StreamSnapshot } from '@fazetime/contracts';
import { LiveBackend, type LiveStore, type SessionRecord, type TopUpRecord } from '../src/live/backend';
import type { TopupStatus, TopUpTracking } from '../src/api/types';
import { loadSnapshotFixture } from '../src/mock/fixtures';
import { describeTopUp } from '../src/state/topupCopy';
import { initialPanelState, PanelController, type PanelState } from '../src/state/controller';

const TOKEN = `fzs_${'T'.repeat(43)}`;
const USER = `usr_${'b'.repeat(32)}`;
const CHECKOUT = 'https://checkout.stripe.com/c/pay/cs_test_a1B2c3D4e5#fidkdWxOYHwnPyd1blpxYHZxWjA0';
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const uuid = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
const topId = (c: string) => `top_${c.repeat(32)}`;

type Responder = (body: { operation_id: string; amount_minor: number }) => { status: number; body: unknown } | 'throw';

function harness(opts: { store?: Partial<LiveStore> & { topup?: TopUpRecord | null }; runOverride?: string; pollMs?: number } = {}) {
  let server: StreamSnapshot = loadSnapshotFixture('open_no_position', Date.now());
  const counts: Record<string, number> = {};
  const posts: Array<{ operation_id: string; amount_minor: number }> = [];
  const postQueue: Responder[] = [];
  const getQueue: TopupStatus[] = [];
  const topups = new Map<string, Record<string, unknown>>();
  const opened: string[] = [];
  const logs: string[] = [];
  const store: LiveStore & { session: SessionRecord | null; topup: TopUpRecord | null } = {
    session: { token: TOKEN, session_id: `ses_${'a'.repeat(32)}`, expires_at_utc: new Date(Date.now() + 3.6e6).toISOString(), user_id: USER, display_name: 'Alice', role: 'VIEWER' },
    topup: opts.store?.topup ?? null,
    getSession: async () => store.session,
    setSession: async (s) => void (store.session = s),
    getDeviceId: async () => '00000000-0000-4000-8000-00000000d001',
    getTopUp: async () => (store.topup ? structuredClone(store.topup) : null),
    setTopUp: async (r) => void (store.topup = r ? structuredClone(r) : null),
  };
  const me = { schema_version: 1, server_time_utc: server.server_time_utc, user: { user_id: USER, display_name: 'Alice', claimed_twitch_login: null, role: 'VIEWER' }, session: { session_id: `ses_${'a'.repeat(32)}`, expires_at_utc: new Date(Date.now() + 3.6e6).toISOString() }, current_stream: { stream_id: server.stream.stream_id, twitch_channel_login: 'fazegavin1234', stream_session_id: server.stream.stream_session_id }, wallet: server.wallet };
  const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
  const envelope = (code: string, status: number, retryable: boolean, extra: Record<string, unknown> = {}) => ({ status, body: { schema_version: 1, error: { code, message: 'x', retryable, retry_after_ms: null, request_id: `req_${'c'.repeat(32)}`, operation_id: null, details: null, ...extra }, server_time_utc: new Date().toISOString() } });
  let nextId = 0;
  const receiptFor = (id: string) => ({ ...topups.get(id)!, checkout_url: topups.get(id)!.status === 'PENDING' ? CHECKOUT : null });
  const created: Responder = (b) => {
    const existing = [...topups.values()].find((t) => t.operation_id === b.operation_id);
    if (existing) return { status: 200, body: { ...receiptFor(existing.topup_id as string), replayed: true } };
    const id = topId('0123456789abcdef'[nextId++ % 16]!);
    topups.set(id, { schema_version: 1, topup_id: id, operation_id: b.operation_id, stream_session_id: opts.runOverride ?? server.stream.stream_session_id, amount_minor: b.amount_minor, currency: 'usd', status: 'PENDING', payment_mode: 'STRIPE_TEST', checkout_expires_at_utc: new Date(Date.now() + 30 * 60_000).toISOString(), replayed: false });
    return { status: 201, body: receiptFor(id) };
  };
  const fetchImpl = (async (url: string, init?: RequestInit) => {
    const u = new URL(url);
    const path = u.pathname;
    counts[path] = (counts[path] ?? 0) + 1;
    if ((init?.headers as Record<string, string>)?.Authorization !== `Bearer ${TOKEN}`) return json(401, envelope('UNAUTHENTICATED', 401, false).body);
    if (path === '/v1/me') return json(200, me);
    if (path.endsWith('/snapshot')) return json(200, { ...server, server_time_utc: new Date().toISOString() });
    if (path === '/v1/topups' && init?.method === 'POST') {
      const body = JSON.parse(String(init.body));
      posts.push(body);
      const r = (postQueue.shift() ?? created)(body);
      if (r === 'throw') throw new TypeError('network down');
      return json(r.status, r.body);
    }
    const m = /^\/v1\/topups\/(top_[0-9a-f]{32})$/.exec(path);
    if (m) {
      const t = topups.get(m[1]!);
      if (!t) return json(404, envelope('NOT_FOUND', 404, false).body);
      const next = getQueue.shift();
      if (next) {
        t.status = next;
        if (next === 'CREDITED')
          server = { ...server, event_hwm: server.event_hwm + 1, wallet: { ...server.wallet, available_minor: server.wallet.available_minor + (t.amount_minor as number), balance_version: server.wallet.balance_version + 1 } };
      }
      return json(200, { ...receiptFor(m[1]!), replayed: false });
    }
    return json(404, envelope('NOT_FOUND', 404, false).body);
  }) as unknown as typeof fetch;
  const backend = new LiveBackend({
    apiBase: 'http://127.0.0.1:8000',
    channel: 'fazegavin1234',
    extensionVersion: 'test',
    store,
    fetch: fetchImpl,
    createWebSocket: () => ({ readyState: 0, send() {}, close() {}, onopen: null, onmessage: null, onclose: null, onerror: null }),
    log: (msg) => logs.push(msg),
    openTab: async (url) => void opened.push(url),
    topupPollMs: opts.pollMs ?? 20,
    topupSlowPollMs: opts.pollMs ?? 20,
    topupRetryDelaysMs: [5, 5, 5],
  });
  return { backend, store, counts, posts, postQueue, getQueue, topups, opened, logs, envelope, created, server: () => server };
}

const getCount = (h: ReturnType<typeof harness>) => Object.entries(h.counts).filter(([p]) => p.startsWith('/v1/topups/')).reduce((n, [, c]) => n + c, 0);

afterEach(() => vi.restoreAllMocks());

describe('LiveBackend Stripe test top-ups (P6-E, CONTRACTS 9.18)', () => {
  it('create: one POST, opens Stripe Checkout once from the background, persists the pending top-up, never exposes the URL', async () => {
    const h = harness();
    const r = await h.backend.createTopUp({ operation_id: uuid(1), amount_minor: 1000 });
    expect(r.ok).toBe(true);
    const view = (r as { body: TopUpTracking }).body;
    expect(view).toMatchObject({ payment_mode: 'STRIPE_TEST', status: 'PENDING', amount_minor: 1000, operation_id: uuid(1), checkout_opened: true, watching: true });
    expect(h.posts).toEqual([{ operation_id: uuid(1), amount_minor: 1000 }]);
    expect(h.opened).toEqual([CHECKOUT]);
    expect(h.store.topup).toMatchObject({ topup_id: view.topup_id, operation_id: uuid(1), amount_minor: 1000, status: 'PENDING' });
    for (const blob of [JSON.stringify(view), JSON.stringify(h.store.topup), JSON.stringify(h.backend.peekTopUp())]) {
      expect(blob).not.toContain('checkout.stripe.com');
      expect(blob).not.toContain('cs_test');
      expect(blob).not.toContain('fzs_');
    }
  });

  it('replay: the same operation_id returns the stored top-up (200) without a second Checkout tab; Reopen opens it again', async () => {
    const h = harness();
    const first = await h.backend.createTopUp({ operation_id: uuid(2), amount_minor: 500 });
    const again = await h.backend.createTopUp({ operation_id: uuid(2), amount_minor: 500 });
    expect(again).toMatchObject({ ok: true, status: 200 });
    expect((again as { body: TopUpTracking }).body.topup_id).toBe((first as { body: TopUpTracking }).body.topup_id);
    expect(h.topups.size).toBe(1);
    expect(h.opened).toHaveLength(1);
    await h.backend.reopenTopUpCheckout();
    expect(h.posts.map((p) => p.operation_id)).toEqual([uuid(2), uuid(2), uuid(2)]);
    expect(h.opened).toHaveLength(2);
  });

  it('a double click while the request is in flight sends ONE request', async () => {
    const h = harness();
    const [a, b] = await Promise.all([h.backend.createTopUp({ operation_id: uuid(3), amount_minor: 500 }), h.backend.createTopUp({ operation_id: uuid(3), amount_minor: 500 })]);
    expect(a.ok && b.ok).toBe(true);
    expect(h.posts).toHaveLength(1);
    expect(h.opened).toHaveLength(1);
  });

  it('retries with the SAME key and body on 500 INTERNAL_ERROR, 429 RATE_LIMITED and a network failure', async () => {
    const h = harness();
    h.postQueue.push(
      () => h.envelope('INTERNAL_ERROR', 500, true),
      () => h.envelope('RATE_LIMITED', 429, true, { retry_after_ms: 10 }),
      () => 'throw',
    );
    const r = await h.backend.createTopUp({ operation_id: uuid(4), amount_minor: 5000 });
    expect(r).toMatchObject({ ok: true, body: { status: 'PENDING', checkout_opened: true } });
    expect(h.posts).toHaveLength(4);
    expect(new Set(h.posts.map((p) => JSON.stringify(p)))).toEqual(new Set([JSON.stringify({ operation_id: uuid(4), amount_minor: 5000 })]));
    expect(h.opened).toHaveLength(1);
  });

  it('after the retries are exhausted the outcome stays unknown and the key is kept for a user retry', async () => {
    const h = harness();
    for (let i = 0; i < 4; i++) h.postQueue.push(() => h.envelope('INTERNAL_ERROR', 500, true));
    const r = await h.backend.createTopUp({ operation_id: uuid(5), amount_minor: 1000 });
    expect(r.ok).toBe(false);
    expect(h.backend.peekTopUp()).toMatchObject({ status: 'SUBMITTING', watching: false, operation_id: uuid(5) });
    expect(describeTopUp(h.backend.peekTopUp()!).action).toBe('REOPEN');
    const retry = await h.backend.reopenTopUpCheckout(); // Same key; the server now creates it.
    expect(retry).toMatchObject({ ok: true, body: { status: 'PENDING', checkout_opened: true } });
    expect(new Set(h.posts.map((p) => p.operation_id))).toEqual(new Set([uuid(5)]));
  });

  it('definitive errors are not retried and leave nothing tracked', async () => {
    const h = harness();
    h.postQueue.push(() => h.envelope('INVALID_AMOUNT', 422, false));
    const r = await h.backend.createTopUp({ operation_id: uuid(6), amount_minor: 450 });
    expect(r).toMatchObject({ ok: false, kind: 'http', error: { error: { code: 'INVALID_AMOUNT' } } });
    expect(h.posts).toHaveLength(1);
    expect(h.backend.peekTopUp()).toBeNull();
    expect(h.store.topup).toBeNull();
    expect(h.opened).toHaveLength(0);
  });

  it('refuses to open anything but https://checkout.stripe.com', async () => {
    const h = harness();
    h.postQueue.push((b) => {
      const r = h.created(b) as { status: number; body: Record<string, unknown> };
      return { status: r.status, body: { ...r.body, checkout_url: 'https://checkout.stripe.com.evil.example/pay' } };
    });
    const r = await h.backend.createTopUp({ operation_id: uuid(7), amount_minor: 500 });
    expect(r).toMatchObject({ ok: true, body: { checkout_opened: false, checkout_blocked: true } });
    expect(h.opened).toHaveLength(0);
  });

  it.each(['CREDITED', 'FAILED', 'EXPIRED'] as const)('polls GET /v1/topups/{id} while PENDING and stops on %s', async (terminal) => {
    const h = harness();
    h.getQueue.push('PENDING', 'PENDING', terminal);
    await h.backend.createTopUp({ operation_id: uuid(8), amount_minor: 1000 });
    await sleep(150);
    expect(h.backend.peekTopUp()).toMatchObject({ status: terminal, watching: false });
    const n = getCount(h);
    expect(n).toBe(3);
    await sleep(120);
    expect(getCount(h)).toBe(n); // Stopped.
    const copy = describeTopUp(h.backend.peekTopUp()!);
    expect(copy.terminal).toBe(true);
    if (terminal === 'CREDITED') expect(copy.text).toBe('Test credits added: $10.00');
    else expect(copy.text).toMatch(/No credits were added/);
  });

  it('CREDITED refreshes the wallet from the server snapshot (and nothing places a wager)', async () => {
    const h = harness();
    await h.backend.getSnapshot();
    const before = (h.backend.peekSnapshot() as { body: StreamSnapshot }).body.wallet.available_minor;
    const fetches = h.backend.snapshotFetches;
    h.getQueue.push('CREDITED');
    await h.backend.createTopUp({ operation_id: uuid(9), amount_minor: 1000 });
    await sleep(120);
    expect(h.backend.snapshotFetches).toBe(fetches + 1);
    expect((h.backend.peekSnapshot() as { body: StreamSnapshot }).body.wallet.available_minor).toBe(before + 1000);
    expect(h.counts['/v1/wagers'] ?? 0).toBe(0);
  });

  it('a top-up for an archived run says it was credited to the previous demo run', async () => {
    const h = harness({ runOverride: `run_${'9'.repeat(32)}` });
    await h.backend.getSnapshot();
    h.getQueue.push('CREDITED');
    await h.backend.createTopUp({ operation_id: uuid(10), amount_minor: 500 });
    await sleep(100);
    const view = h.backend.peekTopUp()!;
    expect(view).toMatchObject({ status: 'CREDITED', previous_run: true });
    expect(describeTopUp(view).text).toBe('Test credits added: $5.00, credited to the previous demo run.');
  });

  it('the return-URL hint polls immediately and never credits by itself', async () => {
    const h = harness({ pollMs: 60_000 }); // No regular poll during this test: only the hint polls.
    const r = await h.backend.createTopUp({ operation_id: uuid(11), amount_minor: 500 });
    const id = (r as { body: TopUpTracking }).body.topup_id!;
    expect(getCount(h)).toBe(0);
    const hinted = await h.backend.topUpHint(id);
    expect(getCount(h)).toBe(1);
    expect(hinted).toMatchObject({ ok: true, body: { status: 'PENDING' } }); // Still the server's status.
    await h.backend.topUpHint(id); // Within 1 s: no extra request (the server throttles to 3 s anyway).
    expect(getCount(h)).toBe(1);
    expect(await h.backend.topUpHint('top_nothex')).toMatchObject({ ok: false, error: { error: { code: 'VALIDATION_FAILED' } } });
    expect(await h.backend.topUpHint(topId('f'))).toMatchObject({ ok: true }); // Another (unknown) id while one is pending: ignored.
    expect(h.backend.peekTopUp()?.topup_id).toBe(id);
    await h.backend.signOut();
  });

  it('a restarted background resumes polling the persisted top-up', async () => {
    const h1 = harness();
    await h1.backend.createTopUp({ operation_id: uuid(12), amount_minor: 1000 });
    const saved = structuredClone(h1.store.topup!);
    await h1.backend.signOut(); // Stop the first worker's timers.
    const h2 = harness({ store: { topup: saved } });
    for (const [k, v] of h1.topups) h2.topups.set(k, v);
    h2.getQueue.push('CREDITED');
    await sleep(120);
    expect(h2.backend.peekTopUp()).toMatchObject({ topup_id: saved.topup_id, status: 'CREDITED' });
  });

  it('no Checkout URL, session token or ticket is ever logged', async () => {
    const spies = (['log', 'info', 'warn', 'error', 'debug'] as const).map((m) => vi.spyOn(console, m));
    const h = harness();
    h.postQueue.push(() => h.envelope('INTERNAL_ERROR', 500, true));
    h.getQueue.push('PENDING', 'CREDITED');
    await h.backend.createTopUp({ operation_id: uuid(13), amount_minor: 1000 });
    await sleep(120);
    const all = [...h.logs, ...spies.flatMap((s) => s.mock.calls.map((c) => c.map(String).join(' ')))].join('\n');
    expect(all).not.toMatch(/checkout\.stripe\.com|cs_test|fzs_|fzw_/);
    expect(h.logs.some((l) => /credited/.test(l))).toBe(true);
  });
});

describe('PanelController top-up handling (content side)', () => {
  const tracking = (over: Partial<TopUpTracking> = {}): TopUpTracking => ({
    payment_mode: 'STRIPE_TEST',
    topup_id: topId('a'),
    operation_id: uuid(20),
    amount_minor: 1000,
    status: 'PENDING',
    checkout_opened: true,
    checkout_blocked: false,
    previous_run: false,
    watching: true,
    updated_at_ms: Date.now(),
    ...over,
  });
  const make = () => {
    const placeWager = vi.fn();
    const api = { placeWager, getSnapshot: vi.fn(async () => ({ ok: false, kind: 'unknown', message: 'x' })) } as never;
    const c = new PanelController(api, { get: async () => null, set: async () => undefined, remove: async () => undefined });
    return { c, placeWager };
  };

  it('a credit after an INSUFFICIENT_FUNDS rejection returns to a fresh card and never re-submits the bet', () => {
    const { c, placeWager } = make();
    const s = c as unknown as { state: PanelState };
    const request = { operation_id: uuid(21), stream_session_id: `run_${'1'.repeat(32)}`, market_id: `mkt_${'1'.repeat(32)}`, rules_version: 1, side: 'YES', amount_minor: 2000 };
    s.state = { ...initialPanelState(), bet: { kind: 'rejected', error: { code: 'INSUFFICIENT_FUNDS', message: 'x', retryable: false, retry_after_ms: null, request_id: `req_${'c'.repeat(32)}`, operation_id: uuid(21), details: null }, request } as never };
    c.onPush({ t: 'topup', topup: tracking() });
    expect(c.getState().bet.kind).toBe('rejected');
    c.onPush({ t: 'topup', topup: tracking({ status: 'CREDITED', watching: false }) });
    expect(c.getState().bet.kind).toBe('idle');
    expect(c.getState().pendingTopUp?.status).toBe('CREDITED');
    expect(placeWager).not.toHaveBeenCalled();
  });

  it('ignores malformed top-up pushes (untrusted message shape)', () => {
    const { c } = make();
    c.onPush({ t: 'topup', topup: { payment_mode: 'STRIPE_TEST', status: 'CREDITED' } as never });
    expect(c.getState().pendingTopUp).toBeNull();
  });
});
