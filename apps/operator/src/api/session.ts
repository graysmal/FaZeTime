// The operator session token lives in sessionStorage only: scoped to this tab and origin, gone when the tab
// closes. It is never put in a URL, logged, or copied into other storage (CONTRACTS §9.8).

const KEY = 'fazetime.operator.session.v1';
const TOKEN_RE = /^fzs_[A-Za-z0-9_-]{16,}$/;

export interface StoredSession {
  token: string;
  session_id: string;
  expires_at_utc: string;
  user_id: string;
  display_name: string;
}

function storageOrNull(storage?: Storage): Storage | null {
  if (storage) return storage;
  try {
    return globalThis.sessionStorage ?? null;
  } catch {
    return null;
  }
}

export function loadSession(storage?: Storage): StoredSession | null {
  const s = storageOrNull(storage);
  if (!s) return null;
  try {
    const raw = s.getItem(KEY);
    if (!raw) return null;
    const v = JSON.parse(raw) as Partial<StoredSession>;
    if (
      typeof v.token !== 'string' ||
      !TOKEN_RE.test(v.token) ||
      typeof v.session_id !== 'string' ||
      typeof v.expires_at_utc !== 'string' ||
      typeof v.user_id !== 'string' ||
      typeof v.display_name !== 'string'
    ) {
      s.removeItem(KEY);
      return null;
    }
    if (Date.parse(v.expires_at_utc) <= Date.now()) {
      s.removeItem(KEY);
      return null;
    }
    return v as StoredSession;
  } catch {
    s.removeItem(KEY);
    return null;
  }
}

export function saveSession(session: StoredSession, storage?: Storage): void {
  if (!TOKEN_RE.test(session.token)) throw new Error('refusing to store a malformed session token');
  storageOrNull(storage)?.setItem(KEY, JSON.stringify(session));
}

export function clearSession(storage?: Storage): void {
  storageOrNull(storage)?.removeItem(KEY);
}

export const SESSION_STORAGE_KEY = KEY;
