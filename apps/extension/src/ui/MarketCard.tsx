import { useEffect, useState } from 'react';
import {
  FIXTURE_MARKET_ORIGINS,
  LOSS_BANNER_TEXT,
  VIEWER_MARKET_STATES,
  bannerFor,
  type Banner,
  type MarketOrigin,
  type Modes,
  type MyPosition,
  type PublicMarket,
  type Side,
  type VoidReason,
} from '@fazetime/contracts';
import {
  checkStake,
  describeAmountProblem,
  estimateGrossReturn,
  formatMinor,
  minorToInput,
  parseDollarsToMinor,
  sharePercent,
  currencySymbol,
} from '../lib/money';
import { awaitsExpectedResult, formatCountdown, remainingMs, resultPending } from '../lib/time';
import { isBusy } from '../state/betFlow';
import { aiName } from './OdysseyDecor';
import { describeError } from '../state/errorCopy';
import { useEnv, useNow, usePanel } from './hooks';

export const ORIGIN_TEXT: Record<MarketOrigin, string> = {
  OPERATOR_FIXTURE: 'Operator fixture',
  CANNED_FIXTURE: 'Canned fixture',
  AI_APPROVED: 'AI proposal, operator approved',
  AI_AUTOMATIC: 'AI proposal, automatic',
};

export const VOID_REASON_TEXT: Record<VoidReason, string> = {
  EMPTY_POOL: 'Nobody placed a bet',
  ONE_SIDED_POOL: 'Only one side had bets at close',
  UNRESOLVABLE: 'The evidence could not decide the outcome',
  RESOLUTION_TIMEOUT: 'No result arrived before the deadline',
  SOURCE_GAP: 'The stream feed dropped out',
  RUN_RESET: 'The demo run was reset',
  OPERATOR_CANCELLED: 'The operator cancelled the market',
};

const STATE_TEXT: Record<string, string> = {
  OPEN: 'OPEN',
  LOCKED: 'LOCKED',
  EVALUATING: 'EVALUATING',
  SETTLED: 'SETTLED',
  VOID: 'VOID',
};

/** Viewer origin text. Live builds (D31): fixture origins are shown like any market (no label). */
export function viewerOriginLabel(origin: string, modes: Modes | undefined, mode: 'mock' | 'live'): string | null {
  if (mode === 'mock') return originLabel(origin, modes);
  return origin === 'AI_APPROVED' || origin === 'AI_AUTOMATIC' ? 'AI suggested' : null;
}

export function originLabel(origin: string, modes: Modes | undefined): string {
  const text = ORIGIN_TEXT[origin as MarketOrigin] ?? 'Unknown origin';
  return modes?.ai_mode === 'FIXTURE' && (origin === 'AI_APPROVED' || origin === 'AI_AUTOMATIC') ? `${text} (fixture data)` : text;
}

export function sideLabel(market: Pick<PublicMarket, 'yes_label' | 'no_label'>, side: Side): string {
  return side === 'YES' ? market.yes_label || 'Yes' : market.no_label || 'No';
}

export interface BannerCopy {
  banner: Banner;
  title: string;
  detail: string;
}

/** Section 9.14 mapping: WON -> win, LOST -> "Ooohhh, so close!!", refunds, neutral. */
export function bannerCopy(market: PublicMarket, pos: MyPosition | null): BannerCopy | null {
  const banner = bannerFor(market, pos);
  if (!banner) return null;
  const winner = market.winning_side ? sideLabel(market, market.winning_side) : null;
  const reason = market.void_reason ? (VOID_REASON_TEXT[market.void_reason] ?? 'Voided') : '';
  const stake = formatMinor(pos?.stake_total_minor ?? 0);
  switch (banner) {
    case 'WIN': {
      const payout = pos?.payout_total_minor ?? 0;
      return {
        banner,
        title: 'You won!',
        detail: `${winner} won. Paid ${formatMinor(payout)} including your ${stake} stake (net +${formatMinor(payout - (pos?.stake_total_minor ?? 0))}).`,
      };
    }
    case 'LOSS':
      return { banner, title: LOSS_BANNER_TEXT, detail: `${winner} won. Your ${stake} stake went to the winning side.` };
    case 'VOID_REFUNDED':
      return { banner, title: 'Market voided, stake refunded', detail: `${reason}. ${formatMinor(pos?.refund_total_minor ?? 0)} is back in your wallet.` };
    case 'UNRESOLVED_REFUNDED':
      return {
        banner,
        title: 'Unresolved, stake refunded',
        detail: `${reason}. Nobody won or lost; ${formatMinor(pos?.refund_total_minor ?? 0)} is back in your wallet.`,
      };
    case 'NEUTRAL':
      return market.state === 'SETTLED'
        ? { banner, title: `Result: ${winner} won`, detail: 'You had no bet on this market.' }
        : { banner, title: 'Market voided', detail: `${reason}. You had no bet on this market.` };
  }
}

