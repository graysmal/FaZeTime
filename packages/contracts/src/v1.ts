// FaZeTime contract v1: a hand-written mirror of docs/CONTRACTS.md section 9.13 (FROZEN v1).
//
// This is the interim TypeScript source until backend Pydantic/OpenAPI generation exists.
// Do not add, rename or reinterpret fields here. Contract changes go through the coordinator
// (CONTRACTS section 8 and 9.12). Field names, enums and units below are copied from the spec.

export const SCHEMA_VERSION = 1 as const;
export type SchemaVersion = typeof SCHEMA_VERSION;

// ---------------------------------------------------------------------------
// 9.1 Formats
// ---------------------------------------------------------------------------

/** Server ID prefixes (section 9.1). `stream_session_id` is a `run_` ID. */
export const ID_PREFIXES = ['usr', 'ses', 'str', 'run', 'mkt', 'wgr', 'txn', 'evd', 'ep', 'req', 'inv'] as const;
export type IdPrefix = (typeof ID_PREFIXES)[number];

/** `<prefix>_<32 lowercase hex>`, generated from uuid4 on the server. */
export type Id<P extends IdPrefix> = `${P}_${string}`;
export type UserId = Id<'usr'>;
export type SessionId = Id<'ses'>;
export type StreamId = Id<'str'>;
export type RunId = Id<'run'>;
export type MarketId = Id<'mkt'>;
export type WagerId = Id<'wgr'>;
export type TxnId = Id<'txn'>;
export type EvidenceId = Id<'evd'>;
export type EpochId = Id<'ep'>;
export type RequestId = Id<'req'>;

/** Canonical lowercase UUID from `crypto.randomUUID()` (operation_id, device_id, tab_instance_id). */
export type CUuid = string;
/** UTC RFC 3339 with exactly three fractional digits and `Z`, e.g. `2026-11-15T02:15:00.000Z`. */
export type Utc = string;
/** Integer demo cents, 0..1_000_000_000 (100 per demo dollar). Never a float. */
export type Minor = number;
/** Positive integer >= 1. */
export type Pos = number;

export const ID_PATTERN_SOURCE = '[0-9a-f]{32}';
export const CUUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
export const UTC_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/;
export const MINOR_MAX = 1_000_000_000;
/** Section 9.2: available balance is at most 1,000,000. */
export const AVAILABLE_BALANCE_MAX_MINOR = 1_000_000;

export function idPattern(prefix: IdPrefix): RegExp {
  return new RegExp(`^${prefix}_${ID_PATTERN_SOURCE}$`);
}

// ---------------------------------------------------------------------------
// A. ENUMS
// ---------------------------------------------------------------------------

export const SIDES = ['YES', 'NO'] as const;
export type Side = (typeof SIDES)[number];

export const MARKET_STATES = ['DRAFT', 'OPEN', 'LOCKED', 'EVALUATING', 'SETTLED', 'VOID'] as const;
export type MarketState = (typeof MARKET_STATES)[number];
/** DRAFT is operator-only and never appears in viewer payloads (section 9.3). */
export const VIEWER_MARKET_STATES = ['OPEN', 'LOCKED', 'EVALUATING', 'SETTLED', 'VOID'] as const;
export type ViewerMarketState = (typeof VIEWER_MARKET_STATES)[number];
export const NONTERMINAL_MARKET_STATES = ['OPEN', 'LOCKED', 'EVALUATING'] as const;
export const TERMINAL_MARKET_STATES = ['SETTLED', 'VOID'] as const;

export const VOID_REASONS = [
  'EMPTY_POOL',
  'ONE_SIDED_POOL',
  'UNRESOLVABLE',
  'RESOLUTION_TIMEOUT',
  'SOURCE_GAP',
  'RUN_RESET',
  'OPERATOR_CANCELLED',
] as const;
export type VoidReason = (typeof VOID_REASONS)[number];
/** `UNRESOLVED_REFUNDED` = VOID with UNRESOLVABLE or RESOLUTION_TIMEOUT. */
export const UNRESOLVED_VOID_REASONS = ['UNRESOLVABLE', 'RESOLUTION_TIMEOUT'] as const;

