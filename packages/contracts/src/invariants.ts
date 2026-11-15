// Section 9.14 invariants shared by the fixture tests and the extension (defence in depth on
// untrusted snapshots). These check consistency only; the backend stays authoritative.

import {
  AVAILABLE_BALANCE_MAX_MINOR,
  SETTLEMENT_ALGORITHM_V1,
  TERMINAL_BANNER_BY_RESULT,
  UNRESOLVED_VOID_REASONS,
  type Banner,
  type Limits,
  type MyPosition,
  type MyResult,
  type Pool,
  type PublicMarket,
  type StreamSnapshot,
} from './v1';
import type { Issue } from './validate';

export const isTerminalState = (state: string): boolean => state === 'SETTLED' || state === 'VOID';

export function checkPool(pool: Pool, path = 'pool'): Issue[] {
  const issues: Issue[] = [];
  if (pool.total_minor !== pool.yes_minor + pool.no_minor)
    issues.push({ path, message: `total_minor ${pool.total_minor} != yes ${pool.yes_minor} + no ${pool.no_minor}` });
  if (pool.simulated_minor > pool.total_minor) issues.push({ path, message: 'simulated_minor exceeds total_minor' });
  return issues;
}

export function checkMarket(market: PublicMarket, path = 'market', opts: { viewer?: boolean } = {}): Issue[] {
  const viewer = opts.viewer ?? true;
  const issues: Issue[] = [...checkPool(market.pool, `${path}.pool`)];
  const add = (message: string) => issues.push({ path, message });
  if (viewer && market.state === 'DRAFT') add('DRAFT must never appear in a viewer payload');
  if ((market.winning_side !== null) !== (market.state === 'SETTLED')) add('winning_side must be present iff SETTLED');
  if ((market.void_reason !== null) !== (market.state === 'VOID')) add('void_reason must be present iff VOID');
  const algoOk = market.state === 'SETTLED' ? market.settlement_algorithm === SETTLEMENT_ALGORITHM_V1 : market.settlement_algorithm === null;
  if (!algoOk) add(`settlement_algorithm must be ${SETTLEMENT_ALGORITHM_V1} iff SETTLED`);
  if ((market.terminal_at_utc !== null) !== isTerminalState(market.state)) add('terminal_at_utc must be present iff terminal');
  if ((market.state === 'LOCKED' || market.state === 'EVALUATING') && market.locked_at_utc === null) add('locked_at_utc required once LOCKED');
  if (market.state === 'SETTLED') {
    const w = market.winning_side === 'YES' ? market.pool.yes_minor : market.pool.no_minor;
    if (!(w > 0 && w < market.pool.total_minor)) add('SETTLED requires 0 < W < T');
  }
  if (viewer && market.aggregate_version < 2) add('viewers first see aggregate_version >= 2 (DRAFT is 1, section 9.15(4))');
  if (market.opened_at_utc && Date.parse(market.opened_at_utc) >= Date.parse(market.close_at_utc)) add('opened_at_utc must precede close_at_utc');
  if (Date.parse(market.close_at_utc) > Date.parse(market.resolve_by_utc)) add('close_at_utc must not follow resolve_by_utc');
  return issues;
}

/** The MyResult a position must carry for its market state (one side per market). */
export function expectedResult(market: PublicMarket, position: Pick<MyPosition, 'side' | 'stake_total_minor'>): MyResult {
  if (position.side === null || position.stake_total_minor === 0) return 'NONE';
  if (market.state === 'SETTLED') return market.winning_side === position.side ? 'WON' : 'LOST';
  if (market.state === 'VOID')
    return (UNRESOLVED_VOID_REASONS as readonly string[]).includes(market.void_reason ?? '') ? 'UNRESOLVED_REFUNDED' : 'VOID_REFUNDED';
  return 'PENDING';
}

/** Banner for a snapshot: null while no market or nonterminal, else exactly one banner. */
export function bannerFor(market: PublicMarket | null, position: MyPosition | null): Banner | null {
  if (!market || !isTerminalState(market.state)) return null;
  const result = position?.result ?? 'NONE';
  if (result === 'PENDING') return null;
  return TERMINAL_BANNER_BY_RESULT[result] ?? null;
}

