import { useCallback, useEffect, useRef, useState } from 'react';
import type { OperatorClient } from '../api/client';
import type { Capabilities } from '../api/capabilities';
import type { EvidenceFrame, EvidenceList, EvidenceObservation } from '../api/types';
import { ErrorNotice, Panel, StateBadge } from './common';
import { formatMediaMs, formatUtcClock, shortId } from './format';
import { usePoll } from './hooks';

const MAX_OBS = 60;
const MAX_FRAMES = 12;

/** Fetches one JPEG with the bearer header (an <img src> cannot send it) and revokes the blob URL on unmount. */
function Thumb({ client, frame }: { client: OperatorClient; frame: EvidenceFrame }) {
  const [src, setSrc] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (frame.file_pruned_at_utc) return undefined;
    const ctrl = new AbortController();
    let url: string | null = null;
    client
      .evidenceImage(frame.evidence_id, ctrl.signal)
      .then((blob) => {
        if (ctrl.signal.aborted) return;
        url = URL.createObjectURL(blob.type === 'image/jpeg' ? blob : new Blob([blob], { type: 'image/jpeg' }));
        setSrc(url);
      })
      .catch(() => {
        if (!ctrl.signal.aborted) setFailed(true);
      });
    return () => {
      ctrl.abort();
      if (url) URL.revokeObjectURL(url);
    };
  }, [client, frame.evidence_id, frame.file_pruned_at_utc]);

  return (
    <figure className="thumb" data-testid="evidence-frame">
      {src ? (
        <img src={src} alt={`Frame ${frame.sequence} at ${formatMediaMs(frame.media_ms)}`} width={160} height={90} />
      ) : (
        <div className="thumb-empty">{frame.file_pruned_at_utc ? 'pruned' : failed ? 'unavailable' : 'loading…'}</div>
      )}
      <figcaption className="small">
        {formatMediaMs(frame.media_ms)} · #{frame.sequence} · {shortId(frame.source_epoch)}
        {frame.pinned_by_market_id ? ' · pinned' : ''}
      </figcaption>
    </figure>
  );
}

function ObservationRow({ o, currentEpoch }: { o: EvidenceObservation; currentEpoch: string | null }) {
  return (
    <tr className={o.source_epoch === currentEpoch ? '' : 'old-epoch'}>
      <td className="mono">
        {formatMediaMs(o.media_start_ms)}–{formatMediaMs(o.media_end_ms)}
      </td>
      <td className="mono" title={o.source_epoch}>
        {shortId(o.source_epoch)}
      </td>
      <td>{o.kind}</td>
      <td className="text">
        {o.kind === 'TRANSCRIPT' && o.transcript ? (
          <span className="untrusted" title="Untrusted stream speech, shown as text">
            {o.transcript.text}
          </span>
        ) : o.kind === 'GAP' ? (
          <span className="gap">GAP: {o.gap_reason}</span>
        ) : (
          <span className="muted">frame {shortId(o.evidence_id)}</span>
        )}
        {o.quality_flags.length > 0 && <span className="flags"> {o.quality_flags.join(' ')}</span>}
      </td>
      <td className="mono small">{formatUtcClock(o.received_at_utc)}</td>
    </tr>
  );
}

function EvidenceFeed({ client }: { client: OperatorClient }) {
  const since = useRef<string | null>(null);
  const [obs, setObs] = useState<EvidenceObservation[]>([]);
  const [frames, setFrames] = useState<EvidenceFrame[]>([]);
  const [last, setLast] = useState<EvidenceList | null>(null);

  const fetchOnce = useCallback(
    async (signal: AbortSignal) => {
      const res = await client.evidence(since.current, signal);
      let max = since.current;
      for (const r of [...res.observations, ...res.frames]) {
        if (max === null || r.received_at_utc > max) max = r.received_at_utc;
      }
      since.current = max;
      if (res.observations.length) {
        setObs((prev) => {
          const seen = new Set(prev.map((o) => `${o.source_epoch}:${o.sequence}`));
          const fresh = res.observations.filter((o) => !seen.has(`${o.source_epoch}:${o.sequence}`));
          return [...fresh.reverse(), ...prev].slice(0, MAX_OBS);
        });
      }
      if (res.frames.length) {
        setFrames((prev) => {
          const seen = new Set(prev.map((f) => f.evidence_id));
          const fresh = res.frames.filter((f) => !seen.has(f.evidence_id));
          return [...fresh.reverse(), ...prev].slice(0, MAX_FRAMES);
        });
      }
      setLast(res);
      return res;
    },
    [client],
  );
  const poll = usePoll(fetchOnce, 3_000);
  const currentEpoch = last?.source_health?.source_epoch ?? null;

  return (
    <div>
      <div className="small">
        Source <StateBadge state={last?.source_health?.state ?? null} />{' '}
        <span className="badge" data-testid="evidence-source-kind">{last?.source_health?.source_kind ?? 'NO SOURCE'}</span>{' '}
        {last?.source_health?.source_kind === 'TEST_FIXTURE' ? '(test fixture, not Twitch)' : ''} epoch{' '}
        <code>{shortId(currentEpoch)}</code> · refreshed
        every 3 s · server {formatUtcClock(last?.server_time_utc)} · {obs.length} observations, {frames.length} frames shown
      </div>
      {poll.error !== null && poll.error !== undefined && <ErrorNotice error={poll.error} title="Evidence poll failed" />}
      <div className="frames">
        {frames.length === 0 ? (
          <p className="muted small">No frames received in the window yet.</p>
        ) : (
          frames.map((f) => <Thumb key={f.evidence_id} client={client} frame={f} />)
        )}
      </div>
      <div className="obs-scroll">
        <table className="obs">
          <thead>
            <tr>
              <th>Media time</th>
              <th>Epoch</th>
              <th>Kind</th>
              <th>Transcript / detail (untrusted text)</th>
              <th>Received</th>
            </tr>
          </thead>
          <tbody>
            {obs.length === 0 ? (
              <tr>
                <td colSpan={5} className="muted small">
                  No observations in the window yet.
                </td>
              </tr>
            ) : (
              obs.map((o) => <ObservationRow key={`${o.source_epoch}:${o.sequence}`} o={o} currentEpoch={currentEpoch} />)
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function EvidencePanel({
  client,
  caps,
  capsError,
  onRecheck,
}: {
  client: OperatorClient;
  caps: Capabilities | null;
  capsError: unknown;
  onRecheck: () => void;
}) {
  let body;
  if (capsError !== null && capsError !== undefined) {
    body = (
      <>
        <ErrorNotice error={capsError} title="Could not read /openapi.json" />
        <button type="button" className="btn small" onClick={onRecheck}>
          Re-check
        </button>
      </>
    );
  } else if (!caps) {
    body = <p className="muted">Checking the API's OpenAPI document…</p>;
  } else if (!caps.evidenceList) {
    body = (
      <div className="notice unknown" data-testid="evidence-unavailable">
        Not available yet: this API has no <code>GET /v1/operator/evidence</code> route (CONTRACTS §9.16 item 6).
        <button type="button" className="btn small" onClick={onRecheck}>
          Re-check
        </button>
      </div>
    );
  } else {
    body = <EvidenceFeed client={client} />;
  }
  return (
    <Panel title="Evidence" tag={<span className="tag">untrusted worker data · rendered as text</span>} className="evidence">
      {body}
    </Panel>
  );
}
