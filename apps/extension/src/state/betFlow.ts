// Pure bet-flow state machine. Success is shown ONLY after a receipt for the same operation_id.
// Unknown outcomes retry the SAME operation_id (CONTRACTS 9.7, 9.10); a new click is a new key.

import type { ErrorBody, WagerReceiptResponse, WagerRequest } from '@fazetime/contracts';
import type { ApiResult } from '../api/types';

export const MAX_AUTO_ATTEMPTS = 4;

export interface PendingWager {
  request: WagerRequest;
  attempts: number;
}

export type BetFlow =
  | { kind: 'idle' }
  | { kind: 'submitting'; pending: PendingWager }
  | { kind: 'unknown'; pending: PendingWager; message: string; retryInMs: number | null }
  | { kind: 'accepted'; receipt: WagerReceiptResponse; recovered: boolean }
  | { kind: 'rejected'; error: ErrorBody; request: WagerRequest };

export type BetAction =
  | { type: 'SUBMIT'; request: WagerRequest }
  | { type: 'RETRY' }
  | { type: 'RESULT'; operationId: string; result: ApiResult<WagerReceiptResponse> }
  | { type: 'RECOVER'; request: WagerRequest; message: string }
  | { type: 'DISMISS' };

export const IDLE: BetFlow = { kind: 'idle' };

export function backoffMs(attempts: number): number {
  return Math.min(1000 * 2 ** Math.max(0, attempts - 1), 8000);
}

export function isBusy(flow: BetFlow): boolean {
  return flow.kind === 'submitting' || flow.kind === 'unknown';
}

export function betReducer(state: BetFlow, action: BetAction): BetFlow {
  switch (action.type) {
    case 'SUBMIT':
      if (isBusy(state)) return state; // Never two economic operations in flight from one panel.
      return { kind: 'submitting', pending: { request: action.request, attempts: 1 } };
    case 'RECOVER':
      if (isBusy(state)) return state;
      return { kind: 'unknown', pending: { request: action.request, attempts: 0 }, message: action.message, retryInMs: 0 };
    case 'RETRY':
      if (state.kind !== 'unknown') return state;
      return { kind: 'submitting', pending: { request: state.pending.request, attempts: state.pending.attempts + 1 } };
    case 'DISMISS':
      return state.kind === 'accepted' || state.kind === 'rejected' ? IDLE : state;
    case 'RESULT': {
      if (state.kind !== 'submitting' && state.kind !== 'unknown') return state;
      const pending = state.pending;
      if (action.operationId !== pending.request.operation_id) return state; // Stale answer for another click.
      const r = action.result;
      if (r.ok) {
        if (r.body.operation_id !== pending.request.operation_id) return state;
        return { kind: 'accepted', receipt: r.body, recovered: pending.attempts !== 1 };
      }
      if (r.kind === 'http' && !r.error.error.retryable) return { kind: 'rejected', error: r.error.error, request: pending.request };
      const message =
        r.kind === 'http'
          ? `${r.error.error.code}: the outcome is unknown, checking again with the same request.`
          : r.message;
      const exhausted = pending.attempts >= MAX_AUTO_ATTEMPTS;
      const serverDelay = r.kind === 'http' ? r.error.error.retry_after_ms : null;
      return {
        kind: 'unknown',
        pending,
        message,
        retryInMs: exhausted ? null : (serverDelay ?? backoffMs(pending.attempts)),
      };
    }
  }
}
