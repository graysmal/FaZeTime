import { createContext, useContext, useEffect, useState, useSyncExternalStore } from 'react';
import type { KV, PanelController, PanelState } from '../state/controller';

export interface Profile {
  display_name: string;
  /** Unverified label typed by the viewer, not an identity (D16, ARCHITECTURE 5). */
  claimed_twitch_login: string | null;
}

export const PROFILE_KEY = 'local:fazetime.profile';
export const PANEL_OPEN_KEY = 'local:fazetime.panelOpen';
export const panelHeightKey = (channel: string) => `local:fazetime.panelHeight.${channel}`;

export interface UiEnv {
  controller: PanelController;
  kv: KV;
  watch<T>(key: string, cb: (value: T | null) => void): () => void;
  channel: string;
  doc: Document;
  /** Build mode. Live builds follow D31: no MOCK/DEMO badges or mode chips on viewer surfaces. */
  mode: 'mock' | 'live';
  /** Ask the panel (if mounted) to expand, e.g. when the overlay needs the top-up dialog. */
  requestPanelOpen: () => void;
  onPanelOpenRequest: (cb: () => void) => () => void;
}

export const EnvContext = createContext<UiEnv | null>(null);

export function useEnv(): UiEnv {
  const env = useContext(EnvContext);
  if (!env) throw new Error('FaZeTime UI rendered without an environment');
  return env;
}

export function usePanel(): PanelState {
  const { controller } = useEnv();
  return useSyncExternalStore(controller.subscribe, controller.getState, controller.getState);
}

/** Ticking clock for countdowns; the interval is cleared on unmount or when disabled. */
export function useNow(intervalMs = 1000, enabled = true): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!enabled) return;
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs, enabled]);
  return now;
}

export function useFullscreen(doc: Document): boolean {
  const [fs, setFs] = useState(() => Boolean(doc.fullscreenElement));
  useEffect(() => {
    const onChange = () => setFs(Boolean(doc.fullscreenElement));
    doc.addEventListener('fullscreenchange', onChange);
    return () => doc.removeEventListener('fullscreenchange', onChange);
  }, [doc]);
  return fs;
}

/** A value persisted in extension storage, kept live across tabs. */
export function useStoredValue<T>(key: string, fallback: T): [T, (v: T) => void, boolean] {
  const { kv, watch } = useEnv();
  const [value, setValue] = useState<T>(fallback);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    let alive = true;
    kv.get<T>(key)
      .then((v) => {
        if (alive) {
          if (v !== null && v !== undefined) setValue(v);
          setLoaded(true);
        }
      })
      .catch(() => alive && setLoaded(true));
    const unwatch = watch<T>(key, (v) => setValue(v ?? fallback));
    return () => {
      alive = false;
      unwatch();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  const update = (v: T) => {
    setValue(v);
    void kv.set(key, v);
  };
  return [value, update, loaded];
}
