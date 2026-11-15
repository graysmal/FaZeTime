// Display-only formatting. Money is integer minor units (100 = one demo dollar); never floats.

/**
 * Display currency (owner request, 2026-11-15): the Odyssey (Θ) theme shows drachmas at 1 ₯ = $1. Display only:
 * every amount stays in integer cents end to end, and the server, Stripe and the ledger never see a drachma.
 */
export type DisplayCurrency = 'USD' | 'DRACHMA';
let displayCurrency: DisplayCurrency = 'USD';
export function setDisplayCurrency(c: DisplayCurrency): void {
  displayCurrency = c;
}
export function currencySymbol(): string {
  return displayCurrency === 'DRACHMA' ? '₯' : '$';
}

export function formatMinor(minor: number | null | undefined): string {
  if (typeof minor !== 'number' || !Number.isSafeInteger(minor)) return '?';
  const sign = minor < 0 ? '-' : '';
  const abs = Math.abs(minor);
  const dollars = Math.trunc(abs / 100);
  const cents = abs % 100;
  return `${sign}${currencySymbol()}${dollars.toLocaleString('en-US')}.${cents.toString().padStart(2, '0')}`;
}

/** Milliseconds between two RFC 3339 instants (b − a), or null if either is missing/invalid. */
export function diffMs(a: string | null | undefined, b: string | null | undefined): number | null {
  if (!a || !b) return null;
  const ta = Date.parse(a);
  const tb = Date.parse(b);
  if (Number.isNaN(ta) || Number.isNaN(tb)) return null;
  return tb - ta;
}

export function formatDuration(ms: number | null): string {
  if (ms === null) return '—';
  const neg = ms < 0;
  const abs = Math.abs(ms);
  let out: string;
  if (abs < 10_000) out = `${(abs / 1000).toFixed(1)} s`;
  else if (abs < 120_000) out = `${Math.round(abs / 1000)} s`;
  else {
    const m = Math.floor(abs / 60_000);
    const s = Math.round((abs % 60_000) / 1000);
    out = `${m} m ${s.toString().padStart(2, '0')} s`;
  }
  return neg ? `-${out}` : out;
}

/** "03:53:18Z": the UTC wall-clock part of an RFC 3339 timestamp. */
export function formatUtcClock(utc: string | null | undefined): string {
  if (!utc) return '—';
  const m = /T(\d{2}:\d{2}:\d{2})(?:\.\d+)?Z$/.exec(utc);
  return m ? `${m[1]}Z` : utc;
}

/** "11-16 04:14Z": month-day plus UTC time, for expiries that are hours or days away. */
export function formatUtcDayTime(utc: string | null | undefined): string {
  if (!utc) return '—';
  const m = /^\d{4}-(\d{2})-(\d{2})T(\d{2}:\d{2})/.exec(utc);
  return m ? `${m[1]}-${m[2]} ${m[3]}Z` : utc;
}

/** Media position within one source epoch: "m:ss.mmm". */
export function formatMediaMs(ms: number | null | undefined): string {
  if (typeof ms !== 'number' || !Number.isFinite(ms) || ms < 0) return '—';
  const total = Math.floor(ms);
  const m = Math.floor(total / 60_000);
  const s = Math.floor((total % 60_000) / 1000);
  const r = total % 1000;
  return `${m}:${s.toString().padStart(2, '0')}.${r.toString().padStart(3, '0')}`;
}

export function shortId(id: string | null | undefined): string {
  if (!id) return '—';
  const [prefix, rest] = id.split('_', 2);
  return rest ? `${prefix}_${rest.slice(0, 8)}…` : id;
}

/** Crockford base32 invite code: hyphens/spaces removed, upper-cased (CONTRACTS §9.8). */
export function normalizeInvite(input: string): string {
  return input.replace(/[\s-]/g, '').toUpperCase();
}

export const INVITE_RE = /^[0-9A-HJKMNP-TV-Z]{12}$/;
