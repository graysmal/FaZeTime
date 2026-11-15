// LIVE adapter (P2). Runs ONLY in the background service worker: content scripts never call the API
// and never see the session token. Implements CONTRACTS 9.8-9.10 and the 9.15 rulings:
// - HTTP with Bearer session; typed error envelopes; transport failures are "unknown" (retry same key).
// - WebSocket: POST /v1/ws-ticket, first frame {"type":"auth"}, ping every 25 s, backoff reconnect.
// - Subscribe, buffer events, fetch the snapshot, then apply newer events. Every event carries full
//   aggregate state, so any higher aggregate_version per (run, aggregate) is applied; jumps > 1 are
//   normal (9.15(14)). The snapshot is refetched ONLY on (re)connect, a run change or a server resync.
//   my_position is derived from wager.updated receipts; a state is pushed to tabs only when consistent.
// - Polling fallback while the socket is not live: 2 s while a market is OPEN, 10 s otherwise.
// - D35 open access: a missing/expired session or a 401 triggers ONE silent name-only re-join with the stored
//   name (single-flight, rate-limited), then the failed request is retried once. Only when the server refuses
//   name-only enroll (invite-only) is the session cleared and the user asked to join in the popup.
// - P6 Stripe test top-ups (9.18): POST /v1/topups (retry the SAME key on RATE_LIMITED, INTERNAL_ERROR or
//   an unknown outcome), open the Stripe-hosted Checkout URL with chrome.tabs.create (never logged,
//   stored or posted to a tab), persist the pending top-up, and poll GET /v1/topups/{id} every 3 s
//   while CREATED/PENDING. Only the server's CREDITED status counts; a return URL is a polling hint.
//   A credit never places a wager: the user confirms a new one.
// - Redemptions stay CAPABILITY_UNAVAILABLE (no network call is made).

import {
  checkSnapshot,
  domainEventV,
  expectedResult,
  enrollResponseV,
  meResponseV,
  streamSnapshotV,
  validate,
  type DomainEvent,
  type EnrollRequest,
  type EnrollResponse,
  type ErrorEnvelope,
  type Me,
  type MeResponse,
  type MyPosition,
  type PresenceAck,
  type PublicMarket,
  type SourceHealth,
  type StreamSnapshot,
  type StreamUpdatedPayload,
  type WagerReceipt,
  type WagerReceiptResponse,
  type WagerRequest,
  type WalletSummary,
  type WsTicketResponse,
} from '@fazetime/contracts';
import { httpError, unknownOutcome } from '../api/errors';
import {
  TOPUP_ID_PATTERN,
  TOPUP_STATUSES,
  type ApiResult,
  type BackendAdapter,
  type BackgroundStatus,
  type EnrollInput,
  type LinkState,
  type PresenceInput,
  type RedeemCatalog,
  type RedemptionReceipt,
  type StripeTopupReceipt,
  type TopupStatus,
  type TopUpRequest,
  type TopUpTracking,
} from '../api/types';
import { defaultDisplayName, refusesNameOnly } from '../lib/join';
import { DEMO_CATALOG } from '../mock/catalog';

/** POST /v1/enroll body. D35 makes invite_code optional; contracts v1 `EnrollRequest` still requires it. */
type EnrollBody = Omit<EnrollRequest, 'invite_code'> & { invite_code?: string };

export interface SessionRecord {
  token: string;
  session_id: string;
  expires_at_utc: string;
  user_id: string;
  display_name: string;
  role: string;
}

/**
 * The one tracked Stripe test top-up, persisted by the background so a tab reload, popup close or
 * service-worker restart keeps it. It never holds the Checkout URL or any token.
 */
export interface TopUpRecord {
  user_id: string;
  operation_id: string;
  amount_minor: number;
  topup_id: string | null;
  status: TopupStatus | 'SUBMITTING';
  stream_session_id: string | null;
  checkout_expires_at_utc: string | null;
  checkout_opened: boolean;
  checkout_blocked: boolean;
  watching: boolean;
  dismissed: boolean;
  created_at_ms: number;
  updated_at_ms: number;
}

/** Background-only persistence. The token is never sent to a page, content script or log. */
export interface LiveStore {
  getSession(): Promise<SessionRecord | null>;
  setSession(session: SessionRecord | null): Promise<void>;
  getDeviceId(): Promise<string>;
  /** P6: the tracked top-up (optional; tests may keep it in memory). */
  getTopUp?(): Promise<TopUpRecord | null>;
  setTopUp?(record: TopUpRecord | null): Promise<void>;
  /** D35: the name of the last successful join, for silent re-join. Not a secret (optional; in memory if absent). */
  getJoinProfile?(): Promise<JoinProfile | null>;
  setJoinProfile?(profile: JoinProfile | null): Promise<void>;
}

/** What a silent re-join sends again: the display name and label the server accepted last time. */
export interface JoinProfile {
  display_name: string;
  claimed_twitch_login: string | null;
}

export interface WsLike {
  readyState: number;
  send(data: string): void;
  close(code?: number, reason?: string): void;
  onopen: ((ev: unknown) => void) | null;
  onmessage: ((ev: { data: unknown }) => void) | null;
  onclose: ((ev: { code: number }) => void) | null;
  onerror: ((ev: unknown) => void) | null;
}

export interface LiveOptions {
  apiBase: string;
  channel: string;
  extensionVersion: string;
  store: LiveStore;
  fetch?: typeof fetch;
  createWebSocket?: (url: string) => WsLike;
  now?: () => number;
  requestTimeoutMs?: number;
  pingIntervalMs?: number;
  pollOpenMs?: number;
  pollIdleMs?: number;
  log?: (msg: string) => void;
  /** Opens Stripe Checkout in a new tab (chrome.tabs.create; background only, no permission needed). */
  openTab?: (url: string) => Promise<void>;
  /** GET /v1/topups/{id} cadence while CREATED/PENDING (default 3 s, the server's reconcile throttle). */
  topupPollMs?: number;
  /** Cadence after the first 15 minutes of an unfinished checkout (default 15 s). */
  topupSlowPollMs?: number;
  /** Same-key retry delays for POST /v1/topups on RATE_LIMITED, INTERNAL_ERROR or unknown outcomes. */
  topupRetryDelaysMs?: number[];
}

const OPEN_TOPUP: readonly string[] = ['CREATED', 'PENDING'];
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const TOPUP_FAST_WINDOW_MS = 15 * 60_000;
/** At most one silent re-join attempt per window, so a broken server cannot cause an enroll storm. */
const REJOIN_MIN_INTERVAL_MS = 10_000;

