import { useEffect, useState } from 'react';
import { formatCountdown, remainingMs } from '../lib/time';
import { MarketCard } from './MarketCard';
import { useEnv, useFullscreen, useNow, usePanel } from './hooks';

const CONTROLS_CLEARANCE_PX = 76; // Keep clear of Twitch's bottom control bar (about 50px) plus margin.

/** Over-video market dropdown. Hidden in full-screen; never covers the bottom player controls. */
export function Overlay({ host }: { host: HTMLElement }) {
  const { doc, mode } = useEnv();
  const st = usePanel();
  const fullscreen = useFullscreen(doc);
  const [expanded, setExpanded] = useState(false);
  const [maxHeight, setMaxHeight] = useState(320);
  const market = st.snapshot?.market ?? null;
  const now = useNow(1000, market?.state === 'OPEN');

  useEffect(() => {
    if (fullscreen) setExpanded(false);
  }, [fullscreen]);

  // Size the dropdown to the player so it never reaches the control bar.
  useEffect(() => {
    if (!expanded) return;
    const player = host.parentElement;
    if (!player) return;
    const measure = () => setMaxHeight(Math.max(140, player.clientHeight - 10 - 40 - CONTROLS_CLEARANCE_PX));
    measure();
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(measure) : null;
    ro?.observe(player);
    return () => ro?.disconnect();
  }, [expanded, host]);

  if (fullscreen) return null;
  const remaining = market ? remainingMs(market.close_at_utc, now, st.offsetMs) : 0;
  const title = market ? market.question : 'No market open';
  return (
    <div className="ft-overlay" onKeyDown={(e) => e.key === 'Escape' && setExpanded(false)}>
      <button
        type="button"
        className="ft-pill"
        aria-expanded={expanded}
        aria-label={mode === 'live' ? 'FaZeTime market' : 'FaZeTime market (MOCK)'}
        onClick={() => setExpanded((v) => !v)}
      >
        {mode === 'live' ? <span className="ft-pill-brand">FaZeTime</span> : <span className="ft-badge ft-badge--mock">MOCK</span>}
        <span className="ft-pill-title">{title}</span>
        {market?.state === 'OPEN' && <span className="ft-pill-time">{remaining > 0 ? formatCountdown(remaining) : 'closing'}</span>}
        {market && market.state !== 'OPEN' && <span className="ft-badge ft-badge--soft">{market.state}</span>}
        <span aria-hidden="true">{expanded ? '▴' : '▾'}</span>
      </button>
      {expanded && (
        <div className="ft-drop" style={{ maxHeight }}>
          <MarketCard surface="overlay" />
          {st.topUp.open && <p className="ft-hint">The demo top-up dialog is open in the FaZeTime panel beside chat.</p>}
        </div>
      )}
    </div>
  );
}
