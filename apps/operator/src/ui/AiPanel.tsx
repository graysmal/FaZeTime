// Supervised AI (CONTRACTS §9.17, D32): AI mode, candidate approval, resolution approval.
// The model only proposes; the server re-validates everything at approval. All model text is untrusted and is
// rendered as plain React text (never HTML). Frames are fetched with the bearer header (AuthThumb).
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { useAlert } from './alert';
import type { OperatorClient } from '../api/client';
import {
  AI_MODE_CHOICES,
  type AiCandidate,
  type AiEvidenceRef,
  type AiModeChoice,
  type AiModeReceipt,
  type AiResolution,
  type CandidateApproveReceipt,
  type CandidateRejectReceipt,
  type HealthAi,
  type MarketLimits,
  type OperatorMarket,
  type ResolutionApproveReceipt,
} from '../api/types';
import { AuthThumb } from './AuthThumb';
import { ErrorNotice, MutationStatus, Panel, StateBadge } from './common';
import { BINDING_TEXT, candidateDeadlines } from './deadlines';
import { formatDuration, formatMediaMs, formatUtcClock, shortId } from './format';
import { approvalCloseInS, genericKindLabel, genericParamsText, isGenericCandidate, subjectsText } from './generic';
import { useMutation, useNow, usePoll } from './hooks';

const AI_ORIGINS = new Set(['AI_APPROVED', 'AI_AUTOMATIC']);
const NONTERMINAL = new Set(['OPEN', 'LOCKED', 'EVALUATING']);

const MODE_EXPLAIN: Record<AiModeChoice, string> = {
  OFF: 'Candidates are dropped (AI_OFF) and AI resolutions are only recorded.',
  SHADOW: 'Candidates are stored for review but never opened; resolutions are only recorded.',
  APPROVAL:
    'Supervised AI: every candidate waits for an operator approval (60 s window), and every YES / NO / UNRESOLVABLE suggestion waits for approval.',
  AUTOMATIC: 'Candidates open at once as AI_AUTOMATIC markets, and clean results settle without approval.',
};

/** Server-clock estimate: the last server_time_utc plus local time elapsed since it arrived. */
function serverNow(serverTimeUtc: string | null | undefined, okAt: number | null, now: number): number | null {
  if (!serverTimeUtc || okAt === null) return null;
  const t = Date.parse(serverTimeUtc);
  return Number.isNaN(t) ? null : t + Math.max(0, now - okAt);
}

function Untrusted({ label, text, testId }: { label: string; text: string; testId?: string }) {
  return (
    <div className="untrusted-box" data-testid={testId}>
      <span className="untrusted-label">{label}</span>
      <span className="untrusted-text">{text || '(empty)'}</span>
    </div>
  );
}

function EvidenceRefs({ client, refs }: { client: OperatorClient; refs: AiEvidenceRef[] }) {
  const frames = refs.filter((r) => r.evidence_id && r.kind === 'FRAME');
  const texts = refs.filter((r) => r.kind === 'TRANSCRIPT');
  return (
    <div className="ai-evidence">
      {texts.length > 0 && (
        <ul className="snippets">
          {texts.map((r) => (
            <li key={r.ref}>
              <span className="mono small">
                {formatMediaMs(r.media_start_ms)}–{formatMediaMs(r.media_end_ms)}
              </span>{' '}
              <span className="untrusted" data-testid="transcript-snippet">
                {r.transcript_text ?? '(transcript unavailable)'}
              </span>{' '}
              <span className="muted small">received {formatUtcClock(r.received_at_utc)}</span>
            </li>
          ))}
        </ul>
      )}
      {frames.length > 0 && (
        <div className="frames">
          {frames.map((r) => (
            <AuthThumb
              key={r.ref}
              client={client}
              evidenceId={r.evidence_id as string}
              alt={`Cited frame at ${formatMediaMs(r.media_start_ms)}`}
              caption={<>{formatMediaMs(r.media_start_ms)} · {formatUtcClock(r.received_at_utc)}</>}
              testId="cited-frame"
            />
          ))}
        </div>
      )}
      {texts.length === 0 && frames.length === 0 && <div className="muted small">No resolvable evidence.</div>}
    </div>
  );
}