/** The server marks EXPIRED on a reconcile after Stripe expires the session, so keep watching a bit. */
const TOPUP_EXPIRY_GRACE_MS = 3 * 60_000;
const TOPUP_NO_EXPIRY_CAP_MS = 30 * 60_000;
const TOPUP_RESULT_TTL_MS = 30 * 60_000;
const TOPUP_UNCONFIRMED_TTL_MS = 60 * 60_000;
const TOPUP_HINT_MIN_GAP_MS = 1000;

/** Only Stripe-hosted Checkout pages may be opened (never an arbitrary URL from a response). */
export function isStripeCheckoutUrl(url: unknown): url is string {
  if (typeof url !== 'string' || url.length > 4096) return false;
  try {
    const u = new URL(url);
    return u.protocol === 'https:' && u.hostname === 'checkout.stripe.com' && u.port === '' && !u.username && !u.password;
  } catch {
    return false;
  }
}

export function isStripeTopupReceipt(v: unknown): v is StripeTopupReceipt {
  if (typeof v !== 'object' || v === null) return false;
  const r = v as Record<string, unknown>;
  return (
    typeof r.topup_id === 'string' &&
    TOPUP_ID_PATTERN.test(r.topup_id) &&
    typeof r.operation_id === 'string' &&
    typeof r.stream_session_id === 'string' &&
    Number.isSafeInteger(r.amount_minor) &&
    (TOPUP_STATUSES as readonly string[]).includes(String(r.status)) &&
    (r.checkout_url === null || r.checkout_url === undefined || typeof r.checkout_url === 'string') &&
    (r.checkout_expires_at_utc === null || r.checkout_expires_at_utc === undefined || typeof r.checkout_expires_at_utc === 'string')
  );
}

/** my_position derived from the user's own receipts for this market (9.15(6), 9.15(7)). */
export function derivePosition(market: PublicMarket, receipts: WagerReceipt[]): MyPosition {
  const wagers = receipts.filter((w) => w.market_id === market.market_id);
  const stake = wagers.reduce((sum, w) => sum + w.amount_minor, 0);
  const pos: MyPosition = {
    market_id: market.market_id,
    side: wagers[0]?.side ?? null,
    stake_total_minor: stake,
    result: 'NONE',
    payout_total_minor: null,
    refund_total_minor: null,
    wagers,
  };
  pos.result = expectedResult(market, pos);
  if (pos.result === 'WON' || pos.result === 'LOST') pos.payout_total_minor = wagers.reduce((sum, w) => sum + (w.payout_minor ?? 0), 0);
  if (pos.result === 'VOID_REFUNDED' || pos.result === 'UNRESOLVED_REFUNDED')
    pos.refund_total_minor = wagers.reduce((sum, w) => sum + (w.refund_minor ?? 0), 0);
  return pos;
}

const stripSchema = (r: WagerReceipt | WagerReceiptResponse): WagerReceipt => {
  const { schema_version: _ignored, ...rest } = r as WagerReceiptResponse;
  return rest;
};

const isEnvelope = (v: unknown): v is ErrorEnvelope =>
  typeof v === 'object' && v !== null && typeof (v as ErrorEnvelope).error?.code === 'string';

export class LiveBackend implements BackendAdapter {
  readonly mode = 'LIVE' as const;
  private session: SessionRecord | null = null;
  private me: Me | null = null;
  private current: StreamSnapshot | null = null;
  private offsetMs = 0;
  private reenroll = false;
  /** D35: last accepted name, for silent re-join. Cleared by an explicit sign-out. */
  private joinProfile: JoinProfile | null = null;
  private rejoinInFlight: Promise<boolean> | null = null;
  private lastRejoinAt = Number.NEGATIVE_INFINITY;
  /** The server refused name-only enroll (invite-only): no more silent attempts until a popup join works. */
  private rejoinRefused = false;
  /** Silent re-joins that produced a new session (diagnostics and tests). */
  rejoins = 0;
  private link: LinkState = 'IDLE';
  private message: string | null = null;
  private demand = 0;
  private ws: WsLike | null = null;
  private wsPhase: 'closed' | 'connecting' | 'auth' | 'live' = 'closed';
  private buffer: DomainEvent[] | null = null;
  private reconnectDelay = 1000;
  private lastFrameAt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private pollTimer: ReturnType<typeof setTimeout> | null = null;
  private refetchTimer: ReturnType<typeof setTimeout> | null = null;
  private idleTimer: ReturnType<typeof setTimeout> | null = null;
  private inconsistentTimer: ReturnType<typeof setTimeout> | null = null;
  /** Highest version seen per aggregate in the current run (reset on run change). */
  private versions = new Map<string, number>();
  private retiredMarkets = new Set<string>();
  /** Snapshot fetches, for diagnostics and tests (9.15(14): no refetch storms). */
  snapshotFetches = 0;
  private readonly changeListeners = new Set<() => void>();
  private readonly statusListeners = new Set<() => void>();
  private readonly ready: Promise<void>;
  private readonly fetchImpl: typeof fetch;
  private readonly now: () => number;
  // P6 top-up tracking (one at a time; the server is authoritative for its status).
  private topup: TopUpRecord | null = null;
  private topupTimer: ReturnType<typeof setTimeout> | null = null;
  private topupPollInFlight: Promise<void> | null = null;
  private lastTopupPollAt = 0;
  private readonly createInFlight = new Map<string, Promise<ApiResult<TopUpTracking>>>();
  private readonly topupListeners = new Set<() => void>();

  constructor(private readonly opts: LiveOptions) {
    this.fetchImpl = opts.fetch ?? ((...a) => fetch(...a));
    this.now = opts.now ?? (() => Date.now());
    this.ready = this.init();
  }

  private async init(): Promise<void> {
    this.session = await this.opts.store.getSession().catch(() => null);
    this.joinProfile = (await this.opts.store.getJoinProfile?.().catch(() => null)) ?? null;
    // Sessions stored before D35 have no join profile: reuse the session's display name.
    if (!this.joinProfile && this.session) this.joinProfile = { display_name: this.session.display_name, claimed_twitch_login: null };
    let expired = false;
    if (this.session && Date.parse(this.session.expires_at_utc) <= this.now()) {
      this.session = null;
      expired = true;
      await this.opts.store.setSession(null).catch(() => undefined);
    }
    // An expired session with a known name re-joins silently (below); otherwise the user joins in the popup.
    this.reenroll = expired && !this.joinProfile;
    this.setLink(this.session ? 'IDLE' : 'NEEDS_ENROLL', this.reenroll ? 'Your session expired. Join again in the FaZeTime popup.' : null);
    await this.restoreTopUp();
    if (expired && this.joinProfile) queueMicrotask(() => void this.silentRejoin().then((ok) => ok || this.markJoinNeeded()));
  }

