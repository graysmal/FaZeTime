// Operator API client. Same-origin relative URLs only (/v1/...): the API serves this app at /operator/.
//
// Rules implemented here (CONTRACTS §9.7, §9.10):
// - Every mutation carries an operation_id; callers get a FRESH one per user intent (each click).
// - A network error, timeout, 5xx or unparseable 2xx leaves the outcome UNKNOWN: the UI must not show
//   success, and may retry only with the SAME operation_id and body (RATE_LIMITED too, after Retry-After).
// - A 2xx counts as success only if it parses and echoes our operation_id (the server receipt).
// - 401 on an authenticated call means the session is gone: onUnauthorized() sends the UI to sign-in.
// - The bearer token is only ever sent in the Authorization header, never in a URL, never logged.
import type { EnrollResponse, MeResponse, StreamSnapshot } from '@fazetime/contracts';
import type {
  EvidenceList,
  InviteReceipt,
  MarketReceipt,
  OperatorHealth,
  OperatorReceipt,
  ResetReceipt,
  StreamReceipt,
} from './types';

export type FailureKind = 'envelope' | 'network' | 'timeout' | 'aborted' | 'bad_response';

/** A §9.10 error body, read leniently: unknown codes (e.g. worker-only STALE_EPOCH) are kept as strings. */
export interface ErrorInfo {
  code: string;
  message: string;
  retryable: boolean;
  retry_after_ms: number | null;
  request_id: string | null;
  operation_id: string | null;
  details: unknown;
}

export interface PendingOperation {
  path: string;
  body: Record<string, unknown>;
  operationId: string;
}

export class ApiFailure extends Error {
  readonly kind: FailureKind;
  readonly status: number | null;
  readonly info: ErrorInfo | null;
  readonly operationId: string | null;
  /** The server may or may not have applied the mutation: never show success, never assume failure. */
  readonly outcomeUnknown: boolean;
  /** Retrying with the same operation_id and body is allowed (§9.7 client rules). */
  readonly retrySameOperation: boolean;
  /** The exact operation to retry when retrySameOperation is true. */
  readonly pending: PendingOperation | null;

  constructor(init: {
    kind: FailureKind;
    status: number | null;
    info: ErrorInfo | null;
    message: string;
    operationId?: string | null;
    outcomeUnknown?: boolean;
    retrySameOperation?: boolean;
    pending?: PendingOperation | null;
  }) {
    super(init.message);
    this.name = 'ApiFailure';
    this.kind = init.kind;
    this.status = init.status;
    this.info = init.info;
    this.operationId = init.operationId ?? init.info?.operation_id ?? null;
    this.outcomeUnknown = init.outcomeUnknown ?? false;
    this.retrySameOperation = init.retrySameOperation ?? false;
    this.pending = init.pending ?? null;
  }

  get code(): string | null {
    return this.info?.code ?? null;
  }
}

export interface MutationResult<T> {
  receipt: T;
  operationId: string;
  replayed: boolean;
  httpStatus: number;
}

export interface ClientConfig {
  getToken: () => string | null;
  onUnauthorized?: (failure: ApiFailure) => void;
  onForbidden?: (failure: ApiFailure) => void;
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
  newOperationId?: () => string;
  baseUrl?: string;
}

interface RequestOptions {
  method?: 'GET' | 'POST';
  body?: unknown;
  auth?: boolean;
  timeoutMs?: number;
  signal?: AbortSignal;
  as?: 'json' | 'blob';
  /** For mutations: failures that leave the outcome unknown carry this pending operation. */
  pending?: PendingOperation;
}

const ID_RE = {
  mkt: /^mkt_[0-9a-f]{32}$/,
  evd: /^evd_[0-9a-f]{32}$/,
  str: /^str_[0-9a-f]{32}$/,
} as const;

/** Server IDs are interpolated into paths only after a strict shape check (they come from responses). */
export function checkedId(kind: keyof typeof ID_RE, value: string): string {
  if (!ID_RE[kind].test(value)) throw new Error(`invalid ${kind} id`);
  return value;
}

function parseErrorInfo(value: unknown): ErrorInfo | null {
  if (typeof value !== 'object' || value === null) return null;
  const err = (value as { error?: unknown }).error;
  if (typeof err !== 'object' || err === null) return null;
  const e = err as Record<string, unknown>;
  if (typeof e.code !== 'string' || typeof e.message !== 'string') return null;
  return {
    code: e.code,
    message: e.message,
    retryable: e.retryable === true,
    retry_after_ms: typeof e.retry_after_ms === 'number' ? e.retry_after_ms : null,
    request_id: typeof e.request_id === 'string' ? e.request_id : null,
    operation_id: typeof e.operation_id === 'string' ? e.operation_id : null,
    details: e.details ?? null,
  };
}