export function MarketCard({ surface }: { surface: 'panel' | 'overlay' }) {
  const { controller, requestPanelOpen, mode } = useEnv();
  const st = usePanel();
  const snap = st.snapshot;
  const market = snap?.market ?? null;
  const pos = snap?.my_position ?? null;
  // Tick while OPEN (countdown) and while an AI market waits for its expected result time (CONTRACTS 9.20 item 2).
  const now = useNow(1000, market?.state === 'OPEN' || awaitsExpectedResult(market));
  const [side, setSide] = useState<Side | null>(null);
  const [stakeText, setStakeText] = useState<string | null>(null);
  const marketId = market?.market_id;
  useEffect(() => {
    setSide(null);
    setStakeText(null);
  }, [marketId]);

  if (!snap) return <p className="ft-hint">{st.snapshotIssue ?? 'Loading the market…'}</p>;
  if (!market)
    return (
      <div className="ft-market">
        <p className="ft-q">{aiName() === 'AI' ? 'No market open right now.' : 'No prophecy yet. The Oracle watches the stream.'}</p>
        <p className="ft-hint">The next prediction appears here as soon as it opens.</p>
      </div>
    );
  if (!(VIEWER_MARKET_STATES as readonly string[]).includes(market.state))
    return <p className="ft-hint">This market is unavailable in this version of the panel.</p>;

  const limits = snap.limits;
  const label = (s: Side) => sideLabel(market, s);
  const lockedSide = pos?.side ?? null;
  const chosen = lockedSide ?? side;
  const stake = stakeText === null ? limits.stake_default_minor : parseDollarsToMinor(stakeText);
  const stakeProblem = checkStake(stake, limits);
  const remaining = remainingMs(market.close_at_utc, now, st.offsetMs);
  const isOpen = market.state === 'OPEN';
  const pastDeadline = isOpen && remaining <= 0;
  const twitchOrigin = !(FIXTURE_MARKET_ORIGINS as readonly string[]).includes(market.origin);
  const sourceBlocked = twitchOrigin && snap.source_health.state !== 'LIVE';
  const operatorPaused = snap.stream.wagering_paused && snap.stream.wagering_paused_reason === 'OPERATOR_PAUSE';
  const busy = isBusy(st.bet);
  const insufficient = stake !== null && !stakeProblem && stake > snap.wallet.available_minor;
  const estimate = chosen && stake !== null && !stakeProblem ? estimateGrossReturn(stake, market.pool, chosen) : null;
  const { yes_minor, no_minor, total_minor, simulated_minor, wager_count } = market.pool;
  const banner = bannerCopy(market, pos);
  // CONTRACTS 9.20 item 2: past the expected result time, still LOCKED/EVALUATING, no result yet.
  const watching = resultPending(market, now, st.offsetMs);
  const stepBy = (dir: 1 | -1) => {
    const base = stake ?? limits.stake_default_minor;
    const next = Math.min(limits.stake_max_minor, Math.max(limits.stake_min_minor, base + dir * limits.stake_step_minor));
    setStakeText(minorToInput(next));
  };

  let action = '';
  let actionDisabled = true;
  if (pastDeadline) action = 'Betting closed (waiting for the server to lock)';
  else if (sourceBlocked) action = 'Betting paused: stream source not live';
  else if (operatorPaused) action = 'Betting paused by the operator';
  else if (busy) action = 'Placing your bet…';
  else if (!chosen) action = 'Pick a side';
  else if (stakeProblem) action = 'Place Bet';
  else if (insufficient) {
    action = 'Top up to bet';
    actionDisabled = false;
  } else {
    action = `Place Bet · ${formatMinor(stake!)} on ${label(chosen)}`;
    actionDisabled = false;
  }

  const onAction = () => {
    if (!chosen || stake === null) return;
    if (insufficient) {
      controller.openTopUp('insufficient', stake - snap.wallet.available_minor);
      if (surface === 'overlay') requestPanelOpen();
      return;
    }
    void controller.placeBet(chosen, stake);
  };

  return (
    <section className="ft-market" aria-label="FaZeTime market">
      <div className="ft-meta">
        <span className={`ft-state ft-state--${market.state}`}>{STATE_TEXT[market.state] ?? 'UNAVAILABLE'}</span>
        {viewerOriginLabel(market.origin, snap.modes, mode) && <span>{viewerOriginLabel(market.origin, snap.modes, mode)}</span>}
        {isOpen && (
          <span className="ft-countdown" title="Display only. The server decides when betting closes.">
            {pastDeadline ? 'Closing…' : `Closes in ${formatCountdown(remaining)}`}
          </span>
        )}
      </div>
      <h3 className="ft-q">{market.question}</h3>

      <div className="ft-choices" role="radiogroup" aria-label="Choose a side">
        {(['YES', 'NO'] as const).map((s) => {
          const amount = s === 'YES' ? yes_minor : no_minor;
          const otherLocked = lockedSide !== null && lockedSide !== s;
          return (
            <button
              key={s}
              type="button"
              role="radio"
              aria-checked={chosen === s}
              className={`ft-choice ft-choice--${s}`}
              disabled={!isOpen || otherLocked || busy}
              title={otherLocked ? 'One side per market: you already backed the other side.' : undefined}
              onClick={() => setSide(s)}
            >
              <span className="ft-choice-label">
                <span className={`ft-dot ft-dot--${s}`} />
                {label(s)}
              </span>
              <span className="ft-choice-sub">
                {formatMinor(amount)} · {sharePercent(amount, total_minor)}%
              </span>
            </button>
          );
        })}
      </div>

      <div className="ft-poolbar" role="img" aria-label={`Pool: ${label('YES')} ${formatMinor(yes_minor)}, ${label('NO')} ${formatMinor(no_minor)}`}>
        {total_minor > 0 && (
          <>
            <div className="ft-poolbar-yes" style={{ width: `${(yes_minor * 100) / total_minor}%` }} />
            <div className="ft-poolbar-no" style={{ width: `${(no_minor * 100) / total_minor}%` }} />
          </>
        )}
      </div>
      <div className="ft-pooltotal">
        Total pool <b>{formatMinor(total_minor)}</b> · {wager_count} {wager_count === 1 ? 'bet' : 'bets'}
        {simulated_minor > 0 && <> · includes {formatMinor(simulated_minor)} simulated bot stakes</>}
      </div>

      {pos && pos.stake_total_minor > 0 && pos.side && (
        <div className="ft-position">
          Your position: <b>{formatMinor(pos.stake_total_minor)}</b> on <b>{label(pos.side)}</b> ({pos.wagers.length}{' '}
          {pos.wagers.length === 1 ? 'bet' : 'bets'}){pos.result === 'PENDING' ? ' · pending' : ''}. One side per market.
        </div>
      )}

      {banner && (
        <div className={`ft-banner ft-banner--${banner.banner}`} role="status">
          <h4>{banner.title}</h4>
          <p>{banner.detail}</p>
        </div>
      )}

      {watching ? (
        <p className="ft-hint ft-hint--watching" role="status">
          <span className="ft-watch" aria-hidden="true">
            <span />
            <span />
            <span />
          </span>
          {aiName()} is watching for the result…{market.state === 'EVALUATING' && ' Unclear results are refunded, never guessed.'}
        </p>
      ) : (
        <>
          {market.state === 'LOCKED' && <p className="ft-hint">Betting closed. Waiting for the result.</p>}
          {market.state === 'EVALUATING' && (
            <p className="ft-hint">Determining the outcome from the stream. Unclear results are refunded, never guessed.</p>
          )}
        </>
      )}

      {isOpen && (
        <div className="ft-bet">
          {(yes_minor === 0 || no_minor === 0) && (
            <p className="ft-hint ft-hint--warn">
              {total_minor === 0 ? 'No bets yet.' : 'Only one side has bets.'} If either side is still empty at close, the market is voided and
              every stake is refunded.
            </p>
          )}
          {sourceBlocked && (
            <p className="ft-hint ft-hint--warn">
              The stream source is {snap.source_health.state}. Betting resumes if it recovers; a long gap voids the market with refunds.
            </p>
          )}
          <div className="ft-row">
            <span className="ft-label">Stake</span>
            <div className="ft-stake">
              <button type="button" aria-label="Decrease stake" onClick={() => stepBy(-1)} disabled={busy}>
                −
              </button>
              <span>{currencySymbol()}</span>
              <input
                aria-label="Stake in demo dollars"
                inputMode="decimal"
                value={stakeText ?? minorToInput(limits.stake_default_minor)}
                onChange={(e) => setStakeText(e.target.value)}
                disabled={busy}
              />
              <button type="button" aria-label="Increase stake" onClick={() => stepBy(1)} disabled={busy}>
                +
              </button>
            </div>
          </div>
          {stakeProblem && (
            <div className="ft-field-error">
              {describeAmountProblem(stakeProblem, limits.stake_min_minor, limits.stake_max_minor, limits.stake_step_minor)}
            </div>
          )}
          <div className="ft-estimate">
            {estimate !== null && chosen ? (
              <>
                If {label(chosen)} wins, est. return <b>{formatMinor(estimate)}</b> incl. stake
                <span className="ft-tag">estimate</span>
                <br />
                Changes as others bet. Not a guaranteed payout.
              </>
            ) : (
              'Pick a side to see an estimated return.'
            )}
          </div>
          <div className="ft-row">
            <span className="ft-label">
              Available <b className="ft-money">{formatMinor(snap.wallet.available_minor)}</b>
            </span>
            {(snap.modes.payment_mode === 'MOCK' || snap.modes.payment_mode === 'STRIPE_TEST') && (
              <button type="button" className="ft-link" onClick={() => (controller.openTopUp('manual'), surface === 'overlay' && requestPanelOpen())}>
                {mode === 'live' ? 'Add funds' : 'Add demo funds'}
              </button>
            )}
          </div>
          <button type="button" className="ft-primary" disabled={actionDisabled} onClick={onAction}>
            {action}
          </button>
        </div>
      )}
      <BetStatus surface={surface} labelFor={label} />
    </section>
  );
}

