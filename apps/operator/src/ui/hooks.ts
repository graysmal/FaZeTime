import { useCallback, useEffect, useRef, useState } from 'react';
import type { MutationResult } from '../api/client';
import type { OperatorReceipt } from '../api/types';

export interface PollState<T> {
  data: T | null;
  error: unknown;
  /** Local time (ms) of the last successful response. */
  okAt: number | null;
  /** Local time (ms) of the last attempt that finished (ok or not). */
  doneAt: number | null;
}

/**
 * Poll `fn` every `intervalMs` while mounted and enabled. One request in flight at a time; the interval
 * and any in-flight request are cancelled on unmount (no listeners or timers left behind).
 */
export function usePoll<T>(
  fn: (signal: AbortSignal) => Promise<T>,
  intervalMs: number,
  enabled = true,
): PollState<T> & { refresh: () => void } {
  const [state, setState] = useState<PollState<T>>({ data: null, error: null, okAt: null, doneAt: null });
  const tickRef = useRef<() => void>(() => undefined);

  useEffect(() => {
    if (!enabled) return undefined;
    let stopped = false;
    let inFlight = false;
    let again = false;
    const ctrl = new AbortController();
    const tick = async () => {
      if (stopped) return;
      if (inFlight) {
        again = true;
        return;
      }
      inFlight = true;
      try {
        const data = await fn(ctrl.signal);
        if (!stopped) setState({ data, error: null, okAt: Date.now(), doneAt: Date.now() });
      } catch (error) {
        if (!stopped) setState((s) => ({ ...s, error, doneAt: Date.now() }));
      } finally {
        inFlight = false;
        if (again && !stopped) {
          again = false;
          void tick();
        }
      }
    };
    tickRef.current = () => void tick();
    void tick();
    const id = setInterval(() => void tick(), intervalMs);
    return () => {
      stopped = true;
      clearInterval(id);
      ctrl.abort();
      tickRef.current = () => undefined;
    };
  }, [fn, intervalMs, enabled]);

  const refresh = useCallback(() => tickRef.current(), []);
  return { ...state, refresh };
}

/** Local clock that re-renders every `ms` (display-only countdowns; the server decides deadlines). */
export function useNow(ms = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(id);
  }, [ms]);
  return now;
}

export type MutationState<T> =
  | { status: 'idle' }
  | { status: 'busy' }
  | { status: 'ok'; result: MutationResult<T> }
  | { status: 'error'; failure: unknown };

/**
 * Tracks one mutation control. `run` ignores clicks while a request is in flight, so a double click cannot
 * send two intents. Success is reported only from a parsed server receipt (see OperatorClient.mutate).
 */
export function useMutation<T extends OperatorReceipt>(onSuccess?: (result: MutationResult<T>) => void) {
  const [state, setState] = useState<MutationState<T>>({ status: 'idle' });
  const busy = useRef(false);
  const mounted = useRef(true);
  const onSuccessRef = useRef(onSuccess);
  onSuccessRef.current = onSuccess;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const run = useCallback(async (exec: () => Promise<MutationResult<T>>): Promise<MutationResult<T> | null> => {
    if (busy.current) return null;
    busy.current = true;
    setState({ status: 'busy' });
    try {
      const result = await exec();
      if (mounted.current) setState({ status: 'ok', result });
      onSuccessRef.current?.(result);
      return result;
    } catch (failure) {
      if (mounted.current) setState({ status: 'error', failure });
      return null;
    } finally {
      busy.current = false;
    }
  }, []);

  const reset = useCallback(() => setState({ status: 'idle' }), []);
  return { state, run, reset };
}
