import { useState, type FormEvent } from 'react';
import type { OperatorClient } from '../api/client';
import type { MarketReceipt, OperatorHealth, OperatorMarket, StreamReceipt } from '../api/types';
import { MutationStatus, Panel, StateBadge } from './common';
import { formatDuration, formatMinor, formatUtcClock, shortId } from './format';
import { useMutation } from './hooks';

const NONTERMINAL = new Set(['OPEN', 'LOCKED', 'EVALUATING']);
const FIXTURE_ORIGINS = new Set(['OPERATOR_FIXTURE', 'CANNED_FIXTURE']);

interface Common {
  client: OperatorClient;
  onChanged: () => void;
}

function untilText(target: string | null, serverNowMs: number | null): string {
  if (!target || serverNowMs === null) return '';
  const t = Date.parse(target);
  if (Number.isNaN(t)) return '';
  const d = t - serverNowMs;
  return d > 0 ? `in ~${formatDuration(d)}` : `${formatDuration(-d)} ago`;
}

function MarketReceiptText({ receipt }: { receipt: MarketReceipt }) {
  const m = receipt.market;
  return (
    <div>
      Market <code title={m.market_id}>{shortId(m.market_id)}</code> is now <StateBadge state={m.state} />
      {m.winning_side && <> · winner {m.winning_side}</>}
      {m.void_reason && <> · {m.void_reason} (stakes refunded)</>} · version {m.aggregate_version}
    </div>
  );
}

function Pools({ m }: { m: OperatorMarket }) {
  const p = m.pool;
  const yesPct = p.total_minor > 0 ? Math.round((p.yes_minor * 100) / p.total_minor) : 0;
  return (
    <div className="pools" data-testid="pools">
      <div className="pool yes">
        <span className="label">YES · {m.yes_label}</span>
        <span className="value">{formatMinor(p.yes_minor)}</span>
      </div>
      <div className="pool no">
        <span className="label">NO · {m.no_label}</span>
        <span className="value">{formatMinor(p.no_minor)}</span>
      </div>
      <div className="pool total">
        <span className="label">Total</span>
        <span className="value">{formatMinor(p.total_minor)}</span>
      </div>
      <div className="pool count">
        <span className="label">Wagers</span>
        <span className="value">{p.wager_count}</span>
      </div>
      <div className="bar" aria-hidden="true">
        <div className="bar-yes" style={{ width: `${yesPct}%` }} />
      </div>
      <div className={`small ${p.simulated_minor > 0 ? 'sim' : 'muted'}`} data-testid="simulated">
        Simulated (bot) stakes: {formatMinor(p.simulated_minor)}, included in the totals above.
      </div>
    </div>
  );
}

type Confirm = { kind: 'settle'; side: 'YES' | 'NO' } | { kind: 'void' } | null;

