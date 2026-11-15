import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Two-tone "needs action" beep. Browsers only allow audio after a user gesture, so the AudioContext is created
 * and resumed on the first pointer or key press. `unlocked` says whether a beep can actually play yet.
 */
export function useAlert() {
  const ctxRef = useRef<AudioContext | null>(null);
  const [sound, setSound] = useState(true);
  const [unlocked, setUnlocked] = useState(false);

  const unlock = useCallback(() => {
    try {
      const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (Ctx && !ctxRef.current) ctxRef.current = new Ctx();
      const ctx = ctxRef.current;
      if (ctx) {
        void ctx
          .resume()
          .then(() => setUnlocked(ctx.state === 'running'))
          .catch(() => undefined);
      }
    } catch {
      ctxRef.current = null;
    }
  }, []);

  useEffect(() => {
    window.addEventListener('pointerdown', unlock);
    window.addEventListener('keydown', unlock);
    return () => {
      window.removeEventListener('pointerdown', unlock);
      window.removeEventListener('keydown', unlock);
      void ctxRef.current?.close().catch(() => undefined);
      ctxRef.current = null;
    };
  }, [unlock]);

  const beep = useCallback(() => {
    const ctx = ctxRef.current;
    if (!sound || !ctx) return;
    try {
      for (const [i, f] of [880, 1320].entries()) {
        const o = ctx.createOscillator();
        const g = ctx.createGain();
        const t = ctx.currentTime + i * 0.18;
        o.frequency.value = f;
        g.gain.setValueAtTime(0.0001, t);
        g.gain.exponentialRampToValueAtTime(0.25, t + 0.02);
        g.gain.exponentialRampToValueAtTime(0.0001, t + 0.16);
        o.connect(g).connect(ctx.destination);
        o.start(t);
        o.stop(t + 0.17);
      }
    } catch {
      /* audio is best effort; the visual alert always shows */
    }
  }, [sound]);

  return { sound, setSound, beep, unlocked, unlock };
}