  // ---------------------------------------------------------------- status / listeners
  status(): BackgroundStatus {
    return {
      mode: 'LIVE',
      link: this.link,
      enrolled: this.session !== null,
      reenroll: this.reenroll,
      displayName: this.session?.display_name ?? null,
      role: this.session?.role ?? null,
      apiBase: this.opts.apiBase,
      channel: this.opts.channel,
      message: this.message,
    };
  }
  onStatus(listener: () => void): () => void {
    this.statusListeners.add(listener);
    return () => this.statusListeners.delete(listener);
  }
  onChange(listener: () => void): () => void {
    this.changeListeners.add(listener);
    return () => this.changeListeners.delete(listener);
  }
  private setLink(link: LinkState, message: string | null = this.message): void {
    if (link === this.link && message === this.message) return;
    this.link = link;
    this.message = message;
    for (const l of [...this.statusListeners]) l();
  }
  private emitChange(): void {
    for (const l of [...this.changeListeners]) l();
  }

  /** Cached snapshot with server time re-estimated now, for pushes to tabs. */
  peekSnapshot(): ApiResult<StreamSnapshot> | null {
    if (!this.current) return null;
    const body = { ...this.current, server_time_utc: new Date(this.now() + this.offsetMs).toISOString() };
    return { ok: true, status: 200, body };
  }

