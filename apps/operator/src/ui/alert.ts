import { useCallback, useEffect, useRef, useState } from 'react';

const VOLUME_KEY = 'fazetime.operator.volume';
const MUTED_KEY = 'fazetime.operator.muted';
const PEAK_GAIN = 0.25;

function readStored(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStored(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* a per-browser convenience only */
  }
}

function initialVolume(): number {
  const v = Number(readStored(VOLUME_KEY));
  return readStored(VOLUME_KEY) !== null && Number.isFinite(v) ? Math.min(1, Math.max(0, v)) : 0.8;
}

/**
 * Two-tone "needs action" beep with a volume and mute. Browsers only allow audio after a user gesture, so the
 * AudioContext is created and resumed on the first pointer or key press. `unlocked` says whether a beep can
 * actually play yet. Volume and mute are remembered per browser (best effort).
 */
export function useAlert() {
  const ctxRef = useRef<AudioContext | null>(null);
  const [volume, setVolumeState] = useState(initialVolume);
  const [muted, setMutedState] = useState(() => readStored(MUTED_KEY) === '1');
  const [unlocked, setUnlocked] = useState(false);
  const level = useRef(0);
  level.current = muted ? 0 : volume;

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
    const peak = PEAK_GAIN * level.current;
    if (!ctx || peak <= 0.001) return;
    try {
      for (const [i, f] of [880, 1320].entries()) {
        const o = ctx.createOscillator();
        const g = ctx.createGain();
        const t = ctx.currentTime + i * 0.18;
        o.frequency.value = f;
        g.gain.setValueAtTime(0.0001, t);
        g.gain.exponentialRampToValueAtTime(peak, t + 0.02);
        g.gain.exponentialRampToValueAtTime(0.0001, t + 0.16);
        o.connect(g).connect(ctx.destination);
        o.start(t);
        o.stop(t + 0.17);
      }
    } catch {
      /* audio is best effort; the visual alert always shows */
    }
  }, []);

  const setVolume = useCallback((v: number) => {
    const next = Math.min(1, Math.max(0, v));
    setVolumeState(next);
    writeStored(VOLUME_KEY, String(next));
    if (next > 0) {
      setMutedState(false);
      writeStored(MUTED_KEY, '0');
    }
  }, []);

  const toggleMute = useCallback(() => {
    setMutedState((m) => {
      writeStored(MUTED_KEY, m ? '0' : '1');
      return !m;
    });
    // Unmuting from 0% restores an audible level.
    setVolumeState((v) => (v === 0 ? 0.5 : v));
  }, []);

  /** Checkbox-style on/off (used by the advanced console). */
  const setSound = useCallback((on: boolean) => {
    setMutedState(!on);
    writeStored(MUTED_KEY, on ? '0' : '1');
    if (on) setVolumeState((v) => (v === 0 ? 0.5 : v));
  }, []);

  const sound = !muted && volume > 0;
  return { sound, setSound, volume, muted, setVolume, toggleMute, beep, unlocked, unlock };
}
