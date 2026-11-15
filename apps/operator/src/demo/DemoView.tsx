// Minimal demo view (default at /operator/): one stream pill, ONE big card that follows the market state, and
// Reset. Everything else (IDs, modes, evidence feed, invites, sign-out) lives in the full console at #advanced.
// - Polls health, candidates and (for an AI market after close) resolutions every 2 s.
// - Every click is a new intent with a fresh operation_id (OperatorClient.mutate). "Try again" after an
//   unknown outcome re-sends the SAME operation (§9.7), so a retry never repeats an economic effect.
// - Model text (questions, labels) is rendered as React text only. Countdowns are display-only.
import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { ApiFailure, type MutationResult, type OperatorClient, type PendingOperation } from '../api/client';
import type { AiCandidate, AiResolution, MarketLimits, MarketReceipt, OperatorMarket, OperatorReceipt, ResetReceipt } from '../api/types';
import { useAlert } from '../ui/alert';
import { AuthThumb } from '../ui/AuthThumb';
import { candidateDeadlines } from '../ui/deadlines';
import { approvalCloseInS, genericKindLabel, isGenericCandidate, ruleNamesSide } from '../ui/generic';
import { useMutation, useNow, usePoll, type MutationState } from '../ui/hooks';
import {
  alertKey,
  cardKey,
  connectionSentence,
  countdownText,
  currentMarket,
  deriveDemoState,
  errorSentence,
  isAiMarket,
  msUntil,
  poolLine,
  resultText,
  serverNow,
  streamPill,
  suggestionText,
  type DemoState,
} from './state';

const REJECT_REASON = 'rejected by operator';
const VOID_NOTE = 'voided by operator';
const SETTLE_NOTE = 'called by operator';
/** Test bets give the operator 5 minutes after close to call the winner (then the server voids and refunds). */
const TEST_BET_RESOLVE_S = 300;
const BASE_TITLE = 'FaZeTime';

type Run = (exec: () => Promise<MutationResult<OperatorReceipt>>) => Promise<MutationResult<OperatorReceipt> | null>;

function ErrorLine({ failure, onRetry }: { failure: unknown; onRetry?: (pending: PendingOperation) => void }) {
  const pending = failure instanceof ApiFailure && failure.retrySameOperation ? failure.pending : null;
  const code = failure instanceof ApiFailure ? (failure.code ?? failure.kind) : 'error';
  return (
    <div className="demo-error" role="alert" data-testid="demo-error" data-code={code} title={code}>
      {errorSentence(failure)}
      {pending && onRetry && (
        <button type="button" className="demo-link" onClick={() => onRetry(pending)}>
          Try again
        </button>
      )}
    </div>
  );
}

function ActionError({ state, run, client }: { state: MutationState<OperatorReceipt>; run: Run; client: OperatorClient }) {
  if (state.status !== 'error') return null;
  return <ErrorLine failure={state.failure} onRetry={(p) => void run(() => client.retry<OperatorReceipt>(p))} />;
}

function Card({ state, children }: { state: string; children: ReactNode }) {
  return (
    <section className="demo-card" data-testid="demo-card" data-state={state} aria-live="polite">
      {children}
    </section>
  );
}

// ---- cards --------------------------------------------------------------------------------------------------

/** One compact YES or NO rule (a generic candidate's predicate), as text. The side word is added only if missing. */
function Rule({ side, label, predicate }: { side: 'yes' | 'no'; label: string; predicate: string }) {
  return (
    <p className={`demo-rule ${side}`}>
      {!ruleNamesSide(predicate, label) && <span className="demo-rule-side">{label}: </span>}
      {predicate}
    </p>
  );
}

