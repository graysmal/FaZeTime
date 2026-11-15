// D35 open-access join helpers, shared by the popup and the background (no secrets, no I/O).
import type { ApiResult } from '../api/types';

/** A default display name when the user leaves "Your name" empty (D35): "Viewer" plus 4 random digits. */
export function defaultDisplayName(): string {
  const n = (crypto.getRandomValues(new Uint16Array(1))[0] ?? 0) % 10_000;
  return `Viewer ${String(n).padStart(4, '0')}`;
}

/**
 * The server refused a NAME-ONLY enroll because it is invite-only: 401 UNAUTHENTICATED (D35, flag off), or an
 * older API whose validation still requires the invite_code field.
 */
export function refusesNameOnly(r: ApiResult<unknown>): boolean {
  if (r.ok || r.kind !== 'http') return false;
  const e = r.error.error;
  if (r.status === 401 || e.code === 'UNAUTHENTICATED') return true;
  if (e.code !== 'VALIDATION_FAILED') return false;
  const fields = (e.details as { fields?: unknown } | null)?.fields;
  return Array.isArray(fields) && fields.some((f) => Array.isArray((f as { loc?: unknown } | null)?.loc) && (f as { loc: unknown[] }).loc.includes('invite_code'));
}
