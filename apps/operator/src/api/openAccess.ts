// D35 open access: the console signs itself in through POST /v1/open/operator-session, on load and again
// whenever a session is lost (any 401), so the operator never has to find a code mid-demo.
// - The device_id lives in localStorage (stable per browser); the session stays in sessionStorage (session.ts).
// - 404 from that route means the server is in invite mode: only then does the UI show the sign-in form.
// - Single flight: concurrent 401s share ONE open-session call. After a failure, new attempts wait at least
//   minGapMs (or the server's retry_after_ms), so a broken server cannot be hammered (it rate-limits the route).
import type { EnrollResponse } from '@fazetime/contracts';
import { ApiFailure, type ReauthOutcome } from './client';
import type { StoredSession } from './session';

const DEVICE_KEY = 'fazetime.operator.device.v1';
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const TOKEN_RE = /^fzs_[A-Za-z0-9_-]{16,}$/;

function localOrNull(storage?: Storage): Storage | null {
  if (storage) return storage;
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null;
  }
}

/** The browser's stable device id (a lowercase v4 UUID, as the API requires). Created once, then reused. */
export function loadOrCreateDeviceId(storage?: Storage): string {
  const s = localOrNull(storage);
  try {
    const v = s?.getItem(DEVICE_KEY);
    if (v && UUID_RE.test(v)) return v;
  } catch {
    /* storage blocked: fall through to a fresh id */
  }
  const id = globalThis.crypto.randomUUID().toLowerCase();
  try {
    s?.setItem(DEVICE_KEY, id);
  } catch {
    /* not persisted; still usable for this call */
  }
  return id;
}

/** An open-session (or enroll) response as a StoredSession, or null if it is not a usable OPERATOR session. */
export function toOperatorSession(res: EnrollResponse | null | undefined): StoredSession | null {
  const user = res?.me?.user;
  if (
    !res ||
    typeof res.session_token !== 'string' ||
    !TOKEN_RE.test(res.session_token) ||
    typeof res.session_id !== 'string' ||
    typeof res.expires_at_utc !== 'string' ||
    !user ||
    user.role !== 'OPERATOR' ||
    typeof user.user_id !== 'string' ||
    typeof user.display_name !== 'string'
  ) {
    return null;
  }
  return {
    token: res.session_token,
    session_id: res.session_id,
    expires_at_utc: res.expires_at_utc,
    user_id: user.user_id,
    display_name: user.display_name,
  };
}

export interface ReopenerOptions {
  open: (deviceId: string) => Promise<EnrollResponse>;
  deviceId: () => string;
  /** Called with the fresh session BEFORE the outcome resolves, so a retried request sees the new token. */
  onSession: (session: StoredSession) => void;
  onInviteMode: () => void;
  now?: () => number;
  minGapMs?: number;
}

export interface Reopener {
  (): Promise<ReauthOutcome>;
  /** The failure behind the last 'failed' outcome (for a one-line "can't reach the server" message). */
  lastFailure: () => unknown;
  /** Milliseconds until a new network attempt is allowed (0 = now). */
  retryInMs: () => number;
}

export function createReopener(o: ReopenerOptions): Reopener {
  const now = o.now ?? Date.now;
  const minGap = o.minGapMs ?? 3_000;
  let inflight: Promise<ReauthOutcome> | null = null;
  let notBefore = 0;
  let inviteMode = false;
  let lastFailure: unknown = null;

  const attempt = async (): Promise<ReauthOutcome> => {
    try {
      const session = toOperatorSession(await o.open(o.deviceId()));
      if (!session) throw new Error('The open-access response was not an operator session.');
      lastFailure = null;
      notBefore = 0;
      o.onSession(session);
      return 'renewed';
    } catch (e) {
      lastFailure = e;
      if (e instanceof ApiFailure && (e.status === 404 || e.status === 405)) {
        inviteMode = true;
        o.onInviteMode();
        return 'invite_mode';
      }
      const after = e instanceof ApiFailure ? (e.info?.retry_after_ms ?? 0) : 0;
      notBefore = now() + Math.max(minGap, after);
      return 'failed';
    }
  };

  const reopen = (() => {
    if (inviteMode) return Promise.resolve<ReauthOutcome>('invite_mode');
    if (inflight) return inflight;
    if (now() < notBefore) return Promise.resolve<ReauthOutcome>('failed');
    inflight = attempt().finally(() => {
      inflight = null;
    });
    return inflight;
  }) as Reopener;
  reopen.lastFailure = () => lastFailure;
  reopen.retryInMs = () => Math.max(0, notBefore - now());
  return reopen;
}
