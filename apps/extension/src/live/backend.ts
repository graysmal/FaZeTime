// LIVE adapter (P2). Runs ONLY in the background service worker: content scripts never call the API
// and never see the session token. Implements CONTRACTS 9.8-9.10 and the 9.15 rulings:
// - HTTP with Bearer session; typed error envelopes; transport failures are "unknown" (retry same key).
// - WebSocket: POST /v1/ws-ticket, first frame {"type":"auth"}, ping every 25 s, backoff reconnect.
// - Subscribe, buffer events, fetch the snapshot, then apply newer events. Every event carries full
//   aggregate state, so any higher aggregate_version per (run, aggregate) is applied; jumps > 1 are
//   normal (9.15(14)). The snapshot is refetched ONLY on (re)connect, a run change or a server resync.
//   my_position is derived from wager.updated receipts; a state is pushed to tabs only when consistent.
// - Polling fallback while the socket is not live: 2 s while a market is OPEN, 10 s otherwise.
// - 401 anywhere clears the session and asks the user to re-enroll.
// - Top-ups and redemptions are CAPABILITY_UNAVAILABLE until P6 (no network call is made).

import {
  checkSnapshot,
  domainEventV,
  expectedResult,
  enrollResponseV,
  meResponseV,
  streamSnapshotV,
  validate,
  type DomainEvent,
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
import type {
  ApiResult,
  BackendAdapter,
  BackgroundStatus,
  EnrollInput,
  LinkState,
  PresenceInput,
  RedeemCatalog,
  RedemptionReceipt,
  TopUpReceipt,
} from '../api/types';
import { DEMO_CATALOG } from '../mock/catalog';

export interface SessionRecord {
  token: string;
  session_id: string;
  expires_at_utc: string;
  user_id: string;
  display_name: string;
  role: string;
}

/** Background-only persistence. The token is never sent to a page, content script or log. */
export interface LiveStore {
  getSession(): Promise<SessionRecord | null>;
  setSession(session: SessionRecord | null): Promise<void>;
  getDeviceId(): Promise<string>;
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

  constructor(private readonly opts: LiveOptions) {
    this.fetchImpl = opts.fetch ?? ((...a) => fetch(...a));
    this.now = opts.now ?? (() => Date.now());
    this.ready = this.init();
  }

  private async init(): Promise<void> {
    this.session = await this.opts.store.getSession().catch(() => null);
    if (this.session && Date.parse(this.session.expires_at_utc) <= this.now()) {
      this.session = null;
      this.reenroll = true;
      await this.opts.store.setSession(null).catch(() => undefined);
    }
    this.setLink(this.session ? 'IDLE' : 'NEEDS_ENROLL', this.reenroll ? 'Your session expired. Re-enroll with a new invite.' : null);
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
  private async call<T>(method: 'GET' | 'POST', path: string, body?: unknown, auth = true): Promise<ApiResult<T>> {
    await this.ready;
    const headers: Record<string, string> = { Accept: 'application/json' };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (auth) {
      if (!this.session) return httpError('UNAUTHENTICATED', 'Not enrolled. Open the FaZeTime popup and enter your invite code.');
      headers.Authorization = `Bearer ${this.session.token}`;
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
      if (res.status === 401 && auth) await this.onUnauthorized();
      return { ok: false, kind: 'http', status: res.status, error: json };
    }
    return unknownOutcome(`HTTP ${res.status} without a typed error; the outcome is unknown.`);
  }

  private async onUnauthorized(): Promise<void> {
    if (!this.session) return;
    this.opts.log?.('session rejected (401); asking the user to re-enroll');
    this.session = null;
    this.me = null;
    this.reenroll = true;
    await this.opts.store.setSession(null).catch(() => undefined);
    this.closeSocket();
    this.stopPolling();
    this.setLink('NEEDS_ENROLL', 'Your session ended. Re-enroll with a new invite code in the FaZeTime popup.');
  }

  // ---------------------------------------------------------------- enrollment (popup -> background)
  async enroll(input: EnrollInput): Promise<ApiResult<{ me: Me }>> {
    await this.ready;
    const device_id = await this.opts.store.getDeviceId();
    const req = {
      invite_code: input.invite_code.trim(),
      display_name: input.display_name.trim(),
      claimed_twitch_login: input.claimed_twitch_login?.trim() || null,
      device_id,
    };
    const r = await this.call<EnrollResponse>('POST', '/v1/enroll', req, false);
    if (!r.ok) return r;
    if (!validate(enrollResponseV, r.body).ok) return httpError('VALIDATION_FAILED', 'Unexpected enrollment response.');
    const { me } = r.body;
    this.session = {
      token: r.body.session_token,
      session_id: r.body.session_id,
      expires_at_utc: r.body.expires_at_utc,
      user_id: me.user.user_id,
      display_name: me.user.display_name,
      role: me.user.role,
    };
    await this.opts.store.setSession(this.session);
    this.me = me;
    this.current = null;
    this.reenroll = false;
    this.setLink('IDLE', null);
    this.ensureLink();
    return { ok: true, status: 201, body: { me } }; // The token never leaves the background.
  }

  async signOut(): Promise<void> {
    await this.ready;
    this.session = null;
    this.me = null;
    this.current = null;
    await this.opts.store.setSession(null);
    this.closeSocket();
    this.stopPolling();
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

  async createTopUp(): Promise<ApiResult<TopUpReceipt>> {
    return httpError('CAPABILITY_UNAVAILABLE', 'Test top-ups arrive with Stripe test mode in phase 6. Nothing was charged.');
  }

  async getCatalog(): Promise<ApiResult<RedeemCatalog>> {
    return { ok: true, status: 200, body: { schema_version: 1, label: 'DEMO_ONLY_NOT_REDEEMABLE', items: [...DEMO_CATALOG] } };
  }

  async redeem(): Promise<ApiResult<RedemptionReceipt>> {
    return httpError('CAPABILITY_UNAVAILABLE', 'Redemptions are unavailable until phase 6. Nothing was debited.');
  }

  async presence(input: PresenceInput): Promise<ApiResult<PresenceAck>> {
    if (!this.session) return httpError('UNAUTHENTICATED', 'Not enrolled.');
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
