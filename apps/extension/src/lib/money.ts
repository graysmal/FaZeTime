// Integer minor-unit helpers. Never use floats for money (CONTRACTS 9.1, ECONOMICS 2).
import type { Limits, Pool, Side } from '@fazetime/contracts';

/** "$1,234.05" for 123405 demo cents. Display only. */
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

export function formatMinor(minor: number): string {
  if (!Number.isSafeInteger(minor)) return '$?';
  const sign = minor < 0 ? '-' : '';
  const abs = Math.abs(minor);
  const dollars = Math.trunc(abs / 100);
  const cents = abs % 100;
  return `${sign}${currencySymbol()}${dollars.toLocaleString('en-US')}.${cents.toString().padStart(2, '0')}`;
}

/** Parse a user-typed dollar amount ("5", "5.5", "$5.50") into integer cents without floats. */
export function parseDollarsToMinor(input: string): number | null {
  const s = input.trim().replace(/^[$₯]/, '').replace(/,/g, '');
  const m = /^(\d{1,7})(?:\.(\d{0,2}))?$/.exec(s);
  if (!m) return null;
  const dollars = Number.parseInt(m[1] ?? '0', 10);
  const centsText = (m[2] ?? '').padEnd(2, '0');
  const cents = Number.parseInt(centsText, 10);
  return dollars * 100 + cents;
}

/** Minor units to an input string ("5" or "5.50"). */
export function minorToInput(minor: number): string {
  const cents = minor % 100;
  const dollars = Math.trunc(minor / 100);
  return cents === 0 ? String(dollars) : `${dollars}.${cents.toString().padStart(2, '0')}`;
}

/**
 * Estimated gross return including stake, shown before lock (CONTRACTS 9.6):
 * floor(s * (T + s) / (W_side + s)). BigInt keeps the arithmetic exact. An estimate only:
 * later bets change it and the server settles (ECONOMICS 4).
 */
export function estimateGrossReturn(stakeMinor: number, pool: Pool, side: Side): number {
  if (!Number.isSafeInteger(stakeMinor) || stakeMinor <= 0) return 0;
  const s = BigInt(stakeMinor);
  const t = BigInt(pool.total_minor);
  const w = BigInt(side === 'YES' ? pool.yes_minor : pool.no_minor);
  return Number((s * (t + s)) / (w + s));
}

export type AmountProblem = 'NOT_A_NUMBER' | 'BELOW_MIN' | 'ABOVE_MAX' | 'OFF_STEP';

export function checkStake(amount: number | null, limits: Limits): AmountProblem | null {
  return checkRange(amount, limits.stake_min_minor, limits.stake_max_minor, limits.stake_step_minor);
}

/** Top-up: a preset, or a custom amount within min/max on the step (CONTRACTS 9.2). */
export function checkTopUp(amount: number | null, limits: Limits): AmountProblem | null {
  if (amount !== null && limits.topup_presets_minor.includes(amount)) return null;
  return checkRange(amount, limits.topup_min_minor, limits.topup_max_minor, limits.topup_step_minor);
}

function checkRange(amount: number | null, min: number, max: number, step: number): AmountProblem | null {
  if (amount === null || !Number.isSafeInteger(amount)) return 'NOT_A_NUMBER';
  if (amount < min) return 'BELOW_MIN';
  if (amount > max) return 'ABOVE_MAX';
  if (step > 0 && amount % step !== 0) return 'OFF_STEP';
  return null;
}

export function describeAmountProblem(problem: AmountProblem, min: number, max: number, step: number): string {
  switch (problem) {
    case 'NOT_A_NUMBER':
      return 'Enter an amount like 5 or 5.00.';
    case 'BELOW_MIN':
      return `Minimum is ${formatMinor(min)}.`;
    case 'ABOVE_MAX':
      return `Maximum is ${formatMinor(max)}.`;
    case 'OFF_STEP':
      return `Use steps of ${formatMinor(step)}.`;
  }
}

/** Integer percentage for display (pool share); never used for money. */
export function sharePercent(part: number, total: number): number {
  if (total <= 0) return 0;
  return Math.round((part * 100) / total);
}