function defaultOperationId(): string {
  return globalThis.crypto.randomUUID();
}

export class OperatorClient {
  private readonly cfg: Required<Omit<ClientConfig, 'onUnauthorized' | 'onForbidden'>> &
    Pick<ClientConfig, 'onUnauthorized' | 'onForbidden'>;

  constructor(cfg: ClientConfig) {
    this.cfg = {
      fetchImpl: cfg.fetchImpl ?? ((input, init) => globalThis.fetch(input, init)),
      timeoutMs: cfg.timeoutMs ?? 10_000,
      newOperationId: cfg.newOperationId ?? defaultOperationId,
      baseUrl: cfg.baseUrl ?? '',
      getToken: cfg.getToken,
      onUnauthorized: cfg.onUnauthorized,
      onForbidden: cfg.onForbidden,
    };
  }

  newOperationId(): string {
    return this.cfg.newOperationId();
  }

  async request<T>(path: string, opts: RequestOptions = {}): Promise<{ data: T; status: number }> {
    if (!(path.startsWith('/v1/') || path === '/openapi.json') || path.includes('..') || path.includes('//')) {
      throw new Error('refusing a non-API path');
    }
    const method = opts.method ?? 'GET';
    const auth = opts.auth ?? true;
    const isMutation = method === 'POST' && opts.pending !== undefined;
    const headers: Record<string, string> = { Accept: opts.as === 'blob' ? 'image/jpeg' : 'application/json' };
    if (auth) {
      const token = this.cfg.getToken();
      if (!token) {
        const failure = new ApiFailure({
          kind: 'envelope',
          status: 401,
          info: null,
          message: 'Not signed in.',
        });
        this.cfg.onUnauthorized?.(failure);
        throw failure;
      }
      headers.Authorization = `Bearer ${token}`;
    }
    if (opts.body !== undefined) headers['Content-Type'] = 'application/json';

    const ctrl = new AbortController();
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      ctrl.abort();
    }, opts.timeoutMs ?? this.cfg.timeoutMs);
    const onAbort = () => ctrl.abort();
    opts.signal?.addEventListener('abort', onAbort, { once: true });
    const unknown = (kind: FailureKind, status: number | null, message: string, info: ErrorInfo | null = null) =>
      new ApiFailure({
        kind,
        status,
        info,
        message,
        operationId: opts.pending?.operationId,
        outcomeUnknown: isMutation,
        retrySameOperation: isMutation,
        pending: isMutation ? opts.pending : null,
      });

    let res: Response;
    try {
      res = await this.cfg.fetchImpl(`${this.cfg.baseUrl}${path}`, {
        method,
        headers,
        body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
        signal: ctrl.signal,
        cache: 'no-store',
        credentials: 'omit',
        redirect: 'error',
        referrerPolicy: 'no-referrer',
      });
    } catch {
      clearTimeout(timer);
      opts.signal?.removeEventListener('abort', onAbort);
      if (timedOut) throw unknown('timeout', null, 'The request timed out; the outcome is unknown.');
      if (opts.signal?.aborted) throw unknown('aborted', null, 'The request was cancelled.');
      throw unknown('network', null, 'Network error: the API did not answer.');
    }

    try {
      if (res.ok) {
        if (opts.as === 'blob') return { data: (await res.blob()) as T, status: res.status };
        const text = await res.text();
        try {
          return { data: JSON.parse(text) as T, status: res.status };
        } catch {
          throw unknown('bad_response', res.status, `HTTP ${res.status} with an unreadable body.`);
        }
      }
      let info: ErrorInfo | null = null;
      try {
        info = parseErrorInfo(JSON.parse(await res.text()));
      } catch {
        info = null;
      }
      const status = res.status;
      const code = info?.code ?? null;
      // §9.10: timeout/5xx = unknown outcome (CAPABILITY_UNAVAILABLE is a definitive refusal).
      const fiveXX = status >= 500 && code !== 'CAPABILITY_UNAVAILABLE';
      const sameOpRetry = isMutation && (fiveXX || code === 'RATE_LIMITED' || code === 'INTERNAL_ERROR');
      const failure = new ApiFailure({
        kind: info ? 'envelope' : 'bad_response',
        status,
        info,
        message: info ? info.message : `HTTP ${status} without a §9.10 error envelope.`,
        operationId: info?.operation_id ?? opts.pending?.operationId,
        outcomeUnknown: isMutation && fiveXX,
        retrySameOperation: sameOpRetry,
        pending: sameOpRetry ? opts.pending : null,
      });
      if (auth && status === 401) this.cfg.onUnauthorized?.(failure);
      if (auth && status === 403 && code === 'FORBIDDEN' && path.startsWith('/v1/operator/')) {
        this.cfg.onForbidden?.(failure);
      }
      throw failure;
    } finally {
      clearTimeout(timer);
      opts.signal?.removeEventListener('abort', onAbort);
    }
  }

  /**
   * One operator mutation. Pass no operationId for a new user intent (a fresh UUID is generated);
   * pass the pending operation's id only to retry an unknown outcome with the identical body.
   */
  async mutate<T extends OperatorReceipt>(
    path: string,
    body: Record<string, unknown>,
    operationId: string = this.newOperationId(),
  ): Promise<MutationResult<T>> {
    const pending: PendingOperation = { path, body, operationId };
    const { data, status } = await this.request<T>(path, {
      method: 'POST',
      body: { ...body, operation_id: operationId },
      pending,
    });
    if (typeof data !== 'object' || data === null || data.operation_id !== operationId) {
      throw new ApiFailure({
        kind: 'bad_response',
        status,
        info: null,
        message: 'The response did not carry this operation’s receipt; the outcome is unknown.',
        operationId,
        outcomeUnknown: true,
        retrySameOperation: true,
        pending,
      });
    }
    return { receipt: data, operationId, replayed: data.replayed === true, httpStatus: status };
  }

  retry<T extends OperatorReceipt>(pending: PendingOperation): Promise<MutationResult<T>> {
    return this.mutate<T>(pending.path, pending.body, pending.operationId);
  }

  // ---- reads -----------------------------------------------------------------------------------
  async enroll(input: { invite_code: string; display_name: string; device_id: string }): Promise<EnrollResponse> {
    const { data } = await this.request<EnrollResponse>('/v1/enroll', {
      method: 'POST',
      auth: false,
      body: { ...input, claimed_twitch_login: null },
    });
    return data;
  }

  async me(signal?: AbortSignal): Promise<MeResponse> {
    return (await this.request<MeResponse>('/v1/me', { signal })).data;
  }

  async health(signal?: AbortSignal): Promise<OperatorHealth> {
    return (await this.request<OperatorHealth>('/v1/operator/health', { signal, timeoutMs: 5_000 })).data;
  }

  async snapshot(streamId: string, signal?: AbortSignal): Promise<StreamSnapshot> {
    const path = `/v1/streams/${checkedId('str', streamId)}/snapshot`;
    return (await this.request<StreamSnapshot>(path, { signal, timeoutMs: 5_000 })).data;
  }

  async openapi(signal?: AbortSignal): Promise<unknown> {
    return (await this.request<unknown>('/openapi.json', { auth: false, signal })).data;
  }

  async evidence(since: string | null, signal?: AbortSignal): Promise<EvidenceList> {
    const q = new URLSearchParams({ limit: '200' });
    if (since) q.set('since', since);
    return (await this.request<EvidenceList>(`/v1/operator/evidence?${q.toString()}`, { signal, timeoutMs: 5_000 })).data;
  }

  async evidenceImage(evidenceId: string, signal?: AbortSignal): Promise<Blob> {
    const path = `/v1/operator/evidence/${checkedId('evd', evidenceId)}`;
    return (await this.request<Blob>(path, { signal, as: 'blob', timeoutMs: 8_000 })).data;
  }

  // ---- mutations (fresh operation_id per call unless retrying) -----------------------------------
  async createStream(twitchChannelLogin: string) {
    return this.mutate<StreamReceipt>('/v1/operator/streams', { twitch_channel_login: twitchChannelLogin });
  }

  async createMarket(input: { question: string; yes_label: string; no_label: string; close_in_s: number; resolve_in_s: number }) {
    return this.mutate<MarketReceipt>('/v1/operator/markets', { ...input });
  }

  async openMarket(marketId: string) {
    return this.mutate<MarketReceipt>(`/v1/operator/markets/${checkedId('mkt', marketId)}/open`, {});
  }

  async settleMarket(marketId: string, winningSide: 'YES' | 'NO', reason: { field: string; text: string } | null) {
    const body: Record<string, unknown> = { winning_side: winningSide };
    if (reason) body[reason.field] = reason.text;
    return this.mutate<MarketReceipt>(`/v1/operator/markets/${checkedId('mkt', marketId)}/settle`, body);
  }

  async voidMarket(marketId: string, note: string) {
    return this.mutate<MarketReceipt>(`/v1/operator/markets/${checkedId('mkt', marketId)}/void`, { note });
  }

  async createViewerInvite() {
    return this.mutate<InviteReceipt>('/v1/operator/invites', { role: 'VIEWER', is_bot: false });
  }

  async resetRun(streamId: string) {
    return this.mutate<ResetReceipt>('/v1/operator/runs/reset', { stream_id: checkedId('str', streamId) });
  }
}
