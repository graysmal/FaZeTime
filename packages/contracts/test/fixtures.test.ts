// Validates every packages/contracts/fixtures/v1 file against the hand-written v1 types (runtime
// validators in strict mode) and the CONTRACTS section 9.14 invariants.

import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  AVAILABLE_BALANCE_MAX_MINOR,
  BANNERS,
  CUUID_PATTERN,
  ERROR_CODES,
  ERROR_HTTP_STATUS,
  EVENT_TYPES,
  ID_PREFIXES,
  MINOR_MAX,
  RETRYABLE_ERROR_CODES,
  TERMINAL_BANNER_BY_RESULT,
  UTC_PATTERN,
  bannerFor,
  checkMarket,
  checkSnapshot,
  checkStakeAmount,
  domainEventV,
  enrollRequestV,
  enrollResponseV,
  errorEnvelopeV,
  meResponseV,
  operatorMarketDraftV,
  presenceAckV,
  presenceHeartbeatV,
  publicMarketV,
  streamSnapshotV,
  validate,
  wagerReceiptResponseV,
  wagerRequestV,
  wsTicketResponseV,
  type DomainEvent,
  type ErrorEnvelope,
  type PublicMarket,
  type StreamSnapshot,
  type V,
  type WagerReceiptResponse,
  type WagerRequest,
} from '../src';

const ROOT = join(__dirname, '..', 'fixtures', 'v1');
const FIXED_TIME = '2026-11-14T20:00:00.000Z';

function listFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name);
    return statSync(full).isDirectory() ? listFiles(full) : [relative(ROOT, full).replace(/\\/g, '/')];
  });
}
const files = listFiles(ROOT).sort();
const load = (rel: string): any => JSON.parse(readFileSync(join(ROOT, rel), 'utf8'));
const fixtures = new Map(files.map((f) => [f.replace(/\.json$/, ''), load(f)]));
const get = <T = any>(name: string): T => {
  const v = fixtures.get(name);
  if (v === undefined) throw new Error(`missing fixture ${name}`);
  return v as T;
};

const SNAPSHOTS = [
  'no_market',
  'open_no_position',
  'open_with_position',
  'open_empty_pool',
  'open_one_sided',
  'open_low_balance',
  'open_source_stale',
  'locked',
  'evaluating',
  'settled_win',
  'settled_loss',
  'settled_no_position',
  'void_one_sided',
  'void_empty',
  'void_source_gap',
  'void_resolution_timeout',
  'void_unresolvable',
  'run_reset',
];
const errorFileName = (code: string) => code.toLowerCase();
const eventFileName = (type: string) => type.replace('.', '_');

const REQUIRED = [
  ...SNAPSHOTS.map((s) => `snapshot/${s}`),
  'operator/market_draft',
  'me/viewer_funded',
  'me/viewer_low_balance',
  'enroll/request',
  'enroll/response',
  'ws/ticket_response',
  'presence/heartbeat',
  'presence/ack',
  'wager/request',
  'wager/receipt_accepted',
  'wager/receipt_replayed',
  'wager/request_conflict',
  ...ERROR_CODES.map((c) => `error/${errorFileName(c)}`),
  ...EVENT_TYPES.map((t) => `event/${eventFileName(t)}`),
  'event/sequence_reorder_duplicate',
  'domain/settlement_worked_example',
];

const VALIDATOR_BY_DIR: Record<string, V<any> | undefined> = {
  snapshot: streamSnapshotV,
  me: meResponseV,
  error: errorEnvelopeV,
  event: domainEventV,
};
const VALIDATOR_BY_NAME: Record<string, V<any>> = {
  'operator/market_draft': operatorMarketDraftV,
  'enroll/request': enrollRequestV,
  'enroll/response': enrollResponseV,
  'ws/ticket_response': wsTicketResponseV,
  'presence/heartbeat': presenceHeartbeatV,
  'presence/ack': presenceAckV,
  'wager/request': wagerRequestV,
  'wager/request_conflict': wagerRequestV,
  'wager/receipt_accepted': wagerReceiptResponseV,
  'wager/receipt_replayed': wagerReceiptResponseV,
};

