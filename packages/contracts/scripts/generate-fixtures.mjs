// Deterministic generator for packages/contracts/fixtures/v1 (CONTRACTS section 9.14).
//
// Run: node scripts/generate-fixtures.mjs
// The emitted JSON files are the deliverable; test/fixtures.test.ts validates them independently of
// this script. Conventions: fixed time 2026-11-14T20:00:00.000Z, deterministic section 9.1 IDs,
// fictional names, placeholder tokens, no phone numbers, P1 modes FIXTURE / MOCK / TEST_FIXTURE.

import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', 'fixtures', 'v1');
const T0 = Date.parse('2026-11-14T20:00:00.000Z');
const at = (sec) => new Date(T0 + Math.round(sec * 1000)).toISOString();
const NOW = at(0);

const hex32 = (n) => n.toString(16).padStart(32, '0');
const sid = (prefix, n) => `${prefix}_${hex32(n)}`;
const uuid = (n) => `00000000-0000-4000-8000-${n.toString(16).padStart(12, '0')}`;

const ID = {
  stream: sid('str', 0x1),
  run1: sid('run', 0x1),
  run2: sid('run', 0x2),
  viewer: sid('usr', 0xa001),
  session: sid('ses', 0xa001),
  epoch: sid('ep', 0x1),
  mDuel: sid('mkt', 0x101),
  mEmpty: sid('mkt', 0x102),
  mOneSided: sid('mkt', 0x103),
  mStale: sid('mkt', 0x104),
  mTimeout: sid('mkt', 0x105),
  mUnres: sid('mkt', 0x106),
  mReset: sid('mkt', 0x107),
  mDraft: sid('mkt', 0x108),
};
const CHANNEL = 'fazetime_demo';
const DEVICE = uuid(0xd001);
const TAB = uuid(0xd101);

const LIMITS = {
  stake_min_minor: 100,
  stake_max_minor: 50000,
  stake_step_minor: 100,
  stake_default_minor: 500,
  topup_presets_minor: [500, 1000, 5000],
  topup_min_minor: 500,
  topup_max_minor: 10000,
  topup_step_minor: 100,
};
const MODES = { ai_mode: 'FIXTURE', payment_mode: 'MOCK', media_source_kind: 'TEST_FIXTURE' };

const stream = (run = ID.run1, over = {}) => ({
  stream_id: ID.stream,
  twitch_channel_login: CHANNEL,
  stream_session_id: run,
  run_state: 'ACTIVE',
  aggregate_version: 3,
  wagering_paused: false,
  wagering_paused_reason: null,
  ...over,
});

const health = (state = 'LIVE', mediaAgeSec = 3) => ({
  state,
  source_kind: 'TEST_FIXTURE',
  source_epoch: ID.epoch,
  last_media_at_utc: at(-mediaAgeSec),
  last_transcript_at_utc: at(-mediaAgeSec - 1),
  updated_at_utc: NOW,
});

const wallet = (available, inPlay, version, run = ID.run1) => ({
  stream_session_id: run,
  available_minor: available,
  in_play_minor: inPlay,
  balance_version: version,
  pending_topup_minor: null,
});

const pool = (yes, no, simulated, count) => ({
  yes_minor: yes,
  no_minor: no,
  total_minor: yes + no,
  simulated_minor: simulated,
  wager_count: count,
});

const RESERVED = {
  criteria: null,
  opening_evidence_ids: null,
  resolution_evidence_ids: null,
  resolution_mode: null,
  resolution_reason: null,
};

// Market timelines (seconds relative to the fixed time).
const OPEN_TIMES = { opened: -60, close: 120, resolve: 600 };
const PAST_TIMES = { opened: -300, close: -150, resolve: 300 };

