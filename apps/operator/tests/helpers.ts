// Test helpers: a scripted fetch, §9.10 envelopes, and minimal React DOM driving (no extra deps).
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { ReactElement } from 'react';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

export const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
export const TOKEN = 'fzs_testtokentesttokentesttoken00';
export const MKT = `mkt_${'a'.repeat(32)}`;
export const STR = `str_${'b'.repeat(32)}`;
export const RUN = `run_${'c'.repeat(32)}`;
export const NOW = '2026-11-15T04:00:00.000Z';

export function envelope(code: string, message = 'refused', extra: Record<string, unknown> = {}) {
  return {
    schema_version: 1,
    error: {
      code,
      message,
      retryable: code === 'RATE_LIMITED' || code === 'INTERNAL_ERROR',
      retry_after_ms: null,
      request_id: `req_${'d'.repeat(32)}`,
      operation_id: null,
      details: null,
      ...extra,
    },
    server_time_utc: NOW,
  };
}

export function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

export interface Call {
  url: string;
  method: string;
  headers: Record<string, string>;
  body: Record<string, unknown> | null;
}

/** A fetch double: `handler` answers each call; every call is recorded with its parsed JSON body. */
export function scriptedFetch(handler: (call: Call) => Response | Promise<Response>) {
  const calls: Call[] = [];
  const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const headers = (init?.headers ?? {}) as Record<string, string>;
    const call: Call = {
      url: String(input),
      method: init?.method ?? 'GET',
      headers,
      body: typeof init?.body === 'string' ? (JSON.parse(init.body) as Record<string, unknown>) : null,
    };
    calls.push(call);
    return handler(call);
  }) as typeof fetch;
  return { fetchImpl, calls };
}

export function operatorMarket(overrides: Record<string, unknown> = {}) {
  return {
    market_id: MKT,
    stream_session_id: RUN,
    rules_version: 1,
    aggregate_version: 2,
    state: 'OPEN',
    origin: 'OPERATOR_FIXTURE',
    question: 'Will FaZeGavin win the 1v1?',
    yes_label: 'Gavin',
    no_label: 'Neville',
    opened_at_utc: NOW,
    close_at_utc: '2026-11-15T04:01:00.000Z',
    resolve_by_utc: '2026-11-15T04:03:00.000Z',
    locked_at_utc: null,
    terminal_at_utc: null,
    pool: { yes_minor: 500, no_minor: 700, total_minor: 1200, simulated_minor: 0, wager_count: 2 },
    winning_side: null,
    void_reason: null,
    settlement_algorithm: null,
    close_in_s: 60,
    resolve_in_s: 120,
    created_at_utc: NOW,
    ...overrides,
  };
}

export function healthBody(overrides: Record<string, unknown> = {}) {
  return {
    schema_version: 1,
    server_time_utc: NOW,
    service: { process_started_at_utc: NOW, sqlite_version: '3.45.1', mode_labels: [] },
    sweeper: { enabled: true, runs: 3, errors: 0, last_run_at_utc: NOW },
    websocket: { subscribers: 0 },
    event_hwm: 5,
    stream: {
      stream_id: STR,
      twitch_channel_login: 'fazegavin1234',
      stream_session_id: RUN,
      run_state: 'ACTIVE',
      aggregate_version: 1,
      wagering_paused: false,
      wagering_paused_reason: null,
    },
    run: { run_id: RUN, stream_id: STR, state: 'ACTIVE', ai_mode: 'OFF', seed_grant_minor: 2000, created_at_utc: NOW, archived_at_utc: null },
    source_health: { state: 'STOPPED', source_kind: null, source_epoch: null, last_media_at_utc: null, last_transcript_at_utc: null, updated_at_utc: NOW },
    markets: [],
    wallets: [],
    funding_source_minor: -4000,
    presence: { present_users: 0, ttl_ms: 45000, users: [] },
    reconciliation: { ok: true, accounts_checked: 4, transactions_checked: 2, markets_checked: 0, problems: [] },
    counts: { users: 3, runs: 1, archived_runs: 0 },
    ...overrides,
  };
}

export interface Mounted {
  container: HTMLElement;
  root: Root;
  unmount: () => void;
}

export async function mount(el: ReactElement): Promise<Mounted> {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(el);
  });
  return {
    container,
    root,
    unmount: () => {
      act(() => root.unmount());
      container.remove();
    },
  };
}

export async function flush(times = 3) {
  for (let i = 0; i < times; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

export async function waitFor<T>(fn: () => T | null | undefined | false, timeoutMs = 2000): Promise<T> {
  const start = Date.now();
  for (;;) {
    const v = fn();
    if (v) return v;
    if (Date.now() - start > timeoutMs) throw new Error('waitFor timed out');
    await flush(1);
  }
}

/** Set a React-controlled input's value through the native setter, then fire `input`. */
export async function typeInto(el: Element | null, value: string) {
  if (!el) throw new Error('no element to type into');
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  await act(async () => {
    Object.getOwnPropertyDescriptor(proto, 'value')!.set!.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

export async function click(el: Element | null | undefined) {
  if (!el) throw new Error('no element to click');
  await act(async () => {
    (el as HTMLElement).click();
  });
}

export function byText(root: ParentNode, selector: string, text: string | RegExp): HTMLElement | null {
  for (const el of Array.from(root.querySelectorAll<HTMLElement>(selector))) {
    const t = el.textContent ?? '';
    if (typeof text === 'string' ? t.includes(text) : text.test(t)) return el;
  }
  return null;
}
