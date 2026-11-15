// CALM / ENRAGE switch for the Twitch panel (owner request, 2026-11-15). CALM = FaZe, ENRAGE = Odyssey.
// Cosmetic only: stored in extension storage so the panel and the over-video dropdown (and other tabs) agree.
import { useEffect, useRef } from 'react';
import { startPixelSky } from './pixelSky';
import { Owl } from './OdysseyDecor';
import type { ThemeName } from './theme';

export function ThemeSwitch({ theme, onChange }: { theme: ThemeName; onChange: (t: ThemeName) => void }) {
  return (
    <div className="ft-theme" role="radiogroup" aria-label="Theme" data-value={theme}>
      <span className="ft-theme-thumb" aria-hidden="true" />
      {(['calm', 'enrage'] as const).map((t) => (
        <button
          key={t}
          type="button"
          role="radio"
          aria-checked={theme === t}
          className="ft-theme-opt"
          title={t === 'calm' ? 'FaZe theme' : 'Odyssey theme'}
          aria-label={t === 'calm' ? 'FaZe theme' : 'Odyssey theme'}
          onClick={() => onChange(t)}
          onKeyDown={(e) => {
            if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
              e.preventDefault();
              onChange(theme === 'calm' ? 'enrage' : 'calm');
            }
          }}
        >
          {t === 'calm' ? 'F' : <span className="omega">Θ</span>}
        </button>
      ))}
    </div>
  );
}

function prefersReducedMotion(): boolean {
  try {
    return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
  } catch {
    return false;
  }
}

/** Panel-sized Odyssey backdrop: drifting pixel storm, a few rain streaks, a rare lightning flash. */
export function OdysseySky() {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas || typeof canvas.getContext !== 'function') return;
    try {
      return startPixelSky(canvas, { cell: 8, fps: 10, still: prefersReducedMotion() });
    } catch {
      return undefined; // decorative only
    }
  }, []);
  return (
    <div className="ft-sky" aria-hidden="true">
      <canvas ref={ref} />
      <div className="ft-rain">
        {Array.from({ length: 7 }, (_, i) => (
          <i key={i} style={{ left: `${8 + ((i * 41) % 90)}%`, animationDelay: `${(i * 0.43) % 2.2}s` }} />
        ))}
      </div>
      <div className="ft-flash" />
      <div className="ft-owl-mark">
        <Owl />
      </div>
    </div>
  );
}
