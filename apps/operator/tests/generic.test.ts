// §9.19 (D37/D39) console helpers: the approval close_in_s rule, the kind label, and H2H-free display helpers.
import { describe, expect, it } from 'vitest';
import {
  GENERIC_KIND_LABEL,
  approvalCloseInS,
  genericKindLabel,
  genericParamsText,
  isGenericCandidate,
  ruleNamesSide,
  subjectsText,
} from '../src/ui/generic';

const GEN = 'GENERIC_BINARY_V1';
const H2H = 'H2H_WINNER_V1';
const generic = (kind: string) => ({ spec_version: 'gen-1', kind, unit: 'level', params: {}, episode_start_media_ms: 0 });

describe('approvalCloseInS (§9.19 item 5)', () => {
  it('sends the clamped close_in_s for GENERIC_BINARY_V1 and null for H2H', () => {
    expect(approvalCloseInS({ template_id: GEN, close_in_s: 35 })).toBe(35);
    expect(approvalCloseInS({ template_id: GEN, close_in_s: 120 })).toBe(120);
    expect(approvalCloseInS({ template_id: H2H, close_in_s: 45 })).toBeNull();
  });

  it('falls back to null (receipt-anchored, the server decides) when the template or value is missing', () => {
    expect(approvalCloseInS({ close_in_s: 35 })).toBeNull(); // an older server without template_id = H2H behaviour
    expect(approvalCloseInS({ template_id: null, close_in_s: 35 })).toBeNull();
    expect(approvalCloseInS({ template_id: GEN, close_in_s: null })).toBeNull();
    expect(approvalCloseInS({ template_id: GEN, close_in_s: 0 })).toBeNull();
    expect(approvalCloseInS({ template_id: GEN, close_in_s: 35.5 })).toBeNull();
  });
});

describe('genericKindLabel', () => {
  it('maps the four kinds to Outcome, Number, Heard on stream and Duration', () => {
    expect(GENERIC_KIND_LABEL).toEqual({
      EPISODE_OUTCOME: 'Outcome',
      END_VALUE_AT_LEAST: 'Number',
      SAY_PHRASE: 'Heard on stream',
      DURATION_OVER: 'Duration',
    });
    for (const [kind, label] of Object.entries(GENERIC_KIND_LABEL)) {
      expect(genericKindLabel({ template_id: GEN, generic: generic(kind) })).toBe(label);
    }
  });

  it('is null for H2H, a missing generic object, or a kind this console does not know', () => {
    expect(genericKindLabel({ template_id: H2H, generic: null })).toBeNull();
    expect(genericKindLabel({ template_id: H2H, generic: generic('EPISODE_OUTCOME') })).toBeNull(); // forbidden for H2H
    expect(genericKindLabel({ template_id: GEN })).toBeNull();
    expect(genericKindLabel({ template_id: GEN, generic: null })).toBeNull();
    expect(genericKindLabel({ template_id: GEN, generic: generic('SOMETHING_NEW') })).toBeNull();
    expect(genericKindLabel({ template_id: GEN, generic: generic('toString') })).toBeNull();
    expect(isGenericCandidate({ template_id: GEN })).toBe(true);
    expect(isGenericCandidate({})).toBe(false);
  });
});

describe('display helpers', () => {
  it('subjectsText never assumes two subjects for a generic candidate', () => {
    expect(subjectsText({ template_id: GEN, subjects: [] })).toBe('No named subject');
    expect(subjectsText({ template_id: GEN, subjects: ['FaZeGavin'] })).toBe('Subject: FaZeGavin');
    expect(subjectsText({ template_id: GEN, subjects: undefined as never })).toBe('No named subject');
    expect(subjectsText({ template_id: H2H, subjects: ['FaZeGavin', 'FaZeNeville'] })).toBe('Subjects: A = FaZeGavin · B = FaZeNeville');
    expect(subjectsText({ template_id: H2H, subjects: [] })).toBe('Subjects: A = ? · B = ?');
  });

  it('genericParamsText keeps primitive values only', () => {
    expect(genericParamsText({ win_verb: 'clear' })).toBe('win_verb=clear');
    expect(genericParamsText({ label: 'time left', threshold: 30 })).toBe('label=time left, threshold=30');
    expect(genericParamsText({ nested: { x: 1 }, n: Number.NaN, ok: 'y' })).toBe('ok=y');
    expect(genericParamsText(null)).toBe('');
    expect(genericParamsText(['a'])).toBe('');
  });

  it('ruleNamesSide detects a rule that already opens with its side word', () => {
    expect(ruleNamesSide('YES if the level ends with a win.', 'Yes')).toBe(true);
    expect(ruleNamesSide('  no if it ends sooner.', 'No')).toBe(true);
    expect(ruleNamesSide('Nobody clears it.', 'No')).toBe(false);
    expect(ruleNamesSide('The streamer clears the level.', 'Yes')).toBe(false);
    expect(ruleNamesSide('', 'Yes')).toBe(false);
    expect(ruleNamesSide('YES if …', '')).toBe(false);
  });
});
