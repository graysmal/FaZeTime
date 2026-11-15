// Display-only approval deadlines for an AI candidate (§9.17 items 2 and 5e). The server re-checks every rule
// at approval; these numbers only tell the operator how long they have.
import type { AiCandidate } from '../api/types';

export type Binding = 'EXPIRY' | 'EVIDENCE' | 'LEAD';

export interface CandidateDeadlines {
  /** expires_at_utc (60 s after receipt) minus now. */
  expiryMs: number | null;
  /** Oldest cited evidence receipt + evidence_fresh_s (90 s) minus now. */
  evidenceMs: number | null;
  /** Receipt-anchored close minus min lead minus now (only without an operator close_in_s override). */
  leadMs: number | null;
  /** The smallest of the above: time left to approve. */
  approveMs: number | null;
  binding: Binding | null;
}

const ms = (utc: string | null | undefined): number | null => {
  if (!utc) return null;
  const t = Date.parse(utc);
  return Number.isNaN(t) ? null : t;
};

export function candidateDeadlines(
  c: Pick<AiCandidate, 'expires_at_utc' | 'evidence' | 'proposed_close_at_utc'>,
  serverNowMs: number,
  opts: { evidenceFreshS: number; minLeadMs: number; override: boolean },
): CandidateDeadlines {
  const exp = ms(c.expires_at_utc);
  const expiryMs = exp === null ? null : exp - serverNowMs;
  const received = (c.evidence ?? []).map((e) => ms(e.received_at_utc)).filter((t): t is number => t !== null);
  const evidenceMs = received.length ? Math.min(...received) + opts.evidenceFreshS * 1000 - serverNowMs : null;
  const close = ms(c.proposed_close_at_utc);
  const leadMs = opts.override || close === null ? null : close - opts.minLeadMs - serverNowMs;
  let approveMs: number | null = null;
  let binding: Binding | null = null;
  for (const [value, name] of [
    [expiryMs, 'EXPIRY'],
    [evidenceMs, 'EVIDENCE'],
    [leadMs, 'LEAD'],
  ] as const) {
    if (value !== null && (approveMs === null || value < approveMs)) {
      approveMs = value;
      binding = name;
    }
  }
  return { expiryMs, evidenceMs, leadMs, approveMs, binding };
}

export const BINDING_TEXT: Record<Binding, string> = {
  EXPIRY: 'candidate expiry (60 s after receipt)',
  EVIDENCE: 'evidence freshness (90 s after the oldest cited evidence)',
  LEAD: 'minimum lead before the receipt-anchored close',
};