/** Walk every (key, value) pair in a JSON tree. */
function walk(node: unknown, visit: (key: string, value: unknown, path: string, parent: any) => void, path = '$'): void {
  if (Array.isArray(node)) node.forEach((v, i) => walk(v, visit, `${path}[${i}]`));
  else if (node && typeof node === 'object')
    for (const [k, v] of Object.entries(node)) {
      visit(k, v, `${path}.${k}`, node);
      walk(v, visit, `${path}.${k}`);
    }
}
const SERVER_ID = new RegExp(`^(${ID_PREFIXES.join('|')})_[0-9a-f]{32}$`);

describe('fixture set (CONTRACTS 9.14)', () => {
  it('contains exactly the required files', () => {
    expect(files.map((f) => f.replace(/\.json$/, '')).sort()).toEqual([...REQUIRED].sort());
  });

  it('has one error file per error code and one event file per event type', () => {
    expect(ERROR_CODES.length).toBe(15);
    for (const code of ERROR_CODES) expect(get<ErrorEnvelope>(`error/${errorFileName(code)}`).error.code).toBe(code);
    for (const type of EVENT_TYPES) expect(get<DomainEvent>(`event/${eventFileName(type)}`).event_type).toBe(type);
  });
});

describe.each(REQUIRED.filter((n) => n !== 'event/sequence_reorder_duplicate' && n !== 'domain/settlement_worked_example'))(
  'schema: %s',
  (name) => {
    it('validates strictly against the v1 type', () => {
      const validator = VALIDATOR_BY_NAME[name] ?? VALIDATOR_BY_DIR[name.split('/')[0]];
      expect(validator, `no validator for ${name}`).toBeDefined();
      const result = validate(validator!, get(name), { strict: true });
      expect(result.issues).toEqual([]);
    });
  },
);

describe('generic invariants on every fixture', () => {
  it.each(files)('%s', (file) => {
    const name = file.replace(/\.json$/, '');
    const body = get(name);
    const problems: string[] = [];
    walk(body, (key, value, path, parent) => {
      if (key.endsWith('_minor') && typeof value === 'number' && !(Number.isSafeInteger(value) && value >= 0 && value <= MINOR_MAX))
        problems.push(`${path}: ${value} is not an integer within 0..${MINOR_MAX}`);
      if (key.endsWith('_utc') && value !== null) {
        if (typeof value !== 'string' || !UTC_PATTERN.test(value) || new Date(value).toISOString() !== value)
          problems.push(`${path}: bad UTC ${value}`);
      }
      if (key === 'server_time_utc' && value !== FIXED_TIME) problems.push(`${path}: server time must be the fixed time`);
      if ((key.endsWith('_id') || key === 'source_epoch') && typeof value === 'string') {
        const isUuidKey = key === 'operation_id' || key === 'device_id' || key === 'tab_instance_id';
        if (isUuidKey ? !CUUID_PATTERN.test(value) : !SERVER_ID.test(value)) problems.push(`${path}: bad ID ${value}`);
      }
      if (key.endsWith('stream_session_id') && typeof value === 'string' && !value.startsWith('run_'))
        problems.push(`${path}: stream_session_id must be a run_ ID`);
      if (key === 'event_id' && !(Number.isSafeInteger(value) && (value as number) >= 1)) problems.push(`${path}: event_id must be positive`);
      if (key === 'state' && value === 'DRAFT' && !name.startsWith('operator/')) problems.push(`${path}: DRAFT in a viewer payload`);
      if (key === 'total_minor' && parent && 'yes_minor' in parent && parent.total_minor !== parent.yes_minor + parent.no_minor)
        problems.push(`${path}: total != yes + no`);
      if (key === 'available_minor' && typeof value === 'number' && value > AVAILABLE_BALANCE_MAX_MINOR)
        problems.push(`${path}: available above ${AVAILABLE_BALANCE_MAX_MINOR}`);
      if (key === 'amount_minor' && typeof value === 'number') {
        const problem = checkStakeAmount(value, get('snapshot/open_no_position').limits);
        if (problem) problems.push(`${path}: ${problem}`);
      }
      if (/phone/i.test(key)) problems.push(`${path}: phone fields are forbidden (D16)`);
      if (typeof value === 'string' && /^(fzs|fzw)_/.test(value) && !value.includes('PLACEHOLDER')) problems.push(`${path}: token is not a placeholder`);
    });
    // Market-shaped objects anywhere (snapshots, events, sequences, operator draft).
    walk(body, (key, value, path) => {
      if ((key === 'market' || key === 'payload' || key === 'expected_final_market') && value && typeof value === 'object' && 'pool' in (value as object)) {
        for (const issue of checkMarket(value as PublicMarket, path, { viewer: true })) problems.push(`${issue.path}: ${issue.message}`);
      }
    });
    expect(problems).toEqual([]);
  });

  it('requests carry no schema_version or user_id (extra=forbid)', () => {
    for (const name of ['wager/request', 'wager/request_conflict', 'enroll/request', 'presence/heartbeat']) {
      expect(get(name)).not.toHaveProperty('schema_version');
      expect(get(name)).not.toHaveProperty('user_id');
    }
  });
});