// ---- AI mode --------------------------------------------------------------------------------------------

function AiModeSelector({ client, ai, onChanged }: { client: OperatorClient; ai: HealthAi | null; onChanged: () => void }) {
  const [target, setTarget] = useState<AiModeChoice | null>(null);
  const change = useMutation<AiModeReceipt>(() => {
    setTarget(null);
    onChanged();
  });
  const current = ai?.ai_mode ?? null;
  const busy = change.state.status === 'busy';
  return (
    <div className="ai-modes" data-testid="ai-mode-selector">
      <span className="label">AI mode</span>
      {AI_MODE_CHOICES.map((mode) => {
        const unavailable = mode === 'AUTOMATIC' && ai?.allow_automatic !== true;
        return (
          <button
            key={mode}
            type="button"
            className={`btn mode ${mode === current ? 'current' : ''} ${unavailable ? 'unavailable' : ''}`}
            disabled={busy || mode === current || unavailable || !ai}
            aria-pressed={mode === current}
            title={unavailable ? 'Unavailable: the server flag FAZETIME_ALLOW_AUTOMATIC is off (D32).' : MODE_EXPLAIN[mode]}
            onClick={() => {
              change.reset();
              setTarget(mode);
            }}
          >
            {mode}
            {unavailable && <span className="small"> · unavailable</span>}
          </button>
        );
      })}
      {ai && ai.effective_ai_mode !== ai.ai_mode && (
        <span className="badge state-stale">effective {ai.effective_ai_mode}</span>
      )}
      {target && (
        <div className="confirm" data-testid="ai-mode-confirm">
          <p>
            Change AI mode from <strong>{current ?? 'unknown'}</strong> to <strong>{target}</strong>? {MODE_EXPLAIN[target]}
          </p>
          <div className="actions">
            <button type="button" className="btn primary" disabled={busy} onClick={() => void change.run(() => client.setAiMode(target))}>
              Confirm: set {target}
            </button>
            <button type="button" className="btn" disabled={busy} onClick={() => setTarget(null)}>
              Cancel
            </button>
          </div>
        </div>
      )}
      <MutationStatus
        state={change.state}
        client={client}
        run={change.run}
        describe={(r) => (
          <div>
            AI mode {r.receipt.previous_ai_mode} → <strong>{r.receipt.ai_mode}</strong>
          </div>
        )}
      />
    </div>
  );
}

// ---- candidates -----------------------------------------------------------------------------------------

