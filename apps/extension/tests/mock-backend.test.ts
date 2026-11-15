import { describe, expect, it } from 'vitest';
import { checkSnapshot, streamSnapshotV, validate, type StreamSnapshot, type WagerRequest } from '@fazetime/contracts';
import { MockBackend, type MockState } from '../src/mock/backend';
import { SNAPSHOT_FIXTURE_NAMES, SNAPSHOT_FIXTURES, ERROR_FIXTURES } from '../src/mock/fixtures';
import { DEMO_CATALOG } from '../src/mock/catalog';
import { PanelController, type KV, type PanelApi } from '../src/state/controller';

const uuid = (n: number) => `00000000-0000-4000-8000-${n.toString(16).padStart(12, '0')}`;

async function backendAt(fixture: string) {
  const b = new MockBackend();
  await b.fixtures.load(fixture);
  const snap = (await b.getSnapshot()) as { ok: true; body: StreamSnapshot };
  return { b, snap: snap.body };
}

function wager(snap: StreamSnapshot, over: Partial<WagerRequest> = {}): WagerRequest {
  return {
    operation_id: uuid(1),
    stream_session_id: snap.stream.stream_session_id,
    market_id: snap.market!.market_id,
    rules_version: snap.market!.rules_version,
    side: 'YES',
    amount_minor: 500,
    ...over,
  };
}

describe('fixtures loaded by the mock', () => {
  it('has every section 9.14 snapshot and every error code', () => {
    expect(Object.keys(SNAPSHOT_FIXTURES).sort()).toEqual([...SNAPSHOT_FIXTURE_NAMES].sort());
    expect(Object.keys(ERROR_FIXTURES)).toHaveLength(15);
  });
  it.each([...SNAPSHOT_FIXTURE_NAMES])('%s shifts to now and stays valid', async (name) => {
    const { snap } = await backendAt(name);
    expect(validate(streamSnapshotV, snap, { strict: true }).issues).toEqual([]);
    expect(checkSnapshot(snap)).toEqual([]);
    expect(Math.abs(Date.parse(snap.server_time_utc) - Date.now())).toBeLessThan(2000);
    if (snap.market?.state === 'OPEN') expect(Date.parse(snap.market.close_at_utc)).toBeGreaterThan(Date.now());
  });
});

