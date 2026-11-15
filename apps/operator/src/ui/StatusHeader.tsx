import type { Modes } from '@fazetime/contracts';
import type { OperatorHealth } from '../api/types';
import { ErrorNotice, StateBadge } from './common';
import { diffMs, formatDuration, formatMinor, formatUtcClock, shortId } from './format';

// D31: the operator console keeps full, explicit labels for media source, AI mode and funding.
const AI_MODE_TEXT: Record<string, string> = {
  OFF: 'AI off: no proposals',
  SHADOW: 'shadow: candidates stored, never opened',
  APPROVAL: 'supervised AI: operator approves',
  AUTOMATIC: 'automatic: opens/settles without approval',
  FIXTURE: 'canned fixtures, not AI',
};
const PAYMENT_TEXT: Record<string, string> = {
  UNAVAILABLE: 'no top-ups: seed grants + fixture credits only',
  MOCK: 'mock payments (dev only)',
  STRIPE_TEST: 'Stripe TEST mode (no real charges)',
};
const SOURCE_TEXT: Record<string, string> = {
  TWITCH_STREAMLINK: 'Twitch via Streamlink',
  TWITCH_TAB_CAPTURE: 'Twitch via operator tab capture',
  TEST_FIXTURE: 'TEST FIXTURE: not Twitch',
};

export interface StatusProps {
  health: OperatorHealth | null;
  healthError: unknown;
  okAt: number | null;
  now: number;
  modes: Modes | null;
  modesError: unknown;
}

function Field({ label, children, title }: { label: string; children: React.ReactNode; title?: string }) {
  return (
    <div className="field" title={title}>
      <span className="label">{label}</span>
      <span className="value">{children}</span>
    </div>
  );
}

export function StatusHeader({ health, healthError, okAt, now, modes, modesError }: StatusProps) {
  const age = okAt === null ? null : Math.max(0, now - okAt);
  const stale = age === null || age > 6_000;
  const h = health;
  const sh = h?.source_health ?? null;
  const mediaAge = sh ? diffMs(sh.last_media_at_utc, h?.server_time_utc) : null;
  const transcriptAge = sh ? diffMs(sh.last_transcript_at_utc, h?.server_time_utc) : null;
  const backlog = sh && typeof sh.asr_backlog_ms === 'number' ? sh.asr_backlog_ms : null;
  const rec = h?.reconciliation ?? null;
  const aiMode = h?.run?.ai_mode ?? modes?.ai_mode ?? 'unknown';
  const payment = modes?.payment_mode ?? 'unknown';
  const mediaSource = modes?.media_source_kind ?? sh?.source_kind ?? null;

  return (
    <section className="status" aria-label="Status">
      <div className={`poll ${stale ? 'poll-stale' : 'poll-ok'}`} data-testid="poll-state">
        {okAt === null
          ? 'Loading operator health…'
          : stale
            ? `STALE: last good health ${formatDuration(age)} ago`
            : `Health updated ${formatDuration(age)} ago (every 2 s)`}
      </div>
      {healthError !== null && healthError !== undefined && <ErrorNotice error={healthError} title="Health poll failed" />}
      <div className="status-grid">
        <div className="card">
          <h3>Run</h3>
          <Field label="Run" title={h?.run?.run_id ?? ''}>
            <code>{shortId(h?.run?.run_id)}</code> <StateBadge state={h?.run?.state ?? 'NO RUN'} />
          </Field>
          <Field label="Channel">{h?.stream?.twitch_channel_login ?? 'no stream yet'}</Field>
          <Field label="Server time">{formatUtcClock(h?.server_time_utc)}</Field>
          <Field label="Archived runs">{h?.counts?.archived_runs ?? '—'}</Field>
        </div>
        <div className="card">
          <h3>Source health</h3>
          <Field label="State">
            <StateBadge state={sh?.state ?? (h ? 'NO STREAM' : null)} />
          </Field>
          <Field label="Epoch" title={sh?.source_epoch ?? ''}>
            <code>{shortId(sh?.source_epoch)}</code> {sh?.source_kind ?? ''}
          </Field>
          <Field label="Last media age">{sh?.last_media_at_utc ? formatDuration(mediaAge) : 'no media'}</Field>
          <Field label="Last transcript age">
            {sh?.last_transcript_at_utc ? formatDuration(transcriptAge) : 'none'}
          </Field>
          <Field label="ASR backlog">{backlog === null ? 'not reported by API' : formatDuration(backlog)}</Field>
        </div>
        <div className="card">
          <h3>Modes</h3>
          <Field label="AI mode" title={AI_MODE_TEXT[aiMode] ?? ''}>
            <span className="badge" data-testid="ai-mode">{aiMode}</span>
          </Field>
          <div className="explain small">{AI_MODE_TEXT[aiMode] ?? 'unrecognized mode (shown as-is)'}</div>
          <Field label="Funding" title={`payment_mode ${payment}`}>
            <span className="badge" data-testid="payment-mode">{payment}</span>
            {modesError !== null && modesError !== undefined && <span className="muted small"> (snapshot failed)</span>}
          </Field>
          <div className="explain small">payment_mode: {PAYMENT_TEXT[payment] ?? 'unknown (snapshot not read yet)'} · test money only</div>
          <Field label="Media source">
            <span className="badge" data-testid="media-source">{mediaSource ?? 'NONE'}</span>
          </Field>
          <div className="explain small">{mediaSource ? SOURCE_TEXT[mediaSource] ?? 'unrecognized source' : 'no worker epoch registered'}</div>
          <Field label="Wagering paused">
            {h?.stream ? (h.stream.wagering_paused ? `yes (${h.stream.wagering_paused_reason ?? '?'})` : 'no') : '—'}
          </Field>
        </div>
        <div className="card">
          <h3>Ledger</h3>
          <Field label="Reconciliation">
            {rec ? (
              <span className={`badge ${rec.ok ? 'state-live' : 'state-gap'}`} data-testid="reconcile">
                {rec.ok ? 'OK' : `FAILED (${rec.problems.length})`}
              </span>
            ) : (
              '—'
            )}
          </Field>
          <Field label="Checked">
            {rec ? `${rec.accounts_checked} accts · ${rec.transactions_checked} txns · ${rec.markets_checked} mkts` : '—'}
          </Field>
          <Field label="Funding source account" title="FUNDING_SOURCE ledger account for this run: seed grants and fixture credits are drawn from it (negative = demo money issued)">
            {formatMinor(h?.funding_source_minor ?? null)}
          </Field>
          <Field label="Seed grant / viewer">{formatMinor(h?.run?.seed_grant_minor ?? null)}</Field>
          {rec && !rec.ok && (
            <ul className="problems">
              {rec.problems.slice(0, 4).map((p, i) => (
                <li key={i}>{p}</li>
              ))}
            </ul>
          )}
        </div>
        <div className="card">
          <h3>Service</h3>
          <Field label="Sweeper">
            {h ? `${h.sweeper.enabled ? 'on' : 'OFF'} · ${h.sweeper.runs} runs · ${h.sweeper.errors} errors` : '—'}
          </Field>
          <Field label="WS subscribers">{h?.websocket?.subscribers ?? '—'}</Field>
          <Field label="Present viewers">{h?.presence ? `${h.presence.present_users}` : '—'}</Field>
          <Field label="Users">{h?.counts?.users ?? '—'}</Field>
        </div>
      </div>
    </section>
  );
}