export function CandidateCard({
  client,
  c,
  serverNowMs,
  limits,
  onChanged,
  isNew,
}: {
  client: OperatorClient;
  c: AiCandidate;
  serverNowMs: number | null;
  limits: { evidenceFreshS: number; minLeadMs: number; closeMin: number; closeMax: number };
  onChanged: () => void;
  isNew: boolean;
}) {
  const [override, setOverride] = useState('');
  const [reason, setReason] = useState('');
  const approve = useMutation<CandidateApproveReceipt>(() => onChanged());
  const reject = useMutation<CandidateRejectReceipt>(() => onChanged());
  const busy = approve.state.status === 'busy' || reject.state.status === 'busy';

  const overrideN = override.trim() === '' ? null : Number(override);
  const overrideOk =
    overrideN === null || (Number.isSafeInteger(overrideN) && overrideN >= limits.closeMin && overrideN <= limits.closeMax);
  // §9.19 item 5: a blank override still sends a generic candidate's own close_in_s (counted from approval);
  // for H2H, blank stays null (receipt-anchored close), unchanged.
  const generic = isGenericCandidate(c);
  const defaultClose = approvalCloseInS(c);
  const closeToSend = overrideN ?? defaultClose;
  const kindLabel = genericKindLabel(c);
  const paramsText = genericParamsText(c.generic?.params);
  const d = serverNowMs === null ? null : candidateDeadlines(c, serverNowMs, { ...limits, override: closeToSend !== null });
  const timeLeft = d?.approveMs ?? null;
  const late = timeLeft !== null && timeLeft <= 0;
  const canAct = c.actionable && !late;
  const pct = d?.expiryMs != null ? Math.max(0, Math.min(100, (d.expiryMs / 60_000) * 100)) : 0;
  const reasonOk = reason.trim().length >= 1 && reason.trim().length <= 200;

  const doApprove = () => {
    if (!canAct || !overrideOk || busy) return;
    void approve.run(() => client.approveCandidate(c.id, closeToSend));
  };
  const doReject = (e: FormEvent) => {
    e.preventDefault();
    if (!c.actionable || !reasonOk || busy) return;
    void reject.run(() => client.rejectCandidate(c.id, reason.trim()));
  };

  return (
    <article
      className={`ai-card ${c.actionable ? 'actionable' : ''} ${isNew ? 'flash' : ''}`}
      data-testid="candidate-card"
      data-status={c.status}
      data-actionable={String(c.actionable)}
    >
      <header>
        <StateBadge state={c.status} />
        {c.reject_code && <span className="badge state-gap">{c.reject_code}</span>}
        {isNew && <span className="badge new">NEW</span>}
        <code title={c.id}>{shortId(c.id)}</code>
        <span className="muted small">
          {c.template_id ?? 'template unknown'} · {c.model} · {c.prompt_version} · received {formatUtcClock(c.received_at_utc)}
        </span>
      </header>

      {c.actionable && d && (
        <div className={`countdown ${late ? 'late' : (timeLeft ?? 0) < 15_000 ? 'urgent' : ''}`} data-testid="candidate-countdown">
          <div className="big">{late ? 'TOO LATE' : formatDuration(timeLeft)}</div>
          <div className="small">
            {late ? 'Approval window closed' : 'left to approve'}
            {d.binding && <> · limited by {BINDING_TEXT[d.binding]}</>}
            <div className="muted">
              Expiry {d.expiryMs === null ? '—' : formatDuration(Math.max(0, d.expiryMs))} · Evidence fresh{' '}
              {d.evidenceMs === null ? '—' : formatDuration(Math.max(0, d.evidenceMs))}
              {d.leadMs !== null && <> · Lead {formatDuration(Math.max(0, d.leadMs))}</>}
            </div>
          </div>
          <div className="bar" aria-hidden="true">
            <div className="bar-yes" style={{ width: `${pct}%` }} />
          </div>
        </div>
      )}

      {generic && (
        <div className="small" data-testid="candidate-kind">
          <span className="badge">{kindLabel ?? 'Generic'}</span>{' '}
          {c.generic ? (
            <>
              <code>{c.generic.kind}</code> · unit {c.generic.unit}
              {paramsText && <> · {paramsText}</>} · episode start {formatMediaMs(c.generic.episode_start_media_ms)}
            </>
          ) : (
            <span className="muted">no generic detail from the server</span>
          )}
        </div>
      )}
      <p className="question">{c.question}</p>
      <div className="sides">
        <div className="side-terms yes">
          <span className="label">YES · {c.yes.label}</span>
          <span>{c.yes.predicate}</span>
        </div>
        <div className="side-terms no">
          <span className="label">NO · {c.no.label}</span>
          <span>{c.no.predicate}</span>
        </div>
      </div>
      <div className="small muted" data-testid="candidate-terms">
        {subjectsText(c)} · episode <code>{c.episode_fingerprint}</code> ·{' '}
        {generic && defaultClose !== null
          ? `close ${defaultClose} s from approval`
          : `close ${c.close_in_s ?? c.suggested_close_in_s} s${c.proposed_close_at_utc ? ` (at ${formatUtcClock(c.proposed_close_at_utc)}, from receipt)` : ''}`}{' '}
        · resolve {c.resolve_in_s ?? c.suggested_resolve_in_s} s
      </div>
      {c.cancellation_conditions.length > 0 && (
        <div className="small">
          VOID if: {c.cancellation_conditions.map((t, i) => <span key={i} className="untrusted">{i ? '; ' : ''}{t}</span>)}
        </div>
      )}
      <Untrusted label="Model text, untrusted" text={c.rationale} testId="rationale" />
      <EvidenceRefs client={client} refs={c.evidence} />

      {c.actionable ? (
        <div className="ai-actions">
          <div className="approve-row">
            <button type="button" className="btn primary big-btn" disabled={!canAct || !overrideOk || busy} onClick={doApprove}>
              Approve → open AI_APPROVED market
            </button>
            <label className="inline-field">
              close_in_s override
              <input
                value={override}
                onChange={(e) => setOverride(e.target.value)}
                inputMode="numeric"
                placeholder={`${limits.closeMin}–${limits.closeMax}`}
                aria-invalid={!overrideOk}
              />
              <span className="muted small">
                {overrideN === null
                  ? defaultClose !== null
                    ? `blank sends its ${defaultClose} s, counted from approval (§9.19)`
                    : `blank keeps the close at ${formatUtcClock(c.proposed_close_at_utc)} (from receipt)`
                  : overrideOk
                    ? `closes ${overrideN} s after approval`
                    : `must be ${limits.closeMin}–${limits.closeMax}`}
              </span>
            </label>
            {d?.binding === 'LEAD' && overrideN === null && (
              <div className="small hint">
                Time is limited by the minimum lead before the receipt-anchored close. An override (counted from approval)
                gives more time, up to the expiry and evidence windows.
              </div>
            )}
          </div>
          <form className="reject-row" onSubmit={doReject} method="post">
            <label>
              Reject reason (required)
              <input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={200} />
            </label>
            <button type="submit" className="btn danger" disabled={!reasonOk || busy}>
              Reject
            </button>
          </form>
        </div>
      ) : (
        <div className="muted small">
          Not actionable ({c.status}
          {c.reject_code ? `, ${c.reject_code}` : ''}){c.market_id ? ` · market ${shortId(c.market_id)}` : ''}
          {c.decision_note ? (
            <>
              {' '}
              · operator note: <span className="untrusted">{c.decision_note}</span>
            </>
          ) : null}
        </div>
      )}
      <MutationStatus
        state={approve.state}
        client={client}
        run={approve.run}
        describe={(r) => (
          <div>
            Opened market <code>{shortId(r.receipt.market.market_id)}</code> <StateBadge state={r.receipt.market.state} />{' '}
            {r.receipt.market.origin} · closes {formatUtcClock(r.receipt.market.close_at_utc)}
          </div>
        )}
      />
      <MutationStatus
        state={reject.state}
        client={client}
        run={reject.run}
        describe={(r) => (
          <div>
            Candidate <code>{shortId(r.receipt.candidate.id)}</code> is {r.receipt.candidate.status} ({r.receipt.candidate.reject_code})
          </div>
        )}
      />
    </article>
  );
}

