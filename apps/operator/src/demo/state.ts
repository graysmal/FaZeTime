// Demo view state machine (pure, display only). The server owns every deadline and transition; this only picks
// which ONE card to show from the polled operator health, candidates and resolutions.
import { ApiFailure } from '../api/client';
import type { AiCandidate, AiResolution, OperatorHealth, OperatorMarket } from '../api/types';
import { formatMinor } from '../ui/format';

const AI_ORIGINS = new Set(['AI_APPROVED', 'AI_AUTOMATIC']);
const FIXTURE_ORIGINS = new Set(['OPERATOR_FIXTURE', 'CANNED_FIXTURE']);
const NONTERMINAL = new Set(['OPEN', 'LOCKED', 'EVALUATING']);
const TERMINAL = new Set(['SETTLED', 'VOID']);

export type DemoState =
  | { kind: 'loading' }
  | { kind: 'no_stream' }
  | { kind: 'idle' }
  | { kind: 'candidate'; candidate: AiCandidate }
  | { kind: 'open'; market: OperatorMarket }
  | { kind: 'closed'; market: OperatorMarket }
  | { kind: 'suggestion'; market: OperatorMarket; resolution: AiResolution }
  | { kind: 'fixture_call'; market: OperatorMarket }
  | { kind: 'result'; market: OperatorMarket };

export interface DemoInput {
  health: OperatorHealth | null;
  candidates: AiCandidate[] | null;
  resolutions: AiResolution[] | null;
}

export const isAiMarket = (m: OperatorMarket) => AI_ORIGINS.has(m.origin);
export const isFixtureMarket = (m: OperatorMarket) => FIXTURE_ORIGINS.has(m.origin);

/** The run's one nonterminal market (health lists the current run's markets, newest first). */
export function currentMarket(health: OperatorHealth | null): OperatorMarket | null {
  return health?.markets?.find((m) => NONTERMINAL.has(m.state)) ?? null;
}

/**
 * Precedence: a nonterminal market first (an AI result suggestion, a fixture call, open, closed), then a
 * pending AI candidate, then the latest result, then idle. A candidate cannot be approved while a market is
 * nonterminal (MARKET_BUSY), so it never hides a live market.
 */
export function deriveDemoState({ health, candidates, resolutions }: DemoInput): DemoState {
  if (!health) return { kind: 'loading' };
  if (!health.stream) return { kind: 'no_stream' };
  const market = currentMarket(health);
  if (market) {
    if (market.state === 'OPEN') return { kind: 'open', market };
    if (isAiMarket(market)) {
      const resolution = (resolutions ?? []).find(
        (r) => r.market_id === market.market_id && r.actionable && r.status === 'PENDING_APPROVAL',
      );
      if (resolution && market.state === 'EVALUATING') return { kind: 'suggestion', market, resolution };
      return { kind: 'closed', market };
    }
    if (market.state === 'EVALUATING' && isFixtureMarket(market)) return { kind: 'fixture_call', market };
    return { kind: 'closed', market };
  }
  const pending = (candidates ?? [])
    .filter((c) => c.actionable && c.status === 'PENDING')
    .sort((a, b) => Date.parse(b.received_at_utc) - Date.parse(a.received_at_utc));
  if (pending[0]) return { kind: 'candidate', candidate: pending[0] };
  const last = health.markets?.find((m) => m.state !== 'DRAFT') ?? null;
  if (last && TERMINAL.has(last.state)) return { kind: 'result', market: last };
  return { kind: 'idle' };
}

/** Stable identity for a card: its action state resets when the card changes. */
export function cardKey(s: DemoState): string {
  switch (s.kind) {
    case 'candidate':
      return `candidate:${s.candidate.id}`;
    case 'suggestion':
      return `suggestion:${s.resolution.id}`;
    case 'open':
    case 'closed':
    case 'fixture_call':
    case 'result':
      return `${s.kind}:${s.market.market_id}`;
    default:
      return s.kind;
  }
}

/** A key per "needs the operator now" moment (sound alert once each), or null. */
export function alertKey(s: DemoState): string | null {
  if (s.kind === 'candidate' || s.kind === 'suggestion' || s.kind === 'fixture_call') return cardKey(s);
  return null;
}

export type PillTone = 'live' | 'connecting' | 'offline';
export interface Pill {
  text: string;
  tone: PillTone;
}

/** ONE stream pill from source health: LIVE, Connecting… (CONNECTING/STALE/GAP, or no fresh health), OFFLINE. */
export function streamPill(health: OperatorHealth | null, healthStale: boolean): Pill {
  if (!health || healthStale) return { text: 'Connecting…', tone: 'connecting' };
  const state = health.source_health?.state ?? 'STOPPED';
  if (state === 'LIVE') return { text: 'LIVE', tone: 'live' };
  if (state === 'STOPPED') return { text: 'OFFLINE', tone: 'offline' };
  return { text: 'Connecting…', tone: 'connecting' };
}

export function sideLabel(m: Pick<OperatorMarket, 'yes_label' | 'no_label'>, side: 'YES' | 'NO'): string {
  return side === 'YES' ? m.yes_label : m.no_label;
}