describe('snapshot invariants', () => {
  it.each(SNAPSHOTS)('%s is internally consistent', (name) => {
    const snap = get<StreamSnapshot>(`snapshot/${name}`);
    expect(checkSnapshot(snap)).toEqual([]);
    expect(snap.modes).toEqual({ ai_mode: 'FIXTURE', payment_mode: 'MOCK', media_source_kind: 'TEST_FIXTURE' });
    expect(snap.limits).toEqual({
      stake_min_minor: 100,
      stake_max_minor: 50000,
      stake_step_minor: 100,
      stake_default_minor: 500,
      topup_presets_minor: [500, 1000, 5000],
      topup_min_minor: 500,
      topup_max_minor: 10000,
      topup_step_minor: 100,
    });
  });

  const EXPECTED_BANNER: Record<string, string | null> = {
    no_market: null,
    open_no_position: null,
    open_with_position: null,
    open_empty_pool: null,
    open_one_sided: null,
    open_low_balance: null,
    open_source_stale: null,
    locked: null,
    evaluating: null,
    settled_win: 'WIN',
    settled_loss: 'LOSS',
    settled_no_position: 'NEUTRAL',
    void_one_sided: 'VOID_REFUNDED',
    void_empty: 'NEUTRAL',
    void_source_gap: 'VOID_REFUNDED',
    void_resolution_timeout: 'UNRESOLVED_REFUNDED',
    void_unresolvable: 'UNRESOLVED_REFUNDED',
    run_reset: null,
  };

  it.each(SNAPSHOTS)('%s maps to the expected banner (exactly one per terminal fixture)', (name) => {
    const snap = get<StreamSnapshot>(`snapshot/${name}`);
    const banner = bannerFor(snap.market, snap.my_position);
    expect(banner).toBe(EXPECTED_BANNER[name]);
    const terminal = snap.market !== null && (snap.market.state === 'SETTLED' || snap.market.state === 'VOID');
    if (terminal) {
      const matches = BANNERS.filter((b) => TERMINAL_BANNER_BY_RESULT[snap.my_position!.result as keyof typeof TERMINAL_BANNER_BY_RESULT] === b);
      expect(matches).toHaveLength(1);
    } else {
      expect(banner).toBeNull();
    }
  });

  it('covers every banner and every viewer market state', () => {
    const banners = new Set(SNAPSHOTS.map((n) => bannerFor(get(`snapshot/${n}`).market, get(`snapshot/${n}`).my_position)).filter(Boolean));
    expect([...banners].sort()).toEqual([...BANNERS].sort());
    const states = new Set(SNAPSHOTS.map((n) => get<StreamSnapshot>(`snapshot/${n}`).market?.state).filter(Boolean));
    expect([...states].sort()).toEqual(['EVALUATING', 'LOCKED', 'OPEN', 'SETTLED', 'VOID']);
  });

  it('run_reset describes a new run with a fresh seeded wallet and no market', () => {
    const before = get<StreamSnapshot>('snapshot/open_no_position');
    const after = get<StreamSnapshot>('snapshot/run_reset');
    expect(after.stream.stream_session_id).not.toBe(before.stream.stream_session_id);
    expect(after.market).toBeNull();
    expect(after.wallet.stream_session_id).toBe(after.stream.stream_session_id);
    const voided = get<DomainEvent<PublicMarket>>('event/market_voided');
    expect(voided.payload.void_reason).toBe('RUN_RESET');
    expect(voided.stream_session_id).toBe(before.stream.stream_session_id);
  });

  it('open_source_stale is a Twitch-origin market with a non-LIVE source (SOURCE_STALE applies)', () => {
    const snap = get<StreamSnapshot>('snapshot/open_source_stale');
    expect(['AI_APPROVED', 'AI_AUTOMATIC']).toContain(snap.market!.origin);
    expect(snap.source_health.state).toBe('STALE');
  });

  it('open_low_balance cannot afford the default stake', () => {
    const snap = get<StreamSnapshot>('snapshot/open_low_balance');
    expect(snap.wallet.available_minor).toBeLessThan(snap.limits.stake_default_minor);
  });
});

