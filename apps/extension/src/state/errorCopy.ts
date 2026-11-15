// Viewer copy for typed errors (CONTRACTS 9.10). Server `message` text is untrusted and only shown
// as plain text for codes this client does not know.

import type { ErrorBody, Side } from '@fazetime/contracts';
import { formatMinor } from '../lib/money';

export interface ErrorCopy {
  title: string;
  detail: string;
  /** Suggested follow-up for the controller/UI. */
  action: 'NONE' | 'OPEN_TOPUP' | 'REFRESH';
}

const d = (body: ErrorBody) => (body.details ?? {}) as Record<string, unknown>;
const money = (v: unknown) => (typeof v === 'number' ? formatMinor(v) : '?');

export function describeError(body: ErrorBody, labelFor: (side: Side) => string = (s) => (s === 'YES' ? 'Yes' : 'No')): ErrorCopy {
  const det = d(body);
  switch (body.code) {
    case 'UNAUTHENTICATED':
      return { title: 'Session expired', detail: 'Enroll again with a new invite code.', action: 'NONE' };
    case 'FORBIDDEN':
      return { title: 'Not allowed', detail: 'This session cannot do that.', action: 'NONE' };
    case 'INVALID_AMOUNT':
      return {
        title: 'Check the amount',
        detail: `Use ${money(det.min_minor)} to ${money(det.max_minor)} in steps of ${money(det.step_minor)}.`,
        action: 'NONE',
      };
    case 'INSUFFICIENT_FUNDS':
      return {
        title: 'Not enough demo funds',
        detail: `You have ${money(det.available_minor)}; this needs ${money(det.requested_minor)}. Top up, then place the bet again. The market may close meanwhile.`,
        action: 'OPEN_TOPUP',
      };
    case 'MARKET_CLOSED': {
      const reason = det.reason === 'PAUSED' ? 'Wagering is paused.' : det.reason === 'DEADLINE' ? 'The deadline passed.' : 'The market is no longer open.';
      return { title: 'Betting is closed', detail: `${reason} No funds were taken.`, action: 'REFRESH' };
    }
    case 'STALE_MARKET':
      return { title: 'The market changed', detail: 'Review the current market and place your bet again. No funds were taken.', action: 'REFRESH' };
    case 'WRONG_RUN':
      return { title: 'A new demo run started', detail: 'Wallets were re-seeded. No funds were taken.', action: 'REFRESH' };
    case 'IDEMPOTENCY_CONFLICT':
      return { title: 'Request conflict', detail: 'That request ID was already used differently. Nothing was charged; try again.', action: 'REFRESH' };
    case 'CAPABILITY_UNAVAILABLE':
      return { title: 'Unavailable right now', detail: 'This feature is not available at the moment.', action: 'NONE' };
    case 'SOURCE_STALE':
      return { title: 'Stream source not live', detail: 'Betting pauses while the stream feed is stale. No funds were taken.', action: 'REFRESH' };
    case 'RATE_LIMITED':
      return { title: 'Slow down', detail: 'Too many requests. Retrying shortly with the same request.', action: 'NONE' };
    case 'VALIDATION_FAILED':
      return { title: 'Request rejected', detail: 'The request was invalid. No funds were taken.', action: 'NONE' };
    case 'SIDE_CONFLICT': {
      const existing = det.existing_side === 'YES' || det.existing_side === 'NO' ? labelFor(det.existing_side) : 'the other side';
      return { title: 'One side per market', detail: `You already backed ${existing}. You can add to that side only.`, action: 'REFRESH' };
    }
    case 'NOT_FOUND':
      return { title: 'Not found', detail: 'Nothing matched that request.', action: 'NONE' };
    case 'INTERNAL_ERROR':
      return { title: 'Outcome unknown', detail: 'Checking again with the same request.', action: 'NONE' };
    default:
      return { title: 'Unavailable', detail: String(body.message ?? 'Unknown error').slice(0, 200), action: 'NONE' };
  }
}