  // ---------------------------------------------------------------- HTTP
  private async call<T>(method: 'GET' | 'POST', path: string, body?: unknown, auth = true, mayRejoin = true): Promise<ApiResult<T>> {
    await this.ready;
    const headers: Record<string, string> = { Accept: 'application/json' };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    let tokenUsed: string | null = null;
    if (auth) {
      if (!this.session && !(mayRejoin && (await this.silentRejoin())))
        return httpError('UNAUTHENTICATED', 'Not signed in. Open the FaZeTime popup and join.');
      tokenUsed = this.session!.token;
      headers.Authorization = `Bearer ${tokenUsed}`;
    }
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), this.opts.requestTimeoutMs ?? 8000);
    let res: Response;
    try {
      res = await this.fetchImpl(`${this.opts.apiBase}${path}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: ctrl.signal,
        credentials: 'omit',
        cache: 'no-store',
      });
    } catch {
      return unknownOutcome('Could not reach the FaZeTime API; the outcome is unknown.');
    } finally {
      clearTimeout(timer);
    }
    let json: unknown = null;
    try {
      json = await res.json();
    } catch {
      json = null;
    }
    if (res.ok) return { ok: true, status: res.status, body: json as T };
    if (isEnvelope(json)) {
      if (res.status === 401 && tokenUsed !== null) {
        // The server applied nothing (auth runs first), so one retry with a fresh session is safe. A concurrent
        // re-join may already have replaced the token; otherwise re-join silently with the stored name.
        if (mayRejoin && ((this.session !== null && this.session.token !== tokenUsed) || (await this.silentRejoin(tokenUsed))))
          return this.call<T>(method, path, body, auth, false);
        await this.onUnauthorized(tokenUsed);
      }
      return { ok: false, kind: 'http', status: res.status, error: json };
    }
    return unknownOutcome(`HTTP ${res.status} without a typed error; the outcome is unknown.`);
  }

  private async onUnauthorized(tokenUsed?: string): Promise<void> {
    if (!this.session) return;
    if (tokenUsed !== undefined && this.session.token !== tokenUsed) return; // Already replaced by a re-join.
    this.opts.log?.('session rejected (401) and no silent re-join; asking the user to join');
    this.session = null;
    this.me = null;
    await this.opts.store.setSession(null).catch(() => undefined);
    this.closeSocket();
    this.stopPolling();
    this.markJoinNeeded();
  }

  private markJoinNeeded(): void {
    if (this.session) return;
    this.reenroll = true;
    this.setLink('NEEDS_ENROLL', 'Your session ended. Join again in the FaZeTime popup.');
  }

  /**
   * D35: one name-only enroll with the stored name, shared by every caller that needs it (single-flight).
   * Resolves true when a new session is in place. Never prompts: if the server is invite-only it records that
   * and the popup asks for a code only after the user presses Join. `staleToken`: re-join only if this token
   * is still the current one (a 401 for an already replaced session just retries).
   */
  private silentRejoin(staleToken?: string): Promise<boolean> {
    if (this.rejoinInFlight) return this.rejoinInFlight;
    if (staleToken !== undefined && this.session && this.session.token !== staleToken) return Promise.resolve(true);
    const profile = this.joinProfile;
    if (!profile || this.rejoinRefused || this.now() - this.lastRejoinAt < REJOIN_MIN_INTERVAL_MS) return Promise.resolve(false);
    this.lastRejoinAt = this.now();
    this.rejoinInFlight = (async () => {
      const r = await this.requestEnroll({ display_name: profile.display_name, claimed_twitch_login: profile.claimed_twitch_login });
      if (!r.ok) {
        if (refusesNameOnly(r)) this.rejoinRefused = true;
        this.opts.log?.(refusesNameOnly(r) ? 'silent re-join refused: the server is invite-only' : 'silent re-join failed');
        return false;
      }
      this.rejoins += 1;
      this.opts.log?.('session replaced by a silent re-join');
      await this.adoptSession(r.body, false);
      return true;
    })()
      .catch(() => false)
      .finally(() => {
        this.rejoinInFlight = null;
      });
    return this.rejoinInFlight;
  }

  /** POST /v1/enroll. No invite code: the field is OMITTED (name-only, D35). Returns the validated response. */
  private async requestEnroll(input: EnrollInput): Promise<ApiResult<EnrollResponse>> {
    const device_id = await this.opts.store.getDeviceId();
    const code = input.invite_code?.trim() ?? '';
    const req: EnrollBody = {
      ...(code !== '' ? { invite_code: code } : {}),
      display_name: input.display_name.trim() || defaultDisplayName(),
      claimed_twitch_login: input.claimed_twitch_login?.trim() || null,
      device_id,
    };
    const r = await this.call<EnrollResponse>('POST', '/v1/enroll', req, false);
    if (!r.ok) return r;
    if (!validate(enrollResponseV, r.body).ok) return httpError('VALIDATION_FAILED', 'Unexpected enrollment response.');
    return r;
  }

  /** Installs a session from an enroll response (popup join or silent re-join). The token stays here. */
  private async adoptSession(body: EnrollResponse, fromPopup: boolean): Promise<Me> {
    const { me } = body;
    const userChanged = this.session?.user_id !== me.user.user_id;
    this.session = {
      token: body.session_token,
      session_id: body.session_id,
      expires_at_utc: body.expires_at_utc,
      user_id: me.user.user_id,
      display_name: me.user.display_name,
      role: me.user.role,
    };
    await this.opts.store.setSession(this.session);
    this.joinProfile = { display_name: me.user.display_name, claimed_twitch_login: me.user.claimed_twitch_login };
    await this.opts.store.setJoinProfile?.(this.joinProfile)?.catch(() => undefined);
    this.me = me;
    this.reenroll = false;
    this.rejoinRefused = false;
    if (fromPopup || userChanged) {
      // A different account: drop the cached wallet/position and versions, and the socket subscribed for the
      // old one (only when established; an in-flight connect picks up the new token by itself).
      this.current = null;
      this.versions.clear();
      if (this.wsPhase === 'live') this.closeSocket();
    }
    this.setLink('IDLE', null);
    this.ensureLink();
    if (this.topup && this.topup.user_id !== me.user.user_id) await this.setTopUpRecord(null);
    else this.scheduleTopUpPoll(0);
    if (!fromPopup && userChanged && this.demand > 0) void this.fetchSnapshot();
    return me;
  }

  // ---------------------------------------------------------------- enrollment (popup -> background)
  /**
   * Popup "Join" (D35): name-only unless the popup passes the invite code it asked for after the server
   * refused name-only enroll (401). An empty name gets a default ("Viewer 1234").
   */
  async enroll(input: EnrollInput): Promise<ApiResult<{ me: Me }>> {
    await this.ready;
    const r = await this.requestEnroll(input);
    if (!r.ok) return r;
    const me = await this.adoptSession(r.body, true);
    return { ok: true, status: 201, body: { me } }; // The token never leaves the background.
  }

  async signOut(): Promise<void> {
    await this.ready;
    this.session = null;
    this.me = null;
    this.current = null;
    // An explicit sign-out must stay signed out: forget the name, so nothing re-joins silently.
    this.joinProfile = null;
    await this.opts.store.setJoinProfile?.(null)?.catch(() => undefined);
    await this.opts.store.setSession(null);
    this.closeSocket();
    this.stopPolling();
    await this.setTopUpRecord(null);
    this.setLink('NEEDS_ENROLL', null);
    this.emitChange();
  }

  private async streamId(): Promise<ApiResult<string>> {
    if (this.me?.current_stream) return { ok: true, status: 200, body: this.me.current_stream.stream_id };
    const r = await this.call<MeResponse>('GET', '/v1/me');
    if (!r.ok) return r;
    if (!validate(meResponseV, r.body).ok) return httpError('VALIDATION_FAILED', 'Unexpected /v1/me response.');
    this.me = r.body;
    if (!r.body.current_stream) {
      this.setLink('NO_STREAM', 'No stream is set up on the server yet.');
      return httpError('NOT_FOUND', 'No stream is set up on the server yet.');
    }
    return { ok: true, status: 200, body: r.body.current_stream.stream_id };
  }

  // ---------------------------------------------------------------- snapshot + events
  async getSnapshot(): Promise<ApiResult<StreamSnapshot>> {
    // While the socket is live, the cache (snapshot at connect + every event since) is authoritative.
    if (this.wsPhase === 'live' && this.current && this.buffer === null) {
      this.ensureLink();
      return this.peekSnapshot()!;
    }
    const r = await this.fetchSnapshot();
    this.ensureLink();
    return r.ok ? (this.peekSnapshot() ?? r) : r;
  }

  private async fetchSnapshot(): Promise<ApiResult<StreamSnapshot>> {
    const sid = await this.streamId();
    if (!sid.ok) return sid;
    this.snapshotFetches += 1;
    const r = await this.call<StreamSnapshot>('GET', `/v1/streams/${sid.body}/snapshot`);
    if (r.ok) this.acceptSnapshot(r.body);
    return r;
  }

  private acceptSnapshot(snap: StreamSnapshot): void {
    const checked = validate(streamSnapshotV, snap);
    if (!checked.ok || checkSnapshot(snap).length > 0) {
      this.opts.log?.('ignored an invalid snapshot');
      return;
    }
    this.offsetMs = Date.parse(snap.server_time_utc) - this.now();
    const cur = this.current;
    const sameRun = cur?.stream.stream_session_id === snap.stream.stream_session_id;
    if (!sameRun) {
      this.versions.clear();
      this.retiredMarkets.clear();
      if (this.topup) queueMicrotask(() => this.emitTopUp()); // previous_run may have flipped.
    }
    if (!cur || !sameRun || snap.event_hwm >= cur.event_hwm) {
      this.current = snap;
      this.noteVersions(snap);
    }
    if (!sameRun && this.me?.current_stream) this.me = { ...this.me, current_stream: { ...this.me.current_stream, stream_session_id: snap.stream.stream_session_id } };
    // Apply events that arrived while this snapshot was in flight.
    const pending = this.buffer;
    this.buffer = null;
    if (pending) for (const ev of pending) this.applyEvent(ev);
    this.emitChange();
    this.schedulePoll();
  }

  private noteVersions(snap: StreamSnapshot): void {
    const bump = (key: string, v: number) => this.versions.set(key, Math.max(this.versions.get(key) ?? 0, v));
    bump('STREAM', snap.stream.aggregate_version);
    bump(`WALLET:${snap.wallet.stream_session_id}`, snap.wallet.balance_version);
    if (snap.market) bump(`MARKET:${snap.market.market_id}`, snap.market.aggregate_version);
  }

  /** Push only consistent states; a transient mid-burst state (e.g. settled before wager.updated) is held. */
  private emitIfConsistent(): void {
    if (!this.current) return;
    if (checkSnapshot(this.current).length === 0) {
      if (this.inconsistentTimer !== null) clearTimeout(this.inconsistentTimer);
      this.inconsistentTimer = null;
      this.emitChange();
      return;
    }
    // Safety net only: if a burst never completes (lost USER events), resync once after 5 s.
    if (this.inconsistentTimer === null)
      this.inconsistentTimer = setTimeout(() => {
        this.inconsistentTimer = null;
        if (this.current && checkSnapshot(this.current).length > 0) {
          this.opts.log?.('event-derived state stayed inconsistent for 5 s; resyncing');
          this.refetchSoon();
        }
      }, 5000);
  }

  private refetchSoon(): void {
    if (this.refetchTimer !== null) return;
    this.refetchTimer = setTimeout(() => {
      this.refetchTimer = null;
      void this.fetchSnapshot();
    }, 50);
  }

  /** Returns true if the event changed the cached state (9.9, 9.15(1), 9.15(14)). */
  applyEvent(ev: DomainEvent): boolean {
    if (this.buffer) {
      this.buffer.push(ev);
      return false;
    }
    const cur = this.current;
    if (!cur) return false; // The connect-time snapshot will include it.
    if (ev.event_id <= cur.event_hwm) return false; // Already in the snapshot, or a duplicate.
    if (ev.stream_session_id !== cur.stream.stream_session_id) {
      this.refetchSoon(); // Run change: one of the three refetch triggers.
      return false;
    }
    const newer = (key: string, version: number): boolean => {
      if (version <= (this.versions.get(key) ?? 0)) return false;
      this.versions.set(key, version);
      return true;
    };
    const next: StreamSnapshot = { ...cur, event_hwm: ev.event_id };
    switch (ev.aggregate_type) {
      case 'MARKET': {
        const m = ev.payload as PublicMarket;
        if (!newer(`MARKET:${m.market_id}`, m.aggregate_version)) return false;
        if (this.retiredMarkets.has(m.market_id)) return false; // A late event for a market we moved past.
        if (cur.market && cur.market.market_id !== m.market_id) {
          this.retiredMarkets.add(cur.market.market_id);
          next.market = m;
          next.my_position = derivePosition(m, []); // A new market: no position yet.
        } else {
          next.market = m;
          next.my_position = derivePosition(m, cur.my_position?.wagers ?? []);
        }
        break;
      }
      case 'WAGER': {
        const w = stripSchema(ev.payload as WagerReceipt);
        if (!newer(`WAGER:${w.wager_id}`, ev.aggregate_version)) return false;
        if (!cur.market || w.market_id !== cur.market.market_id) return false;
        const others = (cur.my_position?.wagers ?? []).filter((x) => x.wager_id !== w.wager_id);
        next.my_position = derivePosition(cur.market, [...others, w]);
        break;
      }
      case 'WALLET': {
        const w = ev.payload as WalletSummary;
        if (w.stream_session_id !== cur.wallet.stream_session_id) return false;
        if (!newer(`WALLET:${w.stream_session_id}`, w.balance_version)) return false;
        next.wallet = w;
        break;
      }
      case 'STREAM': {
        const p = ev.payload as StreamUpdatedPayload;
        if (p.stream.stream_session_id !== cur.stream.stream_session_id) {
          this.refetchSoon(); // Run change.
          return false;
        }
        if (!newer('STREAM', p.stream.aggregate_version)) return false;
        next.stream = p.stream;
        next.modes = p.modes;
        break;
      }
      case 'SOURCE':
        if (!newer('SOURCE', ev.aggregate_version)) return false;
        next.source_health = ev.payload as SourceHealth;
        break;
      default:
        return false; // Reserved aggregates (RAFFLE, CALL) are ignored.
    }
    this.current = next;
    this.emitIfConsistent();
    return true;
  }

  /** Apply our own receipt immediately (the matching events then arrive as equal versions). */
  private applyReceipt(r: WagerReceiptResponse): void {
    const cur = this.current;
    if (!cur?.market || r.market_id !== cur.market.market_id || r.stream_session_id !== cur.stream.stream_session_id) return;
    const w = stripSchema(r);
    if ((cur.my_position?.wagers ?? []).some((x) => x.wager_id === w.wager_id)) return;
    this.versions.set(`WAGER:${w.wager_id}`, Math.max(this.versions.get(`WAGER:${w.wager_id}`) ?? 0, 1));
    const next: StreamSnapshot = { ...cur, my_position: derivePosition(cur.market, [...(cur.my_position?.wagers ?? []), w]) };
    if (w.wallet_after.balance_version > (this.versions.get(`WALLET:${cur.wallet.stream_session_id}`) ?? 0)) {
      this.versions.set(`WALLET:${cur.wallet.stream_session_id}`, w.wallet_after.balance_version);
      next.wallet = w.wallet_after;
    }
    this.current = next;
    this.emitIfConsistent();
  }

  // ---------------------------------------------------------------- link management (WS + polling)
  /** Number of connected tabs. The socket only runs while someone is watching. */
  setDemand(tabs: number): void {
    this.demand = tabs;
    if (tabs > 0) {
      if (this.idleTimer !== null) clearTimeout(this.idleTimer);
      this.idleTimer = null;
      this.ensureLink();
    } else if (this.idleTimer === null) {
      this.idleTimer = setTimeout(() => {
        this.idleTimer = null;
        if (this.demand === 0) {
          this.closeSocket();
          this.stopPolling();
          if (this.session) this.setLink('IDLE');
        }
      }, 30_000);
    }
  }

  onTabConnected(): void {
    if (this.session) void this.fetchSnapshot(); // Authoritative refresh on reload; pushes to every tab.
  }

  ensureLink(): void {
    if (!this.session || this.demand === 0) return;
    if (this.wsPhase === 'closed' && this.reconnectTimer === null && this.link !== 'ORIGIN_REJECTED') void this.openSocket();
    this.schedulePoll();
  }

  private async openSocket(): Promise<void> {
    if (this.wsPhase !== 'closed' || !this.session) return;
    this.wsPhase = 'connecting';
    if (this.link !== 'LIVE') this.setLink('CONNECTING');
    const sid = await this.streamId();
    if (!sid.ok) {
      this.wsPhase = 'closed';
      if (this.session) this.scheduleReconnect();
      return;
    }
    const ticket = await this.call<WsTicketResponse>('POST', '/v1/ws-ticket', { stream_id: sid.body });
    if (!ticket.ok || !this.session) {
      this.wsPhase = 'closed';
      if (this.session) this.scheduleReconnect();
      return;
    }
    const url = `${this.opts.apiBase.replace(/^http/, 'ws')}${ticket.body.ws_path}`;
    let ws: WsLike;
    try {
      ws = this.opts.createWebSocket ? this.opts.createWebSocket(url) : (new WebSocket(url) as unknown as WsLike);
    } catch {
      this.wsPhase = 'closed';
      this.scheduleReconnect();
      return;
    }
    this.ws = ws;
    const secret = ticket.body.ticket; // One-use, 30 s; sent only in the first frame, never in the URL.
    ws.onopen = () => {
      if (this.ws !== ws) return;
      this.wsPhase = 'auth';
      ws.send(JSON.stringify({ type: 'auth', ticket: secret }));
    };
    ws.onmessage = (e) => this.onFrame(ws, e.data);
    ws.onerror = () => undefined; // A close event always follows.
    ws.onclose = (e) => this.onSocketClosed(ws, e.code);
  }

  private onFrame(ws: WsLike, data: unknown): void {
    if (this.ws !== ws || typeof data !== 'string' || data.length > 1_000_000) return;
    let frame: { type?: string; event?: unknown };
    try {
      frame = JSON.parse(data) as typeof frame;
    } catch {
      return;
    }
    this.lastFrameAt = this.now();
    switch (frame.type) {
      case 'ready':
        this.wsPhase = 'live';
        this.reconnectDelay = 1000;
        this.setLink('LIVE', null);
        this.startPing(ws);
        this.buffer = []; // Subscribe-then-snapshot: buffer events until the snapshot lands.
        void this.fetchSnapshot().then((r) => {
          if (!r.ok && this.buffer) {
            const pending = this.buffer;
            this.buffer = null;
            for (const ev of pending) this.applyEvent(ev);
          }
        });
        return;
      case 'event': {
        if (!validate(domainEventV, frame.event).ok) return;
        this.applyEvent(frame.event as DomainEvent);
        return;
      }
      case 'ping':
        ws.send(JSON.stringify({ type: 'pong' }));
        return;
      case 'resync':
        this.refetchSoon();
        return;
      default:
        return; // pong or unknown frames: liveness only.
    }
  }

  private startPing(ws: WsLike): void {
    this.stopPing();
    const every = this.opts.pingIntervalMs ?? 25_000;
    this.pingTimer = setInterval(() => {
      if (this.ws !== ws) return;
      if (this.now() - this.lastFrameAt > every * 2 + 5000) {
        this.opts.log?.('websocket silent too long; reconnecting');
        ws.close(4000, 'stale');
        this.onSocketClosed(ws, 4000);
        return;
      }
      try {
        ws.send(JSON.stringify({ type: 'ping' }));
      } catch {
        // Close follows.
      }
    }, every);
  }

  private stopPing(): void {
    if (this.pingTimer !== null) clearInterval(this.pingTimer);
    this.pingTimer = null;
  }

  private onSocketClosed(ws: WsLike, code: number): void {
    if (this.ws !== ws) return;
    this.ws = null;
    this.wsPhase = 'closed';
    this.buffer = null;
    this.stopPing();
    if (!this.session) return;
    if (code === 4403) {
      this.setLink('ORIGIN_REJECTED', 'The API rejected this extension origin (4403). Check the CORS/WS allowlist.');
      this.schedulePoll();
      return;
    }
    if (code === 4401) void this.streamId(); // A revoked session surfaces as 401 -> re-enroll.
    this.setLink('POLLING', 'Live updates reconnecting; polling the snapshot meanwhile.');
    this.scheduleReconnect();
    this.schedulePoll();
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer !== null || this.demand === 0 || !this.session) return;
    const delay = this.reconnectDelay + Math.floor(Math.random() * 300);
    this.reconnectDelay = Math.min(this.reconnectDelay * 2, 15_000);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      void this.openSocket();
    }, delay);
  }

  private closeSocket(): void {
    const ws = this.ws;
    this.ws = null;
    this.wsPhase = 'closed';
    this.buffer = null;
    this.stopPing();
    if (this.reconnectTimer !== null) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    if (ws) {
      try {
        ws.close(1000, 'idle');
      } catch {
        // Ignore.
      }
    }
  }

  /** Polling fallback whenever the socket is not live (9.9): 2 s while OPEN, else 10 s. */
  private schedulePoll(): void {
    if (this.pollTimer !== null) clearTimeout(this.pollTimer);
    this.pollTimer = null;
    if (!this.session || this.demand === 0 || this.wsPhase === 'live') return;
    const open = this.current?.market?.state === 'OPEN';
    this.pollTimer = setTimeout(() => {
      this.pollTimer = null;
      if (this.wsPhase === 'live') return;
      void this.fetchSnapshot().then(() => this.schedulePoll());
    }, open ? (this.opts.pollOpenMs ?? 2000) : (this.opts.pollIdleMs ?? 10_000));
  }

  private stopPolling(): void {
    if (this.pollTimer !== null) clearTimeout(this.pollTimer);
    this.pollTimer = null;
  }

  /** Test hook: drop the socket abruptly, as a network loss would. */
  debugDropSocket(): void {
    const ws = this.ws;
    if (!ws) return;
    try {
      ws.close(4000, 'debug drop');
    } catch {
      // Ignore.
    }
    this.onSocketClosed(ws, 4000);
  }

  // ---------------------------------------------------------------- wallet API
  placeWager(req: WagerRequest): Promise<ApiResult<WagerReceiptResponse>> {
    return this.call<WagerReceiptResponse>('POST', '/v1/wagers', req).then((r) => {
      if (r.ok) this.applyReceipt(r.body);
      return r;
    });
  }

  getOperation(operationId: string): Promise<ApiResult<WagerReceiptResponse>> {
    if (!/^[0-9a-f-]{36}$/.test(operationId)) return Promise.resolve(httpError('VALIDATION_FAILED', 'Bad operation_id.'));
    return this.call<WagerReceiptResponse>('GET', `/v1/operations/${operationId}`);
  }

  // ---------------------------------------------------------------- P6 Stripe test top-ups (9.18)
  /** Tab-facing view of the tracked top-up. No URL, no token. */
  peekTopUp(): TopUpTracking | null {
    const r = this.topup;
    if (!r || r.dismissed) return null;
    const run = this.current?.stream.stream_session_id ?? this.me?.current_stream?.stream_session_id ?? null;
    return {
      payment_mode: 'STRIPE_TEST',
      topup_id: r.topup_id,
      operation_id: r.operation_id,
      amount_minor: r.amount_minor,
      status: r.status,
      checkout_opened: r.checkout_opened,
      checkout_blocked: r.checkout_blocked,
      previous_run: r.stream_session_id !== null && run !== null && r.stream_session_id !== run,
      watching: r.watching,
      updated_at_ms: r.updated_at_ms,
    };
  }

  onTopUp(listener: () => void): () => void {
    this.topupListeners.add(listener);
    return () => this.topupListeners.delete(listener);
  }

  private emitTopUp(): void {
    for (const l of [...this.topupListeners]) l();
  }

  private async restoreTopUp(): Promise<void> {
    let rec = (await this.opts.store.getTopUp?.().catch(() => null)) ?? null;
    if (!rec || typeof rec.operation_id !== 'string') return;
    const age = this.now() - (rec.updated_at_ms || 0);
    const terminal = !OPEN_TOPUP.includes(rec.status) && rec.status !== 'SUBMITTING';
    const wrongUser = !this.session || rec.user_id !== this.session.user_id;
    if (wrongUser || (terminal && age > TOPUP_RESULT_TTL_MS) || (rec.status === 'SUBMITTING' && age > TOPUP_UNCONFIRMED_TTL_MS)) {
      await this.opts.store.setTopUp?.(null).catch(() => undefined);
      return;
    }
    // A create that was in flight when the worker stopped: its outcome is unknown until the user retries
    // with the SAME operation_id (we never re-send it, or open a tab, without a click).
    if (rec.status === 'SUBMITTING') rec = { ...rec, watching: false };
    else if (OPEN_TOPUP.includes(rec.status)) rec = { ...rec, watching: true };
    this.topup = rec;
    setTimeout(() => this.scheduleTopUpPoll(0), 0);
  }

  private async setTopUpRecord(rec: TopUpRecord | null): Promise<void> {
    this.topup = rec;
    await this.opts.store.setTopUp?.(rec).catch(() => undefined);
    this.emitTopUp();
    this.scheduleTopUpPoll();
  }

  private patchTopUp(patch: Partial<TopUpRecord>): Promise<void> {
    if (!this.topup) return Promise.resolve();
    return this.setTopUpRecord({ ...this.topup, ...patch, updated_at_ms: this.now() });
  }

  /**
   * POST /v1/topups for ONE user click (a fresh operation_id from the panel; the same one only when the
   * user retries an unknown outcome). Retries reuse the same key and body. Opens Stripe Checkout once.
   */
  createTopUp(req: TopUpRequest): Promise<ApiResult<TopUpTracking>> {
    const key = typeof req?.operation_id === 'string' ? req.operation_id : '';
    const inFlight = this.createInFlight.get(key);
    if (inFlight) return inFlight; // A double click or a retry while the first request is still running.
    const p = this.createTopUpOnce(req, false).finally(() => this.createInFlight.delete(key));
    if (key) this.createInFlight.set(key, p);
    return p;
  }

  private async createTopUpOnce(req: TopUpRequest, forceOpen: boolean): Promise<ApiResult<TopUpTracking>> {
    await this.ready;
    if (!this.session && !(await this.silentRejoin())) return httpError('UNAUTHENTICATED', 'Not signed in. Open the FaZeTime popup and join.');
    if (typeof req?.operation_id !== 'string' || !UUID_RE.test(req.operation_id) || !Number.isSafeInteger(req.amount_minor))
      return httpError('VALIDATION_FAILED', 'A top-up needs a lowercase UUID operation_id and an integer amount_minor.');
    const body = { operation_id: req.operation_id, amount_minor: req.amount_minor };
    const prev = this.topup;
    const same = prev !== null && prev.operation_id === body.operation_id && prev.amount_minor === body.amount_minor;
    const now = this.now();
    // Persist the intent BEFORE the request so a worker restart keeps the key.
    await this.setTopUpRecord(
      same
        ? { ...prev!, status: prev!.topup_id ? prev!.status : 'SUBMITTING', watching: true, dismissed: false, checkout_blocked: false, updated_at_ms: now }
        : {
            user_id: this.session!.user_id,
            operation_id: body.operation_id,
            amount_minor: body.amount_minor,
            topup_id: null,
            status: 'SUBMITTING',
            stream_session_id: null,
            checkout_expires_at_utc: null,
            checkout_opened: false,
            checkout_blocked: false,
            watching: true, // While SUBMITTING: the request is in flight. false = outcome unknown.
            dismissed: false,
            created_at_ms: now,
            updated_at_ms: now,
          },
    );
    const r = await this.postTopUp(body);
    if (!r.ok) {
      if (r.kind === 'http' && !r.error.error.retryable) {
        // Definitive: this request created nothing new. Keep only what was already known.
        await this.setTopUpRecord(same ? (prev!.topup_id ? prev : null) : prev);
        return r;
      }
      await this.patchTopUp({ watching: false }); // Outcome unknown: the user retries with the SAME key.
      return r;
    }
    if (!isStripeTopupReceipt(r.body) || r.body.operation_id !== body.operation_id) {
      this.opts.log?.('unexpected top-up response; outcome unknown');
      await this.patchTopUp({ watching: false });
      return { ok: false, kind: 'unknown', message: 'Unexpected top-up response; the outcome is unknown.' };
    }
    const receipt = r.body;
    const checkoutUrl = receipt.checkout_url; // Used once, right here. Never stored, logged or posted.
    await this.adoptReceipt(receipt);
    // Open Checkout once per click. A same-key retry of an already opened checkout does not open a second
    // tab unless the user asked to reopen it.
    const alreadyOpened = same && prev!.checkout_opened && prev!.topup_id === receipt.topup_id;
    if (receipt.status === 'PENDING' && checkoutUrl && (forceOpen || !alreadyOpened)) await this.openCheckout(checkoutUrl);
    return { ok: true, status: r.status, body: this.peekTopUp()! };
  }

  /** Same key, same body on RATE_LIMITED, INTERNAL_ERROR or an unknown outcome (9.10). */
  private async postTopUp(body: { operation_id: string; amount_minor: number }): Promise<ApiResult<StripeTopupReceipt>> {
    const delays = this.opts.topupRetryDelaysMs ?? [1000, 2000, 4000];
    let r = await this.call<StripeTopupReceipt>('POST', '/v1/topups', body);
    for (const base of delays) {
      if (r.ok || !this.session) return r;
      const retryable = r.kind === 'unknown' || r.error.error.retryable;
      if (!retryable) return r;
      const hinted = r.kind === 'http' ? (r.error.error.retry_after_ms ?? 0) : 0;
      await new Promise((resolve) => setTimeout(resolve, Math.min(Math.max(base, hinted), 10_000)));
      r = await this.call<StripeTopupReceipt>('POST', '/v1/topups', body);
    }
    return r;
  }

  private async openCheckout(url: string): Promise<boolean> {
    if (!isStripeCheckoutUrl(url) || !this.opts.openTab) {
      this.opts.log?.('refused to open a top-up link that is not a Stripe Checkout page'); // Never the URL.
      await this.patchTopUp({ checkout_blocked: true });
      return false;
    }
    try {
      await this.opts.openTab(url);
    } catch {
      this.opts.log?.('could not open the Stripe Checkout tab');
      await this.patchTopUp({ checkout_blocked: true });
      return false;
    }
    await this.patchTopUp({ checkout_opened: true, checkout_blocked: false });
    return true;
  }

  /** Apply a server receipt (POST or GET). Only the server's status is shown; credits refresh the wallet. */
  private async adoptReceipt(receipt: StripeTopupReceipt): Promise<void> {
    const prev = this.topup;
    const mine = prev !== null && prev.operation_id === receipt.operation_id ? prev : null;
    const wasCredited = mine?.topup_id === receipt.topup_id && mine.status === 'CREDITED';
    const wasStatus = mine?.status ?? null;
    const now = this.now();
    await this.setTopUpRecord({
      user_id: this.session?.user_id ?? mine?.user_id ?? '',
      operation_id: receipt.operation_id,
      amount_minor: receipt.amount_minor,
      topup_id: receipt.topup_id,
      status: receipt.status,
      stream_session_id: receipt.stream_session_id,
      checkout_expires_at_utc: receipt.checkout_expires_at_utc ?? mine?.checkout_expires_at_utc ?? null,
      checkout_opened: mine?.checkout_opened ?? false,
      checkout_blocked: mine?.checkout_blocked ?? false,
      watching: OPEN_TOPUP.includes(receipt.status),
      dismissed: mine?.dismissed ?? false,
      created_at_ms: mine?.created_at_ms ?? now,
      updated_at_ms: now,
    });
    if (wasStatus !== receipt.status && !OPEN_TOPUP.includes(receipt.status)) this.opts.log?.(`top-up ${receipt.status.toLowerCase()} (server status)`);
    if (receipt.status === 'CREDITED' && !wasCredited) void this.fetchSnapshot(); // Authoritative wallet refresh.
  }

  private scheduleTopUpPoll(delayMs?: number): void {
    if (this.topupTimer !== null) clearTimeout(this.topupTimer);
    this.topupTimer = null;
    const rec = this.topup;
    if (!rec || !rec.topup_id || !OPEN_TOPUP.includes(rec.status) || !rec.watching || !this.session) return;
    const now = this.now();
    const expires = rec.checkout_expires_at_utc ? Date.parse(rec.checkout_expires_at_utc) - this.offsetMs : Number.NaN;
    const deadline = Number.isFinite(expires) ? expires + TOPUP_EXPIRY_GRACE_MS : rec.created_at_ms + TOPUP_NO_EXPIRY_CAP_MS;
    if (now > deadline) {
      this.opts.log?.('stopped polling an unfinished top-up after its checkout expiry');
      void this.patchTopUp({ watching: false });
      return;
    }
    const fast = now - rec.created_at_ms < TOPUP_FAST_WINDOW_MS;
    const every = delayMs ?? (fast ? (this.opts.topupPollMs ?? 3000) : (this.opts.topupSlowPollMs ?? 15_000));
    this.topupTimer = setTimeout(() => {
      this.topupTimer = null;
      void this.pollTopUp();
    }, every);
  }

  /** GET /v1/topups/{id}. Single-flight; the server reconciles with Stripe at most once per 3 s. */
  private pollTopUp(): Promise<void> {
    if (this.topupPollInFlight) return this.topupPollInFlight;
    const p = (async () => {
      const rec = this.topup;
      if (!rec?.topup_id || !this.session) return;
      this.lastTopupPollAt = this.now();
      const r = await this.call<StripeTopupReceipt>('GET', `/v1/topups/${rec.topup_id}`);
      if (this.topup?.topup_id !== rec.topup_id) return; // Replaced meanwhile.
      if (r.ok) {
        if (isStripeTopupReceipt(r.body) && r.body.topup_id === rec.topup_id) await this.adoptReceipt(r.body);
      } else if (r.kind === 'http' && (r.error.error.code === 'NOT_FOUND' || r.error.error.code === 'FORBIDDEN')) {
        this.opts.log?.('the server does not know this top-up for this user; no longer tracking it');
        await this.setTopUpRecord(null);
        return;
      }
    })().finally(() => {
      this.topupPollInFlight = null;
      this.scheduleTopUpPoll();
    });
    this.topupPollInFlight = p;
    return p;
  }

  /** ?fazetime_topup=<id> on the Twitch page: poll now. A hint only; the server decides the status. */
  async topUpHint(topupId: string): Promise<ApiResult<TopUpTracking | null>> {
    await this.ready;
    if (!this.session) return httpError('UNAUTHENTICATED', 'Not enrolled.');
    if (!TOPUP_ID_PATTERN.test(topupId)) return httpError('VALIDATION_FAILED', 'Bad topup_id.');
    const rec = this.topup;
    if (rec?.topup_id === topupId) {
      if (OPEN_TOPUP.includes(rec.status)) {
        if (!rec.watching) await this.patchTopUp({ watching: true }); // "Check again" resumes watching.
        if (this.now() - this.lastTopupPollAt >= TOPUP_HINT_MIN_GAP_MS) await this.pollTopUp();
      }
      return { ok: true, status: 200, body: this.peekTopUp() };
    }
    if (rec && (OPEN_TOPUP.includes(rec.status) || rec.status === 'SUBMITTING')) return { ok: true, status: 200, body: this.peekTopUp() };
    // Not tracked here (for example, extension storage was cleared): read it once; only our own is returned.
    const r = await this.call<StripeTopupReceipt>('GET', `/v1/topups/${topupId}`);
    if (!r.ok) return r.kind === 'http' && r.error.error.code === 'NOT_FOUND' ? { ok: true, status: 200, body: this.peekTopUp() } : r;
    if (isStripeTopupReceipt(r.body) && r.body.topup_id === topupId && !(rec?.topup_id === topupId && rec.dismissed)) await this.adoptReceipt(r.body);
    return { ok: true, status: 200, body: this.peekTopUp() };
  }

  /** User click: reopen Checkout, or re-send an unconfirmed create, with the SAME operation_id and amount. */
  async reopenTopUpCheckout(): Promise<ApiResult<TopUpTracking | null>> {
    await this.ready;
    const rec = this.topup;
    if (!rec || rec.dismissed || !(rec.status === 'SUBMITTING' || OPEN_TOPUP.includes(rec.status)))
      return { ok: true, status: 200, body: this.peekTopUp() };
    const key = rec.operation_id;
    const p =
      this.createInFlight.get(key) ??
      this.createTopUpOnce({ operation_id: key, amount_minor: rec.amount_minor }, true).finally(() => this.createInFlight.delete(key));
    this.createInFlight.set(key, p);
    const r = await p;
    return r.ok ? { ok: true, status: 200, body: this.peekTopUp() } : r;
  }

  /** The user acknowledged a finished result. Unfinished top-ups are never dropped this way. */
  async dismissTopUp(): Promise<ApiResult<null>> {
    await this.ready;
    const rec = this.topup;
    if (rec && !rec.dismissed && !OPEN_TOPUP.includes(rec.status) && rec.status !== 'SUBMITTING') await this.patchTopUp({ dismissed: true });
    return { ok: true, status: 200, body: null };
  }

  async getCatalog(): Promise<ApiResult<RedeemCatalog>> {
    return { ok: true, status: 200, body: { schema_version: 1, label: 'DEMO_ONLY_NOT_REDEEMABLE', items: [...DEMO_CATALOG] } };
  }

  async redeem(): Promise<ApiResult<RedemptionReceipt>> {
    return httpError('CAPABILITY_UNAVAILABLE', 'Redemptions are unavailable until phase 6. Nothing was debited.');
  }

  async presence(input: PresenceInput): Promise<ApiResult<PresenceAck>> {
    await this.ready;
    if (!this.session && !(await this.silentRejoin())) return httpError('UNAUTHENTICATED', 'Not signed in.');
    const sid = await this.streamId();
    if (!sid.ok) return sid;
    return this.call<PresenceAck>('POST', '/v1/presence', {
      device_id: await this.opts.store.getDeviceId(),
      tab_instance_id: input.tab_instance_id,
      stream_id: sid.body,
      known_stream_session_id: this.current?.stream.stream_session_id ?? this.me?.current_stream?.stream_session_id ?? null,
      observed_channel_login: input.observed_channel_login,
      page_visibility: input.page_visibility,
      player_state: input.player_state,
      extension_version: this.opts.extensionVersion,
    });
  }
}