describe('wagers and idempotency fixtures', () => {
  const req = get<WagerRequest>('wager/request');
  const accepted = get<WagerReceiptResponse>('wager/receipt_accepted');
  const replayed = get<WagerReceiptResponse>('wager/receipt_replayed');
  const conflict = get<WagerRequest>('wager/request_conflict');

  it('receipt matches its request', () => {
    for (const k of ['operation_id', 'stream_session_id', 'market_id', 'rules_version', 'side', 'amount_minor'] as const)
      expect(accepted[k]).toBe(req[k]);
    expect(accepted.status).toBe('ACCEPTED');
    expect(accepted.replayed).toBe(false);
  });

  it('replay returns the original receipt with replayed=true', () => {
    expect({ ...replayed, replayed: false }).toEqual(accepted);
    expect(replayed.replayed).toBe(true);
  });

  it('request_conflict reuses the key with a different body', () => {
    expect(conflict.operation_id).toBe(req.operation_id);
    expect(conflict).not.toEqual(req);
    expect(get<ErrorEnvelope>('error/idempotency_conflict').error.operation_id).toBe(req.operation_id);
  });

  it('rejects a request that smuggles user_id or a fractional amount', () => {
    expect(validate(wagerRequestV, { ...req, user_id: 'usr_00000000000000000000000000000001' }).ok).toBe(false);
    expect(validate(wagerRequestV, { ...req, amount_minor: 500.5 }).ok).toBe(false);
    expect(validate(wagerRequestV, { ...req, operation_id: req.operation_id.toUpperCase() }).ok).toBe(false);
  });
});

describe('error fixtures (CONTRACTS 9.10)', () => {
  it.each([...ERROR_CODES])('%s has an HTTP status and correct retryability', (code) => {
    const env = get<ErrorEnvelope>(`error/${errorFileName(code)}`);
    expect(ERROR_HTTP_STATUS[code]).toBeGreaterThanOrEqual(400);
    expect(env.error.retryable).toBe((RETRYABLE_ERROR_CODES as readonly string[]).includes(code));
    if (code === 'RATE_LIMITED') expect(env.error.retry_after_ms).toBeGreaterThan(0);
  });
});

describe('event fixtures', () => {
  it.each(EVENT_TYPES.map(eventFileName))('%s versions agree with its payload', (file) => {
    const ev = get<DomainEvent<any>>(`event/${file}`);
    if (ev.aggregate_type === 'MARKET') {
      expect(ev.aggregate_version).toBe(ev.payload.aggregate_version);
      expect(ev.aggregate_id).toBe(ev.payload.market_id);
    }
    if (ev.aggregate_type === 'STREAM') expect(ev.aggregate_version).toBe(ev.payload.stream.aggregate_version);
    if (ev.aggregate_type === 'WALLET') expect(ev.aggregate_version).toBe(ev.payload.balance_version);
    if (ev.aggregate_type === 'WAGER') expect(ev.aggregate_id).toBe(ev.payload.wager_id);
    expect(ev.audience).toBe(ev.aggregate_type === 'WAGER' || ev.aggregate_type === 'WALLET' ? 'USER' : 'PUBLIC');
  });

  it('sequence_reorder_duplicate: keep-highest-version yields the expected final state', () => {
    const seq = get('event/sequence_reorder_duplicate');
    for (const e of seq.delivered) expect(validate(domainEventV, e, { strict: true }).issues).toEqual([]);
    expect(validate(publicMarketV, seq.expected_final_market, { strict: true }).issues).toEqual([]);
    let highest = seq.initial_market_aggregate_version as number;
    let state: PublicMarket | null = null;
    const applied = seq.delivered.map((e: DomainEvent<PublicMarket>) => {
      if (e.aggregate_version <= highest) return false;
      highest = e.aggregate_version;
      state = e.payload;
      return true;
    });
    expect(applied).toEqual(seq.expected_applied);
    expect(state).toEqual(seq.expected_final_market);
  });
});