function CandidatesSection({
  client,
  limits,
  onChanged,
  sound,
  setSound,
  beep,
}: {
  client: OperatorClient;
  limits: { evidenceFreshS: number; minLeadMs: number; closeMin: number; closeMax: number };
  onChanged: () => void;
  sound: boolean;
  setSound: (v: boolean) => void;
  beep: () => void;
}) {
  const fetchList = useCallback((signal: AbortSignal) => client.candidates(signal), [client]);
  const poll = usePoll(fetchList, 2_000);
  const now = useNow(250);
  const seen = useRef<Set<string>>(new Set());
  const [fresh, setFresh] = useState<Record<string, number>>({});

  const list = poll.data?.candidates ?? [];
  const pendingIds = list.filter((c) => c.status === 'PENDING').map((c) => c.id).join(',');
  useEffect(() => {
    if (!pendingIds) return;
    const added = pendingIds.split(',').filter((id) => !seen.current.has(id));
    if (added.length === 0) return;
    added.forEach((id) => seen.current.add(id));
    const at = Date.now();
    setFresh((f) => ({ ...f, ...Object.fromEntries(added.map((id) => [id, at])) }));
    beep();
  }, [pendingIds, beep]);

  const sNow = serverNow(poll.data?.server_time_utc, poll.okAt, now);
  const actionable = list.filter((c) => c.actionable);
  const recent = list.filter((c) => !c.actionable).slice(0, 3);
  return (
    <div className="ai-section">
      <h3>
        Candidates <span className="muted small">(polled every 2 s)</span>
        <label className="inline small">
          <input type="checkbox" checked={sound} onChange={(e) => setSound(e.target.checked)} /> sound alert
        </label>
      </h3>
      {poll.error !== null && poll.error !== undefined && <ErrorNotice error={poll.error} title="Candidate poll failed" />}
      {actionable.length === 0 && <p className="muted small">No candidate is waiting for approval.</p>}
      {[...actionable, ...recent].map((c) => (
        <CandidateCard
          key={c.id}
          client={client}
          c={c}
          serverNowMs={sNow}
          limits={limits}
          onChanged={() => {
            poll.refresh();
            onChanged();
          }}
          isNew={c.actionable && fresh[c.id] !== undefined && now - fresh[c.id] < 10_000}
        />
      ))}
    </div>
  );
}