describe('mock wager rules (CONTRACTS 9.6 / 9.7)', () => {
  it('accepts once, then replays the original receipt for the same key and body', async () => {
    const { b, snap } = await backendAt('open_no_position');
    const req = wager(snap);
    const first = await b.placeWager(req);
    expect(first).toMatchObject({ ok: true, status: 201, body: { replayed: false, status: 'ACCEPTED' } });
    const again = await b.placeWager(req);
    expect(again).toMatchObject({ ok: true, status: 200, body: { replayed: true } });
    if (first.ok && again.ok) expect(again.body.wager_id).toBe(first.body.wager_id);
    const after = (await b.getSnapshot()) as { ok: true; body: StreamSnapshot };
    expect(after.body.wallet.available_minor).toBe(snap.wallet.available_minor - 500); // Debited exactly once.
    expect(after.body.market!.pool.yes_minor).toBe(snap.market!.pool.yes_minor + 500);
    expect(after.body.market!.pool.total_minor).toBe(after.body.market!.pool.yes_minor + after.body.market!.pool.no_minor);
    expect(checkSnapshot(after.body)).toEqual([]);
  });

  it('same key with a different body is IDEMPOTENCY_CONFLICT with no effect', async () => {
    const { b, snap } = await backendAt('open_no_position');
    await b.placeWager(wager(snap));
    const r = await b.placeWager(wager(snap, { amount_minor: 1000 }));
    expect(r).toMatchObject({ ok: false, kind: 'http', status: 409, error: { error: { code: 'IDEMPOTENCY_CONFLICT' } } });
  });

  it('enforces one side per market, funds, limits, run, market and source', async () => {
    const { b, snap } = await backendAt('open_with_position');
    const code = async (r: Promise<unknown>) => ((await r) as { error?: { error: { code: string } } }).error?.error.code;
    expect(await code(b.placeWager(wager(snap, { operation_id: uuid(2), side: 'NO' })))).toBe('SIDE_CONFLICT');
    expect(await code(b.placeWager(wager(snap, { operation_id: uuid(3), amount_minor: 550 })))).toBe('INVALID_AMOUNT');
    expect(await code(b.placeWager(wager(snap, { operation_id: uuid(4), stream_session_id: 'run_00000000000000000000000000000009' })))).toBe('WRONG_RUN');
    expect(await code(b.placeWager(wager(snap, { operation_id: uuid(5), rules_version: 2 })))).toBe('STALE_MARKET');
    expect(await code(b.placeWager({ ...wager(snap, { operation_id: uuid(6) }), user_id: 'usr_x' } as WagerRequest))).toBe('VALIDATION_FAILED');
    const low = await backendAt('open_low_balance');
    expect(await code(low.b.placeWager(wager(low.snap)))).toBe('INSUFFICIENT_FUNDS');
    const stale = await backendAt('open_source_stale');
    expect(await code(stale.b.placeWager(wager(stale.snap)))).toBe('SOURCE_STALE');
    const locked = await backendAt('locked');
    expect(await code(locked.b.placeWager(wager(locked.snap)))).toBe('MARKET_CLOSED');
  });

  it('a simulated timeout commits once; the retry with the same key replays', async () => {
    const { b, snap } = await backendAt('open_no_position');
    await b.fixtures.armTimeout();
    const req = wager(snap);
    expect(await b.placeWager(req)).toMatchObject({ ok: false, kind: 'unknown' });
    expect(await b.placeWager(req)).toMatchObject({ ok: true, status: 200, body: { replayed: true } });
    const op = await b.getOperation(req.operation_id);
    expect(op.ok).toBe(true);
    const after = (await b.getSnapshot()) as { ok: true; body: StreamSnapshot };
    expect(after.body.wallet.available_minor).toBe(snap.wallet.available_minor - 500);
  });

  it('injected errors are one-shot typed rejections with no effect', async () => {
    const { b, snap } = await backendAt('open_no_position');
    await b.fixtures.injectError('INTERNAL_ERROR');
    expect(await b.placeWager(wager(snap))).toMatchObject({ ok: false, kind: 'http', status: 500, error: { error: { retryable: true } } });
    expect(await b.placeWager(wager(snap))).toMatchObject({ ok: true, status: 201 });
  });
});

describe('mock top-up and redeem', () => {
  it('top-up accepts presets/custom within limits, idempotently', async () => {
    const { b, snap } = await backendAt('open_low_balance');
    const r1 = await b.createTopUp({ operation_id: uuid(10), amount_minor: 1000 });
    expect(r1).toMatchObject({ ok: true, body: { status: 'MOCK_CREDITED', payment_mode: 'MOCK', wallet_after: { available_minor: snap.wallet.available_minor + 1000 } } });
    expect(await b.createTopUp({ operation_id: uuid(10), amount_minor: 1000 })).toMatchObject({ ok: true, body: { replayed: true } });
    expect(await b.createTopUp({ operation_id: uuid(11), amount_minor: 400 })).toMatchObject({ ok: false, error: { error: { code: 'INVALID_AMOUNT' } } });
    expect(await b.createTopUp({ operation_id: uuid(12), amount_minor: 2550 })).toMatchObject({ ok: false, error: { error: { code: 'INVALID_AMOUNT' } } });
    const after = (await b.getSnapshot()) as { ok: true; body: StreamSnapshot };
    expect(after.body.wallet.available_minor).toBe(snap.wallet.available_minor + 1000);
  });

  it('redeem debits once and returns the same NON-REDEEMABLE code on replay', async () => {
    const { b, snap } = await backendAt('no_market');
    const item = DEMO_CATALOG[0]!;
    const r1 = await b.redeem({ operation_id: uuid(20), item_id: item.item_id });
    const r2 = await b.redeem({ operation_id: uuid(20), item_id: item.item_id });
    expect(r1.ok && r2.ok).toBe(true);
    if (r1.ok && r2.ok) {
      expect(r1.body.demo_code).toMatch(/^DEMO-[A-Z2-9]{4}-[A-Z2-9]{4}$/);
      expect(r2.body.demo_code).toBe(r1.body.demo_code);
      expect(r1.body.non_redeemable).toBe(true);
    }
    const after = (await b.getSnapshot()) as { ok: true; body: StreamSnapshot };
    expect(after.body.wallet.available_minor).toBe(snap.wallet.available_minor - item.price_minor);
  });

  it('persists state so a service-worker restart keeps it', async () => {
    let saved: MockState | null = null;
    const persistence = { load: async () => saved, save: async (s: MockState) => void (saved = JSON.parse(JSON.stringify(s))) };
    const b1 = new MockBackend({ persistence });
    await b1.fixtures.load('open_no_position');
    const s1 = (await b1.getSnapshot()) as { ok: true; body: StreamSnapshot };
    await b1.placeWager(wager(s1.body));
    const b2 = new MockBackend({ persistence }); // "Restarted" worker.
    const s2 = (await b2.getSnapshot()) as { ok: true; body: StreamSnapshot };
    expect(s2.body.wallet.available_minor).toBe(s1.body.wallet.available_minor - 500);
    expect(await b2.placeWager(wager(s1.body))).toMatchObject({ ok: true, body: { replayed: true } });
  });
});

