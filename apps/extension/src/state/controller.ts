// Content-side view store. Holds the latest authoritative snapshot from the background, the bet /
// top-up / redeem flows, and dev fixture info. The backend (P1: background MOCK) stays authoritative:
// nothing here changes balances; it only renders what receipts and snapshots say.

import {
  checkSnapshot,
  streamSnapshotV,
  validate,
  type ErrorCode,
  type Side,
  type StreamSnapshot,
  type WagerReceiptResponse,
  type WagerRequest,
} from '@fazetime/contracts';
import type { PushMessage } from '../api/protocol';
import {
  isTopUpTracking,
  TOPUP_ID_PATTERN,
  type ApiResult,
  type BackgroundStatus,
  type FixtureInfo,
  type MarketDataSource,
  type RedeemItem,
  type RedemptionReceipt,
  type TopUpReceipt,
  type TopUpTracking,
  type WalletApi,
} from '../api/types';
import { newOperationId } from '../lib/ids';
import { formatMinor } from '../lib/money';
import { serverOffsetMs } from '../lib/time';
import { betReducer, IDLE, isBusy, type BetAction, type BetFlow } from './betFlow';
import { describeError } from './errorCopy';

export interface KV {
  get<T>(key: string): Promise<T | null>;
  set<T>(key: string, value: T): Promise<void>;
  remove(key: string): Promise<void>;
}

export const PENDING_WAGER_KEY = 'local:fazetime.pendingWager';
const PENDING_MAX_AGE_MS = 15 * 60_000;
const REFRESH_INTERVAL_MS = 10_000;

export interface FixtureApi {
  info(): Promise<ApiResult<FixtureInfo>>;
  load(name: string): Promise<ApiResult<FixtureInfo>>;
  injectError(code: ErrorCode | null): Promise<ApiResult<FixtureInfo>>;
  armTimeout(): Promise<ApiResult<FixtureInfo>>;
}

export type PanelApi = MarketDataSource &
  WalletApi & {
    fixtures: FixtureApi;
    connect(): boolean;
    dispose(): void;
    /** P6 (live builds; the background answers CAPABILITY_UNAVAILABLE elsewhere). */
    topUpHint?(topupId: string): Promise<ApiResult<TopUpTracking | null>>;
    reopenTopUpCheckout?(): Promise<ApiResult<TopUpTracking | null>>;
    dismissTopUp?(): Promise<ApiResult<null>>;
  };

export interface TopUpState {
  open: boolean;
  reason: 'manual' | 'insufficient';
  neededMinor: number | null;
  status: 'idle' | 'submitting' | 'credited' | 'error' | 'unknown';
  message: string | null;
  receipt: TopUpReceipt | null;
  operationId: string | null;
  amountMinor: number | null;
}

export interface RedeemState {
  busyItem: string | null;
  receipt: RedemptionReceipt | null;
  error: string | null;
  retry: { itemId: string; operationId: string } | null;
}

export interface PanelState {
  connection: 'connecting' | 'connected' | 'disconnected';
  adapterMode: 'MOCK' | 'LIVE' | null;
  hasFixtures: boolean;
  snapshot: StreamSnapshot | null;
  snapshotIssue: string | null;
  offsetMs: number;
  runNotice: string | null;
  bet: BetFlow;
  topUp: TopUpState;
  redeem: RedeemState;
  fixtureInfo: FixtureInfo | null;
  catalog: RedeemItem[] | null;
  backend: BackgroundStatus | null;
  /** P6: the background's tracked Stripe test top-up (server status only; never a URL). */
  pendingTopUp: TopUpTracking | null;
  /** The return URL said "cancel" for this top-up: wording only, the status stays the server's. */
  checkoutClosedFor: string | null;
}

const CLOSED_TOPUP: TopUpState = {
  open: false,
  reason: 'manual',
  neededMinor: null,
  status: 'idle',
  message: null,
  receipt: null,
  operationId: null,
  amountMinor: null,
};