function CandidateCard({
  client,
  c,
  serverNowMs,
  limits,
  onDone,
}: {
  client: OperatorClient;
  c: AiCandidate;
  serverNowMs: number | null;
  limits: MarketLimits | null;
  onDone: () => void;
}) {
  const act = useMutation<OperatorReceipt>(() => onDone());
  // §9.19 item 5: a generic candidate is approved with its own close_in_s, counted from approval, so the
  // receipt-anchored minimum lead no longer limits the approval time. H2H sends null, as before.
  const closeInS = approvalCloseInS(c);
  const d =
    serverNowMs === null
      ? null
      : candidateDeadlines(c, serverNowMs, {
          evidenceFreshS: limits?.evidence_fresh_s ?? 90,
          minLeadMs: limits?.min_lead_ms ?? 30_000,
          override: closeInS !== null,
        });
  const left = d?.approveMs ?? null;
  const late = left !== null && left <= 0;
  const busy = act.state.status === 'busy' || act.state.status === 'ok';
  const kind = genericKindLabel(c);
  return (
    <Card state="candidate">
      {kind && (
        <div className="demo-kind" data-testid="demo-kind">
          {kind}
        </div>
      )}
      <h2 className="demo-question" data-testid="demo-question">
        {c.question}
      </h2>
      {isGenericCandidate(c) ? (
        <div className="demo-rules" data-testid="demo-rules">
          <Rule side="yes" label={c.yes.label} predicate={c.yes.predicate} />
          <Rule side="no" label={c.no.label} predicate={c.no.predicate} />
        </div>
      ) : (
        <div className="demo-sides">
          <span className="demo-chip yes">{c.yes.label}</span>
          <span className="demo-chip no">{c.no.label}</span>
        </div>
      )}
      <div className={`demo-count ${late ? 'late' : left !== null && left < 15_000 ? 'urgent' : ''}`} data-testid="demo-countdown">
        {countdownText(left)}
      </div>
      <div className="demo-caption">to approve</div>
      <div className="demo-actions">
        <button
          type="button"
          className="demo-btn go"
          disabled={busy || late}
          onClick={() => void act.run(() => client.approveCandidate(c.id, closeInS))}
        >
          Approve
        </button>
        <button
          type="button"
          className="demo-btn stop"
          disabled={busy}
          onClick={() => void act.run(() => client.rejectCandidate(c.id, REJECT_REASON))}
        >
          Reject
        </button>
      </div>
      {late && act.state.status !== 'error' && <div className="demo-error">Too late to approve: it expired.</div>}
      <ActionError state={act.state} run={act.run} client={client} />
    </Card>
  );
}

function OpenCard({ m, serverNowMs }: { m: OperatorMarket; serverNowMs: number | null }) {
  const left = msUntil(m.close_at_utc, serverNowMs);
  return (
    <Card state="open">
      <h2 className="demo-question" data-testid="demo-question">
        {m.question}
      </h2>
      <div className="demo-pool" data-testid="demo-pool">
        {poolLine(m)}
      </div>
      <div className={`demo-count ${left !== null && left < 10_000 ? 'urgent' : ''}`} data-testid="demo-countdown">
        {countdownText(left)}
      </div>
      <div className="demo-caption">until betting closes</div>
    </Card>
  );
}

function ClosedCard({ m }: { m: OperatorMarket }) {
  return (
    <Card state="closed">
      <h2 className="demo-question" data-testid="demo-question">
        {m.question}
      </h2>
      <div className="demo-status">Betting closed. Waiting for the result.</div>
      <div className="demo-pool">{poolLine(m)}</div>
    </Card>
  );
}

function SuggestionCard({ client, m, r, onDone }: { client: OperatorClient; m: OperatorMarket; r: AiResolution; onDone: () => void }) {
  const act = useMutation<OperatorReceipt>(() => onDone());
  const busy = act.state.status === 'busy' || act.state.status === 'ok';
  const frame = r.evidence.find((e) => e.kind === 'FRAME' && typeof e.evidence_id === 'string' && e.evidence_id);
  return (
    <Card state="suggestion">
      <h2 className="demo-question small" data-testid="demo-question">
        {m.question}
      </h2>
      <div className="demo-verdict" data-testid="demo-verdict">
        {suggestionText(m, r)}
      </div>
      {frame?.evidence_id && (
        <div className="demo-evidence">
          <AuthThumb client={client} evidenceId={frame.evidence_id} alt="What the AI saw" testId="demo-evidence" />
        </div>
      )}
      <div className="demo-actions">
        <button type="button" className="demo-btn go" disabled={busy} onClick={() => void act.run(() => client.approveResolution(r.id))}>
          Approve result
        </button>
        <button type="button" className="demo-btn stop" disabled={busy} onClick={() => void act.run(() => client.voidMarket(m.market_id, VOID_NOTE))}>
          Void &amp; refund
        </button>
      </div>
      <ActionError state={act.state} run={act.run} client={client} />
    </Card>
  );
}