describe('PanelController over the mock (content-side flows)', () => {
  const memoryKV = (): KV & { data: Map<string, unknown> } => {
    const data = new Map<string, unknown>();
    return {
      data,
      get: async <T,>(k: string) => (data.has(k) ? (data.get(k) as T) : null),
      set: async <T,>(k: string, v: T) => void data.set(k, v),
      remove: async (k: string) => void data.delete(k),
    };
  };
  const asApi = (b: MockBackend): PanelApi => {
    const fx = b.fixtures;
    const ok = <T,>(body: T) => ({ ok: true as const, status: 200, body });
    return {
      getSnapshot: () => b.getSnapshot(),
      placeWager: (r) => b.placeWager(r),
      getOperation: (id) => b.getOperation(id),
      createTopUp: (r) => b.createTopUp(r),
      getCatalog: () => b.getCatalog(),
      redeem: (r) => b.redeem(r),
      connect: () => true,
      dispose: () => undefined,
      fixtures: {
        info: async () => ok(await fx.info()),
        load: async (n) => ok(await fx.load(n)),
        injectError: async (c) => ok(await fx.injectError(c)),
        armTimeout: async () => ok(await fx.armTimeout()),
      },
    };
  };

  it('success appears only with a receipt; timeout recovers via same-key retry', async () => {
    const b = new MockBackend();
    await b.fixtures.load('open_no_position');
    const kv = memoryKV();
    const c = new PanelController(asApi(b), kv);
    await c.refresh();
    await b.fixtures.armTimeout();
    await c.placeBet('YES', 500);
    expect(c.getState().bet.kind).toBe('unknown'); // Never "success" on a timeout.
    expect(kv.data.has('local:fazetime.pendingWager')).toBe(true);
    await new Promise((r) => setTimeout(r, 1100)); // First backoff is 1 s.
    expect(c.getState().bet).toMatchObject({ kind: 'accepted', receipt: { replayed: true } });
    expect(kv.data.has('local:fazetime.pendingWager')).toBe(false);
    await c.refresh();
    expect(c.getState().snapshot!.wallet.available_minor).toBe(1500); // 2000 - 500, once.
    c.dispose();
  });

  it('insufficient funds opens the top-up dialog without sending a wager', async () => {
    const b = new MockBackend();
    await b.fixtures.load('open_low_balance');
    const c = new PanelController(asApi(b), memoryKV());
    await c.refresh();
    await c.placeBet('YES', 500);
    expect(c.getState().topUp).toMatchObject({ open: true, reason: 'insufficient', neededMinor: 200 });
    expect(c.getState().bet.kind).toBe('idle');
    await c.submitTopUp(1000);
    expect(c.getState().topUp.status).toBe('credited');
    c.dispose();
  });

  it('a run change shows a notice', async () => {
    const b = new MockBackend();
    await b.fixtures.load('open_no_position');
    const c = new PanelController(asApi(b), memoryKV());
    await c.refresh();
    await c.loadFixture('run_reset');
    expect(c.getState().runNotice).toMatch(/new run started/i);
    c.dispose();
  });
});