export function checkPosition(market: PublicMarket, position: MyPosition, path = 'my_position'): Issue[] {
  const issues: Issue[] = [];
  const add = (message: string) => issues.push({ path, message });
  if (position.market_id !== market.market_id) add('market_id differs from snapshot market');
  const sum = position.wagers.reduce((s, w) => s + w.amount_minor, 0);
  if (sum !== position.stake_total_minor) add(`stake_total_minor ${position.stake_total_minor} != sum of wagers ${sum}`);
  const sides = new Set(position.wagers.map((w) => w.side));
  if (sides.size > 1) add('a user may bet only one side per market');
  if (position.wagers.length > 0 && position.side !== position.wagers[0]?.side) add('side differs from wagers');
  if (position.wagers.length === 0 && position.side !== null) add('side must be null without wagers');
  for (const w of position.wagers) if (w.market_id !== market.market_id) add(`wager ${w.wager_id} belongs to another market`);
  const expected = expectedResult(market, position);
  if (position.result !== expected) add(`result ${position.result} inconsistent with market state (expected ${expected})`);
  const r = position.result;
  if (r === 'WON' && !(position.payout_total_minor !== null && position.payout_total_minor >= position.stake_total_minor))
    add('WON requires payout_total_minor >= stake (gross including stake)');
  if (r === 'LOST' && position.payout_total_minor !== 0) add('LOST requires payout_total_minor = 0');
  if (r !== 'WON' && r !== 'LOST' && position.payout_total_minor !== null) add('payout_total_minor only for WON/LOST');
  const refunded = r === 'VOID_REFUNDED' || r === 'UNRESOLVED_REFUNDED';
  if (refunded && position.refund_total_minor !== position.stake_total_minor) add('refund_total_minor must equal the stake');
  if (!refunded && position.refund_total_minor !== null) add('refund_total_minor only for refunded results');
  return issues;
}

export function checkStakeAmount(amount: number, limits: Limits): string | null {
  if (!Number.isSafeInteger(amount)) return 'not an integer';
  if (amount < limits.stake_min_minor || amount > limits.stake_max_minor) return 'outside stake limits';
  if (amount % limits.stake_step_minor !== 0) return 'not a multiple of the stake step';
  return null;
}

export function checkSnapshot(snapshot: StreamSnapshot): Issue[] {
  const issues: Issue[] = [];
  const run = snapshot.stream.stream_session_id;
  if (snapshot.wallet.stream_session_id !== run) issues.push({ path: 'wallet', message: 'wallet run differs from stream run' });
  if (snapshot.wallet.available_minor > AVAILABLE_BALANCE_MAX_MINOR) issues.push({ path: 'wallet', message: 'available exceeds 1,000,000' });
  if ((snapshot.market === null) !== (snapshot.my_position === null))
    issues.push({ path: 'my_position', message: 'my_position is present iff market is present' });
  if (snapshot.stream.wagering_paused !== (snapshot.stream.wagering_paused_reason !== null))
    issues.push({ path: 'stream', message: 'wagering_paused_reason is present iff wagering_paused' });
  // Section 9.15(2): paused iff the current market is OPEN and (OPERATOR_PAUSE or Twitch-origin with a non-LIVE source).
  const mk = snapshot.market;
  const twitchSourceDown = mk !== null && mk.state === 'OPEN' && (mk.origin === 'AI_APPROVED' || mk.origin === 'AI_AUTOMATIC') && snapshot.source_health.state !== 'LIVE';
  if (snapshot.stream.wagering_paused && mk?.state !== 'OPEN') issues.push({ path: 'stream', message: 'wagering_paused requires an OPEN market' });
  if (twitchSourceDown && !snapshot.stream.wagering_paused) issues.push({ path: 'stream', message: 'Twitch-origin OPEN market with a non-LIVE source must be paused' });
  const m = snapshot.market;
  if (m) {
    issues.push(...checkMarket(m, 'market', { viewer: true }));
    if (m.stream_session_id !== run) issues.push({ path: 'market', message: 'market run differs from stream run' });
    if (snapshot.my_position) {
      issues.push(...checkPosition(m, snapshot.my_position));
      const inPlayExpected = isTerminalState(m.state) ? 0 : snapshot.my_position.stake_total_minor;
      if (snapshot.wallet.in_play_minor !== inPlayExpected)
        issues.push({ path: 'wallet.in_play_minor', message: `expected ${inPlayExpected} in play` });
      for (const w of snapshot.my_position.wagers) {
        const problem = checkStakeAmount(w.amount_minor, snapshot.limits);
        if (problem) issues.push({ path: `my_position.wagers.${w.wager_id}`, message: problem });
      }
    }
  } else if (snapshot.wallet.in_play_minor !== 0) {
    issues.push({ path: 'wallet.in_play_minor', message: 'nothing can be in play without a market' });
  }
  return issues;
}