export const MARKET_ORIGINS = ['OPERATOR_FIXTURE', 'CANNED_FIXTURE', 'AI_APPROVED', 'AI_AUTOMATIC'] as const;
export type MarketOrigin = (typeof MARKET_ORIGINS)[number];
/** Fixture-origin markets are exempt from the LIVE-source wager check (section 9.4). */
export const FIXTURE_MARKET_ORIGINS = ['OPERATOR_FIXTURE', 'CANNED_FIXTURE'] as const;

export const RESOLVER_DECISIONS = ['YES', 'NO', 'WAIT', 'UNRESOLVABLE'] as const;
export type ResolverDecision = (typeof RESOLVER_DECISIONS)[number];

export const WAGER_STATUSES = ['ACCEPTED', 'WON', 'LOST', 'REFUNDED'] as const;
export type WagerStatus = (typeof WAGER_STATUSES)[number];

export const MY_RESULTS = ['NONE', 'PENDING', 'WON', 'LOST', 'VOID_REFUNDED', 'UNRESOLVED_REFUNDED'] as const;
export type MyResult = (typeof MY_RESULTS)[number];

export const MEDIA_HEALTH_STATES = ['CONNECTING', 'LIVE', 'GAP', 'STALE', 'STOPPED'] as const;
export type MediaHealth = (typeof MEDIA_HEALTH_STATES)[number];

export const SOURCE_KINDS = ['TWITCH_STREAMLINK', 'TWITCH_TAB_CAPTURE', 'TEST_FIXTURE'] as const;
export type SourceKind = (typeof SOURCE_KINDS)[number];

/** "supervised AI" = APPROVAL. */
export const AI_MODES = ['OFF', 'SHADOW', 'APPROVAL', 'AUTOMATIC', 'FIXTURE'] as const;
export type AiMode = (typeof AI_MODES)[number];

export const PAYMENT_MODES = ['MOCK', 'UNAVAILABLE', 'STRIPE_TEST'] as const;
export type PaymentMode = (typeof PAYMENT_MODES)[number];

export const ROLES = ['VIEWER', 'OPERATOR', 'MEDIA_WORKER', 'CALL_WORKER'] as const;
export type Role = (typeof ROLES)[number];

export const RUN_STATES = ['ACTIVE', 'ARCHIVED'] as const;
export type RunState = (typeof RUN_STATES)[number];

/** DRAW_BOUNDARY is reserved for P8 and blocks new markets only (D27). */
export const PAUSE_REASONS = ['SOURCE_NOT_LIVE', 'OPERATOR_PAUSE', 'DRAW_BOUNDARY'] as const;
export type PauseReason = (typeof PAUSE_REASONS)[number];

export const PRESENCE_STATES = ['PRESENT', 'ABSENT'] as const;
export type PresenceState = (typeof PRESENCE_STATES)[number];

export const PAGE_VISIBILITIES = ['VISIBLE', 'HIDDEN', 'UNKNOWN'] as const;
export type PageVisibility = (typeof PAGE_VISIBILITIES)[number];

export const PLAYER_STATES = ['PLAYING', 'PAUSED', 'BUFFERING', 'UNKNOWN'] as const;
export type PlayerState = (typeof PLAYER_STATES)[number];

/** RAFFLE and CALL are reserved. */
export const AGGREGATE_TYPES = ['STREAM', 'MARKET', 'WAGER', 'WALLET', 'SOURCE', 'RAFFLE', 'CALL'] as const;
export type AggregateType = (typeof AGGREGATE_TYPES)[number];

export const AUDIENCES = ['PUBLIC', 'USER', 'OPERATOR'] as const;
export type Audience = (typeof AUDIENCES)[number];

/** STRIPE_TEST_TOPUP (P6) and REDEMPTION (P6, optional) are later-phase reasons. */
export const LEDGER_REASONS = [
  'SEED_GRANT',
  'FIXTURE_CREDIT',
  'WAGER_STAKE',
  'PAYOUT',
  'REFUND',
  'STRIPE_TEST_TOPUP',
  'REDEMPTION',
] as const;
export type LedgerReason = (typeof LEDGER_REASONS)[number];