function market(base, over = {}) {
  const t = over.times ?? OPEN_TIMES;
  const m = {
    market_id: base.market_id,
    stream_session_id: base.run ?? ID.run1,
    rules_version: 1,
    aggregate_version: over.aggregate_version ?? 1,
    state: over.state ?? 'OPEN',
    origin: base.origin ?? 'CANNED_FIXTURE',
    question: base.question,
    yes_label: base.yes_label ?? 'Yes',
    no_label: base.no_label ?? 'No',
    opened_at_utc: at(t.opened),
    close_at_utc: at(t.close),
    resolve_by_utc: at(t.resolve),
    locked_at_utc: over.locked_at_utc ?? null,
    terminal_at_utc: over.terminal_at_utc ?? null,
    pool: over.pool ?? pool(0, 0, 0, 0),
    winning_side: over.winning_side ?? null,
    void_reason: over.void_reason ?? null,
    settlement_algorithm: over.state === 'SETTLED' ? 'PARIMUTUEL_FLOOR_REMAINDER_V1' : null,
    ...RESERVED,
  };
  return m;
}

const DUEL = {
  market_id: ID.mDuel,
  question: 'Will RedFox win the first Minecraft duel against BlueJay?',
  yes_label: 'RedFox',
  no_label: 'BlueJay',
};
const EMPTY = { market_id: ID.mEmpty, question: 'Will anyone place a bed in the first 30 seconds of round one?' };
const ONE_SIDED = { market_id: ID.mOneSided, question: 'Will BlueJay find diamonds before round two starts?' };
const STALE = {
  market_id: ID.mStale,
  origin: 'AI_APPROVED',
  question: 'Will RedFox reach the Nether before BlueJay does?',
  yes_label: 'RedFox first',
  no_label: 'BlueJay first',
};
const TIMEOUT = { market_id: ID.mTimeout, origin: 'AI_APPROVED', question: 'Will the duel last longer than five minutes?' };
const UNRES = {
  market_id: ID.mUnres,
  origin: 'AI_AUTOMATIC',
  question: 'Will BlueJay block an arrow with a shield during round one?',
};
const RESET = { market_id: ID.mReset, question: 'Will RedFox build a tower taller than ten blocks?' };

// Viewer wager receipts --------------------------------------------------------------------------

function receipt({ n, market_id, side, amount, status, acceptedSec, terminalSec = null, payout = null, refund = null, mav, walletAfter, run = ID.run1 }) {
  return {
    wager_id: sid('wgr', 0xb000 + n),
    operation_id: uuid(0xc000 + n),
    stream_session_id: run,
    market_id,
    rules_version: 1,
    side,
    amount_minor: amount,
    status,
    accepted_at_utc: at(acceptedSec),
    terminal_at_utc: terminalSec === null ? null : at(terminalSec),
    stake_txn_id: sid('txn', 0xb000 + n),
    terminal_txn_id: terminalSec === null ? null : sid('txn', 0xb100 + n),
    payout_minor: payout,
    refund_minor: refund,
    market_aggregate_version: mav,
    wallet_after: walletAfter,
    replayed: false,
  };
}

const duelWager = (over = {}) =>
  receipt({ n: 1, market_id: ID.mDuel, side: 'YES', amount: 500, status: 'ACCEPTED', acceptedSec: -30, mav: 7, walletAfter: wallet(1500, 500, 2), ...over });

function position(market_id, wagers, result, extra = {}) {
  const side = wagers.length ? wagers[0].side : null;
  return {
    market_id,
    side,
    stake_total_minor: wagers.reduce((s, w) => s + w.amount_minor, 0),
    result,
    payout_total_minor: extra.payout ?? null,
    refund_total_minor: extra.refund ?? null,
    wagers,
  };
}
const noPosition = (market_id) => position(market_id, [], 'NONE');

function snapshot({ hwm = 40, streamOver, run = ID.run1, sourceHealth = health(), market: m = null, my_position = null, wallet: w }) {
  return {
    schema_version: 1,
    server_time_utc: NOW,
    event_hwm: hwm,
    stream: stream(run, streamOver),
    modes: MODES,
    limits: LIMITS,
    source_health: sourceHealth,
    market: m,
    my_position,
    wallet: w,
    raffle: null,
  };
}

// Snapshot fixtures -------------------------------------------------------------------------------

const S = {};
S.no_market = snapshot({ wallet: wallet(2000, 0, 1) });

S.open_no_position = snapshot({
  hwm: 46,
  market: market(DUEL, { aggregate_version: 6, pool: pool(1500, 2500, 2500, 5) }),
  my_position: noPosition(ID.mDuel),
  wallet: wallet(2000, 0, 1),
});

