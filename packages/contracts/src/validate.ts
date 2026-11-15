// Minimal dependency-free runtime validators for contract v1.
//
// Each validator is typed `V<T>` against the hand-written interface in v1.ts. `obj<T>()` requires a
// validator for every key of T, so the compiler links the runtime checks to the TS types.
// `strict` mode reports unknown fields (used by fixture tests); lenient mode ignores them, as
// clients must (section 9.12: "Clients ignore unknown fields").

import {
  AGGREGATE_TYPES,
  AI_MODES,
  AUDIENCES,
  CLAIMED_TWITCH_LOGIN_PATTERN,
  CUUID_PATTERN,
  ERROR_CODES,
  EVENT_TYPES,
  MARKET_CLOSED_REASONS,
  MARKET_ORIGINS,
  MARKET_STATES,
  MEDIA_HEALTH_STATES,
  MINOR_MAX,
  MY_RESULTS,
  PAGE_VISIBILITIES,
  PAUSE_REASONS,
  PAYMENT_MODES,
  PLAYER_STATES,
  PRESENCE_STATES,
  ROLES,
  RUN_STATES,
  SIDES,
  SOURCE_KINDS,
  UTC_PATTERN,
  VOID_REASONS,
  WAGER_STATUSES,
  idPattern,
  type CUuid,
  type DomainEvent,
  type EnrollRequest,
  type EnrollResponse,
  type ErrorBody,
  type ErrorEnvelope,
  type Id,
  type IdPrefix,
  type Limits,
  type Me,
  type MeResponse,
  type Modes,
  type MyPosition,
  type OperatorMarketDraft,
  type Pool,
  type PresenceAck,
  type PresenceHeartbeat,
  type PublicMarket,
  type SideKeyed,
  type SourceHealth,
  type StreamInfo,
  type StreamSnapshot,
  type StreamUpdatedPayload,
  type Utc,
  type WagerReceipt,
  type WagerReceiptResponse,
  type WagerRequest,
  type WalletSummary,
  type WsTicketResponse,
} from './v1';

export interface Issue {
  path: string;
  message: string;
}

export interface Ctx {
  issues: Issue[];
  /** Report unknown object keys as issues. */
  strict: boolean;
}

export interface V<T> {
  (value: unknown, path: string, ctx: Ctx): void;
  /** Phantom, invariant in T. */
  readonly __type?: (t: T) => T;
  /** The key may be absent from its parent object. */
  readonly optional?: boolean;
}

function mk<T>(fn: (value: unknown, path: string, ctx: Ctx) => void, optional = false): V<T> {
  const v = fn as V<T> & { optional?: boolean };
  if (optional) Object.defineProperty(v, 'optional', { value: true });
  return v;
}

const fail = (ctx: Ctx, path: string, message: string) => {
  ctx.issues.push({ path, message });
};

export const str = (min = 0, max = Number.MAX_SAFE_INTEGER, pattern?: RegExp): V<string> =>
  mk((v, p, c) => {
    if (typeof v !== 'string') return fail(c, p, `expected string, got ${typeOf(v)}`);
    // Count code points so a 40-character label with emoji is not rejected by UTF-16 length.
    const len = [...v].length;
    if (len < min || len > max) fail(c, p, `length ${len} outside ${min}..${max}`);
    if (pattern && !pattern.test(v)) fail(c, p, `"${v}" does not match ${pattern}`);
  });

export const int = (min = Number.MIN_SAFE_INTEGER, max = Number.MAX_SAFE_INTEGER): V<number> =>
  mk((v, p, c) => {
    if (typeof v !== 'number' || !Number.isSafeInteger(v)) return fail(c, p, `expected integer, got ${JSON.stringify(v)}`);
    if (v < min || v > max) fail(c, p, `${v} outside ${min}..${max}`);
  });

export const bool: V<boolean> = mk((v, p, c) => {
  if (typeof v !== 'boolean') fail(c, p, `expected boolean, got ${typeOf(v)}`);
});

export const unknownValue: V<unknown> = mk(() => {});

export const nullOnly: V<null> = mk((v, p, c) => {
  if (v !== null) fail(c, p, `expected null, got ${JSON.stringify(v)}`);
});

export const lit = <L extends string | number>(l: L): V<L> =>
  mk((v, p, c) => {
    if (v !== l) fail(c, p, `expected ${JSON.stringify(l)}, got ${JSON.stringify(v)}`);
  });

