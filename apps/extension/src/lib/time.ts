// Server-time offset and display countdown. Display only: the server decides acceptance
// (`close_at_utc` is exclusive and checked at commit time, CONTRACTS 9.3).
import type { MarketResultEta } from '../api/types';

/** Offset to add to the local clock to estimate server time. */
export function serverOffsetMs(serverTimeUtc: string, receivedAtLocalMs: number): number {
  const server = Date.parse(serverTimeUtc);
  return Number.isNaN(server) ? 0 : server - receivedAtLocalMs;
}

export function remainingMs(closeAtUtc: string, nowLocalMs: number, offsetMs: number): number {
  const close = Date.parse(closeAtUtc);
  if (Number.isNaN(close)) return 0;
  return close - (nowLocalMs + offsetMs);
}

/** "2:00", "0:09", "1:02:03"; clamps at 0:00. Rounds up so 0:00 shows only once closed. */
export function formatCountdown(ms: number): string {
  const total = Math.max(0, Math.ceil(ms / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const ss = s.toString().padStart(2, '0');
  return h > 0 ? `${h}:${m.toString().padStart(2, '0')}:${ss}` : `${m}:${ss}`;
}

const AI_ORIGINS = new Set(['AI_APPROVED', 'AI_AUTOMATIC']);
const RESULT_PENDING_STATES = new Set(['LOCKED', 'EVALUATING']);

/** The fields the result-pending check reads (PublicMarket plus the optional 9.20 field). */
export type EtaMarket = { state: string; origin: string; winning_side?: unknown; void_reason?: unknown } & MarketResultEta;

/** The market's expected result time (CONTRACTS 9.20 item 2) in ms, or null when absent, null or unreadable. */
export function expectedResultAtMs(market: MarketResultEta | null | undefined): number | null {
  const v: unknown = market?.expected_result_at_utc; // untrusted: checked at runtime
  if (typeof v !== 'string') return null;
  const t = Date.parse(v);
  return Number.isNaN(t) ? null : t;
}

/** True while a market could still turn into "AI is watching for the result…" (the clock must keep ticking). */
export function awaitsExpectedResult(market: EtaMarket | null | undefined): boolean {
  return Boolean(market && RESULT_PENDING_STATES.has(market.state) && AI_ORIGINS.has(market.origin) && expectedResultAtMs(market) !== null);
}

/**
 * CONTRACTS 9.20 item 2: an AI market is LOCKED or EVALUATING, its expected result time has passed by the
 * server-time estimate (local clock + offset), and there is no result yet. Display only.
 */
export function resultPending(market: EtaMarket | null | undefined, nowLocalMs: number, offsetMs: number): boolean {
  if (!market || !awaitsExpectedResult(market) || market.winning_side || market.void_reason) return false;
  const at = expectedResultAtMs(market);
  return at !== null && nowLocalMs + offsetMs >= at;
}