function FixtureCallCard({ client, m, onDone }: { client: OperatorClient; m: OperatorMarket; onDone: () => void }) {
  const act = useMutation<OperatorReceipt>(() => onDone());
  const busy = act.state.status === 'busy' || act.state.status === 'ok';
  const settle = (side: 'YES' | 'NO') =>
    void act.run(() => client.settleMarket(m.market_id, side, { field: 'note', text: SETTLE_NOTE }));
  return (
    <Card state="fixture_call">
      <h2 className="demo-question" data-testid="demo-question">
        {m.question}
      </h2>
      <div className="demo-pool">{poolLine(m)}</div>
      <div className="demo-actions">
        <button type="button" className="demo-btn go" disabled={busy} onClick={() => settle('YES')}>
          {m.yes_label} won
        </button>
        <button type="button" className="demo-btn go alt" disabled={busy} onClick={() => settle('NO')}>
          {m.no_label} won
        </button>
      </div>
      <ActionError state={act.state} run={act.run} client={client} />
    </Card>
  );
}

function TestBet({ client, limits, onDone }: { client: OperatorClient; limits: MarketLimits | null; onDone: () => void }) {
  const [shown, setShown] = useState(false);
  const [question, setQuestion] = useState('');
  const [yes, setYes] = useState('Yes');
  const [no, setNo] = useState('No');
  const [secs, setSecs] = useState('60');
  const act = useMutation<MarketReceipt>(() => {
    setShown(false);
    onDone();
  });
  const minS = Math.max(1, Math.ceil((limits?.min_lead_ms ?? 30_000) / 1000));
  const maxS = limits?.fixture_max_close_in_s ?? 6 * 3600;
  const n = Number(secs);
  const valid =
    question.trim().length >= 1 &&
    question.trim().length <= 200 &&
    yes.trim().length >= 1 &&
    no.trim().length >= 1 &&
    Number.isSafeInteger(n) &&
    n >= minS &&
    n <= maxS;
  const busy = act.state.status === 'busy';

  // One click = create the fixture market, then open it (two operations, each with its own fresh operation_id).
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!valid || busy) return;
    void act.run(async () => {
      const created = await client.createMarket({
        question: question.trim(),
        yes_label: yes.trim(),
        no_label: no.trim(),
        close_in_s: n,
        resolve_in_s: TEST_BET_RESOLVE_S,
      });
      return client.openMarket(created.receipt.market.market_id);
    });
  };
  // Retry re-sends the exact pending operation; if that was the create, open the created market afterwards.
  const retry = (pending: PendingOperation) =>
    void act.run(async () => {
      const r = await client.retry<MarketReceipt>(pending);
      return pending.path === '/v1/operator/markets' ? client.openMarket(r.receipt.market.market_id) : r;
    });

  if (!shown) {
    return (
      <button
        type="button"
        className="demo-link"
        onClick={() => {
          act.reset();
          setShown(true);
        }}
      >
        test bet
      </button>
    );
  }
  return (
    <form className="demo-testbet" onSubmit={submit} method="post" aria-label="Test bet" data-testid="test-bet">
      <label className="grow">
        <span>Question</span>
        <input value={question} onChange={(e) => setQuestion(e.target.value)} maxLength={200} placeholder="Will FaZeGavin win the 1v1?" />
      </label>
      <label>
        <span>Yes label</span>
        <input value={yes} onChange={(e) => setYes(e.target.value)} maxLength={40} />
      </label>
      <label>
        <span>No label</span>
        <input value={no} onChange={(e) => setNo(e.target.value)} maxLength={40} />
      </label>
      <label className="secs">
        <span>Seconds open</span>
        <input value={secs} onChange={(e) => setSecs(e.target.value)} inputMode="numeric" aria-invalid={!(Number.isSafeInteger(n) && n >= minS && n <= maxS)} />
      </label>
      <button type="submit" className="demo-btn small go" disabled={!valid || busy}>
        Open bet
      </button>
      <button type="button" className="demo-link" onClick={() => setShown(false)} disabled={busy}>
        Cancel
      </button>
      {act.state.status === 'error' && <ErrorLine failure={act.state.failure} onRetry={retry} />}
    </form>
  );
}

