// Loads the contract fixtures (packages/contracts/fixtures/v1) for the P1 MOCK adapter and shifts
// every *_utc value so the fixed fixture time (2026-11-14T20:00:00.000Z) becomes "now".

import type { ErrorCode, ErrorEnvelope, StreamSnapshot } from '@fazetime/contracts';

export const FIXTURE_TIME_MS = Date.parse('2026-11-14T20:00:00.000Z');

/** Section 9.14 order, used by the dev Fixture switcher. */
export const SNAPSHOT_FIXTURE_NAMES = [
  'no_market',
  'open_no_position',
  'open_with_position',
  'open_empty_pool',
  'open_one_sided',
  'open_low_balance',
  'open_source_stale',
  'locked',
  'evaluating',
  'settled_win',
  'settled_loss',
  'settled_no_position',
  'void_one_sided',
  'void_empty',
  'void_source_gap',
  'void_resolution_timeout',
  'void_unresolvable',
  'run_reset',
] as const;
export type SnapshotFixtureName = (typeof SNAPSHOT_FIXTURE_NAMES)[number];
export const DEFAULT_FIXTURE: SnapshotFixtureName = 'open_no_position';

const snapshotModules = import.meta.glob('../../../../packages/contracts/fixtures/v1/snapshot/*.json', {
  eager: true,
  import: 'default',
}) as Record<string, StreamSnapshot>;
const errorModules = import.meta.glob('../../../../packages/contracts/fixtures/v1/error/*.json', {
  eager: true,
  import: 'default',
}) as Record<string, ErrorEnvelope>;

const baseName = (path: string) => path.slice(path.lastIndexOf('/') + 1).replace(/\.json$/, '');

export const SNAPSHOT_FIXTURES: Readonly<Record<string, StreamSnapshot>> = Object.fromEntries(
  Object.entries(snapshotModules).map(([path, body]) => [baseName(path), body]),
);

export const ERROR_FIXTURES: Readonly<Partial<Record<ErrorCode, ErrorEnvelope>>> = Object.fromEntries(
  Object.values(errorModules).map((body) => [body.error.code, body]),
);

export function isSnapshotFixtureName(name: string): name is SnapshotFixtureName {
  return (SNAPSHOT_FIXTURE_NAMES as readonly string[]).includes(name) && name in SNAPSHOT_FIXTURES;
}

/** Deep copy with every `*_utc` string moved by deltaMs. */
export function shiftUtc<T>(value: T, deltaMs: number): T {
  if (Array.isArray(value)) return value.map((v) => shiftUtc(v, deltaMs)) as T;
  if (value && typeof value === 'object') {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value)) {
      out[k] = k.endsWith('_utc') && typeof v === 'string' ? new Date(Date.parse(v) + deltaMs).toISOString() : shiftUtc(v, deltaMs);
    }
    return out as T;
  }
  return value;
}

export function loadSnapshotFixture(name: SnapshotFixtureName, nowMs: number): StreamSnapshot {
  const base = SNAPSHOT_FIXTURES[name];
  if (!base) throw new Error(`Unknown snapshot fixture ${name}`);
  return shiftUtc(base, nowMs - FIXTURE_TIME_MS);
}