export const oneOf = <T extends string>(values: readonly T[]): V<T> =>
  mk((v, p, c) => {
    if (typeof v !== 'string' || !(values as readonly string[]).includes(v))
      fail(c, p, `expected one of ${values.join('|')}, got ${JSON.stringify(v)}`);
  });

export const nullable = <T>(inner: V<T>): V<T | null> =>
  mk((v, p, c) => {
    if (v !== null) inner(v, p, c);
  });

export const optional = <T>(inner: V<T>): V<T | undefined> =>
  mk((v, p, c) => {
    if (v !== undefined) inner(v, p, c);
  }, true);

export const arr = <T>(inner: V<T>, min = 0, max = Number.MAX_SAFE_INTEGER): V<T[]> =>
  mk((v, p, c) => {
    if (!Array.isArray(v)) return fail(c, p, `expected array, got ${typeOf(v)}`);
    if (v.length < min || v.length > max) fail(c, p, `array length ${v.length} outside ${min}..${max}`);
    v.forEach((item, i) => inner(item, `${p}[${i}]`, c));
  });

type Shape<T> = { [K in keyof T]-?: V<T[K]> };

export const obj = <T extends object>(shape: Shape<T>, opts: { forbidExtra?: boolean } = {}): V<T> =>
  mk((v, p, c) => {
    if (typeof v !== 'object' || v === null || Array.isArray(v)) return fail(c, p, `expected object, got ${typeOf(v)}`);
    const record = v as Record<string, unknown>;
    for (const key of Object.keys(shape) as (keyof T & string)[]) {
      const validator = shape[key] as V<unknown>;
      if (!(key in record)) {
        if (!validator.optional) fail(c, `${p}.${key}`, 'missing required field');
        continue;
      }
      validator(record[key], `${p}.${key}`, c);
    }
    if (c.strict || opts.forbidExtra) {
      for (const key of Object.keys(record)) {
        if (!(key in shape)) fail(c, `${p}.${key}`, 'unknown field');
      }
    }
  });

function typeOf(v: unknown): string {
  if (v === null) return 'null';
  if (Array.isArray(v)) return 'array';
  return typeof v;
}

// ---------------------------------------------------------------------------
// Primitive formats (section 9.1)
// ---------------------------------------------------------------------------

export const id = <P extends IdPrefix>(prefix: P): V<Id<P>> => str(0, 64, idPattern(prefix)) as unknown as V<Id<P>>;
export const cuuid: V<CUuid> = str(36, 36, CUUID_PATTERN);
export const utc: V<Utc> = mk((v, p, c) => {
  if (typeof v !== 'string' || !UTC_PATTERN.test(v)) return fail(c, p, `expected UTC RFC 3339 with .mmmZ, got ${JSON.stringify(v)}`);
  const t = Date.parse(v);
  if (Number.isNaN(t) || new Date(t).toISOString() !== v) fail(c, p, `invalid calendar time ${v}`);
});
export const minor: V<number> = int(0, MINOR_MAX);
export const pos: V<number> = int(1);
export const nonneg: V<number> = int(0);
export const schemaVersion = lit(1 as const);

// ---------------------------------------------------------------------------
// B. SHARED
// ---------------------------------------------------------------------------

export const limitsV: V<Limits> = obj<Limits>({
  stake_min_minor: minor,
  stake_max_minor: minor,
  stake_step_minor: pos,
  stake_default_minor: minor,
  topup_presets_minor: arr(minor),
  topup_min_minor: minor,
  topup_max_minor: minor,
  topup_step_minor: pos,
});

export const modesV: V<Modes> = obj<Modes>({
  ai_mode: oneOf(AI_MODES),
  payment_mode: oneOf(PAYMENT_MODES),
  media_source_kind: nullable(oneOf(SOURCE_KINDS)),
});

export const walletV: V<WalletSummary> = obj<WalletSummary>({
  stream_session_id: id('run'),
  available_minor: minor,
  in_play_minor: minor,
  balance_version: nonneg,
  pending_topup_minor: optional(nullable(minor)),
});

export const streamInfoV: V<StreamInfo> = obj<StreamInfo>({
  stream_id: id('str'),
  twitch_channel_login: str(1, 25, CLAIMED_TWITCH_LOGIN_PATTERN),
  stream_session_id: id('run'),
  run_state: oneOf(RUN_STATES),
  aggregate_version: pos,
  wagering_paused: bool,
  wagering_paused_reason: nullable(oneOf(PAUSE_REASONS)),
});