export const ERROR_CODES = [
  'UNAUTHENTICATED',
  'FORBIDDEN',
  'INVALID_AMOUNT',
  'INSUFFICIENT_FUNDS',
  'MARKET_CLOSED',
  'STALE_MARKET',
  'WRONG_RUN',
  'IDEMPOTENCY_CONFLICT',
  'CAPABILITY_UNAVAILABLE',
  'SOURCE_STALE',
  'RATE_LIMITED',
  'VALIDATION_FAILED',
  'SIDE_CONFLICT',
  'NOT_FOUND',
  'INTERNAL_ERROR',
] as const;
export type ErrorCode = (typeof ERROR_CODES)[number];

/** Section 9.10 HTTP status per error code. */
export const ERROR_HTTP_STATUS: Readonly<Record<ErrorCode, number>> = {
  UNAUTHENTICATED: 401,
  FORBIDDEN: 403,
  NOT_FOUND: 404,
  INSUFFICIENT_FUNDS: 409,
  MARKET_CLOSED: 409,
  STALE_MARKET: 409,
  WRONG_RUN: 409,
  IDEMPOTENCY_CONFLICT: 409,
  SOURCE_STALE: 409,
  SIDE_CONFLICT: 409,
  INVALID_AMOUNT: 422,
  VALIDATION_FAILED: 422,
  RATE_LIMITED: 429,
  INTERNAL_ERROR: 500,
  CAPABILITY_UNAVAILABLE: 503,
};

/** Section 9.10: only these are retryable with the same key and body. */
export const RETRYABLE_ERROR_CODES = ['RATE_LIMITED', 'INTERNAL_ERROR'] as const;

/** `raffle.*` and `call.state` are reserved and intentionally not listed yet. */
export const EVENT_TYPES = [
  'stream.updated',
  'source.health',
  'market.opened',
  'pool.updated',
  'market.locked',
  'market.evaluating',
  'market.settled',
  'market.voided',
  'wager.updated',
  'wallet.changed',
] as const;
export type EventType = (typeof EVENT_TYPES)[number];

/** Settlement algorithm identifier, present iff SETTLED (ECONOMICS section 4). */
export const SETTLEMENT_ALGORITHM_V1 = 'PARIMUTUEL_FLOOR_REMAINDER_V1' as const;

// ---------------------------------------------------------------------------
// B. SHARED
// ---------------------------------------------------------------------------

/** Published by the server in `snapshot.limits`; clients never hardcode these (section 9.2). */
export interface Limits {
  stake_min_minor: Minor;
  stake_max_minor: Minor;
  stake_step_minor: Minor;
  stake_default_minor: Minor;
  topup_presets_minor: Minor[];
  topup_min_minor: Minor;
  topup_max_minor: Minor;
  topup_step_minor: Minor;
}

export interface Modes {
  ai_mode: AiMode;
  payment_mode: PaymentMode;
  media_source_kind: SourceKind | null;
}

/** There is no total field (section 9.5). */
export interface WalletSummary {
  stream_session_id: RunId;
  available_minor: Minor;
  in_play_minor: Minor;
  balance_version: number;
  /** Reserved for P6. Optional with default null. */
  pending_topup_minor?: Minor | null;
}

export interface StreamInfo {
  stream_id: StreamId;
  twitch_channel_login: string;
  stream_session_id: RunId;
  run_state: RunState;
  aggregate_version: Pos;
  wagering_paused: boolean;
  wagering_paused_reason: PauseReason | null;
}

export interface SourceHealth {
  state: MediaHealth;
  source_kind: SourceKind | null;
  source_epoch: EpochId | null;
  last_media_at_utc: Utc | null;
  last_transcript_at_utc: Utc | null;
  updated_at_utc: Utc;
}

// ---------------------------------------------------------------------------
// C. StreamSnapshot: GET /v1/streams/{stream_id}/snapshot (authenticated)
// ---------------------------------------------------------------------------

