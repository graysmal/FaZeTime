// P1 MOCK adapter. Runs only in the background service worker and emulates the server's contract
// behaviour (CONTRACTS 9.6 check order, 9.7 idempotency, 9.10 errors) on local fixture data.
// It is clearly labelled MOCK everywhere; no network, no payment provider, no real money.
// State is persisted to storage.session so a service-worker restart does not lose it.

import {
  CUUID_PATTERN,
  AVAILABLE_BALANCE_MAX_MINOR,
  ERROR_CODES,
  FIXTURE_MARKET_ORIGINS,
  validate,
  wagerRequestV,
  type ErrorCode,
  type StreamSnapshot,
  type WagerReceipt,
  type WagerReceiptResponse,
  type WagerRequest,
} from '@fazetime/contracts';
import { httpError, unknownOutcome } from '../api/errors';
import type {
  ApiResult,
  BackendAdapter,
  FixtureControls,
  FixtureInfo,
  RedeemCatalog,
  RedemptionReceipt,
  RedemptionRequest,
  TopUpReceipt,
  TopUpRequest,
} from '../api/types';
import { checkStake, checkTopUp } from '../lib/money';
import { randomHex32 } from '../lib/ids';
import { DEMO_CATALOG, generateDemoCode } from './catalog';
import { DEFAULT_FIXTURE, ERROR_FIXTURES, isSnapshotFixtureName, loadSnapshotFixture, SNAPSHOT_FIXTURE_NAMES } from './fixtures';

type OpType = 'wager' | 'topup' | 'redeem';

export interface MockState {
  v: 1;
  fixture: string;
  snapshot: StreamSnapshot;
  /** Idempotency records: (single mock actor, operation_id) -> type, request hash, receipt. */
  ops: Record<string, { type: OpType; hash: string; receipt: unknown }>;
  injectedError: ErrorCode | null;
  timeoutArmed: boolean;
}

export interface MockPersistence {
  load(): Promise<MockState | null>;
  save(state: MockState): Promise<void>;
}

export interface MockBackendOptions {
  persistence?: MockPersistence;
  now?: () => number;
  latencyMs?: number;
}

