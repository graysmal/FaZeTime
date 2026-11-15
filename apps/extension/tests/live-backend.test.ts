import { describe, expect, it } from 'vitest';
import { checkSnapshot, type DomainEvent, type PublicMarket, type StreamSnapshot } from '@fazetime/contracts';
import { LiveBackend, type LiveStore, type SessionRecord, type WsLike } from '../src/live/backend';
import { loadSnapshotFixture } from '../src/mock/fixtures';

const TOKEN = `fzs_${'T'.repeat(43)}`;
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

class FakeWs implements WsLike {
  readyState = 0;
  sent: string[] = [];
  closed: number | null = null;
  onopen: ((ev: unknown) => void) | null = null;
  onmessage: ((ev: { data: unknown }) => void) | null = null;
  onclose: ((ev: { code: number }) => void) | null = null;
  onerror: ((ev: unknown) => void) | null = null;
  constructor(public url: string) {}
  send(data: string) {
    this.sent.push(data);
  }
  close(code = 1000) {
    this.closed = code;
  }
  serverSend(frame: unknown) {
    this.onmessage?.({ data: JSON.stringify(frame) });
  }
}

function harness(opts: { enrolled?: boolean } = {}) {
  let server: StreamSnapshot = loadSnapshotFixture('open_no_position', Date.now());
  const counts: Record<string, number> = {};
  let fail401 = false;
  const store: LiveStore & { session: SessionRecord | null } = {
    session: opts.enrolled === false ? null : { token: TOKEN, session_id: `ses_${'a'.repeat(32)}`, expires_at_utc: new Date(Date.now() + 3.6e6).toISOString(), user_id: `usr_${'b'.repeat(32)}`, display_name: 'Alice', role: 'VIEWER' },
    getSession: async () => store.session,
    setSession: async (s) => void (store.session = s),
    getDeviceId: async () => '00000000-0000-4000-8000-00000000d001',
  };
  const me = { schema_version: 1, server_time_utc: server.server_time_utc, user: { user_id: `usr_${'b'.repeat(32)}`, display_name: 'Alice', claimed_twitch_login: null, role: 'VIEWER' }, session: { session_id: `ses_${'a'.repeat(32)}`, expires_at_utc: new Date(Date.now() + 3.6e6).toISOString() }, current_stream: { stream_id: server.stream.stream_id, twitch_channel_login: 'fazegavin1234', stream_session_id: server.stream.stream_session_id }, wallet: server.wallet };
  const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
  const unauth = () => json(401, { schema_version: 1, error: { code: 'UNAUTHENTICATED', message: 'x', retryable: false, retry_after_ms: null, request_id: `req_${'c'.repeat(32)}`, operation_id: null, details: null }, server_time_utc: new Date().toISOString() });
  const fetchImpl = (async (url: string, init?: RequestInit) => {
    const path = new URL(url).pathname;
    counts[path] = (counts[path] ?? 0) + 1;
    const auth = (init?.headers as Record<string, string>)?.Authorization;
    if (path !== '/v1/enroll' && (fail401 || auth !== `Bearer ${TOKEN}`)) return unauth();
    if (path === '/v1/me') return json(200, me);
    if (path.endsWith('/snapshot')) return json(200, { ...server, server_time_utc: new Date().toISOString() });
    if (path === '/v1/ws-ticket') return json(200, { schema_version: 1, ticket: `fzw_${'k'.repeat(43)}`, expires_at_utc: new Date(Date.now() + 30000).toISOString(), ws_path: '/v1/ws' });
    if (path === '/v1/enroll') return json(201, { schema_version: 1, session_token: TOKEN, session_id: me.session.session_id, expires_at_utc: me.session.expires_at_utc, me: { ...me, schema_version: undefined } });
    if (path === '/v1/presence') return json(200, { ok: true });
    return json(404, { schema_version: 1, error: { code: 'NOT_FOUND', message: 'x', retryable: false, retry_after_ms: null, request_id: `req_${'d'.repeat(32)}`, operation_id: null, details: null }, server_time_utc: new Date().toISOString() });
  }) as unknown as typeof fetch;
  const sockets: FakeWs[] = [];
  const backend = new LiveBackend({
    apiBase: 'http://127.0.0.1:8000',
    channel: 'fazegavin1234',
    extensionVersion: 'test',
    store,
    fetch: fetchImpl,
    createWebSocket: (url) => {
      const ws = new FakeWs(url);
      sockets.push(ws);
      return ws;
    },
    pollOpenMs: 40,
    pollIdleMs: 200,
    pingIntervalMs: 60,
  });
  return {
    backend,
    store,
    counts,
    sockets,
    setServer: (f: (s: StreamSnapshot) => StreamSnapshot) => void (server = f(server)),
    server: () => server,
    fail401: () => void (fail401 = true),
  };
}