function BetStatus({ surface, labelFor }: { surface: 'panel' | 'overlay'; labelFor: (s: Side) => string }) {
  const { controller, requestPanelOpen, mode } = useEnv();
  const { bet } = usePanel();
  switch (bet.kind) {
    case 'idle':
      return null;
    case 'submitting':
      return (
        <div className="ft-status ft-status--wait" role="status">
          <div>
            <strong>Placing your bet…</strong>
            <p>Not confirmed yet.</p>
          </div>
        </div>
      );
    case 'unknown':
      return (
        <div className="ft-status ft-status--wait" role="status">
          <div>
            <strong>Outcome unknown</strong>
            <p>{bet.message}</p>
            <p>{bet.retryInMs !== null ? 'Retrying with the same request (it can only be charged once).' : 'Automatic retries stopped.'}</p>
          </div>
          {bet.retryInMs === null && (
            <button type="button" className="ft-secondary" onClick={() => void controller.checkBetStatus()}>
              Check status
            </button>
          )}
        </div>
      );
    case 'accepted':
      return (
        <div className="ft-status ft-status--ok" role="status">
          <div>
            <strong>Bet accepted</strong>
            <p>
              {formatMinor(bet.receipt.amount_minor)} on {labelFor(bet.receipt.side)}.
              {bet.receipt.replayed ? ' Confirmed from the original receipt; charged once.' : ''}
            </p>
          </div>
          <button type="button" className="ft-link" onClick={() => controller.dismissBet()}>
            Dismiss
          </button>
        </div>
      );
    case 'rejected': {
      const copy = describeError(bet.error, labelFor);
      return (
        <div className="ft-status ft-status--err" role="alert">
          <div>
            <strong>{copy.title}</strong>
            <p>{copy.detail}</p>
            {copy.action === 'OPEN_TOPUP' && (
              <button
                type="button"
                className="ft-link"
                onClick={() => {
                  controller.openTopUp('insufficient');
                  if (surface === 'overlay') requestPanelOpen();
                }}
              >
                {mode === 'live' ? 'Add funds' : 'Add demo funds'}
              </button>
            )}
          </div>
          <button type="button" className="ft-link" onClick={() => controller.dismissBet()}>
            Dismiss
          </button>
        </div>
      );
    }
  }
}