/** "Yes $5.00 · No $7.00 · 2 bets", with the market's own side labels. */
export function poolLine(m: OperatorMarket): string {
  const n = m.pool.wager_count;
  return `${m.yes_label} ${formatMinor(m.pool.yes_minor)} · ${m.no_label} ${formatMinor(m.pool.no_minor)} · ${n} ${n === 1 ? 'bet' : 'bets'}`;
}

export function resultText(m: OperatorMarket): string {
  if (m.state === 'SETTLED' && (m.winning_side === 'YES' || m.winning_side === 'NO')) {
    return `${sideLabel(m, m.winning_side)} won. Winners paid.`;
  }
  return 'Voided. Everyone refunded.';
}

export function suggestionText(m: OperatorMarket, r: AiResolution): string {
  if (r.decision === 'YES' || r.decision === 'NO') return `AI says: ${sideLabel(m, r.decision)} won`;
  return 'AI says: no clear winner';
}

/** Big countdown text: "1:05", "0:09"; never negative. */
export function countdownText(ms: number | null): string {
  if (ms === null || !Number.isFinite(ms)) return '–:––';
  const total = Math.max(0, Math.ceil(ms / 1000));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
}

/** Server-clock estimate: the last server_time_utc plus local time elapsed since it arrived. */
export function serverNow(serverTimeUtc: string | null | undefined, okAt: number | null, now: number): number | null {
  if (!serverTimeUtc || okAt === null) return null;
  const t = Date.parse(serverTimeUtc);
  return Number.isNaN(t) ? null : t + Math.max(0, now - okAt);
}

export function msUntil(utc: string | null | undefined, serverNowMs: number | null): number | null {
  if (!utc || serverNowMs === null) return null;
  const t = Date.parse(utc);
  return Number.isNaN(t) ? null : t - serverNowMs;
}

const REJECT_TEXT: Record<string, string> = {
  EXPIRED: 'Too late to approve: it expired.',
  INSUFFICIENT_LEAD: 'Too late to approve: not enough betting time left.',
  STALE_EVIDENCE: 'Too late to approve: what the AI saw is too old now.',
  MARKET_BUSY: 'Another bet is still running. Finish it first.',
  SOURCE_NOT_LIVE: "The stream isn't live, so this bet can't open.",
  STALE_EPOCH: 'The stream restarted, so this no longer counts.',
  DUPLICATE_EPISODE: 'This bet was already used. Reset for the next take.',
  UNPAIRED_SIDES: "The AI's two sides don't match up, so it can't open.",
};

const KNOWN_MODES = new Set(['OFF', 'SHADOW', 'APPROVAL', 'AUTOMATIC']);

/** One short human sentence for any failure. Never the raw envelope (codes stay in the Advanced view). */
export function errorSentence(e: unknown): string {
  if (!(e instanceof ApiFailure)) return "That didn't go through. Try again.";
  if (e.outcomeUnknown) return 'No answer from the server, so it may or may not have gone through.';
  if (e.kind === 'network' || e.kind === 'timeout') return "Can't reach the server.";
  if (e.kind === 'aborted') return 'Cancelled.';
  const details = e.info?.details && typeof e.info.details === 'object' ? (e.info.details as Record<string, unknown>) : {};
  const reject = typeof details.reject_code === 'string' ? details.reject_code : null;
  if (reject && REJECT_TEXT[reject]) return REJECT_TEXT[reject];
  switch (e.code) {
    case 'MARKET_CLOSED':
      if (details.reason === 'DEADLINE') return 'Too late: the deadline passed.';
      if (details.reason === 'PAUSED') return 'Betting is paused.';
      return 'Too late: that already moved on.';
    case 'STALE_MARKET':
      return 'Another bet is still running. Finish it first.';
    case 'SOURCE_STALE':
      return "The stream isn't live right now.";
    case 'FORBIDDEN': {
      const mode = typeof details.ai_mode === 'string' && KNOWN_MODES.has(details.ai_mode) ? details.ai_mode : null;
      return mode ? `AI is set to ${mode}. Switch it to APPROVAL under Advanced.` : "That isn't allowed.";
    }
    case 'NOT_FOUND':
      return "It's gone: there is nothing to act on.";
    case 'RATE_LIMITED':
      return 'Too many clicks. Wait a moment, then try again.';
    case 'VALIDATION_FAILED':
      return "The server didn't accept those details.";
    case 'IDEMPOTENCY_CONFLICT':
      return 'That click was already used. Nothing changed.';
    case 'UNAUTHENTICATED':
      return 'Reconnecting…';
    case 'CAPABILITY_UNAVAILABLE':
      return "This server can't do that yet.";
    case 'INTERNAL_ERROR':
      return 'Server error. Try again.';
    default:
      return "That didn't go through. Try again.";
  }
}

/** The one-line connection message for a failing health poll, or null while health is fresh. */
export function connectionSentence(error: unknown, stale: boolean): string | null {
  if (!stale || error === null || error === undefined) return null;
  if (error instanceof ApiFailure && error.status === 401) return 'Reconnecting…';
  return "Can't reach the server. Retrying…";
}