// ---- resolutions ----------------------------------------------------------------------------------------

export function ResolutionCard({
  client,
  r,
  market,
  serverNowMs,
  onChanged,
}: {
  client: OperatorClient;
  r: AiResolution;
  market: OperatorMarket | null;
  serverNowMs: number | null;
  onChanged: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const approve = useMutation<ResolutionApproveReceipt>(() => {
    setConfirming(false);
    onChanged();
  });
  const busy = approve.state.status === 'busy';
  const deadline = r.market_resolve_by_utc ? Date.parse(r.market_resolve_by_utc) : NaN;
  const left = serverNowMs !== null && !Number.isNaN(deadline) ? deadline - serverNowMs : null;
  const settles = r.decision === 'YES' || r.decision === 'NO';
  const sideLabel = r.decision === 'YES' ? market?.yes_label : r.decision === 'NO' ? market?.no_label : null;
  const action = settles ? `settle ${r.decision}${sideLabel ? ` (${sideLabel})` : ''}` : 'VOID as UNRESOLVABLE (every stake refunded)';
  return (
    <article className={`ai-card ${r.actionable ? 'actionable' : ''}`} data-testid="resolution-card" data-status={r.status} data-actionable={String(r.actionable)}>
      <header>
        <span className={`badge decision-${r.decision.toLowerCase()}`}>{r.decision}</span>
        <StateBadge state={r.status} />
        {r.status_reason && <span className="muted small">{r.status_reason}</span>}
        <code title={r.id}>{shortId(r.id)}</code>
        <span className="muted small">
          {r.model} · {r.prompt_version} · received {formatUtcClock(r.received_at_utc)}
        </span>
      </header>
      {r.actionable && left !== null && (
        <div className={`countdown ${left < 30_000 ? 'urgent' : ''}`}>
          <div className="big">{formatDuration(Math.max(0, left))}</div>
          <div className="small">
            until resolve_by ({formatUtcClock(r.market_resolve_by_utc)}). After that the sweeper VOIDs the market
            (RESOLUTION_TIMEOUT) and refunds everyone.
          </div>
        </div>
      )}
      <div className="small">
        Media {formatMediaMs(r.media_interval.start_ms)}–{formatMediaMs(r.media_interval.end_ms)} · predicate support: YES{' '}
        {r.predicate_support.YES ? 'supported' : 'not supported'}, NO {r.predicate_support.NO ? 'supported' : 'not supported'}
      </div>
      {r.contradictions.length > 0 && (
        <div className="untrusted-box" data-testid="contradictions">
          <span className="untrusted-label">Contradictions (model text, untrusted)</span>
          <ul>
            {r.contradictions.map((t, i) => (
              <li key={i} className="untrusted-text">
                {t}
              </li>
            ))}
          </ul>
        </div>
      )}
      <Untrusted label="Reason (model text, untrusted)" text={r.reason} testId="resolution-reason" />
      <EvidenceRefs client={client} refs={r.evidence} />
      {r.actionable ? (
        confirming ? (
          <div className="confirm" data-testid="resolution-confirm">
            <p>
              Approve this suggestion and <strong>{action}</strong>? The server applies exactly what the suggestion says, in
              one transaction. This is final.
            </p>
            <div className="actions">
              <button type="button" className="btn primary" disabled={busy} onClick={() => void approve.run(() => client.approveResolution(r.id))}>
                Confirm: {action}
              </button>
              <button type="button" className="btn" disabled={busy} onClick={() => setConfirming(false)}>
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <div className="actions">
            <button
              type="button"
              className="btn primary big-btn"
              onClick={() => {
                approve.reset();
                setConfirming(true);
              }}
            >
              Approve: {action}…
            </button>
          </div>
        )
      ) : (
        <div className="muted small">Not actionable ({r.status}{r.status_reason ? `, ${r.status_reason}` : ''}).</div>
      )}
      <MutationStatus
        state={approve.state}
        client={client}
        run={approve.run}
        describe={(res) => (
          <div>
            Market <code>{shortId(res.receipt.market.market_id)}</code> is now <StateBadge state={res.receipt.market.state} />
            {res.receipt.market.winning_side && <> · winner {res.receipt.market.winning_side}</>}
            {res.receipt.market.void_reason && <> · {res.receipt.market.void_reason} (refunded)</>}
          </div>
        )}
      />
    </article>
  );
}

function ResolutionsSection({ client, market, onChanged }: { client: OperatorClient; market: OperatorMarket; onChanged: () => void }) {
  const fetchList = useCallback((signal: AbortSignal) => client.resolutions(market.market_id, signal), [client, market.market_id]);
  const poll = usePoll(fetchList, 2_000);
  const now = useNow(500);
  const sNow = serverNow(poll.data?.server_time_utc, poll.okAt, now);
  const list = poll.data?.resolutions ?? [];
  return (
    <div className="ai-section">
      <h3>
        Resolutions for <code>{shortId(market.market_id)}</code> <StateBadge state={market.state} />{' '}
        <span className="muted small">{market.origin}</span>
      </h3>
      <p className="question small">{market.question}</p>
      {poll.error !== null && poll.error !== undefined && <ErrorNotice error={poll.error} title="Resolution poll failed" />}
      {list.length === 0 && (
        <p className="muted small">
          {market.state === 'EVALUATING' ? 'Waiting for an AI resolution suggestion…' : 'No resolution suggestions yet.'}
        </p>
      )}
      {list.slice(0, 4).map((r) => (
        <ResolutionCard
          key={r.id}
          client={client}
          r={r}
          market={market}
          serverNowMs={sNow}
          onChanged={() => {
            poll.refresh();
            onChanged();
          }}
        />
      ))}
      {NONTERMINAL.has(market.state) && (
        <p className="muted small">
          For an AI market, either approve a suggestion here or void the market with a reason in Market controls
          (OPERATOR_CANCELLED, every stake refunded). Hand settlement is fixture-only.
        </p>
      )}
    </div>
  );
}

// ---- panel ----------------------------------------------------------------------------------------------

export function AiPanel({
  client,
  ai,
  markets,
  limits,
  hasStream,
  onChanged,
}: {
  client: OperatorClient;
  ai: HealthAi | null;
  markets: OperatorMarket[];
  limits: MarketLimits | null;
  hasStream: boolean;
  onChanged: () => void;
}) {
  const { sound, setSound, beep } = useAlert();
  const aiMarket =
    markets.find((m) => NONTERMINAL.has(m.state) && AI_ORIGINS.has(m.origin)) ?? markets.find((m) => AI_ORIGINS.has(m.origin)) ?? null;
  const lim = {
    evidenceFreshS: limits?.evidence_fresh_s ?? 90,
    minLeadMs: limits?.min_lead_ms ?? 30_000,
    closeMin: limits?.ai_close_in_s?.min ?? 45,
    closeMax: limits?.ai_close_in_s?.max ?? 600,
  };
  const attention = (ai?.pending_candidates ?? 0) + (ai?.pending_resolutions ?? 0) > 0;
  return (
    <Panel
      title="Supervised AI"
      className={`ai ${attention ? 'attention' : ''}`}
      tag={
        <>
          <span className="tag">§9.17 · model proposes, server validates, operator decides</span>
          {(ai?.pending_candidates ?? 0) > 0 && <span className="badge alert">{ai?.pending_candidates} candidate(s) pending</span>}
          {(ai?.pending_resolutions ?? 0) > 0 && <span className="badge alert">{ai?.pending_resolutions} resolution(s) to approve</span>}
        </>
      }
    >
      {!hasStream ? (
        <p className="muted">Create the stream first.</p>
      ) : (
        <>
          <AiModeSelector client={client} ai={ai} onChanged={onChanged} />
          <CandidatesSection client={client} limits={lim} onChanged={onChanged} sound={sound} setSound={setSound} beep={beep} />
          {aiMarket && <ResolutionsSection key={aiMarket.market_id} client={client} market={aiMarket} onChanged={onChanged} />}
        </>
      )}
    </Panel>
  );
}