S.open_with_position = snapshot({
  hwm: 48,
  market: market(DUEL, { aggregate_version: 7, pool: pool(2000, 2500, 2500, 6) }),
  my_position: position(ID.mDuel, [duelWager()], 'PENDING'),
  wallet: wallet(1500, 500, 2),
});

S.open_empty_pool = snapshot({
  hwm: 41,
  market: market(EMPTY, { aggregate_version: 2 }),
  my_position: noPosition(ID.mEmpty),
  wallet: wallet(2000, 0, 1),
});

S.open_one_sided = snapshot({
  hwm: 43,
  market: market(ONE_SIDED, { aggregate_version: 3, pool: pool(1500, 0, 1000, 2) }),
  my_position: noPosition(ID.mOneSided),
  wallet: wallet(2000, 0, 1),
});

S.open_low_balance = snapshot({
  hwm: 46,
  market: market(DUEL, { aggregate_version: 6, pool: pool(1500, 2500, 2500, 5) }),
  my_position: noPosition(ID.mDuel),
  wallet: wallet(300, 0, 5),
});

S.open_source_stale = snapshot({
  hwm: 52,
  streamOver: { aggregate_version: 4, wagering_paused: true, wagering_paused_reason: 'SOURCE_NOT_LIVE' },
  sourceHealth: health('STALE', 18),
  market: market(STALE, { aggregate_version: 4, pool: pool(1000, 1000, 1000, 3) }),
  my_position: noPosition(ID.mStale),
  wallet: wallet(2000, 0, 1),
});

const LOCKED_POOL = pool(2000, 3000, 3000, 7);
const lockedTimes = { ...PAST_TIMES };
S.locked = snapshot({
  hwm: 50,
  market: market(DUEL, { times: lockedTimes, state: 'LOCKED', aggregate_version: 9, pool: LOCKED_POOL, locked_at_utc: at(-150) }),
  my_position: position(ID.mDuel, [duelWager({ acceptedSec: -200 })], 'PENDING'),
  wallet: wallet(1500, 500, 2),
});

S.evaluating = snapshot({
  hwm: 51,
  market: market(DUEL, { times: lockedTimes, state: 'EVALUATING', aggregate_version: 10, pool: LOCKED_POOL, locked_at_utc: at(-150) }),
  my_position: position(ID.mDuel, [duelWager({ acceptedSec: -200 })], 'PENDING'),
  wallet: wallet(1500, 500, 2),
});

// Settled: T = 5000, YES = 2000, NO = 3000. A 500 YES stake wins 500 * 5000 / 2000 = 1250 exactly.
const settledMarket = (winning_side) =>
  market(DUEL, {
    times: lockedTimes,
    state: 'SETTLED',
    aggregate_version: 11,
    pool: LOCKED_POOL,
    locked_at_utc: at(-150),
    terminal_at_utc: at(-20),
    winning_side,
  });

S.settled_win = snapshot({
  hwm: 55,
  market: settledMarket('YES'),
  my_position: position(
    ID.mDuel,
    [duelWager({ acceptedSec: -200, status: 'WON', terminalSec: -20, payout: 1250 })],
    'WON',
    { payout: 1250 },
  ),
  wallet: wallet(2750, 0, 3),
});

S.settled_loss = snapshot({
  hwm: 55,
  market: settledMarket('NO'),
  my_position: position(
    ID.mDuel,
    [duelWager({ acceptedSec: -200, status: 'LOST', terminalSec: -20, payout: 0 })],
    'LOST',
    { payout: 0 },
  ),
  wallet: wallet(1500, 0, 2),
});

S.settled_no_position = snapshot({
  hwm: 55,
  market: settledMarket('YES'),
  my_position: noPosition(ID.mDuel),
  wallet: wallet(2000, 0, 1),
});