function MarketCard({
  client,
  onChanged,
  market: m,
  serverNowMs,
  blockingMarket,
  settleReasonField,
}: Common & {
  market: OperatorMarket;
  serverNowMs: number | null;
  blockingMarket: OperatorMarket | null;
  settleReasonField: string | null;
}) {
  const action = useMutation<MarketReceipt>(() => onChanged());
  const [confirm, setConfirm] = useState<Confirm>(null);
  const [reason, setReason] = useState('');
  const busy = action.state.status === 'busy';
  const canSettle = m.state === 'EVALUATING' && FIXTURE_ORIGINS.has(m.origin);
  const canVoid = NONTERMINAL.has(m.state);
  const reasonOk = reason.trim().length >= 3 && reason.trim().length <= 200;

  const begin = (c: Confirm) => {
    setConfirm(c);
    setReason('');
    action.reset();
  };

  const submitConfirm = (e: FormEvent) => {
    e.preventDefault();
    if (!confirm || !reasonOk || busy) return;
    const text = reason.trim();
    // A fresh operation_id per confirmed intent (generated inside the client call).
    if (confirm.kind === 'settle') {
      const side = confirm.side;
      void action
        .run(() => client.settleMarket(m.market_id, side, settleReasonField ? { field: settleReasonField, text } : null))
        .then((r) => r && setConfirm(null));
    } else {
      void action.run(() => client.voidMarket(m.market_id, text)).then((r) => r && setConfirm(null));
    }
  };

  return (
    <article className={`market-card state-${m.state.toLowerCase()}`} data-testid="market-card" data-market-state={m.state}>
      <header>
        <StateBadge state={m.state} />
        <span className="tag">{m.origin}</span>
        <code title={m.market_id}>{shortId(m.market_id)}</code>
        <span className="muted small">v{m.aggregate_version}</span>
        {(m.state === 'SETTLED' || m.state === 'VOID') && <span className="muted small">recent result</span>}
      </header>
      <p className="question">{m.question}</p>
      {m.state === 'DRAFT' ? (
        <div className="muted small">
          Draft terms: wagers close {m.close_in_s} s after opening; resolve within {m.resolve_in_s} s after close.
        </div>
      ) : (
        <>
          <div className="times small">
            <span>Opened {formatUtcClock(m.opened_at_utc)}</span>
            <span>
              Close {formatUtcClock(m.close_at_utc)} <span className="muted">{m.state === 'OPEN' ? untilText(m.close_at_utc, serverNowMs) : ''}</span>
            </span>
            <span>
              Resolve by {formatUtcClock(m.resolve_by_utc)}{' '}
              <span className="muted">{NONTERMINAL.has(m.state) ? untilText(m.resolve_by_utc, serverNowMs) : ''}</span>
            </span>
          </div>
          <Pools m={m} />
        </>
      )}
      {m.state === 'SETTLED' && (
        <div className="result">
          Settled <strong>{m.winning_side}</strong> ({m.winning_side === 'YES' ? m.yes_label : m.no_label}) ·{' '}
          {m.settlement_algorithm}
        </div>
      )}
      {m.state === 'VOID' && <div className="result">Void: {m.void_reason}. Every accepted stake refunded.</div>}

      <div className="actions">
        {m.state === 'DRAFT' && (
          <button
            type="button"
            className="btn primary"
            disabled={busy}
            onClick={() => {
              setConfirm(null);
              void action.run(() => client.openMarket(m.market_id));
            }}
          >
            Open market
          </button>
        )}
        {NONTERMINAL.has(m.state) && (
          <>
            <button type="button" className="btn" disabled={busy || !canSettle} onClick={() => begin({ kind: 'settle', side: 'YES' })}>
              Settle YES…
            </button>
            <button type="button" className="btn" disabled={busy || !canSettle} onClick={() => begin({ kind: 'settle', side: 'NO' })}>
              Settle NO…
            </button>
          </>
        )}
        {canVoid && (
          <button type="button" className="btn danger" disabled={busy} onClick={() => begin({ kind: 'void' })}>
            Void…
          </button>
        )}
      </div>
      {m.state === 'DRAFT' && blockingMarket && (
        <div className="muted small">
          Market {shortId(blockingMarket.market_id)} is still {blockingMarket.state}; the server will refuse to open this
          one (STALE_MARKET) until it is terminal.
        </div>
      )}
      {NONTERMINAL.has(m.state) && !canSettle && (
        <div className="muted small">
          {m.state === 'OPEN'
            ? 'Settlement unlocks after close, while EVALUATING and before resolve_by. One-sided or empty pools VOID automatically at lock.'
            : m.state === 'LOCKED'
              ? 'Locked; the sweeper moves it to EVALUATING.'
              : 'Only fixture-origin markets settle by hand.'}
        </div>
      )}

      {confirm && (
        <form className="confirm" onSubmit={submitConfirm} method="post" data-testid="confirm-box">
          {confirm.kind === 'settle' ? (
            <p>
              Settle as <strong>{confirm.side}</strong> ({confirm.side === 'YES' ? m.yes_label : m.no_label})? The whole pool
              ({formatMinor(m.pool.total_minor)}) is paid to {confirm.side} stakers, pari-mutuel with zero fee. This is final.
            </p>
          ) : (
            <p>
              Void this market (OPERATOR_CANCELLED)? Every accepted stake ({m.pool.wager_count} wagers,{' '}
              {formatMinor(m.pool.total_minor)}) is refunded exactly once. This is final.
            </p>
          )}
          <label>
            Reason (required)
            <textarea value={reason} onChange={(e) => setReason(e.target.value)} maxLength={200} rows={2} />
          </label>
          <div className="muted small">
            {confirm.kind === 'void'
              ? 'Sent as the void note.'
              : settleReasonField
                ? `Sent as "${settleReasonField}".`
                : 'This API has no settle-reason field yet, so the reason is not stored. The audit log records you, the operation_id and the winning side.'}
          </div>
          <div className="actions">
            <button type="submit" className={`btn ${confirm.kind === 'void' ? 'danger' : 'primary'}`} disabled={!reasonOk || busy}>
              {confirm.kind === 'settle' ? `Confirm settle ${confirm.side}` : 'Confirm void'}
            </button>
            <button type="button" className="btn" onClick={() => setConfirm(null)} disabled={busy}>
              Cancel
            </button>
          </div>
        </form>
      )}
      <MutationStatus state={action.state} client={client} run={action.run} describe={(r) => <MarketReceiptText receipt={r.receipt} />} />
    </article>
  );
}

