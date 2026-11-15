// Content script <-> background wire protocol over one runtime Port per content-script instance.
// Messages are untrusted input on both sides: validate shape before use.

import { ERROR_CODES, type ErrorCode } from '@fazetime/contracts';
import type { ApiResult, BackgroundStatus, TopUpTracking } from './types';

export const PORT_NAME = 'fazetime/v1';
export const REQUEST_TIMEOUT_MS = 10_000;

export const METHODS = [
  'getSnapshot',
  'placeWager',
  'getOperation',
  'createTopUp',
  'getCatalog',
  'redeem',
  'fixtures.info',
  'fixtures.load',
  'fixtures.injectError',
  'fixtures.armTimeout',
  'presence',
  'status',
  'topupHint',
  'reopenTopUpCheckout',
  'dismissTopUp',
  /** Ask the background to open the toolbar popup (where joining happens). It cannot enroll by itself. */
  'openJoin',
] as const;
export type Method = (typeof METHODS)[number];

export interface RequestMessage {
  t: 'req';
  id: number;
  method: Method;
  params?: unknown;
}

export type ResponseMessage = { t: 'res'; id: number; result: ApiResult<unknown> };

/** Pushed to every connected tab whenever state may have changed. */
export type PushMessage =
  | { t: 'snapshot'; result: ApiResult<unknown> }
  | { t: 'hello'; mode: 'MOCK' | 'LIVE'; fixtures: boolean }
  | { t: 'status'; status: BackgroundStatus }
  /** P6: the tracked Stripe test top-up (never its Checkout URL), or null when none is tracked. */
  | { t: 'topup'; topup: TopUpTracking | null };

/** Popup (extension page) -> background. Content scripts are refused. */
export const POPUP_METHODS = ['status', 'enroll', 'signout'] as const;
export type PopupMethod = (typeof POPUP_METHODS)[number];
export interface PopupRequest {
  t: 'popup';
  method: PopupMethod;
  params?: unknown;
}

export type FromBackground = ResponseMessage | PushMessage;

export function isRequestMessage(msg: unknown): msg is RequestMessage {
  if (typeof msg !== 'object' || msg === null) return false;
  const m = msg as Record<string, unknown>;
  return m.t === 'req' && Number.isSafeInteger(m.id) && typeof m.method === 'string' && (METHODS as readonly string[]).includes(m.method);
}

export function isFromBackground(msg: unknown): msg is FromBackground {
  if (typeof msg !== 'object' || msg === null) return false;
  const m = msg as Record<string, unknown>;
  if (m.t === 'res') return Number.isSafeInteger(m.id) && isApiResult(m.result);
  if (m.t === 'snapshot') return isApiResult(m.result);
  if (m.t === 'hello') return m.mode === 'MOCK' || m.mode === 'LIVE';
  if (m.t === 'status') return typeof m.status === 'object' && m.status !== null;
  if (m.t === 'topup') return m.topup === null || (typeof m.topup === 'object' && !Array.isArray(m.topup));
  return false;
}

function isApiResult(r: unknown): r is ApiResult<unknown> {
  if (typeof r !== 'object' || r === null) return false;
  const v = r as Record<string, unknown>;
  if (v.ok === true) return typeof v.status === 'number' && 'body' in v;
  if (v.ok === false && v.kind === 'unknown') return typeof v.message === 'string';
  if (v.ok === false && v.kind === 'http') {
    const env = v.error as { error?: { code?: unknown } } | undefined;
    return typeof v.status === 'number' && typeof env?.error?.code === 'string';
  }
  return false;
}

export function isErrorCode(v: unknown): v is ErrorCode {
  return typeof v === 'string' && (ERROR_CODES as readonly string[]).includes(v);
}

/** Minimal Port surface so tests can use an in-memory pair. */
export interface PortLike {
  name: string;
  postMessage(msg: unknown): void;
  disconnect(): void;
  onMessage: { addListener(cb: (msg: unknown) => void): void; removeListener(cb: (msg: unknown) => void): void };
  onDisconnect: { addListener(cb: () => void): void; removeListener(cb: () => void): void };
}