export interface Pool {
  yes_minor: Minor;
  no_minor: Minor;
  /** = yes + no */
  total_minor: Minor;
  /** Bot stakes, included in the totals. */
  simulated_minor: Minor;
  wager_count: number;
}

/** Reserved, null until P4/P5. Criteria are keyed by side. */
export interface SideKeyed<T> {
  YES: T;
  NO: T;
}

export interface PublicMarket {
  market_id: MarketId;
  stream_session_id: RunId;
  rules_version: Pos;
  aggregate_version: Pos;
  state: MarketState;
  origin: MarketOrigin;
  /** 1..200 chars. Untrusted text: render as text. */
  question: string;
  /** 1..40 chars, default "Yes", bound to side YES. */
  yes_label: string;
  /** 1..40 chars, default "No", bound to side NO. */
  no_label: string;
  opened_at_utc: Utc;
  /** Exclusive: a wager is accepted only if the server commit time is < close_at_utc. */
  close_at_utc: Utc;
  resolve_by_utc: Utc;
  /** §9.20 item 2: when the AI expects the result; null when unknown. Viewers get it only after lock. */
  expected_result_at_utc?: Utc | null;
  locked_at_utc: Utc | null;
  terminal_at_utc: Utc | null;
  pool: Pool;
  /** Present iff SETTLED. */
  winning_side: Side | null;
  /** Present iff VOID. */
  void_reason: VoidReason | null;
  /** "PARIMUTUEL_FLOOR_REMAINDER_V1" iff SETTLED. */
  settlement_algorithm: string | null;
  // Reserved, null until P4/P5.
  criteria: SideKeyed<unknown> | null;
  opening_evidence_ids: EvidenceId[] | null;
  resolution_evidence_ids: EvidenceId[] | null;
  resolution_mode: string | null;
  resolution_reason: string | null;
}

export interface MyPosition {
  market_id: MarketId;
  side: Side | null;
  stake_total_minor: Minor;
  result: MyResult;
  /** WON: gross including stake; LOST: 0. */
  payout_total_minor: Minor | null;
  refund_total_minor: Minor | null;
  wagers: WagerReceipt[];
}

export interface StreamSnapshot {
  schema_version: SchemaVersion;
  server_time_utc: Utc;
  /** Highest committed event_id included in this snapshot. */
  event_hwm: number;
  stream: StreamInfo;
  modes: Modes;
  limits: Limits;
  source_health: SourceHealth;
  /** The nonterminal market, else the latest terminal market in the run, else null. */
  market: PublicMarket | null;
  my_position: MyPosition | null;
  wallet: WalletSummary;
  /** Reserved for P8. */
  raffle: null;
}

// ---------------------------------------------------------------------------
// D. WagerRequest: POST /v1/wagers (extra=forbid; no user_id, no schema_version)
// ---------------------------------------------------------------------------

export interface WagerRequest {
  operation_id: CUuid;
  stream_session_id: RunId;
  market_id: MarketId;
  rules_version: Pos;
  side: Side;
  amount_minor: number;
}

// ---------------------------------------------------------------------------
// E. WagerReceipt: 201 the first time; 200 with replayed=true
// ---------------------------------------------------------------------------

export interface WagerReceipt {
  wager_id: WagerId;
  operation_id: CUuid;
  stream_session_id: RunId;
  market_id: MarketId;
  rules_version: Pos;
  side: Side;
  amount_minor: Minor;
  status: WagerStatus;
  accepted_at_utc: Utc;
  terminal_at_utc: Utc | null;
  stake_txn_id: TxnId;
  terminal_txn_id: TxnId | null;
  payout_minor: Minor | null;
  refund_minor: Minor | null;
  market_aggregate_version: Pos;
  wallet_after: WalletSummary;
  replayed: boolean;
}

/** The top-level HTTP response body of POST /v1/wagers and GET /v1/operations/{id}. */
export interface WagerReceiptResponse extends WagerReceipt {
  schema_version: SchemaVersion;
}

// ---------------------------------------------------------------------------
// F. Me: GET /v1/me
// ---------------------------------------------------------------------------

export interface MeUser {
  user_id: UserId;
  /** 1..32 chars. */
  display_name: string;
  /** Unverified label, not identity. */
  claimed_twitch_login: string | null;
  role: Role;
}