describe('domain/settlement_worked_example (ECONOMICS 4)', () => {
  // Test-only reference arithmetic to check the fixture's numbers. The backend owns settlement.
  it('floor payouts plus remainder cents reproduce the expected numbers', () => {
    const ex = get('domain/settlement_worked_example');
    const winners = ex.wagers.filter((w: any) => w.side === ex.winning_side);
    const T = ex.wagers.reduce((s: number, w: any) => s + w.amount_minor, 0);
    const W = winners.reduce((s: number, w: any) => s + w.amount_minor, 0);
    expect(T).toBe(ex.expected.total_minor);
    expect(T).toBe(ex.pool.total_minor);
    expect(W).toBe(ex.expected.winning_total_minor);
    const rows = winners.map((w: any) => ({
      wager_id: w.wager_id,
      amount: w.amount_minor,
      initial: Number((BigInt(w.amount_minor) * BigInt(T)) / BigInt(W)),
      remainder: Number((BigInt(w.amount_minor) * BigInt(T)) % BigInt(W)),
    }));
    const initialSum = rows.reduce((s: number, r: any) => s + r.initial, 0);
    expect(initialSum).toBe(ex.expected.initial_payout_sum_minor);
    let left = T - initialSum;
    expect(left).toBe(ex.expected.unallocated_minor);
    const order = [...rows].sort((a, b) => b.remainder - a.remainder || (a.wager_id < b.wager_id ? -1 : a.wager_id > b.wager_id ? 1 : 0));
    const extra = new Map<string, number>();
    for (const r of order) {
      if (left === 0) break;
      extra.set(r.wager_id, 1);
      left -= 1;
    }
    const finals = rows.map((r: any) => ({
      wager_id: r.wager_id,
      initial_payout_minor: r.initial,
      remainder_numerator: r.remainder,
      final_payout_minor: r.initial + (extra.get(r.wager_id) ?? 0),
      net_profit_minor: r.initial + (extra.get(r.wager_id) ?? 0) - r.amount,
    }));
    expect(finals).toEqual(ex.expected.payouts);
    expect(finals.reduce((s: number, r: any) => s + r.final_payout_minor, 0)).toBe(ex.expected.final_payout_sum_minor);
    expect(ex.expected.final_payout_sum_minor).toBe(T);
    expect(ex.fee_minor).toBe(0);
  });
});

describe('validators reject malformed input', () => {
  it('rejects timestamps without three fractional digits or Z', () => {
    const snap = structuredClone(get<StreamSnapshot>('snapshot/no_market'));
    snap.server_time_utc = '2026-11-14T20:00:00Z';
    expect(validate(streamSnapshotV, snap).ok).toBe(false);
    snap.server_time_utc = '2026-11-14T20:00:00.000+00:00';
    expect(validate(streamSnapshotV, snap).ok).toBe(false);
  });

  it('rejects unknown enum values and DRAFT in viewer invariants', () => {
    const snap = structuredClone(get<StreamSnapshot>('snapshot/open_no_position'));
    (snap.market as any).state = 'PAUSED';
    expect(validate(streamSnapshotV, snap).ok).toBe(false);
    (snap.market as any).state = 'DRAFT';
    expect(checkMarket(snap.market!, 'market', { viewer: true }).some((i) => i.message.includes('DRAFT'))).toBe(true);
  });

  it('lenient mode ignores unknown fields; strict mode reports them', () => {
    const snap = { ...structuredClone(get('snapshot/no_market')), future_field: 1 };
    expect(validate(streamSnapshotV, snap).ok).toBe(true);
    expect(validate(streamSnapshotV, snap, { strict: true }).ok).toBe(false);
  });

  it('rejects a pool whose total is not yes + no', () => {
    const snap = structuredClone(get<StreamSnapshot>('snapshot/open_no_position'));
    snap.market!.pool.total_minor += 1;
    expect(checkSnapshot(snap).some((i) => i.message.includes('total_minor'))).toBe(true);
  });
});
