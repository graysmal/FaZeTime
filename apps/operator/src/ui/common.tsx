import type { ReactNode } from 'react';
import { ApiFailure, type MutationResult, type OperatorClient } from '../api/client';
import type { OperatorReceipt } from '../api/types';
import type { MutationState } from './hooks';

const CODE_HINTS: Record<string, string> = {
  UNAUTHENTICATED: 'Session missing, expired or revoked. Sign in again.',
  FORBIDDEN: 'This session is not allowed to do that (operator session required).',
  NOT_FOUND: 'Not found: no stream exists yet, or the id is unknown.',
  STALE_MARKET: 'Another market in this run is still OPEN, LOCKED or EVALUATING. Settle or void it first.',
  WRONG_RUN: 'That market belongs to an archived run.',
  IDEMPOTENCY_CONFLICT: 'This operation_id was already used with a different request. Nothing changed.',
  VALIDATION_FAILED: 'The server rejected the input.',
  INVALID_AMOUNT: 'Amount outside the allowed range or step.',
  RATE_LIMITED: 'Too many requests. Wait, then retry the same operation.',
  INTERNAL_ERROR: 'Server error. The outcome is unknown until confirmed.',
  CAPABILITY_UNAVAILABLE: 'Not available in this phase or build.',
  SOURCE_STALE: 'The Twitch source is not LIVE.',
};

const CLOSED_HINTS: Record<string, string> = {
  STATE: 'The market is in the wrong state for this action.',
  DEADLINE: 'The deadline has passed. The sweeper voids the market at resolve_by (RESOLUTION_TIMEOUT).',
  PAUSED: 'Wagering is paused by the operator.',
};

function detailLines(info: ApiFailure['info']): ReactNode {
  if (!info || info.details === null || info.details === undefined) return null;
  const d = info.details as Record<string, unknown>;
  if (info.code === 'VALIDATION_FAILED' && Array.isArray(d.fields)) {
    return (
      <ul className="fields">
        {(d.fields as { loc?: unknown; msg?: unknown }[]).map((f, i) => (
          <li key={i}>
            <code>{Array.isArray(f.loc) ? f.loc.join('.') : String(f.loc ?? '')}</code>: {String(f.msg ?? '')}
          </li>
        ))}
      </ul>
    );
  }
  return <pre className="details">{JSON.stringify(info.details, null, 2)}</pre>;
}

/** A typed §9.10 error (or a transport failure), rendered as text. */
export function ErrorNotice({ error, title }: { error: unknown; title?: string }) {
  if (!(error instanceof ApiFailure)) {
    const message = error instanceof Error ? error.message : String(error);
    return (
      <div className="notice error" role="alert">
        <strong>{title ?? 'Error'}</strong>: {message}
      </div>
    );
  }
  const info = error.info;
  const closedReason =
    info?.code === 'MARKET_CLOSED' && info.details && typeof info.details === 'object'
      ? String((info.details as Record<string, unknown>).reason ?? '')
      : '';
  const hint = info ? (info.code === 'MARKET_CLOSED' ? CLOSED_HINTS[closedReason] : CODE_HINTS[info.code]) : undefined;
  return (
    <div className={`notice ${error.outcomeUnknown ? 'unknown' : 'error'}`} role="alert" data-testid="error-notice">
      <div className="notice-head">
        <strong>{title ?? (error.outcomeUnknown ? 'Outcome unknown' : 'Refused')}</strong>
        {info ? <span className="code">{info.code}</span> : <span className="code">{error.kind.toUpperCase()}</span>}
        {error.status !== null && <span className="muted">HTTP {error.status}</span>}
      </div>
      <div>{error.message}</div>
      {hint && <div className="muted">{hint}</div>}
      {detailLines(info)}
      <div className="muted small">
        {info?.request_id && <>request_id <code>{info.request_id}</code> · </>}
        {error.operationId && <>operation_id <code>{error.operationId}</code> · </>}
        {info ? `retryable: ${info.retryable ? 'yes' : 'no'}` : 'no error envelope'}
        {info?.retry_after_ms ? ` · retry after ${Math.ceil(info.retry_after_ms / 1000)} s` : ''}
      </div>
      {error.outcomeUnknown && (
        <div className="small">
          Do not assume it failed or succeeded. Retry sends the <em>same</em> operation_id, so the server applies it at
          most once; or check the status panels.
        </div>
      )}
    </div>
  );
}

/** Busy / receipt / error line under a mutation control. */
export function MutationStatus<T extends OperatorReceipt>({
  state,
  client,
  run,
  describe,
}: {
  state: MutationState<T>;
  client: OperatorClient;
  run: (exec: () => Promise<MutationResult<T>>) => Promise<MutationResult<T> | null>;
  describe?: (result: MutationResult<T>) => ReactNode;
}) {
  if (state.status === 'idle') return null;
  if (state.status === 'busy') return <div className="notice busy">Sending… waiting for the server receipt.</div>;
  if (state.status === 'ok') {
    const r = state.result;
    return (
      <div className="notice ok" data-testid="receipt">
        <div className="notice-head">
          <strong>Server receipt</strong>
          <span className="muted">HTTP {r.httpStatus}</span>
          {r.replayed && <span className="code">REPLAYED</span>}
        </div>
        {describe?.(r)}
        <div className="muted small">
          operation_id <code>{r.operationId}</code>
        </div>
      </div>
    );
  }
  const failure = state.failure;
  const pending = failure instanceof ApiFailure && failure.retrySameOperation ? failure.pending : null;
  return (
    <div>
      <ErrorNotice error={failure} />
      {pending && (
        <button type="button" className="btn small" onClick={() => void run(() => client.retry<T>(pending))}>
          Retry same operation
        </button>
      )}
    </div>
  );
}

export function Panel({ title, tag, children, className }: { title: string; tag?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`panel ${className ?? ''}`} aria-label={title}>
      <h2>
        {title}
        {tag}
      </h2>
      {children}
    </section>
  );
}

export function StateBadge({ state }: { state: string | null | undefined }) {
  const s = state ?? 'UNKNOWN';
  return <span className={`badge state-${s.toLowerCase()}`}>{s}</span>;
}