const voidTimes = { ...PAST_TIMES };
S.void_one_sided = snapshot({
  hwm: 45,
  market: market(ONE_SIDED, {
    times: voidTimes,
    state: 'VOID',
    aggregate_version: 5,
    pool: pool(2000, 0, 1000, 3),
    locked_at_utc: at(-150),
    terminal_at_utc: at(-150),
    void_reason: 'ONE_SIDED_POOL',
  }),
  my_position: position(
    ID.mOneSided,
    [
      receipt({
        n: 2,
        market_id: ID.mOneSided,
        side: 'YES',
        amount: 500,
        status: 'REFUNDED',
        acceptedSec: -200,
        terminalSec: -150,
        refund: 500,
        mav: 4,
        walletAfter: wallet(1500, 500, 2),
      }),
    ],
    'VOID_REFUNDED',
    { refund: 500 },
  ),
  wallet: wallet(2000, 0, 3),
});

S.void_empty = snapshot({
  hwm: 42,
  market: market(EMPTY, {
    times: voidTimes,
    state: 'VOID',
    aggregate_version: 3,
    locked_at_utc: at(-150),
    terminal_at_utc: at(-150),
    void_reason: 'EMPTY_POOL',
  }),
  my_position: noPosition(ID.mEmpty),
  wallet: wallet(2000, 0, 1),
});

S.void_source_gap = snapshot({
  hwm: 54,
  streamOver: { aggregate_version: 4 },
  sourceHealth: health('GAP', 40),
  market: market(STALE, {
    state: 'VOID',
    aggregate_version: 6,
    pool: pool(1500, 1000, 1000, 4),
    terminal_at_utc: at(-35),
    void_reason: 'SOURCE_GAP',
  }),
  my_position: position(
    ID.mStale,
    [
      receipt({
        n: 3,
        market_id: ID.mStale,
        side: 'YES',
        amount: 500,
        status: 'REFUNDED',
        acceptedSec: -50,
        terminalSec: -35,
        refund: 500,
        mav: 5,
        walletAfter: wallet(1500, 500, 2),
      }),
    ],
    'VOID_REFUNDED',
    { refund: 500 },
  ),
  wallet: wallet(2000, 0, 3),
});

const timeoutTimes = { opened: -700, close: -580, resolve: -10 };
S.void_resolution_timeout = snapshot({
  hwm: 60,
  market: market(TIMEOUT, {
    times: timeoutTimes,
    state: 'VOID',
    aggregate_version: 9,
    pool: pool(1500, 2000, 1500, 5),
    locked_at_utc: at(-580),
    terminal_at_utc: at(-10),
    void_reason: 'RESOLUTION_TIMEOUT',
  }),
  my_position: position(
    ID.mTimeout,
    [
      receipt({
        n: 4,
        market_id: ID.mTimeout,
        side: 'NO',
        amount: 1000,
        status: 'REFUNDED',
        acceptedSec: -640,
        terminalSec: -10,
        refund: 1000,
        mav: 5,
        walletAfter: wallet(1000, 1000, 2),
      }),
    ],
    'UNRESOLVED_REFUNDED',
    { refund: 1000 },
  ),
  wallet: wallet(2000, 0, 3),
});

S.void_unresolvable = snapshot({
  hwm: 58,
  market: market(UNRES, {
    times: PAST_TIMES,
    state: 'VOID',
    aggregate_version: 8,
    pool: pool(2000, 1500, 2000, 5),
    locked_at_utc: at(-150),
    terminal_at_utc: at(-25),
    void_reason: 'UNRESOLVABLE',
  }),
  my_position: position(
    ID.mUnres,
    [
      receipt({
        n: 5,
        market_id: ID.mUnres,
        side: 'YES',
        amount: 500,
        status: 'REFUNDED',
        acceptedSec: -200,
        terminalSec: -25,
        refund: 500,
        mav: 5,
        walletAfter: wallet(1500, 500, 2),
      }),
    ],
    'UNRESOLVED_REFUNDED',
    { refund: 500 },
  ),
  wallet: wallet(2000, 0, 3),
});

// After an operator reset: the snapshot describes the NEW run. The old run's market was voided with
// RUN_RESET inside that run (see event/market_voided.json); the new run has no market yet.
S.run_reset = snapshot({
  hwm: 70,
  run: ID.run2,
  streamOver: { aggregate_version: 5 },
  wallet: wallet(2000, 0, 1, ID.run2),
});

// Other fixtures -----------------------------------------------------------------------------------

