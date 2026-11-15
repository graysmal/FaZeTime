import { useState } from 'react';
import type { OperatorClient } from '../api/client';
import type { OperatorHealth, ResetReceipt } from '../api/types';
import { MutationStatus, Panel } from './common';
import { formatMinor, formatUtcClock, shortId } from './format';
import { useMutation } from './hooks';

type Step = 'idle' | 'explain' | 'type';

export function RunPanel({ client, health, onChanged }: { client: OperatorClient; health: OperatorHealth | null; onChanged: () => void }) {
  const [step, setStep] = useState<Step>('idle');
  const [typed, setTyped] = useState('');
  const reset = useMutation<ResetReceipt>(() => {
    setStep('idle');
    setTyped('');
    onChanged();
  });
  const stream = health?.stream ?? null;
  const run = health?.run ?? null;
  const open = health?.markets?.find((m) => m.state === 'OPEN' || m.state === 'LOCKED' || m.state === 'EVALUATING') ?? null;

  return (
    <Panel title="Run controls">
      {!stream || !run ? (
        <p className="muted">No stream or run yet.</p>
      ) : (
        <>
          <div className="small">
            Run <code title={run.run_id}>{shortId(run.run_id)}</code> · {run.state} · since {formatUtcClock(run.created_at_utc)} ·
            seed {formatMinor(run.seed_grant_minor)} per viewer
          </div>
          {step === 'idle' && (
            <button
              type="button"
              className="btn danger"
              onClick={() => {
                reset.reset();
                setStep('explain');
              }}
            >
              Reset run…
            </button>
          )}
          {step === 'explain' && (
            <div className="confirm" data-testid="reset-explain">
              <p>Reset will, in one server transaction:</p>
              <ol>
                <li>
                  {open ? (
                    <>
                      VOID the {open.state} market <code>{shortId(open.market_id)}</code> with reason RUN_RESET and refund
                      every accepted stake ({formatMinor(open.pool.total_minor)}).
                    </>
                  ) : (
                    'VOID the open market with RUN_RESET and refund its stakes (none is open right now).'
                  )}
                </li>
                <li>
                  ARCHIVE run <code>{shortId(run.run_id)}</code>. It stays inspectable; ledger history and idempotency keys are
                  kept.
                </li>
                <li>Create a new run and give every viewer a fresh SEED_GRANT. Wallets are per run, so balances start over.</li>
              </ol>
              <p>This cannot be undone.</p>
              <div className="actions">
                <button type="button" className="btn danger" onClick={() => setStep('type')}>
                  Continue
                </button>
                <button type="button" className="btn" onClick={() => setStep('idle')}>
                  Cancel
                </button>
              </div>
            </div>
          )}
          {step === 'type' && (
            <form
              className="confirm"
              method="post"
              onSubmit={(e) => {
                e.preventDefault();
                if (typed === 'RESET') void reset.run(() => client.resetRun(stream.stream_id));
              }}
            >
              <label>
                Second confirmation: type RESET
                <input value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" spellCheck={false} />
              </label>
              <div className="actions">
                <button type="submit" className="btn danger" disabled={typed !== 'RESET' || reset.state.status === 'busy'}>
                  Reset run now
                </button>
                <button type="button" className="btn" onClick={() => setStep('idle')} disabled={reset.state.status === 'busy'}>
                  Cancel
                </button>
              </div>
            </form>
          )}
          <MutationStatus
            state={reset.state}
            client={client}
            run={reset.run}
            describe={(r) => (
              <div>
                Archived <code>{shortId(r.receipt.archived_stream_session_id)}</code> → new run{' '}
                <code>{shortId(r.receipt.stream_session_id)}</code>
                {r.receipt.voided_market_id ? (
                  <>
                    {' '}
                    · voided <code>{shortId(r.receipt.voided_market_id)}</code> (refunded)
                  </>
                ) : (
                  ' · no market needed voiding'
                )}
              </div>
            )}
          />
        </>
      )}
    </Panel>
  );
}
