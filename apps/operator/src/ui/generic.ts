// §9.19 (D37/D39) on the console side: which close_in_s an approval sends, and the display helpers for a
// GENERIC_BINARY_V1 candidate. Pure functions. Every string here comes from the server and is untrusted, so callers
// render it as React text only. success_cue / failure_cue are untrusted model text and are never read here.
import { GENERIC_KINDS, GENERIC_TEMPLATE_ID, type AiCandidate, type GenericKind } from '../api/types';

export const GENERIC_KIND_LABEL: Record<GenericKind, string> = {
  EPISODE_OUTCOME: 'Outcome',
  END_VALUE_AT_LEAST: 'Number',
  SAY_PHRASE: 'Heard on stream',
  DURATION_OVER: 'Duration',
};

export function isGenericCandidate(c: Pick<AiCandidate, 'template_id'>): boolean {
  return c.template_id === GENERIC_TEMPLATE_ID;
}

/** Outcome, Number, Heard on stream or Duration; null for H2H, a missing generic object, or an unknown kind. */
export function genericKindLabel(c: Pick<AiCandidate, 'template_id' | 'generic'>): string | null {
  if (!isGenericCandidate(c)) return null;
  const kind = c.generic?.kind;
  return typeof kind === 'string' && (GENERIC_KINDS as readonly string[]).includes(kind) ? GENERIC_KIND_LABEL[kind as GenericKind] : null;
}

/**
 * §9.19 item 5: approving a GENERIC_BINARY_V1 candidate sends its clamped close_in_s, so the server counts the
 * betting window (35 s floor, D39) from approval. H2H sends null: the receipt-anchored close, unchanged (§9.17 5e).
 * A generic candidate without a usable close_in_s also sends null and leaves the decision to the server.
 */
export function approvalCloseInS(c: Pick<AiCandidate, 'template_id' | 'close_in_s'>): number | null {
  if (!isGenericCandidate(c)) return null;
  const v = c.close_in_s;
  return typeof v === 'number' && Number.isSafeInteger(v) && v > 0 ? v : null;
}

/** Advanced view: "Subjects: A = x · B = y" for H2H; a generic candidate has 0 or 1 subject. Never assumes two. */
export function subjectsText(c: Pick<AiCandidate, 'template_id' | 'subjects'>): string {
  const s = Array.isArray(c.subjects) ? c.subjects.filter((x): x is string => typeof x === 'string' && x !== '') : [];
  if (isGenericCandidate(c)) return s.length === 0 ? 'No named subject' : `Subject: ${s.join(', ')}`;
  return `Subjects: A = ${s[0] ?? '?'} · B = ${s[1] ?? '?'}`;
}

/** Advanced view: "win_verb=clear" or "label=time left, threshold=30". Primitive values only. */
export function genericParamsText(params: unknown): string {
  if (typeof params !== 'object' || params === null || Array.isArray(params)) return '';
  return Object.entries(params as Record<string, unknown>)
    .filter(([, v]) => typeof v === 'string' || typeof v === 'boolean' || (typeof v === 'number' && Number.isFinite(v)))
    .map(([k, v]) => `${k}=${String(v)}`)
    .join(', ');
}

/** True when a rule already opens with its side word ("YES if …" for label "Yes"), so a card need not repeat it. */
export function ruleNamesSide(predicate: string, label: string): boolean {
  const word = label.trim().toLowerCase();
  const p = predicate.trimStart().toLowerCase();
  return word !== '' && p.startsWith(word) && !/[\p{L}\p{N}]/u.test(p.charAt(word.length));
}