const viewerUser = { user_id: ID.viewer, display_name: 'PixelPilot', claimed_twitch_login: 'pixelpilot_demo', role: 'VIEWER' };
const meBody = (w) => ({
  server_time_utc: NOW,
  user: viewerUser,
  session: { session_id: ID.session, expires_at_utc: at(72 * 3600) },
  current_stream: { stream_id: ID.stream, twitch_channel_login: CHANNEL, stream_session_id: ID.run1 },
  wallet: w,
});

const F = {};
F['operator/market_draft'] = {
  ...market(
    { market_id: ID.mDraft, origin: 'OPERATOR_FIXTURE', question: 'Will RedFox win the rematch?', yes_label: 'RedFox', no_label: 'BlueJay' },
    { state: 'DRAFT', times: { opened: 0, close: 150, resolve: 900 } },
  ),
  opened_at_utc: null,
  close_at_utc: null,
  resolve_by_utc: null,
};

F['me/viewer_funded'] = { schema_version: 1, ...meBody(wallet(2000, 0, 1)) };
F['me/viewer_low_balance'] = { schema_version: 1, ...meBody(wallet(300, 0, 5)) };

F['enroll/request'] = {
  invite_code: 'FAKE-C0DE-2026',
  display_name: 'PixelPilot',
  claimed_twitch_login: 'pixelpilot_demo',
  device_id: DEVICE,
};
const placeholderToken = (prefix, label) => `${prefix}_${(label + '0'.repeat(43)).slice(0, 43)}`;
F['enroll/response'] = {
  schema_version: 1,
  session_token: placeholderToken('fzs', 'PLACEHOLDER_NOT_A_REAL_SESSION_TOKEN_'),
  session_id: ID.session,
  expires_at_utc: at(72 * 3600),
  me: meBody(wallet(2000, 0, 1)),
};

F['ws/ticket_response'] = {
  schema_version: 1,
  ticket: placeholderToken('fzw', 'PLACEHOLDER_NOT_A_REAL_WS_TICKET_'),
  expires_at_utc: at(30),
  ws_path: '/v1/ws',
};

F['presence/heartbeat'] = {
  device_id: DEVICE,
  tab_instance_id: TAB,
  stream_id: ID.stream,
  known_stream_session_id: ID.run1,
  observed_channel_login: CHANNEL,
  page_visibility: 'VISIBLE',
  player_state: 'PLAYING',
  extension_version: '0.1.0',
};
F['presence/ack'] = {
  schema_version: 1,
  server_time_utc: NOW,
  last_seen_utc: NOW,
  presence_state: 'PRESENT',
  heartbeat_interval_ms: 15000,
  presence_ttl_ms: 45000,
  current_stream_session_id: ID.run1,
};

const acceptedReceipt = duelWager({ acceptedSec: 0 });
F['wager/request'] = {
  operation_id: acceptedReceipt.operation_id,
  stream_session_id: ID.run1,
  market_id: ID.mDuel,
  rules_version: 1,
  side: 'YES',
  amount_minor: 500,
};
F['wager/receipt_accepted'] = { schema_version: 1, ...acceptedReceipt };
F['wager/receipt_replayed'] = { schema_version: 1, ...acceptedReceipt, replayed: true };
// Same operation_id as wager/request with a different body: the server answers IDEMPOTENCY_CONFLICT.
F['wager/request_conflict'] = { ...F['wager/request'], amount_minor: 1000 };