export function initialPanelState(): PanelState {
  return {
    connection: 'connecting',
    adapterMode: null,
    hasFixtures: false,
    snapshot: null,
    snapshotIssue: null,
    offsetMs: 0,
    runNotice: null,
    bet: IDLE,
    topUp: CLOSED_TOPUP,
    redeem: { busyItem: null, receipt: null, error: null, retry: null },
    fixtureInfo: null,
    catalog: null,
    backend: null,
    pendingTopUp: null,
    checkoutClosedFor: null,
  };
}

export class PanelController {
  private state: PanelState = initialPanelState();
  private readonly listeners = new Set<() => void>();
  private readonly timers = new Set<ReturnType<typeof setTimeout>>();
  private refreshInterval: ReturnType<typeof setInterval> | null = null;
  private disposed = false;
  private started = false;

  constructor(
    private readonly api: PanelApi,
    private readonly kv: KV,
    private readonly now: () => number = () => Date.now(),
  ) {}

  // --- store plumbing (useSyncExternalStore) ---
  getState = (): PanelState => this.state;
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };
  private set(patch: Partial<PanelState>): void {
    if (this.disposed) return;
    this.state = { ...this.state, ...patch };
    for (const l of [...this.listeners]) l();
  }
  private later(fn: () => void, ms: number): void {
    const t = setTimeout(() => {
      this.timers.delete(t);
      if (!this.disposed) fn();
    }, ms);
    this.timers.add(t);
  }

  // --- lifecycle ---
  start(): void {
    if (this.started || this.disposed) return;
    this.started = true;
    this.api.connect();
    void this.refresh();
    void this.recoverPendingWager();
    this.refreshInterval = setInterval(() => void this.refresh(), REFRESH_INTERVAL_MS);
  }

  dispose(): void {
    this.disposed = true;
    if (this.refreshInterval !== null) clearInterval(this.refreshInterval);
    for (const t of this.timers) clearTimeout(t);
    this.timers.clear();
    this.listeners.clear();
  }

  onConnection = (state: 'connected' | 'disconnected'): void => {
    this.set({ connection: state });
  };

  onPush = (msg: PushMessage): void => {
    if (msg.t === 'status') {
      const prev = this.state.backend;
      this.set({ backend: msg.status });
      if (prev && (prev.enrolled !== msg.status.enrolled || prev.link !== msg.status.link)) void this.refresh();
      return;
    }
    if (msg.t === 'topup') {
      this.applyTopUp(msg.topup);
      return;
    }
    if (msg.t === 'hello') {
      this.set({ adapterMode: msg.mode, hasFixtures: msg.fixtures, connection: 'connected' });
      void this.refresh(); // Service worker may have restarted: resync from the snapshot.
      if (msg.fixtures) void this.refreshFixtureInfo();
      return;
    }
    this.applySnapshot(msg.result as ApiResult<StreamSnapshot>);
  };

  async refresh(opts: { force?: boolean } = {}): Promise<void> {
    const result = await this.api.getSnapshot();
    if (!this.disposed) this.applySnapshot(result, opts);
  }

  applySnapshot(result: ApiResult<StreamSnapshot>, opts: { force?: boolean } = {}): void {
    if (!result.ok) {
      let issue = 'Reconnecting…';
      if (result.kind === 'http') {
        const code = result.error.error.code;
        issue =
          code === 'UNAUTHENTICATED'
            ? 'Not signed in. Open the FaZeTime toolbar popup and press Join.'
            : code === 'NOT_FOUND'
              ? 'No stream is set up on the server yet.'
              : describeError(result.error.error).title;
        if (code === 'UNAUTHENTICATED') {
          this.set({ snapshot: null, snapshotIssue: issue });
          return;
        }
      }
      this.set({ snapshotIssue: issue });
      return;
    }
    const snap = result.body;
    const checked = validate(streamSnapshotV, snap);
    const issues = checked.ok ? checkSnapshot(snap) : checked.issues;
    if (issues.length > 0) {
      console.warn('[FaZeTime] rejected inconsistent snapshot', issues.slice(0, 5));
      this.set({ snapshotIssue: 'Market data unavailable (invalid update ignored).' });
      return;
    }
    const prev = this.state.snapshot;
    const sameRun = prev?.stream.stream_session_id === snap.stream.stream_session_id;
    if (!opts.force && prev && sameRun && snap.event_hwm < prev.event_hwm) return; // Older than what we show.
    const patch: Partial<PanelState> = {
      snapshot: snap,
      snapshotIssue: null,
      offsetMs: serverOffsetMs(snap.server_time_utc, this.now()),
    };
    if (prev && !sameRun) {
      patch.runNotice = 'A new run started. Balances were reset for this run.';
      if (!isBusy(this.state.bet)) patch.bet = IDLE;
    }
    const terminal = snap.market?.state === 'SETTLED' || snap.market?.state === 'VOID';
    if (terminal && this.state.bet.kind === 'accepted') patch.bet = IDLE; // The banner replaces the stale toast.
    this.set(patch);
  }

  dismissRunNotice(): void {
    this.set({ runNotice: null });
  }

  // --- wagers ---
  private dispatchBet(action: BetAction): void {
    this.set({ bet: betReducer(this.state.bet, action) });
  }

  async placeBet(side: Side, amountMinor: number): Promise<void> {
    const snap = this.state.snapshot;
    const market = snap?.market;
    if (!snap || !market || isBusy(this.state.bet)) return;
    if (amountMinor > snap.wallet.available_minor) {
      // Convenience pre-check only; the server would answer INSUFFICIENT_FUNDS.
      this.openTopUp('insufficient', amountMinor - snap.wallet.available_minor);
      return;
    }
    const request: WagerRequest = {
      operation_id: newOperationId(), // A new key for every user intent (CONTRACTS 9.7).
      stream_session_id: snap.stream.stream_session_id,
      market_id: market.market_id,
      rules_version: market.rules_version,
      side,
      amount_minor: amountMinor,
    };
    this.dispatchBet({ type: 'SUBMIT', request });
    if (this.state.bet.kind !== 'submitting') return;
    await this.kv.set(PENDING_WAGER_KEY, { request, savedAt: this.now() }).catch(() => undefined);
    await this.sendPending();
  }

  private async sendPending(): Promise<void> {
    const flow = this.state.bet;
    if (flow.kind !== 'submitting') return;
    const request = flow.pending.request;
    const result = await this.api.placeWager(request);
    if (this.disposed) return;
    await this.finishWager(request, result);
  }

  private async finishWager(request: WagerRequest, result: ApiResult<WagerReceiptResponse>): Promise<void> {
    this.dispatchBet({ type: 'RESULT', operationId: request.operation_id, result });
    const flow = this.state.bet;
    if (flow.kind === 'accepted' || flow.kind === 'rejected') {
      await this.kv.remove(PENDING_WAGER_KEY).catch(() => undefined);
      void this.refresh();
    }
    if (flow.kind === 'rejected') {
      const copy = describeError(flow.error);
      if (copy.action === 'OPEN_TOPUP') {
        const det = (flow.error.details ?? {}) as { available_minor?: number; requested_minor?: number };
        const needed = (det.requested_minor ?? request.amount_minor) - (det.available_minor ?? 0);
        this.openTopUp('insufficient', needed > 0 ? needed : null);
      }
    }
    if (flow.kind === 'unknown' && flow.retryInMs !== null) {
      this.later(() => {
        this.dispatchBet({ type: 'RETRY' });
        void this.sendPending();
      }, flow.retryInMs);
    }
  }

  /** Manual "check status" for an unknown outcome: look up the receipt, else resend the same key. */
  async checkBetStatus(): Promise<void> {
    const flow = this.state.bet;
    if (flow.kind !== 'unknown') return;
    const request = flow.pending.request;
    const lookup = await this.api.getOperation(request.operation_id);
    if (this.disposed) return;
    if (lookup.ok) {
      await this.finishWager(request, lookup);
      return;
    }
    if (lookup.kind === 'http' && lookup.error.error.code === 'NOT_FOUND') {
      this.dispatchBet({ type: 'RETRY' });
      await this.sendPending();
      return;
    }
    this.set({ bet: { ...flow, message: 'Still unable to confirm. Your bet is not shown as placed until a receipt arrives.' } });
  }

  private async recoverPendingWager(): Promise<void> {
    const saved = await this.kv.get<{ request: WagerRequest; savedAt: number }>(PENDING_WAGER_KEY).catch(() => null);
    if (!saved || this.disposed) return;
    if (this.now() - saved.savedAt > PENDING_MAX_AGE_MS) {
      await this.kv.remove(PENDING_WAGER_KEY).catch(() => undefined);
      return;
    }
    this.dispatchBet({ type: 'RECOVER', request: saved.request, message: 'Checking the outcome of your last bet…' });
    await this.checkBetStatus();
  }

  dismissBet(): void {
    this.dispatchBet({ type: 'DISMISS' });
  }

  // --- top-up (MOCK: immediate synthetic credit. LIVE P6: Stripe-hosted Checkout in a new tab) ---
  openTopUp(reason: 'manual' | 'insufficient', neededMinor: number | null = null): void {
    this.set({ topUp: { ...CLOSED_TOPUP, open: true, reason, neededMinor } });
  }

  closeTopUp(): void {
    if (this.state.topUp.status === 'submitting') return;
    // Closing the dialog never cancels a pending Stripe checkout; the background keeps polling it.
    this.set({ topUp: CLOSED_TOPUP });
  }

  async submitTopUp(amountMinor: number): Promise<void> {
    const t = this.state.topUp;
    if (t.status === 'submitting') return;
    // A new key for every click; the SAME key only to retry an unknown outcome of the same amount.
    const reuse = t.status === 'unknown' && t.amountMinor === amountMinor && t.operationId;
    const operationId = reuse ? t.operationId! : newOperationId();
    this.set({ topUp: { ...t, status: 'submitting', message: null, operationId, amountMinor } });
    const r = await this.api.createTopUp({ operation_id: operationId, amount_minor: amountMinor });
    if (this.disposed) return;
    const cur = this.state.topUp;
    if (r.ok && isTopUpTracking(r.body)) {
      // LIVE: Stripe Checkout opened in a new tab (by the background). Nothing is credited yet.
      this.set({ topUp: { ...cur, status: 'idle', message: null }, checkoutClosedFor: null });
      this.applyTopUp(r.body);
    } else if (r.ok) {
      const body = r.body as TopUpReceipt;
      this.set({
        topUp: { ...cur, status: 'credited', receipt: body, message: `Added ${formatMinor(body.amount_minor)} of MOCK demo funds. No payment was made.` },
      });
      void this.refresh();
    } else if (r.kind === 'http' && !r.error.error.retryable) {
      const copy = describeError(r.error.error);
      this.set({ topUp: { ...cur, status: 'error', message: `${copy.title}. ${copy.detail}` } });
    } else {
      this.set({
        topUp: { ...cur, status: 'unknown', message: 'Outcome unknown. Press FaZe Up! again to safely retry the same request.' },
      });
    }
  }

  /** Background push (or a create/hint answer): the tracked top-up's SERVER status. */
  applyTopUp(next: TopUpTracking | null): void {
    if (next !== null && !isTopUpTracking(next)) return; // Untrusted message shape.
    const prev = this.state.pendingTopUp;
    const patch: Partial<PanelState> = { pendingTopUp: next };
    const t = this.state.topUp;
    // A late answer for the request the dialog is waiting on supersedes its "unknown" message.
    if (next && t.operationId === next.operation_id && t.status === 'unknown' && next.status !== 'SUBMITTING')
      patch.topUp = { ...t, status: 'idle', message: null };
    const newlyCredited = next?.status === 'CREDITED' && !(prev?.status === 'CREDITED' && prev.topup_id === next.topup_id);
    if (newlyCredited) {
      // The credit never places or resumes a wager: a bet refused for funds goes back to a fresh card,
      // which shows a new estimate, and the user confirms a new bet (P6).
      const bet = this.state.bet;
      if (bet.kind === 'rejected' && bet.error.code === 'INSUFFICIENT_FUNDS') patch.bet = IDLE;
    }
    this.set(patch);
    if (newlyCredited) void this.refresh();
  }

  /** The page URL carried ?fazetime_topup=<id> (Stripe's return). Poll now; this never credits. */
  async topUpHint(topupId: string, opts: { closed?: boolean } = {}): Promise<void> {
    if (!TOPUP_ID_PATTERN.test(topupId) || !this.api.topUpHint) return;
    if (opts.closed) this.set({ checkoutClosedFor: topupId });
    const r = await this.api.topUpHint(topupId);
    if (!this.disposed && r.ok) this.applyTopUp(r.body);
  }

  /** User click: reopen Stripe Checkout (or retry an unconfirmed create) with the same operation_id. */
  async reopenTopUpCheckout(): Promise<void> {
    if (!this.api.reopenTopUpCheckout) return;
    this.set({ checkoutClosedFor: null });
    const r = await this.api.reopenTopUpCheckout();
    if (this.disposed) return;
    if (r.ok) this.applyTopUp(r.body);
    else if (r.kind === 'http' && !r.error.error.retryable) {
      const copy = describeError(r.error.error);
      this.set({ topUp: { ...this.state.topUp, status: 'error', message: `${copy.title}. ${copy.detail}` } });
    }
  }

  /** User click: ask the server again for an unfinished top-up. */
  async checkTopUpAgain(): Promise<void> {
    const id = this.state.pendingTopUp?.topup_id;
    if (id) await this.topUpHint(id);
  }

  /** The user acknowledged a finished top-up result. */
  async dismissTopUpResult(): Promise<void> {
    const cur = this.state.pendingTopUp;
    if (!cur || !['CREDITED', 'FAILED', 'EXPIRED'].includes(cur.status)) return;
    this.set({ pendingTopUp: null, checkoutClosedFor: null });
    await this.api.dismissTopUp?.();
  }

  // --- redeem (P1 mock; codes are NON-REDEEMABLE) ---
  async loadCatalog(): Promise<void> {
    const r = await this.api.getCatalog();
    if (r.ok && !this.disposed) this.set({ catalog: r.body.items });
  }

  async redeem(itemId: string): Promise<void> {
    const rs = this.state.redeem;
    if (rs.busyItem) return;
    const operationId = rs.retry?.itemId === itemId ? rs.retry.operationId : newOperationId();
    this.set({ redeem: { ...rs, busyItem: itemId, error: null } });
    const r = await this.api.redeem({ operation_id: operationId, item_id: itemId });
    if (this.disposed) return;
    if (r.ok) {
      this.set({ redeem: { busyItem: null, receipt: r.body, error: null, retry: null } });
      void this.refresh();
    } else if (r.kind === 'http' && !r.error.error.retryable) {
      const copy = describeError(r.error.error);
      this.set({ redeem: { busyItem: null, receipt: this.state.redeem.receipt, error: `${copy.title}. ${copy.detail}`, retry: null } });
    } else {
      this.set({
        redeem: {
          busyItem: null,
          receipt: this.state.redeem.receipt,
          error: 'Outcome unknown. Press Redeem again to safely retry the same request.',
          retry: { itemId, operationId },
        },
      });
    }
  }

  // --- dev fixture controls (MOCK only) ---
  async refreshFixtureInfo(): Promise<void> {
    const r = await this.api.fixtures.info();
    if (r.ok && !this.disposed) this.set({ fixtureInfo: r.body });
  }

  async loadFixture(name: string): Promise<void> {
    const r = await this.api.fixtures.load(name);
    if (this.disposed || !r.ok) return;
    const patch: Partial<PanelState> = { fixtureInfo: r.body, runNotice: null };
    if (!isBusy(this.state.bet)) patch.bet = IDLE;
    this.set(patch);
    await this.refresh({ force: true });
  }

  async injectError(code: ErrorCode | null): Promise<void> {
    const r = await this.api.fixtures.injectError(code);
    if (r.ok && !this.disposed) this.set({ fixtureInfo: r.body });
  }

  async armTimeout(): Promise<void> {
    const r = await this.api.fixtures.armTimeout();
    if (r.ok && !this.disposed) this.set({ fixtureInfo: r.body });
  }
}