export interface MeSession {
  session_id: SessionId;
  expires_at_utc: Utc;
}

export interface MeCurrentStream {
  stream_id: StreamId;
  twitch_channel_login: string;
  stream_session_id: RunId;
}

export interface Me {
  server_time_utc: Utc;
  user: MeUser;
  session: MeSession;
  current_stream: MeCurrentStream | null;
  wallet: WalletSummary | null;
}

export interface MeResponse extends Me {
  schema_version: SchemaVersion;
}

// ---------------------------------------------------------------------------
// G. ErrorEnvelope: every non-2xx (section 9.10)
// ---------------------------------------------------------------------------

export interface InsufficientFundsDetails {
  available_minor: Minor;
  requested_minor: Minor;
}
export interface InvalidAmountDetails {
  min_minor: Minor;
  max_minor: Minor;
  step_minor: Minor;
}
export const MARKET_CLOSED_REASONS = ['DEADLINE', 'STATE', 'PAUSED'] as const;
export type MarketClosedReason = (typeof MARKET_CLOSED_REASONS)[number];
export interface MarketClosedDetails {
  state: MarketState;
  close_at_utc: Utc;
  reason: MarketClosedReason;
}
export interface StaleMarketDetails {
  current_market_id: MarketId | null;
  current_rules_version: Pos | null;
}
export interface WrongRunDetails {
  current_stream_session_id: RunId;
}
export interface SourceStaleDetails {
  source_state: MediaHealth;
}
export interface SideConflictDetails {
  existing_side: Side;
}
export interface ValidationFailedDetails {
  fields: { loc: (string | number)[]; msg: string }[];
}

export interface ErrorDetailsByCode {
  INSUFFICIENT_FUNDS: InsufficientFundsDetails;
  INVALID_AMOUNT: InvalidAmountDetails;
  MARKET_CLOSED: MarketClosedDetails;
  STALE_MARKET: StaleMarketDetails;
  WRONG_RUN: WrongRunDetails;
  SOURCE_STALE: SourceStaleDetails;
  SIDE_CONFLICT: SideConflictDetails;
  VALIDATION_FAILED: ValidationFailedDetails;
}

export type ErrorDetails = ErrorDetailsByCode[keyof ErrorDetailsByCode];

export interface ErrorBody {
  code: ErrorCode;
  /** Safe text. Still untrusted: render as text. */
  message: string;
  retryable: boolean;
  retry_after_ms: number | null;
  request_id: RequestId;
  operation_id: CUuid | null;
  details: ErrorDetails | Record<string, unknown> | null;
}

export interface ErrorEnvelope {
  schema_version: SchemaVersion;
  error: ErrorBody;
  server_time_utc: Utc;
}

// ---------------------------------------------------------------------------
// H. DomainEvent and WebSocket control frames
// ---------------------------------------------------------------------------

export interface StreamUpdatedPayload {
  stream: StreamInfo;
  modes: Modes;
}

export type DomainEventPayload = PublicMarket | WagerReceipt | WalletSummary | SourceHealth | StreamUpdatedPayload;

export interface DomainEvent<P extends DomainEventPayload = DomainEventPayload> {
  schema_version: SchemaVersion;
  event_id: Pos;
  stream_session_id: RunId;
  aggregate_type: AggregateType;
  aggregate_id: string;
  aggregate_version: Pos;
  event_type: EventType;
  audience: Audience;
  occurred_at_utc: Utc;
  /** Full current aggregate state. */
  payload: P;
}

export interface WsClientAuthFrame {
  type: 'auth';
  ticket: string;
}
export interface WsReadyFrame {
  type: 'ready';
  event_hwm: number;
}
export interface WsResyncFrame {
  type: 'resync';
  reason: string;
}
export interface WsPingFrame {
  type: 'ping';
}
export interface WsPongFrame {
  type: 'pong';
}
export interface WsEventFrame {
  type: 'event';
  event: DomainEvent;
}
export type WsServerFrame = WsReadyFrame | WsResyncFrame | WsPingFrame | WsPongFrame | WsEventFrame;
export type WsClientFrame = WsClientAuthFrame | WsPingFrame | WsPongFrame;
export const WS_CLOSE_AUTH = 4401;
export const WS_CLOSE_ORIGIN_OR_ROLE = 4403;