export const sourceHealthV: V<SourceHealth> = obj<SourceHealth>({
  state: oneOf(MEDIA_HEALTH_STATES),
  source_kind: nullable(oneOf(SOURCE_KINDS)),
  source_epoch: nullable(id('ep')),
  last_media_at_utc: nullable(utc),
  last_transcript_at_utc: nullable(utc),
  updated_at_utc: utc,
});

// ---------------------------------------------------------------------------
// C. Snapshot
// ---------------------------------------------------------------------------

export const poolV: V<Pool> = obj<Pool>({
  yes_minor: minor,
  no_minor: minor,
  total_minor: minor,
  simulated_minor: minor,
  wager_count: nonneg,
});

const criteriaV: V<SideKeyed<unknown> | null> = nullable(obj<SideKeyed<unknown>>({ YES: unknownValue, NO: unknownValue }));

const marketShape = {
  market_id: id('mkt'),
  stream_session_id: id('run'),
  rules_version: pos,
  aggregate_version: pos,
  state: oneOf(MARKET_STATES),
  origin: oneOf(MARKET_ORIGINS),
  question: str(1, 200),
  yes_label: str(1, 40),
  no_label: str(1, 40),
  opened_at_utc: utc,
  close_at_utc: utc,
  resolve_by_utc: utc,
  locked_at_utc: nullable(utc),
  terminal_at_utc: nullable(utc),
  pool: poolV,
  winning_side: nullable(oneOf(SIDES)),
  void_reason: nullable(oneOf(VOID_REASONS)),
  settlement_algorithm: nullable(str(1, 64)),
  criteria: criteriaV,
  opening_evidence_ids: nullable(arr(id('evd'))),
  resolution_evidence_ids: nullable(arr(id('evd'))),
  resolution_mode: nullable(str(1, 64)),
  resolution_reason: nullable(str(0, 2000)),
} satisfies Shape<PublicMarket>;

export const publicMarketV: V<PublicMarket> = obj<PublicMarket>(marketShape);

export const operatorMarketDraftV: V<OperatorMarketDraft> = obj<OperatorMarketDraft>({
  ...marketShape,
  state: lit('DRAFT'),
  opened_at_utc: nullOnly,
  close_at_utc: nullOnly,
  resolve_by_utc: nullOnly,
});

const walletAfterV = walletV;

const wagerReceiptShape = {
  wager_id: id('wgr'),
  operation_id: cuuid,
  stream_session_id: id('run'),
  market_id: id('mkt'),
  rules_version: pos,
  side: oneOf(SIDES),
  amount_minor: minor,
  status: oneOf(WAGER_STATUSES),
  accepted_at_utc: utc,
  terminal_at_utc: nullable(utc),
  stake_txn_id: id('txn'),
  terminal_txn_id: nullable(id('txn')),
  payout_minor: nullable(minor),
  refund_minor: nullable(minor),
  market_aggregate_version: pos,
  wallet_after: walletAfterV,
  replayed: bool,
} satisfies Shape<WagerReceipt>;

export const wagerReceiptV: V<WagerReceipt> = obj<WagerReceipt>(wagerReceiptShape);
export const wagerReceiptResponseV: V<WagerReceiptResponse> = obj<WagerReceiptResponse>({
  ...wagerReceiptShape,
  schema_version: schemaVersion,
});

export const myPositionV: V<MyPosition> = obj<MyPosition>({
  market_id: id('mkt'),
  side: nullable(oneOf(SIDES)),
  stake_total_minor: minor,
  result: oneOf(MY_RESULTS),
  payout_total_minor: nullable(minor),
  refund_total_minor: nullable(minor),
  wagers: arr(wagerReceiptV),
});

export const streamSnapshotV: V<StreamSnapshot> = obj<StreamSnapshot>({
  schema_version: schemaVersion,
  server_time_utc: utc,
  event_hwm: nonneg,
  stream: streamInfoV,
  modes: modesV,
  limits: limitsV,
  source_health: sourceHealthV,
  market: nullable(publicMarketV),
  my_position: nullable(myPositionV),
  wallet: walletV,
  raffle: nullOnly,
});

// ---------------------------------------------------------------------------
// D. WagerRequest (extra=forbid)
// ---------------------------------------------------------------------------

export const wagerRequestV: V<WagerRequest> = obj<WagerRequest>(
  {
    operation_id: cuuid,
    stream_session_id: id('run'),
    market_id: id('mkt'),
    rules_version: pos,
    side: oneOf(SIDES),
    amount_minor: int(),
  },
  { forbidExtra: true },
);

