// Content-script side: implements MarketDataSource/WalletApi by messaging the background.
// It never touches the network and never sees a session token (P2 keeps it in the background).

import type { ErrorCode, StreamSnapshot, WagerReceiptResponse, WagerRequest } from '@fazetime/contracts';
import { isFromBackground, REQUEST_TIMEOUT_MS, type Method, type PortLike, type PushMessage } from './protocol';
import { unknownOutcome } from './errors';
import type {
  ApiResult,
  FixtureControls,
  FixtureInfo,
  MarketDataSource,
  PresenceInput,
  RedeemCatalog,
  RedemptionReceipt,
  RedemptionRequest,
  TopUpReceipt,
  TopUpRequest,
  TopUpTracking,
  WalletApi,
} from './types';

export interface BackgroundClientOptions {
  connect: () => PortLike;
  onPush: (msg: PushMessage) => void;
  onConnection?: (state: 'connected' | 'disconnected') => void;
  /** False once the extension context is invalidated (extension reload/update). */
  isValid?: () => boolean;
  timeoutMs?: number;
}

const RECONNECT_MIN_MS = 500;
const RECONNECT_MAX_MS = 10_000;

export class BackgroundClient implements MarketDataSource, WalletApi {
  private port: PortLike | null = null;
  private nextId = 1;
  private readonly pending = new Map<number, { resolve: (r: ApiResult<unknown>) => void; timer: ReturnType<typeof setTimeout> }>();
  private disposed = false;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectDelay = RECONNECT_MIN_MS;

  constructor(private readonly opts: BackgroundClientOptions) {}

  /** Open the port eagerly so pushes arrive. Safe to call repeatedly. */
  connect(): boolean {
    return this.ensurePort() !== null;
  }

  get connected(): boolean {
    return this.port !== null;
  }

  private ensurePort(): PortLike | null {
    if (this.disposed) return null;
    if (this.port) return this.port;
    if (this.opts.isValid && !this.opts.isValid()) return null;
    let port: PortLike;
    try {
      port = this.opts.connect();
    } catch {
      return null; // Extension context invalidated.
    }
    port.onMessage.addListener(this.onMessage);
    port.onDisconnect.addListener(this.onDisconnect);
    this.port = port;
    this.reconnectDelay = RECONNECT_MIN_MS;
    this.opts.onConnection?.('connected');
    return port;
  }

  private readonly onMessage = (msg: unknown) => {
    if (!isFromBackground(msg)) return;
    if (msg.t === 'res') {
      const entry = this.pending.get(msg.id);
      if (!entry) return;
      clearTimeout(entry.timer);
      this.pending.delete(msg.id);
      entry.resolve(msg.result);
      return;
    }
    this.opts.onPush(msg);
  };

  private readonly onDisconnect = () => {
    const port = this.port;
    if (port) {
      port.onMessage.removeListener(this.onMessage);
      port.onDisconnect.removeListener(this.onDisconnect);
    }
    this.port = null;
    this.failPending('The connection to the extension background was lost; the outcome is unknown.');
    this.opts.onConnection?.('disconnected');
    this.scheduleReconnect();
  };

  private scheduleReconnect(): void {
    if (this.disposed || this.reconnectTimer !== null) return;
    if (this.opts.isValid && !this.opts.isValid()) return;
    const delay = this.reconnectDelay;
    this.reconnectDelay = Math.min(this.reconnectDelay * 2, RECONNECT_MAX_MS);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      if (!this.ensurePort()) this.scheduleReconnect();
    }, delay);
  }

  private failPending(message: string): void {
    for (const entry of this.pending.values()) {
      clearTimeout(entry.timer);
      entry.resolve(unknownOutcome(message));
    }
    this.pending.clear();
  }

  request<T>(method: Method, params?: unknown): Promise<ApiResult<T>> {
    const port = this.ensurePort();
    if (!port) return Promise.resolve(unknownOutcome<T>('The extension background is unavailable; the outcome is unknown.'));
    const id = this.nextId++;
    return new Promise<ApiResult<T>>((resolve) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        resolve(unknownOutcome<T>('Timed out waiting for the extension background; the outcome is unknown.'));
      }, this.opts.timeoutMs ?? REQUEST_TIMEOUT_MS);
      this.pending.set(id, { resolve: resolve as (r: ApiResult<unknown>) => void, timer });
      try {
        port.postMessage({ t: 'req', id, method, params });
      } catch {
        clearTimeout(timer);
        this.pending.delete(id);
        resolve(unknownOutcome<T>('Could not reach the extension background; the outcome is unknown.'));
      }
    });
  }

  getSnapshot(): Promise<ApiResult<StreamSnapshot>> {
    return this.request('getSnapshot');
  }
  placeWager(req: WagerRequest): Promise<ApiResult<WagerReceiptResponse>> {
    return this.request('placeWager', req);
  }
  getOperation(operationId: string): Promise<ApiResult<WagerReceiptResponse>> {
    return this.request('getOperation', { operation_id: operationId });
  }
  createTopUp(req: TopUpRequest): Promise<ApiResult<TopUpReceipt | TopUpTracking>> {
    return this.request('createTopUp', req);
  }
  /** The page URL carried ?fazetime_topup=<id>. A polling hint only; it never credits. */
  topUpHint(topupId: string): Promise<ApiResult<TopUpTracking | null>> {
    return this.request('topupHint', { topup_id: topupId });
  }
  reopenTopUpCheckout(): Promise<ApiResult<TopUpTracking | null>> {
    return this.request('reopenTopUpCheckout');
  }
  dismissTopUp(): Promise<ApiResult<null>> {
    return this.request('dismissTopUp');
  }
  /** Opens the toolbar popup so the viewer can join (verify). Never enrolls from the page. */
  openJoin(): Promise<ApiResult<{ opened: boolean }>> {
    return this.request('openJoin');
  }
  presence(input: PresenceInput): Promise<ApiResult<unknown>> {
    return this.request('presence', input);
  }
  getCatalog(): Promise<ApiResult<RedeemCatalog>> {
    return this.request('getCatalog');
  }
  redeem(req: RedemptionRequest): Promise<ApiResult<RedemptionReceipt>> {
    return this.request('redeem', req);
  }

  readonly fixtures: { [K in keyof FixtureControls]: (...args: Parameters<FixtureControls[K]>) => Promise<ApiResult<FixtureInfo>> } = {
    info: () => this.request('fixtures.info'),
    load: (name: string) => this.request('fixtures.load', { name }),
    injectError: (code: ErrorCode | null) => this.request('fixtures.injectError', { code }),
    armTimeout: () => this.request('fixtures.armTimeout'),
  };

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    if (this.reconnectTimer !== null) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    const port = this.port;
    this.port = null;
    if (port) {
      port.onMessage.removeListener(this.onMessage);
      port.onDisconnect.removeListener(this.onDisconnect);
      try {
        port.disconnect();
      } catch {
        // Already gone.
      }
    }
    this.failPending('The panel was closed; the outcome is unknown.');
  }
}
