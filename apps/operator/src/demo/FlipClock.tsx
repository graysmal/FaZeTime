// Retro split-flap countdown. Display-only: the server decides every deadline (see state.ts countdownText).
// On mount it spins up from 0:00 to the current time left (fast, easing into place), then flips down once a
// second. The exact text is kept in a visually hidden node with the original data-testid for tests and
// screen readers; the flaps themselves are aria-hidden.
import { useEffect, useRef, useState } from 'react';
import { countdownText } from './state';

const SPIN_FLIP_MS = 90;
const TICK_FLIP_MS = 460;

function prefersReducedMotion(): boolean {
  try {
    return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
  } catch {
    return false;
  }
}

/** Seconds shown during the spin-up, or null once it has finished (or never runs). */
function useSpinUp(ms: number | null, reduce: boolean): number | null {
  const [spin, setSpin] = useState<number | null>(null);
  const [done, setDone] = useState(reduce);
  const goal = useRef<number | null>(null);
  goal.current = ms === null ? null : Math.max(0, Math.ceil(ms / 1000));
  const ready = ms !== null;

  useEffect(() => {
    if (done || !ready || typeof requestAnimationFrame !== 'function') return;
    const target = goal.current ?? 0;
    const duration = Math.min(1500, 600 + target * 6);
    const t0 = performance.now();
    let raf = 0;
    const step = (t: number) => {
      const p = Math.min(1, (t - t0) / duration);
      const eased = 1 - Math.pow(1 - p, 3); // fast start, settles into the real time
      setSpin(Math.round(target * eased));
      if (p < 1) raf = requestAnimationFrame(step);
      else {
        setSpin(null);
        setDone(true);
      }
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [ready, done]);

  return done ? null : spin;
}

function FlipDigit({ value, animate }: { value: string; animate: boolean }) {
  const [cur, setCur] = useState(value);
  const [prev, setPrev] = useState(value);
  const [flips, setFlips] = useState(0);
  if (value !== cur) {
    // Derived state: remember the old face so the top flap can fall away from it.
    setPrev(cur);
    setCur(value);
    setFlips(flips + 1);
  }
  return (
    <span className="flip-digit">
      <span className="flip-half top">
        <span>{cur}</span>
      </span>
      <span className="flip-half bottom">
        <span>{animate ? prev : cur}</span>
      </span>
      {animate && flips > 0 && (
        <>
          <span key={`t${flips}`} className="flip-flap top">
            <span>{prev}</span>
          </span>
          <span key={`b${flips}`} className="flip-flap bottom">
            <span>{cur}</span>
          </span>
        </>
      )}
    </span>
  );
}

export function FlipClock({ ms, tone, testId = 'demo-countdown' }: { ms: number | null; tone: '' | 'urgent' | 'late'; testId?: string }) {
  const [reduce] = useState(prefersReducedMotion);
  const spin = useSpinUp(ms, reduce);
  const exact = countdownText(ms);
  const shown = spin === null ? exact : countdownText(spin * 1000);
  const [min, sec] = shown.split(':');
  const flipMs = spin === null ? TICK_FLIP_MS : SPIN_FLIP_MS;
  return (
    <div className={`flip-clock ${tone}`} style={{ ['--flip-ms' as string]: `${flipMs}ms` }}>
      <span className="sr-only" data-testid={testId}>
        {exact}
      </span>
      <span className="flip-face" aria-hidden="true">
        {[...min].map((ch, i) => (
          <FlipDigit key={`m${min.length - i}`} value={ch} animate={!reduce} />
        ))}
        <span className="flip-colon">
          <i />
          <i />
        </span>
        {[...(sec ?? '')].map((ch, i) => (
          <FlipDigit key={`s${i}`} value={ch} animate={!reduce} />
        ))}
      </span>
    </div>
  );
}