function CreateStream({ client, onChanged }: Common) {
  const [login, setLogin] = useState('');
  const create = useMutation<StreamReceipt>(() => onChanged());
  const ok = /^[A-Za-z0-9_]{1,25}$/.test(login);
  return (
    <form
      className="inline-form"
      method="post"
      onSubmit={(e) => {
        e.preventDefault();
        if (ok) void create.run(() => client.createStream(login));
      }}
    >
      <p>No stream exists yet. Create the single demo stream (its first run is seeded for every viewer).</p>
      <label>
        Twitch channel login
        <input value={login} onChange={(e) => setLogin(e.target.value)} maxLength={25} spellCheck={false} />
      </label>
      <button type="submit" className="btn primary" disabled={!ok || create.state.status === 'busy'}>
        Create stream
      </button>
      <MutationStatus
        state={create.state}
        client={client}
        run={create.run}
        describe={(r) => (
          <div>
            Stream <code>{shortId(r.receipt.stream.stream_id)}</code> {r.receipt.created ? 'created' : 'already existed'} · run{' '}
            <code>{shortId(r.receipt.stream.stream_session_id)}</code>
          </div>
        )}
      />
    </form>
  );
}

function CreateMarket({ client, onChanged, disabled }: Common & { disabled: boolean }) {
  const [question, setQuestion] = useState('');
  const [yes, setYes] = useState('Yes');
  const [no, setNo] = useState('No');
  const [closeIn, setCloseIn] = useState('60');
  const [resolveIn, setResolveIn] = useState('120');
  const create = useMutation<MarketReceipt>(() => onChanged());

  const closeN = Number(closeIn);
  const resolveN = Number(resolveIn);
  const valid =
    question.trim().length >= 1 &&
    question.trim().length <= 200 &&
    yes.trim().length >= 1 &&
    no.trim().length >= 1 &&
    Number.isSafeInteger(closeN) &&
    closeN >= 1 &&
    Number.isSafeInteger(resolveN) &&
    resolveN >= 1;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!valid || disabled) return;
    void create.run(() =>
      client.createMarket({
        question: question.trim(),
        yes_label: yes.trim(),
        no_label: no.trim(),
        close_in_s: closeN,
        resolve_in_s: resolveN,
      }),
    );
  };

  return (
    <form className="create-market" onSubmit={submit} method="post" aria-label="Create fixture market">
      <h3>New fixture market</h3>
      <label className="wide">
        Question
        <input value={question} onChange={(e) => setQuestion(e.target.value)} maxLength={200} placeholder="Will FaZeGavin win the 1v1?" />
      </label>
      <div className="row">
        <label>
          YES label
          <input value={yes} onChange={(e) => setYes(e.target.value)} maxLength={40} />
        </label>
        <label>
          NO label
          <input value={no} onChange={(e) => setNo(e.target.value)} maxLength={40} />
        </label>
        <label>
          close_in_s
          <input value={closeIn} onChange={(e) => setCloseIn(e.target.value)} inputMode="numeric" />
        </label>
        <label>
          resolve_in_s
          <input value={resolveIn} onChange={(e) => setResolveIn(e.target.value)} inputMode="numeric" />
        </label>
      </div>
      <div className="muted small">
        Creates a DRAFT (origin OPERATOR_FIXTURE). On open: close_at = open + close_in_s; resolve_by = close_at +
        resolve_in_s. The server enforces the minimum lead (default 30 s) and maximums.
      </div>
      <button type="submit" className="btn primary" disabled={!valid || disabled || create.state.status === 'busy'}>
        Create draft
      </button>
      <MutationStatus
        state={create.state}
        client={client}
        run={create.run}
        describe={(r) => (
          <>
            <MarketReceiptText receipt={r.receipt} />
            <div className="muted small">Open it from its DRAFT card above.</div>
          </>
        )}
      />
    </form>
  );
}

export function MarketPanel({
  client,
  onChanged,
  health,
  serverNowMs,
  settleReasonField,
}: Common & { health: OperatorHealth | null; serverNowMs: number | null; settleReasonField: string | null }) {
  if (!health) {
    return (
      <Panel title="Market controls">
        <p className="muted">Waiting for operator health…</p>
      </Panel>
    );
  }
  if (!health.stream) {
    return (
      <Panel title="Market controls">
        <CreateStream client={client} onChanged={onChanged} />
      </Panel>
    );
  }
  const markets = health.markets ?? [];
  const live = markets.find((m) => NONTERMINAL.has(m.state)) ?? null;
  const drafts = markets.filter((m) => m.state === 'DRAFT');
  const terminal = markets.filter((m) => m.state === 'SETTLED' || m.state === 'VOID').slice(0, 2);
  // One keyed list: a card keeps its confirm/receipt state while its market moves OPEN -> SETTLED.
  const ordered = [...(live ? [live] : []), ...drafts, ...terminal];
  return (
    <Panel title="Market controls" tag={<span className="tag">fixture markets · test money</span>}>
      {!live && <p className="muted">No market is OPEN, LOCKED or EVALUATING in this run.</p>}
      <div className="market-list">
        {ordered.map((m) => (
          <MarketCard
            key={m.market_id}
            client={client}
            onChanged={onChanged}
            market={m}
            serverNowMs={serverNowMs}
            blockingMarket={m.state === 'DRAFT' ? live : null}
            settleReasonField={settleReasonField}
          />
        ))}
      </div>
      <CreateMarket client={client} onChanged={onChanged} disabled={false} />
    </Panel>
  );
}