// Errors: one file per code ----------------------------------------------------------------------
const OP = F['wager/request'].operation_id;
const err = (n, code, message, { retryable = false, retry_after_ms = null, operation_id = null, details = null } = {}) => ({
  schema_version: 1,
  error: { code, message, retryable, retry_after_ms, request_id: sid('req', 0xe000 + n), operation_id, details },
  server_time_utc: NOW,
});
const ERRORS = {
  unauthenticated: err(1, 'UNAUTHENTICATED', 'Session missing, expired or revoked.'),
  forbidden: err(2, 'FORBIDDEN', 'This session cannot perform that action.'),
  invalid_amount: err(3, 'INVALID_AMOUNT', 'Stake must be between 100 and 50000 in steps of 100.', {
    operation_id: OP,
    details: { min_minor: 100, max_minor: 50000, step_minor: 100 },
  }),
  insufficient_funds: err(4, 'INSUFFICIENT_FUNDS', 'Available balance is lower than the stake.', {
    operation_id: OP,
    details: { available_minor: 300, requested_minor: 500 },
  }),
  market_closed: err(5, 'MARKET_CLOSED', 'The market is no longer accepting wagers.', {
    operation_id: OP,
    details: { state: 'LOCKED', close_at_utc: at(-150), reason: 'DEADLINE' },
  }),
  stale_market: err(6, 'STALE_MARKET', 'The market terms changed or the market is unknown.', {
    operation_id: OP,
    details: { current_market_id: ID.mDuel, current_rules_version: 1 },
  }),
  wrong_run: err(7, 'WRONG_RUN', 'A new demo run has started.', {
    operation_id: OP,
    details: { current_stream_session_id: ID.run2 },
  }),
  idempotency_conflict: err(8, 'IDEMPOTENCY_CONFLICT', 'This operation_id was already used with a different request.', {
    operation_id: OP,
  }),
  capability_unavailable: err(9, 'CAPABILITY_UNAVAILABLE', 'This capability is not available right now.'),
  source_stale: err(10, 'SOURCE_STALE', 'The stream source is not live; wagering is paused.', {
    operation_id: OP,
    details: { source_state: 'STALE' },
  }),
  rate_limited: err(11, 'RATE_LIMITED', 'Too many requests.', { retryable: true, retry_after_ms: 2000, operation_id: OP }),
  validation_failed: err(12, 'VALIDATION_FAILED', 'The request body is invalid.', {
    details: { fields: [{ loc: ['body', 'user_id'], msg: 'Extra inputs are not permitted' }] },
  }),
  side_conflict: err(13, 'SIDE_CONFLICT', 'You already backed the other side of this market.', {
    operation_id: OP,
    details: { existing_side: 'YES' },
  }),
  not_found: err(14, 'NOT_FOUND', 'No such operation for this user.'),
  internal_error: err(15, 'INTERNAL_ERROR', 'The outcome is unknown. Retry with the same operation_id.', {
    retryable: true,
    operation_id: OP,
  }),
};
for (const [name, body] of Object.entries(ERRORS)) F[`error/${name}`] = body;

// Events: one file per event type ------------------------------------------------------------------
const ev = (event_id, event_type, aggregate_type, aggregate_id, aggregate_version, audience, occurredSec, payload, run = ID.run1) => ({
  schema_version: 1,
  event_id,
  stream_session_id: run,
  aggregate_type,
  aggregate_id,
  aggregate_version,
  event_type,
  audience,
  occurred_at_utc: at(occurredSec),
  payload,
});

const duelOpen = (v, p) => market(DUEL, { aggregate_version: v, pool: p });
const duelPast = (over) => market(DUEL, { times: lockedTimes, pool: LOCKED_POOL, locked_at_utc: at(-150), ...over });

const EVENTS = {
  stream_updated: ev(70, 'stream.updated', 'STREAM', ID.stream, 5, 'PUBLIC', 0, { stream: stream(ID.run2, { aggregate_version: 5 }), modes: MODES }, ID.run2),
  source_health: ev(52, 'source.health', 'SOURCE', ID.stream, 12, 'PUBLIC', 0, health('STALE', 18)),
  market_opened: ev(41, 'market.opened', 'MARKET', ID.mDuel, 2, 'PUBLIC', -60, duelOpen(2, pool(0, 0, 0, 0))),
  pool_updated: ev(48, 'pool.updated', 'MARKET', ID.mDuel, 7, 'PUBLIC', -30, duelOpen(7, pool(2000, 2500, 2500, 6))),
  market_locked: ev(50, 'market.locked', 'MARKET', ID.mDuel, 9, 'PUBLIC', -150, duelPast({ state: 'LOCKED', aggregate_version: 9 })),
  market_evaluating: ev(51, 'market.evaluating', 'MARKET', ID.mDuel, 10, 'PUBLIC', -150, duelPast({ state: 'EVALUATING', aggregate_version: 10 })),
  market_settled: ev(53, 'market.settled', 'MARKET', ID.mDuel, 11, 'PUBLIC', -20, settledMarket('YES')),
  market_voided: ev(
    69,
    'market.voided',
    'MARKET',
    ID.mReset,
    4,
    'PUBLIC',
    -1,
    market(RESET, { state: 'VOID', aggregate_version: 4, pool: pool(1000, 500, 500, 3), terminal_at_utc: at(-1), void_reason: 'RUN_RESET' }),
  ),
  wager_updated: ev(
    54,
    'wager.updated',
    'WAGER',
    sid('wgr', 0xb001),
    2,
    'USER',
    -20,
    duelWager({ acceptedSec: -200, status: 'WON', terminalSec: -20, payout: 1250 }),
  ),
  wallet_changed: ev(55, 'wallet.changed', 'WALLET', ID.viewer, 3, 'USER', -20, wallet(2750, 0, 3)),
};
for (const [name, body] of Object.entries(EVENTS)) F[`event/${name}`] = body;