const marketEvent = (snap: StreamSnapshot, id: number, version: number, type: DomainEvent['event_type'] = 'pool.updated', over: Partial<PublicMarket> = {}): DomainEvent => ({
  schema_version: 1,
  event_id: id,
  stream_session_id: snap.stream.stream_session_id,
  aggregate_type: 'MARKET',
  aggregate_id: snap.market!.market_id,
  aggregate_version: version,
  event_type: type,
  audience: 'PUBLIC',
  occurred_at_utc: new Date().toISOString(),
  payload: { ...snap.market!, aggregate_version: version, ...over },
});

async function connected() {
  const h = harness();
  h.backend.setDemand(1);
  await h.backend.getSnapshot();
  await sleep(20);
  const ws = h.sockets[0]!;
  ws.onopen?.({});
  ws.serverSend({ type: 'ready', schema_version: 1, event_hwm: h.server().event_hwm, stream_id: h.server().stream.stream_id, server_time_utc: new Date().toISOString() });
  await sleep(20);
  return { ...h, ws };
}

describe('LiveBackend (background-only live adapter)', () => {
  it('authenticates the socket with the ticket in the FIRST FRAME, never in the URL', async () => {
    const { ws, backend } = await connected();
    expect(ws.url).toBe('ws://127.0.0.1:8000/v1/ws');
    expect(JSON.parse(ws.sent[0]!)).toEqual({ type: 'auth', ticket: `fzw_${'k'.repeat(43)}` });
    expect(backend.status().link).toBe('LIVE');
    ws.serverSend({ type: 'ping' });
    expect(JSON.parse(ws.sent.at(-1)!)).toEqual({ type: 'pong' });
    await sleep(80);
    expect(ws.sent.some((f) => JSON.parse(f).type === 'ping')).toBe(true); // Client app-level ping.
  });

  it('applies any newer version (jumps are normal), ignores older/duplicates, and never refetches for them (9.15(14))', async () => {
    const { backend, server } = await connected();
    const s = server();
    const base = s.market!.aggregate_version;
    const fetches = backend.snapshotFetches;
    const bumped = { ...s.market!.pool, yes_minor: s.market!.pool.yes_minor + 500, total_minor: s.market!.pool.total_minor + 500, wager_count: s.market!.pool.wager_count + 1 };
    expect(backend.applyEvent(marketEvent(s, s.event_hwm + 1, base + 1, 'pool.updated', { pool: bumped }))).toBe(true);
    expect((backend.peekSnapshot() as { body: StreamSnapshot }).body.market!.pool.yes_minor).toBe(bumped.yes_minor);
    expect(backend.applyEvent(marketEvent(s, s.event_hwm + 2, base, 'pool.updated'))).toBe(false); // Older version.
    expect(backend.applyEvent(marketEvent(s, s.event_hwm + 1, base + 1, 'pool.updated'))).toBe(false); // Duplicate event_id.
    expect(backend.applyEvent(marketEvent(s, s.event_hwm + 3, base + 5, 'pool.updated', { pool: bumped }))).toBe(true); // Jump: applied.
    await sleep(80);
    expect(backend.snapshotFetches).toBe(fetches); // No refetch storm.
  });

  it('derives a new market and a settlement burst from events alone', async () => {
    const { backend, server } = await connected();
    const s = server();
    const fetches = backend.snapshotFetches;
    const run = s.stream.stream_session_id;
    const mid = `mkt_${'e'.repeat(32)}` as `mkt_${string}`;
    const fresh: PublicMarket = { ...s.market!, market_id: mid, aggregate_version: 2, pool: { yes_minor: 0, no_minor: 0, total_minor: 0, simulated_minor: 0, wager_count: 0 } };
    let id = s.event_hwm;
    const ev = (aggregate_type: DomainEvent['aggregate_type'], event_type: DomainEvent['event_type'], aggregate_id: string, aggregate_version: number, payload: unknown, audience: DomainEvent['audience'] = 'PUBLIC'): DomainEvent =>
      ({ schema_version: 1, event_id: ++id, stream_session_id: run, aggregate_type, aggregate_id, aggregate_version, event_type, audience, occurred_at_utc: new Date().toISOString(), payload }) as DomainEvent;
    // The previous market was replaced by a new OPEN one: no position yet.
    expect(backend.applyEvent(ev('MARKET', 'market.opened', mid, 2, fresh))).toBe(true);
    let snap = (backend.peekSnapshot() as { body: StreamSnapshot }).body;
    expect(snap.market!.market_id).toBe(mid);
    expect(snap.my_position).toMatchObject({ market_id: mid, side: null, stake_total_minor: 0, result: 'NONE' });
    // Own wager, then settlement: market.settled + wager.updated + wallet.changed (wallet jumps several versions).
    const wager = { ...s.my_position!.wagers[0], market_id: mid } as never as Record<string, unknown>;
    const walletV = s.wallet.balance_version;
    const pool = { yes_minor: 500, no_minor: 700, total_minor: 1200, simulated_minor: 0, wager_count: 2 };
    backend.applyEvent(ev('MARKET', 'pool.updated', mid, 4, { ...fresh, aggregate_version: 4, pool }));
    backend.applyEvent(ev('WAGER', 'wager.updated', `wgr_${'f'.repeat(32)}`, 1, { wager_id: `wgr_${'f'.repeat(32)}`, operation_id: '00000000-0000-4000-8000-0000000000aa', stream_session_id: run, market_id: mid, rules_version: 1, side: 'YES', amount_minor: 500, status: 'ACCEPTED', accepted_at_utc: new Date().toISOString(), terminal_at_utc: null, stake_txn_id: `txn_${'1'.repeat(32)}`, terminal_txn_id: null, payout_minor: null, refund_minor: null, market_aggregate_version: 3, wallet_after: { ...s.wallet, available_minor: 1500, in_play_minor: 500, balance_version: walletV + 1 }, replayed: false }, 'USER'));
    backend.applyEvent(ev('WALLET', 'wallet.changed', `usr_${'b'.repeat(32)}`, walletV + 1, { ...s.wallet, available_minor: 1500, in_play_minor: 500, balance_version: walletV + 1 }, 'USER'));
    const settledAt = new Date().toISOString();
    backend.applyEvent(ev('MARKET', 'market.settled', mid, 7, { ...fresh, aggregate_version: 7, pool, state: 'SETTLED', locked_at_utc: settledAt, terminal_at_utc: settledAt, winning_side: 'YES', settlement_algorithm: 'PARIMUTUEL_FLOOR_REMAINDER_V1' }));
    backend.applyEvent(ev('WAGER', 'wager.updated', `wgr_${'f'.repeat(32)}`, 2, { wager_id: `wgr_${'f'.repeat(32)}`, operation_id: '00000000-0000-4000-8000-0000000000aa', stream_session_id: run, market_id: mid, rules_version: 1, side: 'YES', amount_minor: 500, status: 'WON', accepted_at_utc: settledAt, terminal_at_utc: settledAt, stake_txn_id: `txn_${'1'.repeat(32)}`, terminal_txn_id: `txn_${'2'.repeat(32)}`, payout_minor: 1200, refund_minor: null, market_aggregate_version: 7, wallet_after: { ...s.wallet, available_minor: 1500, in_play_minor: 500, balance_version: walletV + 1 }, replayed: false }, 'USER'));
    backend.applyEvent(ev('WALLET', 'wallet.changed', `usr_${'b'.repeat(32)}`, walletV + 4, { ...s.wallet, available_minor: 2700, in_play_minor: 0, balance_version: walletV + 4 }, 'USER'));
    snap = (backend.peekSnapshot() as { body: StreamSnapshot }).body;
    expect(snap.my_position).toMatchObject({ side: 'YES', stake_total_minor: 500, result: 'WON', payout_total_minor: 1200 });
    expect(snap.wallet).toMatchObject({ available_minor: 2700, in_play_minor: 0 });
    expect(checkSnapshot(snap)).toEqual([]);
    await sleep(80);
    expect(backend.snapshotFetches).toBe(fetches);
  });

  it('a server resync frame refetches the snapshot', async () => {
    const { backend, ws } = await connected();
    const fetches = backend.snapshotFetches;
    ws.serverSend({ type: 'resync', reason: 'overflow' });
    await sleep(120);
    expect(backend.snapshotFetches).toBe(fetches + 1);
  });

  it('refetches on a run change instead of mixing runs', async () => {
    const { backend, server, counts } = await connected();
    const s = server();
    const before = counts[`/v1/streams/${s.stream.stream_id}/snapshot`] ?? 0;
    const ev = { ...marketEvent(s, s.event_hwm + 1, 99), stream_session_id: `run_${'9'.repeat(32)}` as `run_${string}` };
    expect(backend.applyEvent(ev)).toBe(false);
    await sleep(80);
    expect(counts[`/v1/streams/${s.stream.stream_id}/snapshot`]).toBeGreaterThan(before);
  });

  it('wallet events apply only with a higher balance_version in the same run', async () => {
    const { backend, server } = await connected();
    const s = server();
    const wallet = (v: number, a: number) => ({ schema_version: 1 as const, event_id: s.event_hwm + v, stream_session_id: s.stream.stream_session_id, aggregate_type: 'WALLET' as const, aggregate_id: `usr_${'b'.repeat(32)}`, aggregate_version: s.wallet.balance_version + v, event_type: 'wallet.changed' as const, audience: 'USER' as const, occurred_at_utc: new Date().toISOString(), payload: { ...s.wallet, balance_version: s.wallet.balance_version + v, available_minor: a } });
    expect(backend.applyEvent(wallet(2, 1234))).toBe(true);
    expect(backend.applyEvent(wallet(1, 999))).toBe(false);
    expect((backend.peekSnapshot() as { body: StreamSnapshot }).body.wallet.available_minor).toBe(1234);
  });

  it('falls back to polling when the socket drops, and reconnects', async () => {
    const { backend, ws, counts, server, sockets } = await connected();
    const path = `/v1/streams/${server().stream.stream_id}/snapshot`;
    const before = counts[path] ?? 0;
    backend.debugDropSocket();
    expect(backend.status().link).toBe('POLLING');
    await sleep(200);
    expect(counts[path]! - before).toBeGreaterThanOrEqual(2); // 40 ms poll while OPEN (2 s in production).
    await sleep(1400);
    expect(sockets.length).toBeGreaterThan(1); // Backoff reconnect opened a new socket.
    expect(ws.closed).toBe(4000);
  });

  it('origin rejection (4403) is surfaced and not hammered', async () => {
    const { backend, ws, sockets } = await connected();
    ws.onclose?.({ code: 4403 });
    expect(backend.status().link).toBe('ORIGIN_REJECTED');
    await sleep(1400);
    expect(sockets).toHaveLength(1);
  });

  it('a 401 that survives the silent re-join clears the session and asks the user to join', async () => {
    const h = await connected();
    h.fail401();
    const r = await h.backend.getOperation('00000000-0000-4000-8000-000000000001');
    expect(r).toMatchObject({ ok: false, kind: 'http', status: 401 });
    expect(h.store.session).toBeNull();
    expect(h.backend.status()).toMatchObject({ enrolled: false, reenroll: true, link: 'NEEDS_ENROLL' });
  });

  it('enrollment keeps the token in the background store only', async () => {
    const h = harness({ enrolled: false });
    const r = await h.backend.enroll({ invite_code: 'FAKE-C0DE-2026', display_name: 'Alice', claimed_twitch_login: null });
    expect(r.ok).toBe(true);
    expect(JSON.stringify(r)).not.toContain('fzs_');
    expect(JSON.stringify(h.backend.status())).not.toContain('fzs_');
    expect(h.store.session?.token).toBe(TOKEN);
    h.backend.setDemand(1);
    await h.backend.getSnapshot();
    expect(JSON.stringify(h.backend.peekSnapshot())).not.toContain('fzs_');
  });

  it('redemptions stay CAPABILITY_UNAVAILABLE without a network call (top-ups: see live-topup.test.ts)', async () => {
    const h = harness();
    expect(await h.backend.redeem()).toMatchObject({ ok: false, status: 503, error: { error: { code: 'CAPABILITY_UNAVAILABLE' } } });
    expect(Object.keys(h.counts)).toHaveLength(0);
  });
});