function IdleCard({
  client,
  last,
  aiListening,
  limits,
  onDone,
}: {
  client: OperatorClient;
  last: OperatorMarket | null;
  aiListening: boolean;
  limits: MarketLimits | null;
  onDone: () => void;
}) {
  return (
    <Card state={last ? 'result' : 'idle'}>
      {last && (
        <>
          <h2 className="demo-question small" data-testid="demo-question">
            {last.question}
          </h2>
          <div className="demo-verdict" data-testid="demo-result">
            {resultText(last)}
          </div>
        </>
      )}
      <div className={last ? 'demo-wait small' : 'demo-wait'} data-testid="demo-wait">
        {aiListening ? 'Waiting for the AI to spot a bet' : 'AI is off. Turn it on under Advanced.'}
      </div>
      <TestBet client={client} limits={limits} onDone={onDone} />
    </Card>
  );
}

function ResetBar({ client, streamId, onDone }: { client: OperatorClient; streamId: string; onDone: () => void }) {
  const [confirming, setConfirming] = useState(false);
  const act = useMutation<ResetReceipt>(() => {
    setConfirming(false);
    onDone();
  });
  const busy = act.state.status === 'busy';
  return (
    <div className="demo-reset">
      {confirming ? (
        <span className="demo-confirm" data-testid="reset-confirm">
          Reset balances and bets for the next take?
          <button type="button" className="demo-btn small stop" disabled={busy} onClick={() => void act.run(() => client.resetRun(streamId))}>
            Reset
          </button>
          <button type="button" className="demo-link" disabled={busy} onClick={() => setConfirming(false)}>
            Cancel
          </button>
        </span>
      ) : (
        <button
          type="button"
          className="demo-btn small"
          onClick={() => {
            act.reset();
            setConfirming(true);
          }}
        >
          Reset for next take
        </button>
      )}
      {act.state.status === 'ok' && !confirming && <span className="demo-done">Reset done.</span>}
      {act.state.status === 'error' && (
        <ErrorLine failure={act.state.failure} onRetry={(p) => void act.run(() => client.retry<ResetReceipt>(p))} />
      )}
    </div>
  );
}

// ---- view ---------------------------------------------------------------------------------------------------