export interface WsTicketRequest {
  stream_id: StreamId;
}
export interface WsTicketResponse {
  schema_version: SchemaVersion;
  /** "fzw_..." */
  ticket: string;
  /** 30 s after issue. */
  expires_at_utc: Utc;
  ws_path: '/v1/ws';
}

// ---------------------------------------------------------------------------
// I. Presence
// ---------------------------------------------------------------------------

export interface PresenceHeartbeat {
  device_id: CUuid;
  tab_instance_id: CUuid;
  stream_id: StreamId;
  known_stream_session_id: RunId | null;
  observed_channel_login: string | null;
  page_visibility: PageVisibility;
  player_state: PlayerState;
  /** 1..32 chars. */
  extension_version: string;
}

export interface PresenceAck {
  schema_version: SchemaVersion;
  server_time_utc: Utc;
  last_seen_utc: Utc;
  presence_state: PresenceState;
  heartbeat_interval_ms: number;
  presence_ttl_ms: number;
  current_stream_session_id: RunId;
}

// ---------------------------------------------------------------------------
// J. Enroll
// ---------------------------------------------------------------------------

/** 12 Crockford base32 characters, case- and hyphen-insensitive. */
export const INVITE_CODE_PATTERN = /^[0-9A-HJKMNP-TV-Z]{12}$/;
export const CLAIMED_TWITCH_LOGIN_PATTERN = /^[A-Za-z0-9_]{1,25}$/;

export function normalizeInviteCode(input: string): string {
  return input.replace(/-/g, '').toUpperCase();
}

export interface EnrollRequest {
  invite_code: string;
  display_name: string;
  claimed_twitch_login: string | null;
  device_id: CUuid;
}

export interface EnrollResponse {
  schema_version: SchemaVersion;
  /** "fzs_..." returned once, never logged. */
  session_token: string;
  session_id: SessionId;
  expires_at_utc: Utc;
  me: Me;
}

// ---------------------------------------------------------------------------
// K. Operation lookup: GET /v1/operations/{operation_id} -> WagerReceiptResponse or NOT_FOUND
// ---------------------------------------------------------------------------

export type OperationLookupResponse = WagerReceiptResponse;

// ---------------------------------------------------------------------------
// Operator-only shapes needed by the section 9.14 fixture list (P2 defines the operator routes).
// ---------------------------------------------------------------------------

/**
 * `operator/market_draft`: PublicMarket fields with state DRAFT. Section 9.15(3): close/resolve
 * times are null until OPEN (operator create takes close_in_s / resolve_in_s). P2 owns operator routes.
 */
export interface OperatorMarketDraft extends Omit<PublicMarket, 'state' | 'opened_at_utc' | 'close_at_utc' | 'resolve_by_utc'> {
  state: 'DRAFT';
  opened_at_utc: null;
  close_at_utc: null;
  resolve_by_utc: null;
}

// ---------------------------------------------------------------------------
// Section 9.14 banner mapping (terminal fixtures map to exactly one banner)
// ---------------------------------------------------------------------------

export const BANNERS = ['WIN', 'LOSS', 'VOID_REFUNDED', 'UNRESOLVED_REFUNDED', 'NEUTRAL'] as const;
export type Banner = (typeof BANNERS)[number];

/** PENDING never maps to a terminal banner. */
export const TERMINAL_BANNER_BY_RESULT: Readonly<Record<Exclude<MyResult, 'PENDING'>, Banner>> = {
  WON: 'WIN',
  LOST: 'LOSS',
  VOID_REFUNDED: 'VOID_REFUNDED',
  UNRESOLVED_REFUNDED: 'UNRESOLVED_REFUNDED',
  NONE: 'NEUTRAL',
};

/** Exact loss banner copy from the phase plan. */
export const LOSS_BANNER_TEXT = 'Ooohhh, so close!!';
