// CALM / ENRAGE theme switch (owner request, 2026-11-15). CALM = the FaZe theme; ENRAGE = the Odyssey theme
// (parchment, navy, Greek key, drifting pixel storm). Purely cosmetic: the choice lives in this browser's
// localStorage (best effort) and sets <html data-theme>, which the stylesheet keys off.
import { useCallback, useEffect, useRef, useState } from 'react';
import { startPixelSky } from '../demo/pixelSky';
import { setDisplayCurrency } from './format';
import { Owl, setOracleFlavour } from './odysseyDecor';

export type Theme = 'calm' | 'enrage';
const KEY = 'fazetime.operator.theme';

function readTheme(): Theme {
  try {
    return window.localStorage.getItem(KEY) === 'enrage' ? 'enrage' : 'calm';
  } catch {
    return 'calm';
  }
}

function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme === 'enrage' ? 'odyssey' : 'faze';
}

/** Call once at startup so the stored theme applies before the first paint. */
export function applyStoredTheme(): void {
  applyTheme(readTheme());
}

// Shared across every mounted switch (the demo view and the advanced console) in this tab.
const listeners = new Set<(t: Theme) => void>();

export function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setThemeState] = useState<Theme>(readTheme);
  setDisplayCurrency(theme === 'enrage' ? 'DRACHMA' : 'USD'); // before the view renders any amount
  setOracleFlavour(theme === 'enrage');
  useEffect(() => {
    applyTheme(theme);
  }, [theme]);
  useEffect(() => {
    listeners.add(setThemeState);
    return () => {
      listeners.delete(setThemeState);
    };
  }, []);
  const setTheme = useCallback((t: Theme) => {
    try {
      window.localStorage.setItem(KEY, t);
    } catch {
      /* per-browser convenience only */
    }
    listeners.forEach((l) => l(t));
  }, []);
  return [theme, setTheme];
}

export function ThemeSwitch({ theme, onChange }: { theme: Theme; onChange: (t: Theme) => void }) {
  return (
    <div className="theme-switch" role="radiogroup" aria-label="Theme" data-value={theme} data-testid="theme-switch">
      <span className="theme-thumb" aria-hidden="true" />
      {(['calm', 'enrage'] as const).map((t) => (
        <button
          key={t}
          type="button"
          role="radio"
          aria-checked={theme === t}
          className="theme-opt"
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

/** Full-page Odyssey backdrop: the pixel storm canvas, rain streaks and a rare lightning flash. Decorative. */
export function OdysseySky() {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas || typeof canvas.getContext !== 'function') return;
    try {
      return startPixelSky(canvas, { cell: 12, fps: 10, still: prefersReducedMotion() });
    } catch {
      return undefined; // decorative only
    }
  }, []);
  return (
    <div className="ody-sky" aria-hidden="true">
      <canvas ref={ref} />
      <div className="ody-rain">
        {Array.from({ length: 14 }, (_, i) => (
          <i key={i} style={{ left: `${(i * 73) % 100}%`, animationDelay: `${(i * 0.37) % 2.6}s`, animationDuration: `${1.6 + ((i * 7) % 5) * 0.25}s` }} />
        ))}
      </div>
      <div className="ody-flash" />
      <div className="ody-owl-mark">
        <Owl />
      </div>
    </div>
  );
}