// ---------------------------------------------------------------------------
// F. Me
// ---------------------------------------------------------------------------

const meShape = {
  server_time_utc: utc,
  user: obj<Me['user']>({
    user_id: id('usr'),
    display_name: str(1, 32),
    claimed_twitch_login: nullable(str(1, 25, CLAIMED_TWITCH_LOGIN_PATTERN)),
    role: oneOf(ROLES),
  }),
  session: obj<Me['session']>({ session_id: id('ses'), expires_at_utc: utc }),
  current_stream: nullable(
    obj<NonNullable<Me['current_stream']>>({
      stream_id: id('str'),
      twitch_channel_login: str(1, 25, CLAIMED_TWITCH_LOGIN_PATTERN),
      stream_session_id: id('run'),
    }),
  ),
  wallet: nullable(walletV),
} satisfies Shape<Me>;

export const meV: V<Me> = obj<Me>(meShape);
export const meResponseV: V<MeResponse> = obj<MeResponse>({ ...meShape, schema_version: schemaVersion });

// ---------------------------------------------------------------------------
// G. Errors
// ---------------------------------------------------------------------------

const detailsByCode: Partial<Record<ErrorBody['code'], V<unknown>>> = {
  INSUFFICIENT_FUNDS: obj({ available_minor: minor, requested_minor: minor }) as V<unknown>,
  INVALID_AMOUNT: obj({ min_minor: minor, max_minor: minor, step_minor: pos }) as V<unknown>,
  MARKET_CLOSED: obj({ state: oneOf(MARKET_STATES), close_at_utc: utc, reason: oneOf(MARKET_CLOSED_REASONS) }) as V<unknown>,
  STALE_MARKET: obj({ current_market_id: nullable(id('mkt')), current_rules_version: nullable(pos) }) as V<unknown>,
  WRONG_RUN: obj({ current_stream_session_id: id('run') }) as V<unknown>,
  SOURCE_STALE: obj({ source_state: oneOf(MEDIA_HEALTH_STATES) }) as V<unknown>,
  SIDE_CONFLICT: obj({ existing_side: oneOf(SIDES) }) as V<unknown>,
  VALIDATION_FAILED: obj({
    fields: arr(
      obj<{ loc: (string | number)[]; msg: string }>({
        loc: arr(mk<string | number>((v, p, c) => {
          if (typeof v !== 'string' && !(typeof v === 'number' && Number.isInteger(v))) fail(c, p, 'expected string or integer');
        })),
        msg: str(1, 500),
      }),
    ),
  }) as V<unknown>,
};

const errorBodyV: V<ErrorBody> = mk((v, p, c) => {
  obj<ErrorBody>({
    code: oneOf(ERROR_CODES),
    message: str(1, 500),
    retryable: bool,
    retry_after_ms: nullable(nonneg),
    request_id: id('req'),
    operation_id: nullable(cuuid),
    details: unknownValue as V<ErrorBody['details']>,
  })(v, p, c);
  if (typeof v !== 'object' || v === null) return;
  const body = v as Partial<ErrorBody>;
  const detailV = body.code ? detailsByCode[body.code] : undefined;
  if (body.details === null || body.details === undefined) {
    if (detailV) fail(c, `${p}.details`, `details required for ${body.code}`);
    return;
  }
  if (detailV) detailV(body.details, `${p}.details`, c);
  else if (typeof body.details !== 'object' || Array.isArray(body.details)) fail(c, `${p}.details`, 'expected object or null');
});

export const errorEnvelopeV: V<ErrorEnvelope> = obj<ErrorEnvelope>({
  schema_version: schemaVersion,
  error: errorBodyV,
  server_time_utc: utc,
});

// ---------------------------------------------------------------------------
// H. DomainEvent (payload validated by event type)
// ---------------------------------------------------------------------------

const streamUpdatedPayloadV: V<StreamUpdatedPayload> = obj<StreamUpdatedPayload>({ stream: streamInfoV, modes: modesV });

export const EVENT_SPEC: Readonly<
  Record<DomainEvent['event_type'], { aggregate: DomainEvent['aggregate_type']; payload: V<unknown>; marketState?: string }>