// Reordered and duplicated delivery for one MARKET aggregate. The client starts from the
// open_no_position snapshot (aggregate_version 6), keeps the highest version seen, and discards older.
const v8 = duelOpen(8, pool(2000, 3000, 3000, 7));
F['event/sequence_reorder_duplicate'] = {
  schema_version: 1,
  description:
    'Starting from snapshot/open_no_position (market aggregate_version 6), events arrive out of order and duplicated. ' +
    'Apply an event only if its aggregate_version is greater than the highest version already applied for that aggregate.',
  initial_market_aggregate_version: 6,
  delivered: [
    EVENTS.pool_updated,
    EVENTS.market_opened,
    EVENTS.pool_updated,
    EVENTS.market_locked,
    ev(49, 'pool.updated', 'MARKET', ID.mDuel, 8, 'PUBLIC', -40, v8),
  ],
  expected_applied: [true, false, false, true, false],
  expected_final_market: EVENTS.market_locked.payload,
};

// ECONOMICS section 4 worked example -----------------------------------------------------------------
F['domain/settlement_worked_example'] = {
  schema_version: 1,
  description: 'ECONOMICS.md section 4 worked example: zero fee, floor payouts, remainder cents by descending remainder then wager_id ascending.',
  settlement_algorithm: 'PARIMUTUEL_FLOOR_REMAINDER_V1',
  fee_minor: 0,
  winning_side: 'YES',
  pool: pool(600, 400, 0, 4),
  wagers: [
    { wager_id: sid('wgr', 0xe001), label: 'A', side: 'YES', amount_minor: 100 },
    { wager_id: sid('wgr', 0xe002), label: 'B', side: 'YES', amount_minor: 200 },
    { wager_id: sid('wgr', 0xe003), label: 'C', side: 'YES', amount_minor: 300 },
    { wager_id: sid('wgr', 0xe004), label: 'D', side: 'NO', amount_minor: 400 },
  ],
  expected: {
    total_minor: 1000,
    winning_total_minor: 600,
    initial_payout_sum_minor: 999,
    unallocated_minor: 1,
    final_payout_sum_minor: 1000,
    payouts: [
      { wager_id: sid('wgr', 0xe001), initial_payout_minor: 166, remainder_numerator: 400, final_payout_minor: 167, net_profit_minor: 67 },
      { wager_id: sid('wgr', 0xe002), initial_payout_minor: 333, remainder_numerator: 200, final_payout_minor: 333, net_profit_minor: 133 },
      { wager_id: sid('wgr', 0xe003), initial_payout_minor: 500, remainder_numerator: 0, final_payout_minor: 500, net_profit_minor: 200 },
    ],
    losing_payouts: [{ wager_id: sid('wgr', 0xe004), final_payout_minor: 0 }],
  },
};

// Write ---------------------------------------------------------------------------------------------
rmSync(ROOT, { recursive: true, force: true });
let count = 0;
const write = (rel, body) => {
  const file = join(ROOT, `${rel}.json`);
  mkdirSync(dirname(file), { recursive: true });
  writeFileSync(file, JSON.stringify(body, null, 2) + '\n');
  count += 1;
};
for (const [name, body] of Object.entries(S)) write(`snapshot/${name}`, body);
for (const [name, body] of Object.entries(F)) write(name, body);
console.log(`wrote ${count} fixtures to ${ROOT}`);