export function DemoView({ client }: { client: OperatorClient }) {
  const healthFn = useCallback((signal: AbortSignal) => client.health(signal), [client]);
  const health = usePoll(healthFn, 2_000);
  const h = health.data;
  const hasStream = Boolean(h?.stream);

  const candidatesFn = useCallback((signal: AbortSignal) => client.candidates(signal), [client]);
  const candidates = usePoll(candidatesFn, 2_000, hasStream);

  const market = currentMarket(h);
  const aiMarketId = market && isAiMarket(market) && market.state !== 'OPEN' ? market.market_id : null;
  const resolutionsFn = useCallback(
    (signal: AbortSignal) => (aiMarketId ? client.resolutions(aiMarketId, signal) : Promise.resolve(null)),
    [client, aiMarketId],
  );
  const resolutions = usePoll(resolutionsFn, 2_000, aiMarketId !== null);

  const now = useNow(250);
  const stale = health.okAt === null || now - health.okAt > 6_000;
  const serverNowMs = serverNow(h?.server_time_utc, health.okAt, now);
  const state: DemoState = deriveDemoState({
    health: h,
    candidates: candidates.data?.candidates ?? null,
    resolutions: resolutions.data?.resolutions ?? null,
  });

  const refreshHealth = health.refresh;
  const refreshCandidates = candidates.refresh;
  const refreshResolutions = resolutions.refresh;
  const refresh = useCallback(() => {
    refreshHealth();
    refreshCandidates();
    refreshResolutions();
  }, [refreshHealth, refreshCandidates, refreshResolutions]);

  // Sound + tab title when the operator is needed (a candidate, a result suggestion, a fixture call).
  const { sound, setSound, beep, unlocked } = useAlert();
  const seen = useRef<Set<string>>(new Set());
  const needKey = alertKey(state);
  useEffect(() => {
    if (!needKey || seen.current.has(needKey)) return;
    seen.current.add(needKey);
    beep();
  }, [needKey, beep]);
  useEffect(() => {
    document.title = needKey ? `(!) ${BASE_TITLE}` : BASE_TITLE;
  }, [needKey]);
  useEffect(
    () => () => {
      document.title = BASE_TITLE;
    },
    [],
  );

  const pill = streamPill(h, stale);
  const connection = connectionSentence(health.error, stale);
  const effectiveAi = h?.ai?.effective_ai_mode ?? h?.run?.ai_mode ?? null;
  const aiListening = effectiveAi === null || effectiveAi === 'APPROVAL' || effectiveAi === 'AUTOMATIC';
  const limits = h?.market_limits ?? null;

  let card: ReactNode;
  switch (state.kind) {
    case 'loading':
      card = (
        <Card state="loading">
          <div className="demo-wait">Connecting…</div>
        </Card>
      );
      break;
    case 'no_stream':
      card = (
        <Card state="no_stream">
          <div className="demo-wait">No stream yet.</div>
          <a className="demo-link" href="#advanced">
            Set it up under Advanced
          </a>
        </Card>
      );
      break;
    case 'candidate':
      card = <CandidateCard client={client} c={state.candidate} serverNowMs={serverNowMs} limits={limits} onDone={refresh} />;
      break;
    case 'open':
      card = <OpenCard m={state.market} serverNowMs={serverNowMs} />;
      break;
    case 'closed':
      card = <ClosedCard m={state.market} />;
      break;
    case 'suggestion':
      card = <SuggestionCard client={client} m={state.market} r={state.resolution} onDone={refresh} />;
      break;
    case 'fixture_call':
      card = <FixtureCallCard client={client} m={state.market} onDone={refresh} />;
      break;
    case 'result':
      card = <IdleCard client={client} last={state.market} aiListening={aiListening} limits={limits} onDone={refresh} />;
      break;
    default:
      card = <IdleCard client={client} last={null} aiListening={aiListening} limits={limits} onDone={refresh} />;
  }

  return (
    <div className="demo" data-testid="demo-view">
      <header className="demo-top">
        <h1>FaZeTime</h1>
        <span className={`stream-pill ${pill.tone}`} data-testid="stream-pill">
          {pill.text}
        </span>
      </header>
      <main className="demo-main">
        {connection && (
          <div className="demo-error" role="status" data-testid="demo-connection">
            {connection}
          </div>
        )}
        <div key={cardKey(state)} className="demo-slot">
          {card}
        </div>
      </main>
      <footer className="demo-bottom">
        {h?.stream ? <ResetBar client={client} streamId={h.stream.stream_id} onDone={refresh} /> : <span />}
        <span className="demo-spacer" />
        <button
          type="button"
          className="demo-link"
          aria-pressed={sound}
          onClick={() => setSound(unlocked ? !sound : true)}
          data-testid="sound-toggle"
        >
          {!sound ? 'Sound off' : unlocked ? 'Sound on' : 'Enable sound'}
        </button>
        <a className="demo-link" href="#advanced" data-testid="advanced-link">
          Advanced
        </a>
      </footer>
    </div>
  );
}