> = {
  'stream.updated': { aggregate: 'STREAM', payload: streamUpdatedPayloadV as V<unknown> },
  'source.health': { aggregate: 'SOURCE', payload: sourceHealthV as V<unknown> },
  'market.opened': { aggregate: 'MARKET', payload: publicMarketV as V<unknown>, marketState: 'OPEN' },
  'pool.updated': { aggregate: 'MARKET', payload: publicMarketV as V<unknown>, marketState: 'OPEN' },
  'market.locked': { aggregate: 'MARKET', payload: publicMarketV as V<unknown>, marketState: 'LOCKED' },
  'market.evaluating': { aggregate: 'MARKET', payload: publicMarketV as V<unknown>, marketState: 'EVALUATING' },
  'market.settled': { aggregate: 'MARKET', payload: publicMarketV as V<unknown>, marketState: 'SETTLED' },
  'market.voided': { aggregate: 'MARKET', payload: publicMarketV as V<unknown>, marketState: 'VOID' },
  'wager.updated': { aggregate: 'WAGER', payload: wagerReceiptV as V<unknown> },
  'wallet.changed': { aggregate: 'WALLET', payload: walletV as V<unknown> },
};

export const domainEventV: V<DomainEvent> = mk((v, p, c) => {
  obj<DomainEvent>({
    schema_version: schemaVersion,
    event_id: pos,
    stream_session_id: id('run'),
    aggregate_type: oneOf(AGGREGATE_TYPES),
    aggregate_id: str(1, 64),
    aggregate_version: pos,
    event_type: oneOf(EVENT_TYPES),
    audience: oneOf(AUDIENCES),
    occurred_at_utc: utc,
    payload: unknownValue as V<DomainEvent['payload']>,
  })(v, p, c);
  if (typeof v !== 'object' || v === null) return;
  const ev = v as DomainEvent;
  const spec = EVENT_SPEC[ev.event_type];
  if (!spec) return;
  if (ev.aggregate_type !== spec.aggregate) fail(c, `${p}.aggregate_type`, `${ev.event_type} must be ${spec.aggregate}`);
  spec.payload(ev.payload, `${p}.payload`, c);
  if (spec.marketState && (ev.payload as PublicMarket).state !== spec.marketState)
    fail(c, `${p}.payload.state`, `${ev.event_type} payload must be ${spec.marketState}`);
});

// ---------------------------------------------------------------------------
// I. Presence, J. Enroll, WS ticket
// ---------------------------------------------------------------------------

export const presenceHeartbeatV: V<PresenceHeartbeat> = obj<PresenceHeartbeat>(
  {
    device_id: cuuid,
    tab_instance_id: cuuid,
    stream_id: id('str'),
    known_stream_session_id: nullable(id('run')),
    observed_channel_login: nullable(str(1, 25, CLAIMED_TWITCH_LOGIN_PATTERN)),
    page_visibility: oneOf(PAGE_VISIBILITIES),
    player_state: oneOf(PLAYER_STATES),
    extension_version: str(1, 32),
  },
  { forbidExtra: true },
);

export const presenceAckV: V<PresenceAck> = obj<PresenceAck>({
  schema_version: schemaVersion,
  server_time_utc: utc,
  last_seen_utc: utc,
  presence_state: oneOf(PRESENCE_STATES),
  heartbeat_interval_ms: pos,
  presence_ttl_ms: pos,
  current_stream_session_id: id('run'),
});

export const enrollRequestV: V<EnrollRequest> = obj<EnrollRequest>(
  {
    invite_code: str(12, 20, /^[0-9A-Za-z-]+$/),
    display_name: str(1, 32),
    claimed_twitch_login: nullable(str(1, 25, CLAIMED_TWITCH_LOGIN_PATTERN)),
    device_id: cuuid,
  },
  { forbidExtra: true },
);

export const enrollResponseV: V<EnrollResponse> = obj<EnrollResponse>({
  schema_version: schemaVersion,
  session_token: str(5, 200, /^fzs_[A-Za-z0-9_-]+$/),
  session_id: id('ses'),
  expires_at_utc: utc,
  me: meV,
});

export const wsTicketResponseV: V<WsTicketResponse> = obj<WsTicketResponse>({
  schema_version: schemaVersion,
  ticket: str(5, 200, /^fzw_[A-Za-z0-9_-]+$/),
  expires_at_utc: utc,
  ws_path: lit('/v1/ws'),
});

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

export interface ValidationResult<T> {
  ok: boolean;
  value: T;
  issues: Issue[];
}

export function validate<T>(validator: V<T>, value: unknown, opts: { strict?: boolean; path?: string } = {}): ValidationResult<T> {
  const ctx: Ctx = { issues: [], strict: opts.strict ?? false };
  validator(value, opts.path ?? '$', ctx);
  return { ok: ctx.issues.length === 0, value: value as T, issues: ctx.issues };
}
