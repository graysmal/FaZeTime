// Viewer copy for the tracked Stripe test top-up (P6, CONTRACTS 9.18). Everything here is derived from
// the SERVER status relayed by the background. The return-URL query parameter is only a polling hint:
// `cancelledHint` changes wording ("checkout was closed"), never the status, and never credits.

import type { TopUpTracking } from '../api/types';
import { formatMinor } from '../lib/money';

export interface TopUpCopy {
  tone: 'ok' | 'wait' | 'err';
  text: string;
  /** REOPEN: reopen Checkout with the same operation_id. CHECK: ask the server again. */
  action: 'REOPEN' | 'CHECK' | null;
  terminal: boolean;
}

export function creditedText(t: Pick<TopUpTracking, 'amount_minor' | 'previous_run'>): string {
  const base = `Test credits added: ${formatMinor(t.amount_minor)}`;
  return t.previous_run ? `${base}, credited to the previous demo run.` : base;
}

export function describeTopUp(t: TopUpTracking, cancelledHint = false): TopUpCopy {
  const amount = formatMinor(t.amount_minor);
  switch (t.status) {
    case 'CREDITED':
      return { tone: 'ok', text: creditedText(t), action: null, terminal: true };
    case 'FAILED':
      return { tone: 'err', text: `The ${amount} payment didn't go through. No credits were added.`, action: null, terminal: true };
    case 'EXPIRED':
      return { tone: 'err', text: `The ${amount} checkout expired. No credits were added.`, action: null, terminal: true };
    case 'SUBMITTING':
      return t.watching
        ? { tone: 'wait', text: 'Opening secure checkout…', action: null, terminal: false }
        : { tone: 'wait', text: `We couldn't confirm your ${amount} top-up request yet. Nothing is credited until Stripe confirms.`, action: 'REOPEN', terminal: false };
    case 'CREATED':
    case 'PENDING':
      if (t.checkout_blocked) return { tone: 'err', text: 'The checkout page could not be opened.', action: 'REOPEN', terminal: false };
      if (!t.watching) return { tone: 'wait', text: `Still waiting for Stripe to confirm your ${amount} top-up.`, action: 'CHECK', terminal: false };
      if (cancelledHint) return { tone: 'wait', text: `Checkout was closed before payment. No credits were added.`, action: 'REOPEN', terminal: false };
      if (t.status === 'CREATED' || !t.checkout_opened) return { tone: 'wait', text: `Preparing your ${amount} checkout…`, action: 'REOPEN', terminal: false };
      return { tone: 'wait', text: `Finish paying ${amount} in the Stripe tab. Credits appear here once Stripe confirms.`, action: 'REOPEN', terminal: false };
  }
}