/** Sorted-key JSON, the canonical request form hashed for idempotency (CONTRACTS 9.7). */
export function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`;
  if (value && typeof value === 'object')
    return `{${Object.keys(value)
      .sort()
      .map((k) => `${JSON.stringify(k)}:${canonicalJson((value as Record<string, unknown>)[k])}`)
      .join(',')}}`;
  return JSON.stringify(value);
}

const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

export class MockBackend implements BackendAdapter {
  readonly mode = 'MOCK' as const;
  readonly fixtures: FixtureControls;
  private state!: MockState;
  private readonly listeners = new Set<() => void>();
  private readonly ready: Promise<void>;
  private readonly now: () => number;
  private chain: Promise<unknown> = Promise.resolve();

  constructor(private readonly opts: MockBackendOptions = {}) {
    this.now = opts.now ?? (() => Date.now());
    this.ready = this.init();
    this.fixtures = {
      info: async () => {
        await this.ready;
        return this.info();
      },
      load: (name) =>
        this.serial(async () => {
          if (!isSnapshotFixtureName(name)) return this.info();
          this.state.fixture = name;
          this.state.snapshot = loadSnapshotFixture(name, this.now());
          await this.commit();
          return this.info();
        }),
      injectError: (code) =>
        this.serial(async () => {
          this.state.injectedError = code;
          await this.persist();
          return this.info();
        }),
      armTimeout: () =>
        this.serial(async () => {
          this.state.timeoutArmed = true;
          await this.persist();
          return this.info();
        }),
    };
  }

  private async init(): Promise<void> {
    const saved = await this.opts.persistence?.load().catch(() => null);
    if (saved && saved.v === 1 && saved.snapshot) {
      this.state = saved;
      return;
    }
    this.state = {
      v: 1,
      fixture: DEFAULT_FIXTURE,
      snapshot: loadSnapshotFixture(DEFAULT_FIXTURE, this.now()),
      ops: {},
      injectedError: null,
      timeoutArmed: false,
    };
  }

  /** One mutation at a time, like a single database writer. */
  private serial<T>(fn: () => Promise<T>): Promise<T> {
    const run = this.chain.then(async () => {
      await this.ready;
      return fn();
    });
    this.chain = run.catch(() => undefined);
    return run;
  }

  private info(): FixtureInfo {
    return {
      names: [...SNAPSHOT_FIXTURE_NAMES],
      current: this.state.fixture,
      injectedError: this.state.injectedError,
      timeoutArmed: this.state.timeoutArmed,
      errorCodes: [...ERROR_CODES],
    };
  }

  private async persist(): Promise<void> {
    await this.opts.persistence?.save(this.state).catch(() => undefined);
  }

  private async commit(): Promise<void> {
    await this.persist();
    for (const l of [...this.listeners]) l();
  }

  private async latency(): Promise<void> {
    const ms = this.opts.latencyMs ?? 0;
    if (ms > 0) await new Promise((r) => setTimeout(r, ms));
  }

  onChange(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  async getSnapshot(): Promise<ApiResult<StreamSnapshot>> {
    await this.ready;
    const body = clone(this.state.snapshot);
    body.server_time_utc = new Date(this.now()).toISOString();
    return { ok: true, status: 200, body };
  }

  /** Consume a one-shot injected error (dev Fixture menu): a typed rejection with no effect. */
  private takeInjectedError<T>(operationId: string | null): ApiResult<T> | null {
    const code = this.state.injectedError;
    if (!code) return null;
    this.state.injectedError = null;
    const fixture = ERROR_FIXTURES[code];
    if (!fixture) return httpError(code, `Injected ${code} (MOCK).`, { operation_id: operationId });
    const env = clone(fixture);
    env.error.operation_id = env.error.operation_id === null ? null : operationId;
    env.server_time_utc = new Date(this.now()).toISOString();
    return httpError<T>(code, env.error.message, {
      operation_id: env.error.operation_id,
      details: env.error.details as Record<string, unknown> | null,
      retry_after_ms: env.error.retry_after_ms,
      now: this.now(),
    });
  }

  private replayOrConflict<T>(operationId: string, type: OpType, hash: string, replay: (r: T) => T): ApiResult<T> | null {
    const prior = this.state.ops[operationId];
    if (!prior) return null;
    if (prior.type === type && prior.hash === hash) return { ok: true, status: 200, body: replay(clone(prior.receipt as T)) };
    return httpError('IDEMPOTENCY_CONFLICT', 'This operation_id was already used with a different request.', { operation_id: operationId });
  }

  placeWager(req: WagerRequest): Promise<ApiResult<WagerReceiptResponse>> {
    return this.serial(async () => {
      await this.latency();
      const snap = this.state.snapshot;
      const limits = snap.limits;
      // Before the transaction: validation (extra=forbid, so user_id fails), then INVALID_AMOUNT.
      const checked = validate(wagerRequestV, req);
      if (!checked.ok) {
        const amountOnly = checked.issues.every((i) => i.path === '$.amount_minor');
        if (!amountOnly)
          return httpError('VALIDATION_FAILED', 'The wager request is invalid.', {
            operation_id: typeof req?.operation_id === 'string' ? req.operation_id : null,
            details: { fields: checked.issues.map((i) => ({ loc: i.path.replace(/^\$\.?/, 'body.').split('.'), msg: i.message })) },
          });
      }
      const amountDetails = { min_minor: limits.stake_min_minor, max_minor: limits.stake_max_minor, step_minor: limits.stake_step_minor };
      if (checkStake(Number.isSafeInteger(req.amount_minor) ? req.amount_minor : null, limits))
        return httpError('INVALID_AMOUNT', 'The stake is outside the published limits.', { operation_id: req.operation_id, details: amountDetails });

      const injected = this.takeInjectedError<WagerReceiptResponse>(req.operation_id);
      if (injected) {
        await this.persist();
        return injected;
      }

      // Inside the (emulated) BEGIN IMMEDIATE, in CONTRACTS 9.6 order.
      const hash = canonicalJson(req);
      const replay = this.replayOrConflict<WagerReceiptResponse>(req.operation_id, 'wager', hash, (r) => ({ ...r, replayed: true }));
      if (replay) return replay;
      if (req.stream_session_id !== snap.stream.stream_session_id)
        return httpError('WRONG_RUN', 'A new demo run has started.', {
          operation_id: req.operation_id,
          details: { current_stream_session_id: snap.stream.stream_session_id },
        });
      const m = snap.market;
      if (!m || m.market_id !== req.market_id || m.rules_version !== req.rules_version)
        return httpError('STALE_MARKET', 'The market changed or is unknown.', {
          operation_id: req.operation_id,
          details: { current_market_id: m?.market_id ?? null, current_rules_version: m?.rules_version ?? null },
        });
      const closedDetails = (reason: 'DEADLINE' | 'STATE' | 'PAUSED') => ({ state: m.state, close_at_utc: m.close_at_utc, reason });
      if (m.state !== 'OPEN')
        return httpError('MARKET_CLOSED', 'The market is not open.', { operation_id: req.operation_id, details: closedDetails('STATE') });
      if (this.now() >= Date.parse(m.close_at_utc))
        return httpError('MARKET_CLOSED', 'Betting closed at the deadline.', { operation_id: req.operation_id, details: closedDetails('DEADLINE') });
      if (snap.stream.wagering_paused && snap.stream.wagering_paused_reason === 'OPERATOR_PAUSE')
        return httpError('MARKET_CLOSED', 'Wagering is paused.', { operation_id: req.operation_id, details: closedDetails('PAUSED') });
      const twitchOrigin = !(FIXTURE_MARKET_ORIGINS as readonly string[]).includes(m.origin);
      if (twitchOrigin && snap.source_health.state !== 'LIVE')
        return httpError('SOURCE_STALE', 'The stream source is not live.', {
          operation_id: req.operation_id,
          details: { source_state: snap.source_health.state },
        });
      const pos = snap.my_position;
      if (pos?.side && pos.side !== req.side)
        return httpError('SIDE_CONFLICT', 'You already backed the other side.', { operation_id: req.operation_id, details: { existing_side: pos.side } });
      if (snap.wallet.available_minor < req.amount_minor)
        return httpError('INSUFFICIENT_FUNDS', 'Not enough demo funds.', {
          operation_id: req.operation_id,
          details: { available_minor: snap.wallet.available_minor, requested_minor: req.amount_minor },
        });

      // Accept: debit available, credit escrow (pool), insert the wager, bump versions.
      const amount = req.amount_minor;
      if (req.side === 'YES') m.pool.yes_minor += amount;
      else m.pool.no_minor += amount;
      m.pool.total_minor = m.pool.yes_minor + m.pool.no_minor;
      m.pool.wager_count += 1;
      m.aggregate_version += 1;
      const w = snap.wallet;
      w.available_minor -= amount;
      w.in_play_minor += amount;
      w.balance_version += 1;
      const receipt: WagerReceipt = {
        wager_id: `wgr_${randomHex32()}`,
        operation_id: req.operation_id,
        stream_session_id: req.stream_session_id,
        market_id: m.market_id,
        rules_version: m.rules_version,
        side: req.side,
        amount_minor: amount,
        status: 'ACCEPTED',
        accepted_at_utc: new Date(this.now()).toISOString(),
        terminal_at_utc: null,
        stake_txn_id: `txn_${randomHex32()}`,
        terminal_txn_id: null,
        payout_minor: null,
        refund_minor: null,
        market_aggregate_version: m.aggregate_version,
        wallet_after: clone(w),
        replayed: false,
      };
      const position = snap.my_position ?? {
        market_id: m.market_id,
        side: null,
        stake_total_minor: 0,
        result: 'NONE' as const,
        payout_total_minor: null,
        refund_total_minor: null,
        wagers: [],
      };
      position.side = req.side;
      position.stake_total_minor += amount;
      position.result = 'PENDING';
      position.wagers.push(receipt);
      snap.my_position = position;
      snap.event_hwm += 2;
      const body: WagerReceiptResponse = { schema_version: 1, ...receipt };
      this.state.ops[req.operation_id] = { type: 'wager', hash, receipt: body };
      const simulateTimeout = this.state.timeoutArmed;
      this.state.timeoutArmed = false;
      await this.commit();
      if (simulateTimeout) return unknownOutcome('Simulated timeout (MOCK): the bet may or may not have been accepted.');
      return { ok: true, status: 201, body };
    });
  }

  async getOperation(operationId: string): Promise<ApiResult<WagerReceiptResponse>> {
    await this.ready;
    const op = this.state.ops[operationId];
    if (!op || op.type !== 'wager') return httpError('NOT_FOUND', 'No such operation for this user.');
    // Section 9.15(7): lookups return the stored original receipt with replayed: true.
    return { ok: true, status: 200, body: { ...clone(op.receipt as WagerReceiptResponse), replayed: true } };
  }

  createTopUp(req: TopUpRequest): Promise<ApiResult<TopUpReceipt>> {
    return this.serial(async () => {
      await this.latency();
      const limits = this.state.snapshot.limits;
      if (typeof req?.operation_id !== 'string' || !CUUID_PATTERN.test(req.operation_id))
        return httpError('VALIDATION_FAILED', 'operation_id must be a lowercase UUID.', {
          details: { fields: [{ loc: ['body', 'operation_id'], msg: 'invalid' }] },
        });
      const details = { min_minor: limits.topup_min_minor, max_minor: limits.topup_max_minor, step_minor: limits.topup_step_minor };
      if (checkTopUp(Number.isSafeInteger(req.amount_minor) ? req.amount_minor : null, limits))
        return httpError('INVALID_AMOUNT', 'Top-up amount is outside the published limits.', { operation_id: req.operation_id, details });
      const injected = this.takeInjectedError<TopUpReceipt>(req.operation_id);
      if (injected) {
        await this.persist();
        return injected;
      }
      const hash = canonicalJson({ amount_minor: req.amount_minor, operation_id: req.operation_id });
      const replay = this.replayOrConflict<TopUpReceipt>(req.operation_id, 'topup', hash, (r) => ({ ...r, replayed: true }));
      if (replay) return replay;
      const w = this.state.snapshot.wallet;
      if (w.available_minor + req.amount_minor > AVAILABLE_BALANCE_MAX_MINOR)
        return httpError('INVALID_AMOUNT', 'That would exceed the demo balance cap.', { operation_id: req.operation_id, details });
      w.available_minor += req.amount_minor;
      w.balance_version += 1;
      this.state.snapshot.event_hwm += 1;
      const receipt: TopUpReceipt = {
        schema_version: 1,
        topup_id: `mock_${randomHex32()}`,
        operation_id: req.operation_id,
        amount_minor: req.amount_minor,
        status: 'MOCK_CREDITED',
        payment_mode: 'MOCK',
        wallet_after: clone(w),
        replayed: false,
      };
      this.state.ops[req.operation_id] = { type: 'topup', hash, receipt };
      await this.commit();
      return { ok: true, status: 201, body: receipt };
    });
  }

  async getCatalog(): Promise<ApiResult<RedeemCatalog>> {
    return { ok: true, status: 200, body: { schema_version: 1, label: 'DEMO_ONLY_NOT_REDEEMABLE', items: clone([...DEMO_CATALOG]) } };
  }

  redeem(req: RedemptionRequest): Promise<ApiResult<RedemptionReceipt>> {
    return this.serial(async () => {
      await this.latency();
      if (typeof req?.operation_id !== 'string' || !CUUID_PATTERN.test(req.operation_id))
        return httpError('VALIDATION_FAILED', 'operation_id must be a lowercase UUID.', {
          details: { fields: [{ loc: ['body', 'operation_id'], msg: 'invalid' }] },
        });
      const item = DEMO_CATALOG.find((i) => i.item_id === req.item_id);
      if (!item) return httpError('NOT_FOUND', 'No such demo catalog item.');
      const hash = canonicalJson({ item_id: req.item_id, operation_id: req.operation_id });
      const replay = this.replayOrConflict<RedemptionReceipt>(req.operation_id, 'redeem', hash, (r) => ({ ...r, replayed: true }));
      if (replay) return replay;
      const w = this.state.snapshot.wallet;
      if (w.available_minor < item.price_minor)
        return httpError('INSUFFICIENT_FUNDS', 'Not enough demo funds.', {
          operation_id: req.operation_id,
          details: { available_minor: w.available_minor, requested_minor: item.price_minor },
        });
      w.available_minor -= item.price_minor;
      w.balance_version += 1;
      this.state.snapshot.event_hwm += 1;
      const receipt: RedemptionReceipt = {
        schema_version: 1,
        redemption_id: `mock_${randomHex32()}`,
        operation_id: req.operation_id,
        item_id: item.item_id,
        price_minor: item.price_minor,
        demo_code: generateDemoCode(),
        non_redeemable: true,
        wallet_after: clone(w),
        replayed: false,
      };
      this.state.ops[req.operation_id] = { type: 'redeem', hash, receipt };
      await this.commit();
      return { ok: true, status: 201, body: receipt };
    });
  }
}
