# Shared contract specification

Version: **v1 FROZEN on 2026-11-14.** §9 is authoritative for P1/P2. This is a design contract, not generated OpenAPI or application code. [PROJECT_PLAN](../PROJECT_PLAN.md) is authoritative. The coordinator owns contract edits; implementers propose changes before changing both sides independently. Backend Pydantic/OpenAPI will become the executable schema; generated TypeScript types should derive from it.

## 1. Canonical vocabulary

Use these exact wire names after P0 review. Narrative references to run/session/epoch map here; do not create duplicate competing identifiers.

| Field | Meaning |
|---|---|
| `schema_version` | Envelope contract version; initially 1 |
| `stream_id` | Stable internal identity for the single Twitch channel |
| `stream_session_id` | One explicit demo/broadcast accounting run; also called demo run in prose |
| `source_epoch` | New ID on ingest restart, seek/loop, adapter change or discontinuity recovery; formerly described as ingest session |
| `sequence` | Monotonic integer within source epoch |
| `market_id`, `rules_version`, `aggregate_version` | Immutable market identity; the frozen-terms version that wagers check; and a per-change ordering version (§9.3) |
| `operation_id` | Durable client-generated economic idempotency key, scoped to authenticated actor/type |
| `event_id` | Durable domain-event cursor; not the provider webhook event ID |
| `amount_minor` | Integer demo currency units, 100 units per displayed demo dollar |
| `server_time_utc` | RFC 3339 UTC timestamp from authoritative API; display local time separately |
| `media_start_ms`, `media_end_ms` | Decode positions in named source epoch, not epoch/Unix time |
| `received_at_utc` | Backend receipt time; distinct from when action happened at source |

All records that can outlive a reset carry `stream_session_id` where applicable. Phone/call identity uses opaque internal user IDs, never an LLM-inferred name. Integers crossing TypeScript must stay within JSON safe-integer limits; reject unreasonable amounts well below that bound.

## 2. State machines

Market states: `DRAFT`, `OPEN`, `LOCKED`, `EVALUATING`, `SETTLED`, `VOID`.
Normal transitions: DRAFT→OPEN→LOCKED→EVALUATING→SETTLED. Any accepted but not terminal market can become VOID under its fixed cancellation policy. Empty/one-sided pools must become VOID at lock (D12). A rejected candidate is not a market and has no ledger effects. No reopen, post-bet question edit, or terminal-to-terminal change.

Only one market in OPEN/LOCKED/EVALUATING is permitted per stream session, even if the UI has hidden it. Enforce transactionally. A pending candidate does not reserve funds. A new market waits until the previous one is terminal and any draw boundary is released.

Resolver decisions: `YES`, `NO`, `WAIT`, `UNRESOLVABLE`. WAIT/UNRESOLVABLE never mean NO. Backend chooses settlement/void under fixed criteria; only SETTLED has a winning side. Resolution deadline and cancellation conditions are frozen before OPEN.

Media health: `CONNECTING`, `LIVE`, `GAP`, `STALE`, `STOPPED`. `LIVE` means recent coherent media, not merely a running process. A gap compromising an unresolved market stops acceptance and applies the void policy; already terminal markets stay immutable.

Call job states: `PENDING`, `SUBMITTING`, `ALLOCATED`, `BRIDGE_READY`, `ACTIVE_OBSERVED`, `ENDING`, `COMPLETED`, `FAILED`, `UNKNOWN_EXTERNAL_STATE`. Map actual provider states to these deliberately. A submission timeout stays uncertain until reconciled. ACTIVE_OBSERVED must not assert both humans joined if the provider cannot report that; record an operator observation separately.

Raffle states: `UNARMED`, `ARMED`, `WAITING_FOR_MARKETS`, `DRAWN`, `EMPTY`. One draw identity per stream session. Call outcome is separate from raffle state.

## 3. Minimal persistent entities

| Entity | Core data / constraints |
|---|---|
| User | ID, display name, optional claimed Twitch name, bot flag, call opt-in, optional protected phone, verification status |
| Session | Hashed token, user/role, expiry, revocation; no auth by phone/name alone |
| StreamSession | Channel identity, run state, start/end, AI mode, current source epoch, draw pause |
| Presence | User/device/channel/session, last heartbeat, observable state; unique device identity |
| Evidence | Source epoch, sequence/interval, kind, hash, bounded artifact ref, freshness, supersession |
| InferenceTrace | Prompt/model versions, input evidence IDs, timing/usage, result validation status; no secrets |
| Market | Question/options/predicates, template, source episode, immutable opening evidence, deadlines, state/version, terminal decision |
| Wager | User, market, side, amount, acceptance timestamp, operation key, settlement/refund reference |
| LedgerTransaction | Unique economic operation/source, reason, timestamp, balanced entry references |
| LedgerEntry | Account, signed minor-unit movement, transaction; append-only |
| Balance | Derived/materialized amount with transactionally maintained version; reconcilable |
| Payment | Internal top-up intent, user/run, expected amount/currency, Stripe IDs, test marker, fulfillment transaction |
| ProviderReceipt | Provider and event ID uniqueness, verified status, payload hash and processed timestamp |
| DomainEvent | Event cursor, aggregate/version, audience, compact payload; persisted with mutation |
| RaffleSnapshot | Session, eligible-user weights, total, hash, trigger evidence, draw value/winner, unique draw operation |
| CallJob | User/raffle/market reference, line alias, provider call ID, attempt/idempotency, scoped capability, state |
| WagerIntent | Call/user/market, amount/side, confirmation nonce, expiry, accepted operation or cancellation |
| Redemption | User/item/demo code/ledger operation, unique redemption request; no retailer fulfillment |

Combine tables when doing so preserves invariants; these are conceptual records, not a demand for an enterprise schema. Worker observation artifacts live in bounded local storage, not large base64 database rows. Foreign keys and uniqueness must match the actual database engine.

## 4. Viewer HTTP surface

Names are proposed routes to finalize once; all mutation responses return the authoritative version and receipt.

| Route | Inputs / behavior |
|---|---|
| `POST /v1/enroll` | One-time invite code + minimal profile; creates revocable demo session, rate limited |
| `GET /v1/me` | Own profile, balance, role and current run membership |
| `POST /v1/presence` | Device ID, stream/session, page/player observations; server stamps last_seen |
| `GET /v1/streams/{id}/snapshot` | Public current market/pools, own wager/receipt/balance, source health, server time, event high-water mark |
| `POST /v1/ws-ticket` | Authenticated short-lived one-use ticket for scoped event subscription |
| `POST /v1/wagers` | operation_id, stream_session_id, market_id, rules_version, side YES/NO, amount_minor; atomic acceptance or typed failure (§9.6) |
| `POST /v1/topups` | operation_id + amount_minor; server-fixed currency and allowlisted Stripe return path; returns Checkout URL/intent |
| `GET /v1/topups/{id}` | Own authoritative fulfillment status; useful when redirect/webhook lag |
| `POST /v1/redemptions` | operation_id + fixed catalog item ID; transactionally debit, generate demo code once |
| `GET /v1/raffle` | Current eligible weight/total, snapshot when drawn, winner display label; no full phone lists |

Never accept client-supplied user_id as authority for a wallet action. Market version mismatches yield `STALE_MARKET`; the client refreshes and obtains new user intent where needed. UI estimates are not accepted settlement terms. Frozen in §9.3: the wager precondition checks `rules_version`. Pool updates never cause `STALE_MARKET`.

Typed failure codes: `UNAUTHENTICATED`, `FORBIDDEN`, `INVALID_AMOUNT`, `INSUFFICIENT_FUNDS`, `MARKET_CLOSED`, `STALE_MARKET`, `WRONG_RUN`, `IDEMPOTENCY_CONFLICT`, `CAPABILITY_UNAVAILABLE`, `SOURCE_STALE`, `RATE_LIMITED`, `VALIDATION_FAILED`. Do not show a generic success toast for an unresolved timeout. Retry the same operation key or read its receipt.

## 5. Worker and operator boundaries

Worker routes accept bounded media/evidence batches, proposal candidates and resolution candidates under a worker credential. Authenticate role, content size, rate, stream/session/epoch, schema, ID references and freshness. An evidence artifact reference must resolve within approved storage, never fetch arbitrary URLs or filesystem paths supplied by a model.

Proposal fields: candidate ID; template/version; episode fingerprint; question; two display labels; subject labels/IDs; YES and NO predicates; evidence IDs; expected source event-start boundary if actually known; suggested close time; resolution deadline; cancellation conditions; concise rationale; model/prompt version. Backend computes authoritative deadlines and validates temporal feasibility. Missing reliable source timing yields abstention or explicit controlled-demo policy, not fabricated precision.

Resolution fields: market ID and frozen version; YES/NO/WAIT/UNRESOLVABLE; supporting evidence IDs; media interval; predicate support; contradictions/missing evidence; concise reason; model/prompt version. Store suggestions separately from accepted outcomes. Late candidate responses cannot mutate a newer epoch or market.

Operator routes: set AI mode, approve candidate/result with reason, void unresolved market under rules, arm raffle, begin/archive a run, inspect sanitized health/evidence, submit constrained OBS action, reconcile/retry same call job. All require operator session and audit event. Do not expose arbitrary SQL, shell, URL fetch, provider RPC or balance-edit consoles.

Voice worker tools: fetch bound market snapshot, prepare intent, confirm exact intent nonce, cancel intent. The backend binds caller user from CallJob, rejects group-call mutations, and checks expiry, market, side, amount and fresh confirmation. Tools cannot choose a new recipient or charge arbitrary cards. One confirmation nonce can commit once.

## 6. Payment webhook contract

Stripe raw request bytes plus signature verify before parsing business data. Reject non-test events for this demo. Resolve the known internal top-up intent; require expected user mapping, amount, currency and actual paid state. Persist provider event receipt and call the shared idempotent fulfillment function. Uniqueness applies both to event delivery and the underlying economic payment/session object.

A valid duplicate returns success with no new credit. Unknown or mismatched objects are logged for review without granting funds. Preserve raw payload only if necessary and redacted/limited; never log all headers or secrets. HTTP acknowledgment alone is not wallet authority. Domain notifications derive from committed fulfillment.

If a prior run's valid payment completes after reset, reconcile it to that original intent/account/run according to the recorded reset policy. Do not mint credits into a new run or discard it merely to simplify the demo. Seeded resets must be a distinct source from provider payments.

## 7. Domain notifications

Envelope: schema_version, event_id, stream_session_id, aggregate type/ID, aggregate_version, occurred_at_utc, event_type, compact payload. Examples: `market.opened`, `market.locked`, `pool.updated`, `wallet.changed`, `market.settled`, `market.voided`, `source.health`, `raffle.drawn`, `call.state`.

Deliver public market/pool state to channel subscribers; wallet/wager/payment details only to their owner and authorized operator. Reordering or duplication is normal. Clients discard older aggregate versions and refetch on missing state or run change. Event delivery is at least once; economic effect is idempotent, not guaranteed by WebSocket.

## 8. Acceptance fixtures and changes

Before independent coding, publish examples for each state/error, source gap, duplicate receipt, and call confirmation. Examples include exact units and nullable semantics. Keep one enum source and validate generated TS/Python compatibility. Contract changes increment schema version or are backward-compatible additive fields with defaults; do not alter amount units in place.

A contract change proposal states affected producer/consumer, migration and tests. Coordinator approves, updates this file and the phase task packet, then schedules both sides. Incomplete consumers should use explicit mocks of the same contract rather than invent another API.

## 9. v1 freeze (2026-11-14, coordinator; D26)

Status: **FROZEN v1** for P1 and P2.
- Sources: planner proposals F1–F16 and reviewer findings H1–H6 and M1–M8 (docs/evidence/p0/P0-G-contract-review.md).
- Precedence: where §1–8 or ECONOMICS conflict with this section, this section wins.
- Changes: follow §8 and §9.12.

### 9.1 Formats

- **Server IDs:** `<prefix>_<32 lowercase hex>`, generated from uuid4.
  - Prefixes: `usr ses str run mkt wgr txn evd ep req inv`.
  - `stream_session_id` is a `run_` ID.
- **Client IDs** (`operation_id`, `device_id`, `tab_instance_id`): canonical lowercase UUID, from `crypto.randomUUID()`.
- **Counters:** `event_id`, versions and `sequence` are positive integers.
- **Stable ordering** (tie-breaks and raffle intervals): ASCII ascending on the ID string.
- **Times:** UTC RFC 3339 with exactly three fractional digits and `Z`, e.g. `2026-11-15T02:15:00.000Z`. Reject inputs without an offset.
- **Durations:** integer `*_ms`. Media positions use only `media_*_ms`, within one `source_epoch`.
- **Money:** integer `*_minor`, 100 per demo dollar. Payout and estimate arithmetic uses Python/TS integers within the §9.2 bounds. Never use floats or SQL arithmetic for payouts.

### 9.2 Limits

The server publishes these in `snapshot.limits`. Clients never hardcode them.

| Limit | Value |
|---|---|
| Stake | 100–50,000, step 100, default 500 |
| Top-up presets | 500 / 1,000 / 5,000 |
| Custom top-up | 500–10,000, step 100 |
| Available balance | at most 1,000,000 |
| Seed grant per real user per run | 2,000 (configurable) |

### 9.3 Markets

- **States:** `DRAFT OPEN LOCKED EVALUATING SETTLED VOID`.
  - DRAFT is operator-only and never appears in viewer payloads.
  - SETTLED and VOID are terminal and immutable.
- **Sides:** `YES` and `NO`.
  - `yes_label` and `no_label` are bound to their side.
  - P4 criteria are keyed by side (`criteria.YES`, `criteria.NO`).
  - A candidate whose labels and predicates are not paired by side is rejected.
- **Frozen at OPEN:**
  - `question`, labels and criteria.
  - `opened_at_utc` and `resolve_by_utc`.
  - `close_at_utc`, which is exclusive: a wager is accepted only if the server commit time is `< close_at_utc`.
  - The cancellation rules.
- **`rules_version`** identifies those frozen terms. It is 1 in v1; there are no edits after OPEN.
- **`aggregate_version`** increments on every state or pool change. It orders events and snapshots, and never causes `STALE_MARKET`.
- At most one market per run may be in `OPEN`, `LOCKED` or `EVALUATING`, enforced by a partial unique index.
- **Origins:** `OPERATOR_FIXTURE CANNED_FIXTURE AI_APPROVED AI_AUTOMATIC`. The origin is always shown.

The API owns every transition. Each is a conditional `UPDATE … WHERE state IN (…)`, written with its ledger and outbox rows in one `BEGIN IMMEDIATE` transaction.

| From → to | Trigger | Guards and effects |
|---|---|---|
| DRAFT → OPEN | Operator approval, or AUTOMATIC mode | No other nonterminal market in the run. Source is `LIVE` for Twitch-origin markets. `close_at_utc − now ≥ min_lead_ms` (configurable, default 30,000), rechecked at commit |
| OPEN → LOCKED | The sweeper, at `close_at_utc` | The sweeper runs every second and at startup. Wager acceptance checks `close_at_utc` itself and never depends on the sweeper. Records `locked_at_utc`, `lock_source_epoch` and `lock_media_ms` (nullable before P3) |
| OPEN → VOID at lock | The same lock transaction, if `yes_minor = 0` or `no_minor = 0` | Reason `EMPTY_POOL` or `ONE_SIDED_POOL`. Refunds happen in the same transaction (D12) |
| LOCKED → EVALUATING | The sweeper, immediately after lock | EVALUATING means "awaiting an accepted outcome" |
| EVALUATING → SETTLED | An accepted YES/NO outcome before `resolve_by_utc`, by operator approval or AUTOMATIC mode | Asserts `0 < W < T`. Payouts follow ECONOMICS §4, and they and the state change happen in one transaction |
| OPEN / LOCKED / EVALUATING → VOID | `UNRESOLVABLE` (immediate in AUTOMATIC mode; in APPROVAL mode the operator decides before the deadline), `RESOLUTION_TIMEOUT` (the sweeper at `resolve_by_utc`, in every mode), `SOURCE_GAP` (§9.4), `RUN_RESET` (§9.5), `OPERATOR_CANCELLED` | Every accepted wager is refunded exactly once, in the same transaction. No raffle weight |

### 9.4 Source health and gaps

The API derives health from worker observations and heartbeats, using `received_at_utc`. The thresholds are configurable defaults, to be tuned in P3.

Measured 2026-11-14: default Streamlink delivers Twitch media in bursts of 2 s fMP4 segments about 6 s apart (spikes/p0-media/README.md). A threshold of 6 s or less would therefore flicker every cycle.

| State | Meaning |
|---|---|
| `CONNECTING` | New epoch; no fresh media yet |
| `LIVE` | Fresh media no more than 12 s old, in the current epoch |
| `STALE` | Newest media is 12–30 s old |
| `STOPPED` | Newest media is more than 30 s old, or the worker heartbeat has been missing for more than 30 s |
| `GAP` | The worker reported a discontinuity |

- A wager on a Twitch-origin market commits only while health is `LIVE`; otherwise it fails with `SOURCE_STALE`. Fixture-origin markets are exempt and labelled.
- Between OPEN and an accepted outcome:
  - if the `source_epoch` changes, or health reaches `GAP` or `STOPPED`, the market becomes VOID with `SOURCE_GAP`;
  - `STALE` (30 s or less) only pauses acceptance.
- Before P3, the snapshot reports `STOPPED` with null fields.

### 9.5 Runs, wallets and reset

- **Wallets** are per (user, run).
  - Each new run seeds every real demo user with a labelled `SEED_GRANT`.
  - Bots have separate seeded wallets, flagged as simulated.
- **Reset** is an operator mutation with an `operation_id`. It:
  1. voids the nonterminal market with `RUN_RESET`, refunding its stakes;
  2. marks the run `ARCHIVED` (it stays inspectable);
  3. creates a new run and its seed grants.
  Ledger history and idempotency keys are never deleted.
- A payment that completes for an archived run credits that run's wallet, never the new run (P6).
- **Wallet fields:**
  - `available_minor`: DB `CHECK ≥ 0`; debited only conditionally.
  - `in_play_minor`: your own stakes in the nonterminal market.
  - `balance_version`.
  - `pending_topup_minor`: reserved for P6.
  - There is no total field.

### 9.6 Wagers

- **Request fields:** `operation_id`, `stream_session_id`, `market_id`, `rules_version`, `side`, `amount_minor`. The request uses `extra="forbid"`, so a body containing `user_id` fails with `VALIDATION_FAILED`.
- **One side per user per market.**
  - More wagers on the same side are allowed; each is a new operation.
  - A wager on the other side fails with `SIDE_CONFLICT`.
  - No edits, cancellations, cashouts or side switches.
- **Check order:**
  - Before the transaction: authentication, then rate limit, then validation / `INVALID_AMOUNT`.
  - Inside `BEGIN IMMEDIATE`, in order:
    1. idempotency replay or conflict
    2. `WRONG_RUN`
    3. `STALE_MARKET` (unknown market, or `rules_version` mismatch)
    4. `MARKET_CLOSED` (state is not OPEN, `now ≥ close_at_utc`, or acceptance is paused)
    5. `SOURCE_STALE`
    6. `SIDE_CONFLICT`
    7. `INSUFFICIENT_FUNDS`
    8. accept: debit available, credit escrow, insert the wager, insert the outbox event.
- **Estimated gross return** shown before lock: `floor(s × (T + s) / (W_side + s))`. It is labelled as an estimate.

### 9.7 Idempotency

- **Key:** unique on (actor user ID, `operation_id`). Store the operation type and a SHA-256 of the canonical request (sorted-key JSON).
- **Replays and conflicts:**
  - Same key and same hash: return the original receipt, HTTP 200, `replayed: true`. This holds even after close or reset.
  - Same key with a different hash or type: `IDEMPOTENCY_CONFLICT`, with no effect.
  - Another user's identical key is a separate operation.
- **What is recorded:** only committed effects. Business rejections are not cached.
- **Client rules:**
  - Create a new `operation_id` for every user intent, such as each Place Bet click.
  - Reuse the same key and body only after a network error, timeout, 5xx or `RATE_LIMITED`, until a definitive answer arrives.
  - Keep the pending operation in extension storage so a popup close or reload does not lose it.
- **Lookup:** `GET /v1/operations/{operation_id}` returns the caller's own receipt, or `NOT_FOUND`.
- Every operator mutation carries an `operation_id`: approve, void, reset, fixture credit, fixture market.
- Keys are kept for the life of the database.

### 9.8 Identity

- **Invite code:**
  - 12 Crockford base32 characters, case- and hyphen-insensitive.
  - Single use, enforced by a conditional update. Valid for 24 h. Stored hashed.
  - The code binds the role (`VIEWER` or `OPERATOR`) and the bot flag on the server. The enroll body cannot set them.
- **Session:**
  - `fzs_` + 32 random bytes (base64url), stored as SHA-256.
  - 72 h absolute expiry, revocable.
  - Sent only as `Authorization: Bearer` from the trusted extension context. Never put in URLs or exposed to page scripts.
  - A lost session is recovered with a new invite; P2 may bind it to the existing user.
- **Workers** use separate role credentials (`MEDIA_WORKER`, `CALL_WORKER`) from local configuration.
- No phone fields in P1 or P2 (D16).
- **Operator routes** live under `/v1/operator/*`. P2 defines them. Each requires an operator session, an `operation_id` and an audit event. They are not part of the viewer contract.

### 9.9 Snapshot, events and WebSocket

- **Snapshot:** `GET /v1/streams/{stream_id}/snapshot` is built in one read transaction. `event_hwm` is the highest committed `event_id` it includes.
- **Ticket:** `POST /v1/ws-ticket {stream_id}` returns `{ticket: "fzw_…", expires_at_utc (30 s), ws_path: "/v1/ws"}`.
- **Socket protocol:**
  - The socket URL carries no secret.
  - The first client frame must be `{"type":"auth","ticket"}` within 5 s, or the server closes with 4401.
  - The server answers `{"type":"ready","event_hwm"}`, then sends `{"type":"event","event":DomainEvent}`.
  - Either side may send an app-level ping every 25 s.
  - The server checks Origin against an allowlist: the pinned extension origin and `https://www.twitch.tv`.
- **Events:**
  - Each market is one aggregate (`MARKET`), and every event carries the full current aggregate state. A client keeps the highest `aggregate_version` it has seen and discards older ones.
  - Client sequence: subscribe and buffer, fetch the snapshot, then apply newer events. Refetch on a version gap or a run change.
  - Gaps in `event_id` are normal, because events are filtered by audience.
- **Polling fallback:** read the same snapshot every 2 s while a market is OPEN, and every 10 s otherwise.

### 9.10 Errors

Every non-2xx response returns:
`{error:{code, message, retryable, retry_after_ms, request_id, operation_id, details}, server_time_utc}`.

The codes are the §4 list plus `SIDE_CONFLICT`, `NOT_FOUND` and `INTERNAL_ERROR`.

| HTTP | Codes |
|---|---|
| 401 | `UNAUTHENTICATED` |
| 403 | `FORBIDDEN` |
| 404 | `NOT_FOUND` |
| 409 | `INSUFFICIENT_FUNDS`, `MARKET_CLOSED`, `STALE_MARKET`, `WRONG_RUN`, `IDEMPOTENCY_CONFLICT`, `SOURCE_STALE`, `SIDE_CONFLICT` |
| 422 | `INVALID_AMOUNT`, `VALIDATION_FAILED` |
| 429 | `RATE_LIMITED`, with `Retry-After` |
| 500 | `INTERNAL_ERROR` |
| 503 | `CAPABILITY_UNAVAILABLE` |

- Only `RATE_LIMITED` and `INTERNAL_ERROR` are retryable with the same key and body.
- A timeout or 5xx means the outcome is unknown. Retry with the same key, or read `/v1/operations/{id}`. Never show a success toast.

### 9.11 Persistence (P2)

- **SQLite settings (D23):** `journal_mode=DELETE`, `synchronous=FULL`, `foreign_keys=ON` and `busy_timeout=5000` on every connection.
- **Transactions:**
  - Every money or state mutation uses `BEGIN IMMEDIATE`: driver autocommit plus an explicit begin hook.
  - Snapshot reads run inside one `BEGIN`.
- **Backups:** use `sqlite3.Connection.backup`.
- **Constraints:**
  - A partial unique index allows only one nonterminal market per run.
  - `CHECK (available_minor >= 0)`.
  - Ledger tables are append-only, enforced by triggers that reject UPDATE and DELETE.

### 9.12 Versioning

- Every response and event carries `schema_version: 1`.
- **Additive (no version bump):** new optional fields with defaults, and new event types.
- **Needs a version bump plus a coordinator change record:** renames, removals, a change of type, unit or meaning, new required request fields, and new enum values that clients branch on.
- Requests use `extra="forbid"`.
- Clients ignore unknown fields, and render unknown enum values as a disabled "unavailable" state.

### 9.13 Schema sketch (v1)

```text
Utc = str "2026-11-15T02:15:00.000Z" | Minor = StrictInt demo cents 0..1_000_000_000 | Pos = StrictInt >= 1
Id(p) = ^p_[0-9a-f]{32}$ | CUuid = lowercase canonical UUID | every response/event: schema_version: Literal[1]

A. ENUMS
Side             YES | NO
MarketState      DRAFT | OPEN | LOCKED | EVALUATING | SETTLED | VOID      # DRAFT is operator-only
VoidReason       EMPTY_POOL | ONE_SIDED_POOL | UNRESOLVABLE | RESOLUTION_TIMEOUT | SOURCE_GAP | RUN_RESET | OPERATOR_CANCELLED
MarketOrigin     OPERATOR_FIXTURE | CANNED_FIXTURE | AI_APPROVED | AI_AUTOMATIC
ResolverDecision YES | NO | WAIT | UNRESOLVABLE                             # P5
WagerStatus      ACCEPTED | WON | LOST | REFUNDED
MyResult         NONE | PENDING | WON | LOST | VOID_REFUNDED | UNRESOLVED_REFUNDED
                 # UNRESOLVED_REFUNDED = VOID with UNRESOLVABLE or RESOLUTION_TIMEOUT
MediaHealth      CONNECTING | LIVE | GAP | STALE | STOPPED
SourceKind       TWITCH_STREAMLINK | TWITCH_TAB_CAPTURE | TEST_FIXTURE
AiMode           OFF | SHADOW | APPROVAL | AUTOMATIC | FIXTURE              # "supervised AI" = APPROVAL
PaymentMode      MOCK | UNAVAILABLE | STRIPE_TEST
Role             VIEWER | OPERATOR | MEDIA_WORKER | CALL_WORKER
RunState         ACTIVE | ARCHIVED
PauseReason      SOURCE_NOT_LIVE | OPERATOR_PAUSE | DRAW_BOUNDARY          # DRAW_BOUNDARY reserved (P8); blocks new markets only (D27)
PresenceState    PRESENT | ABSENT
PageVisibility   VISIBLE | HIDDEN | UNKNOWN
PlayerState      PLAYING | PAUSED | BUFFERING | UNKNOWN
AggregateType    STREAM | MARKET | WAGER | WALLET | SOURCE | RAFFLE (reserved) | CALL (reserved)
Audience         PUBLIC | USER | OPERATOR
LedgerReason     SEED_GRANT | FIXTURE_CREDIT | WAGER_STAKE | PAYOUT | REFUND | STRIPE_TEST_TOPUP (P6) | REDEMPTION (P6, optional)
ErrorCode        UNAUTHENTICATED | FORBIDDEN | INVALID_AMOUNT | INSUFFICIENT_FUNDS | MARKET_CLOSED | STALE_MARKET |
                 WRONG_RUN | IDEMPOTENCY_CONFLICT | CAPABILITY_UNAVAILABLE | SOURCE_STALE | RATE_LIMITED |
                 VALIDATION_FAILED | SIDE_CONFLICT | NOT_FOUND | INTERNAL_ERROR
event_type       stream.updated | source.health | market.opened | pool.updated | market.locked | market.evaluating |
                 market.settled | market.voided | wager.updated | wallet.changed | raffle.* (reserved) | call.state (reserved)

B. SHARED
Limits: stake_min_minor=100, stake_max_minor=50000, stake_step_minor=100, stake_default_minor=500,
  topup_presets_minor=[500,1000,5000], topup_min_minor=500, topup_max_minor=10000, topup_step_minor=100
Modes: ai_mode AiMode; payment_mode PaymentMode; media_source_kind SourceKind|None
WalletSummary: stream_session_id Id(run); available_minor Minor; in_play_minor Minor; balance_version int>=0;
  pending_topup_minor Minor|None = None (P6)
StreamInfo: stream_id Id(str); twitch_channel_login str; stream_session_id Id(run); run_state RunState;
  aggregate_version Pos; wagering_paused bool; wagering_paused_reason PauseReason|None
SourceHealth: state MediaHealth; source_kind SourceKind|None; source_epoch Id(ep)|None;
  last_media_at_utc Utc|None; last_transcript_at_utc Utc|None; updated_at_utc Utc

C. StreamSnapshot: GET /v1/streams/{stream_id}/snapshot (authenticated)
server_time_utc; event_hwm int>=0; stream StreamInfo; modes Modes; limits Limits; source_health SourceHealth;
market PublicMarket|None          # the nonterminal market, else the latest terminal market in the run, else None
my_position MyPosition|None; wallet WalletSummary; raffle None (reserved P8)
PublicMarket: market_id Id(mkt); stream_session_id Id(run); rules_version Pos; aggregate_version Pos;
  state MarketState; origin MarketOrigin; question str[1..200]; yes_label str[1..40]="Yes"; no_label str[1..40]="No";
  opened_at_utc; close_at_utc; resolve_by_utc; locked_at_utc|None; terminal_at_utc|None;
  pool {yes_minor, no_minor, total_minor (= yes + no), simulated_minor (bot stakes, included in totals), wager_count int};
  winning_side Side|None (iff SETTLED); void_reason VoidReason|None (iff VOID);
  settlement_algorithm str|None ("PARIMUTUEL_FLOOR_REMAINDER_V1" iff SETTLED);
  reserved, null until P4/P5: criteria {YES, NO}, opening_evidence_ids, resolution_evidence_ids,
  resolution_mode, resolution_reason
MyPosition: market_id; side Side|None; stake_total_minor Minor; result MyResult;
  payout_total_minor Minor|None (WON: gross including stake; LOST: 0); refund_total_minor Minor|None;
  wagers [WagerReceipt]

D. WagerRequest: POST /v1/wagers (extra=forbid; no user_id)
operation_id CUuid; stream_session_id Id(run); market_id Id(mkt); rules_version Pos; side Side; amount_minor StrictInt
  # an error isolated to amount_minor -> INVALID_AMOUNT with details {min_minor, max_minor, step_minor}

E. WagerReceipt: 201 the first time; 200 with replayed=true
wager_id Id(wgr); operation_id; stream_session_id; market_id; rules_version; side; amount_minor;
status WagerStatus; accepted_at_utc; terminal_at_utc|None; stake_txn_id Id(txn); terminal_txn_id Id(txn)|None;
payout_minor|None; refund_minor|None; market_aggregate_version Pos; wallet_after WalletSummary; replayed bool

F. Me: GET /v1/me
server_time_utc; user {user_id Id(usr); display_name str[1..32]; claimed_twitch_login str|None (unverified label); role Role};
session {session_id Id(ses); expires_at_utc}; current_stream {stream_id, twitch_channel_login, stream_session_id}|None;
wallet WalletSummary|None

G. ErrorEnvelope: every non-2xx (see 9.10)
error {code; message (safe text); retryable bool; retry_after_ms int|None; request_id Id(req);
  operation_id CUuid|None; details obj|None}; server_time_utc
details: INSUFFICIENT_FUNDS {available_minor, requested_minor} | INVALID_AMOUNT {min_minor, max_minor, step_minor} |
  MARKET_CLOSED {state, close_at_utc, reason DEADLINE|STATE|PAUSED} |
  STALE_MARKET {current_market_id|None, current_rules_version|None} | WRONG_RUN {current_stream_session_id} |
  SOURCE_STALE {source_state} | SIDE_CONFLICT {existing_side} | VALIDATION_FAILED {fields [{loc, msg}]}

H. DomainEvent: WS frame {"type":"event","event": ...}
event_id Pos; stream_session_id; aggregate_type; aggregate_id str; aggregate_version Pos; event_type; audience;
occurred_at_utc; payload = full current state (PublicMarket | WagerReceipt | WalletSummary | SourceHealth | {stream, modes})
WS control: client {"type":"auth","ticket"} within 5 s; server {"type":"ready","event_hwm"} | {"type":"resync","reason"};
  {"type":"ping"} / {"type":"pong"}; close codes 4401 (auth) and 4403 (origin or role)
POST /v1/ws-ticket {stream_id} -> {ticket "fzw_...", expires_at_utc, ws_path "/v1/ws"}

I. PresenceHeartbeat: POST /v1/presence (keyed by session user + device_id; aggregated per user and stream)
device_id CUuid; tab_instance_id CUuid; stream_id Id(str); known_stream_session_id Id(run)|None;
observed_channel_login str|None; page_visibility PageVisibility; player_state PlayerState; extension_version str[1..32]
PresenceAck: server_time_utc; last_seen_utc; presence_state PresenceState; heartbeat_interval_ms=15000;
  presence_ttl_ms=45000; current_stream_session_id Id(run)

J. Enroll: POST /v1/enroll (rate limited: 10 per 10 min per client)
request: invite_code str (12 Crockford base32, case- and hyphen-insensitive); display_name str[1..32];
  claimed_twitch_login ^[A-Za-z0-9_]{1,25}$ | None; device_id CUuid
response: session_token "fzs_..." (returned once, never logged); session_id; expires_at_utc; me Me
  # a bad, used or expired code -> UNAUTHENTICATED (indistinguishable)

K. Operation lookup: GET /v1/operations/{operation_id} -> the caller's own receipt (WagerReceipt for wagers) or NOT_FOUND
```

### 9.14 Fixtures

- **Location:** `packages/contracts/fixtures/v1/`. The extension engineer owns them; a backend contract test validates them.
- **Conventions:**
  - Fixed time `2026-11-14T20:00:00.000Z` and deterministic IDs.
  - Fictional names, placeholder tokens, no phone numbers.
  - P1 fixtures use modes `FIXTURE`, `MOCK` and `TEST_FIXTURE`.
  - The P1 mock adapter shifts every `*_utc` value to "now".
- **Required files:**
  - `snapshot/`: no_market, open_no_position, open_with_position, open_empty_pool, open_one_sided, open_low_balance, open_source_stale, locked, evaluating, settled_win, settled_loss, settled_no_position, void_one_sided, void_empty, void_source_gap, void_resolution_timeout, void_unresolvable, run_reset.
  - `operator/`: market_draft.
  - `me/`: viewer_funded, viewer_low_balance.
  - `enroll/`: request, response.
  - `ws/`: ticket_response.
  - `presence/`: heartbeat, ack.
  - `wager/`: request, receipt_accepted, receipt_replayed, request_conflict.
  - `error/`: one file per error code.
  - `event/`: one file per event type, plus sequence_reorder_duplicate (with its expected final state).
  - `domain/`: settlement_worked_example (ECONOMICS §4).
  - P1-only mocks (the redeem catalog and code) live outside the contract folder.
- **Invariants checked on every fixture:**
  - `total = yes + no`.
  - `winning_side` is present only when SETTLED; `void_reason` only when VOID.
  - No DRAFT appears in viewer payloads.
  - Amounts are integers within §9.2.
  - Timestamps and IDs match §9.1.
  - Each terminal fixture maps to exactly one banner:

| `MyResult` | Banner |
|---|---|
| `WON` | Win |
| `LOST` | "Ooohhh, so close!!" |
| `VOID_REFUNDED` | Void, refunded |
| `UNRESOLVED_REFUNDED` | Unresolved, refunded |
| `NONE` | Neutral |

### 9.15 v1 clarifications (2026-11-14, from the P1/P2 worker findings)

These are additive rulings. No schema version change.

1. **Wallet events:** aggregate `WALLET`, with `aggregate_id = user_id` and `aggregate_version = balance_version`. The version restarts each run. Clients key wallet state by (`stream_session_id`, `aggregate_id`) and refetch on a run change. `balance_version` increments on any `WalletSummary` change, including `in_play_minor`.
2. **`wagering_paused`** is true iff the current market is OPEN and either:
   - `OPERATOR_PAUSE` is set; or
   - the market is Twitch-origin (`AI_APPROVED`/`AI_AUTOMATIC`) and health is not `LIVE` (`SOURCE_NOT_LIVE`).
   Error codes:
   - A SOURCE_NOT_LIVE pause rejects wagers with `SOURCE_STALE`.
   - `MARKET_CLOSED` with reason `PAUSED` is only for `OPERATOR_PAUSE`.
   - `DRAW_BOUNDARY` never blocks wagers (D27).
   - The fixture `void_source_gap` should show `wagering_paused: false`.
3. **DRAFT:** `close_at_utc` and `resolve_by_utc` are null until OPEN. Operator create takes `close_in_s` and `resolve_in_s`, and `resolve_by_utc = close_at_utc + resolve_in_s`. Absolute times in `operator/market_draft` are illustrative.
4. **Versions:** `aggregate_version` is 1 at DRAFT creation, so viewers first see 2 or higher. Clients never assume a starting value.
5. **`schema_version`:**
   - Required on top-level responses, events and error envelopes.
   - Optional or omitted on embedded objects.
   - Never in viewer or operator requests. Worker requests (§9.16, §9.17) may carry `schema_version: 1`.
6. **`my_position`:** present iff `market` is present. "No position" means `side: null`, `stake_total_minor: 0`, `result: NONE`.
7. **Receipts:**
   - LOST: `payout_minor = 0`.
   - REFUNDED: `refund_minor` = the stake and `payout_minor = null`.
   - A POST replay and `GET /v1/operations/{id}` both return the stored original receipt with **`replayed: true`**. Live status comes from the snapshot or `wager.updated`.
8. **Amounts:** VOID pools keep their accepted totals. Stakes and custom top-ups must be multiples of their step.
9. **HTTP details:**
   - `VALIDATION_FAILED` `loc` is a Pydantic-style array with a `"body"` prefix.
   - Enroll returns 201 and ws-ticket returns 200.
   - An unknown method returns 405 with `NOT_FOUND`.
   - A rejected CORS preflight returns 403 with `FORBIDDEN`.
10. **Operator error codes:**
    - Opening while another market is nonterminal: `STALE_MARKET`.
    - Wrong state: `MARKET_CLOSED` with reason `STATE`.
    - Settling after `resolve_by`: `MARKET_CLOSED` with reason `DEADLINE`.
    - Settling a non-fixture market by hand: `VALIDATION_FAILED`.
    - No stream yet: `NOT_FOUND`.
    - Credit out of range: `INVALID_AMOUNT`.
    - An invite replay returns `invite_code: null`; the code is shown once.
11. **Audiences:** USER-audience events go only to the owning user's sockets. Operators inspect through `/v1/operator/*`.
12. **WebSocket:**
    - A missing or disallowed Origin closes with 4403.
    - `ready` carries `schema_version`, `stream_id`, `server_time_utc` and `event_hwm`.
    - The extension ID is pinned with a manifest `key`, and the CORS and WS allowlists use that `chrome-extension://` origin.
13. **P1-local shapes:** the top-up and redeem response shapes stay local to P1 until P6. The catalog is static.
14. **Version gaps:**
    - Every event carries the full aggregate state. Clients apply any event whose `aggregate_version` is greater than the one they hold for that (`stream_session_id`, aggregate).
    - Jumps of more than 1 are normal (for example, one settlement can bump a wallet several times) and are not gaps.
    - Clients refetch the snapshot only on (re)connect, on a run change, or on a server `resync` frame.
15. **Origins:** the allowlists contain exact origins only. By default that is `https://www.twitch.tv` for the WebSocket, plus the pinned `chrome-extension://<id>` from `FAZETIME_ALLOWED_ORIGINS`. Wildcards are not allowed.
16. **Operators (D30):** OPERATOR-role users cannot wager (403 `FORBIDDEN`), receive no seed grant, and are never raffle-eligible.

### 9.16 Media-worker contract (v1, for P3)

**Authentication and limits**
- `Authorization: Bearer fzk_…` (32 random bytes). The operator CLI issues it for role `MEDIA_WORKER`, and it is stored hashed. The worker reads it from `FAZETIME_WORKER_TOKEN`.
- Every `/v1/worker/*` route requires that role.
- JSON bodies are limited to 256 KB, and frame uploads to 300 KB JPEG.
- Errors use the §9.10 envelope, plus a worker-only code `STALE_EPOCH` (409) for data from an epoch that is not current.
- Media positions are milliseconds within the epoch's decoded stream, computed from sample counts, not from wall time. Transcript text is untrusted data. It is stored verbatim and never interpreted as instructions.

**Routes**

1. `POST /v1/worker/epochs`. Request:
   - `schema_version`, `stream_id`
   - `source_epoch` (`ep_` ID)
   - `source_kind`: `TWITCH_STREAMLINK`, `TWITCH_TAB_CAPTURE` or `TEST_FIXTURE`
   - `reason`: `PROCESS_START`, `PROCESS_RESTART`, `PTS_DISCONTINUITY`, `AFTER_GAP` or `ADAPTER_SWITCH`
   - `variant` (string or null), `host_id`, `started_at_utc`

   It is idempotent per `source_epoch`, and the epoch becomes the stream's current one. If a **Twitch-origin** market is OPEN, LOCKED or EVALUATING, that market becomes VOID with `SOURCE_GAP` (§9.4). Fixture-origin markets are exempt. The response is 201 when created and 200 on an identical retry.

2. `POST /v1/worker/heartbeat`, sent every 5 s. Request:
   - `schema_version`, `stream_id`
   - `source_epoch` (or null)
   - `worker_state` (a `MediaHealth` value)
   - `last_media_end_ms` (or null), `last_input_age_ms` (or null)
   - `asr_backlog_ms`, `queue_depth`, `gap_threshold_ms`
   - `host_id`, `host_wall_utc`

   Response: `{server_time_utc, stream_session_id, current_source_epoch}`.

3. `POST /v1/worker/evidence`, multipart:
   - part `meta`: `{source_epoch, sequence, kind: "FRAME", media_ms, width, height, sha256}`
   - part `file`: one JPEG, at most 300 KB

   Response: `{evidence_id, deduped}`. The API keeps frames in a bounded evidence directory: the last 600 frames or 30 minutes, plus any frame a market references.

4. `POST /v1/worker/observations`: `{schema_version, stream_id, source_epoch, items}`, with at most 50 items. Each item has:
   - `sequence`: monotonic per epoch. The dedupe key is (`source_epoch`, `sequence`).
   - `kind`: `TRANSCRIPT`, `FRAME` or `GAP`.
   - `media_start_ms` and `media_end_ms`. They are equal for a FRAME.
   - `captured_at_utc`: the worker host's wall time.
   - `source_wall_time_utc`: null. It is reserved until verified against an OBS clock (D29).
   - `quality_flags`: any of `PARTIAL`, `CLOSED_BY_GAP`, `CLOSED_BY_PTS_DISCONTINUITY`, `CLOSED_BY_STOP`, `AFTER_GAP`, `DRAINED_AFTER_STOP`, `LATE_SPLIT`, `PTS_UNKNOWN`, `IN_DISCONTINUITY_HOLE`, `LOW_CONFIDENCE`, `DEDUPED_OVERLAP`.
   - `transcript`: `{text (at most 1,000 chars), avg_logprob, no_speech_prob, model, language}`, or null.
   - `evidence_id`: required for FRAME.
   - `gap`: `{reason}`, or null.

   Response: `{accepted, duplicates, rejected: [{sequence, code}]}`. The server stamps `received_at_utc`.

5. **Health derivation (API).** Health is `LIVE` when all of the following hold for the current epoch:
   - a heartbeat arrived no more than 12 s ago;
   - it reported `worker_state=LIVE`;
   - `last_media_end_ms` advanced within the last 12 s.

   An `asr_backlog_ms` above 12,000 makes health at least `STALE`. The remaining thresholds are as in §9.4.

6. **Operator evidence:**
   - `GET /v1/operator/evidence?since=<received_at_utc>` returns recent observations and frame metadata.
   - `GET /v1/operator/evidence/{evidence_id}` returns the JPEG.
   - Both are operator-only.

7. **Proposals and resolutions:** `POST /v1/worker/proposals` and `POST /v1/worker/resolutions` are frozen in §9.17.

### 9.17 AI proposal, approval and resolution contract (v1, for P4/P5)

The model only proposes. The backend validates and decides. Model text is untrusted data.

**Template `H2H_WINNER_V1`**
- One announced head-to-head challenge between two named subjects, for example "Will FaZeGavin win the 1v1 against FaZeNeville?".
- `YES` means subject A wins and `NO` means subject B wins.
- Draws, no-contest, an abandoned fight, or an unclear winner fall under the cancellation conditions and lead to VOID.

**1. `POST /v1/worker/proposals`** (MEDIA_WORKER role)

Request: `{schema_version, stream_id, source_epoch, candidate}`, where `candidate` has:
- `candidate_id` (client UUID), `template_id`
- `episode_fingerprint`: the normalized subjects plus challenge, for example `h2h:fazegavin|fazeneville:minecraft-1v1`
- `question` (at most 200 chars)
- `yes {label, predicate}` and `no {label, predicate}`
- `subjects [A, B]`
- `evidence_ids`: 1–20 observation or evidence IDs from the current epoch
- `announced_at_media_ms`
- `suggested_close_in_s` and `suggested_resolve_in_s`
- `cancellation_conditions[]`
- `rationale` (at most 300 chars)
- `model` and `prompt_version`

The backend validates, in order. Each failure has the reject code shown:

| Check | Reject code |
|---|---|
| Schema, and the epoch is current | `STALE_EPOCH` |
| The evidence exists, belongs to this epoch, and was received within the last 90 s | `STALE_EVIDENCE` |
| No market in the run is nonterminal | `MARKET_BUSY` |
| `episode_fingerprint` is not already used or rejected in this run | `DUPLICATE_EPISODE` |
| Labels and predicates are paired by side | `UNPAIRED_SIDES` |
| Source health is `LIVE` | `SOURCE_NOT_LIVE` |

After those checks the backend clamps `close_in_s` to [45, 600] and `resolve_in_s` to [60, 900]. A `close_in_s` below 45 is rejected with `INSUFFICIENT_LEAD`.

What happens next depends on the AI mode:
- `OFF`: the candidate is dropped with `AI_OFF`.
- `SHADOW`: the candidate is stored, and is never opened.
- `APPROVAL`: it is stored as a pending candidate for the operator.
- `AUTOMATIC` (only when allowed, D32): it opens immediately as an `AI_AUTOMATIC` market.

Response: `{candidate_id, status: PENDING|SHADOW|OPENED|REJECTED, reject_code, market_id}`. It is idempotent on `candidate_id`.

**2. Operator candidate routes**
- `GET /v1/operator/candidates` returns pending, shadow and recent candidates, with evidence references and frame URLs.
- `POST /v1/operator/candidates/{id}/approve {operation_id, close_in_s?}` opens an `AI_APPROVED` market.
  - It re-runs every validation at commit, and checks the minimum lead against the real clock.
  - A candidate becomes `EXPIRED` once it is more than 60 s past `announced` receipt without approval.
- `POST /v1/operator/candidates/{id}/reject {operation_id, reason}`.

**3. AI mode**
- `POST /v1/operator/ai-mode {operation_id, mode: OFF|SHADOW|APPROVAL|AUTOMATIC}`.
- `AUTOMATIC` is refused with `FORBIDDEN` unless the server flag allows it.
- The current mode appears in `snapshot.modes.ai_mode`. The viewer UI does not display it (D31); the operator console does.

**4. `POST /v1/worker/resolutions`** (MEDIA_WORKER role)

Request: `{schema_version, stream_id, source_epoch, resolution}`, where `resolution` has:
- `resolution_id` (client UUID)
- `market_id` and `rules_version`
- `decision`: `YES`, `NO`, `WAIT` or `UNRESOLVABLE`
- `evidence_ids` (at least 1)
- `media_interval {start_ms, end_ms}`
- `predicate_support {YES: bool, NO: bool}`
- `contradictions[]`
- `reason` (at most 300 chars)
- `model` and `prompt_version`

The backend validates:
- The market is `EVALUATING` and `rules_version` matches; otherwise `STALE_MARKET`.
- `source_epoch` equals the market's lock epoch. An epoch change has already voided the market per §9.4.
- All the evidence comes after `lock_media_ms`.
- `predicate_support` agrees with the decision: YES needs YES-only support, and NO needs NO-only support.

Then the decision is handled by mode:

| Decision | `AUTOMATIC` | `APPROVAL` |
|---|---|---|
| `WAIT` | Recorded only | Recorded only |
| `YES` / `NO` | Settles | Stored as a suggestion awaiting the operator |
| `UNRESOLVABLE` | `VOID UNRESOLVABLE` | Stored as a suggestion awaiting the operator |

Late or duplicate resolutions for a terminal or other market are recorded and ignored. Response: `{resolution_id, status: RECORDED|SETTLED|VOIDED|PENDING_APPROVAL|IGNORED, reason}`.

**5. Operator resolution routes**
- `GET /v1/operator/resolutions?market_id=` lists the stored suggestions.
- `POST /v1/operator/resolutions/{id}/approve {operation_id}` settles or voids the market exactly as suggested.
- `POST /v1/operator/markets/{id}/settle` stays fixture-only. For AI markets the operator either approves a suggestion or voids with a reason (`OPERATOR_CANCELLED`).
- At `resolve_by_utc`, the sweeper voids the market with `RESOLUTION_TIMEOUT` (§9.3).

**5b. Worker market view (added 2026-11-14 after the P4/P5 worker review).** `GET /v1/worker/market?stream_id=` (MEDIA_WORKER role) returns `{schema_version, market: {market_id, rules_version, state, origin, question, yes_label, no_label, close_at_utc, resolve_by_utc, lock_source_epoch, lock_media_ms} | null}`. That is the run's nonterminal market, or null. The resolver uses it to learn the lock position. It has no balances and no user data.

**5c. Evidence reference format.** A frame is cited by its `evd_` ID. A transcript observation is cited as `<source_epoch>:<sequence>`, and only once the API has accepted it. The backend resolves both kinds and rejects unknown references with `STALE_EVIDENCE`.

**5d. Takes and episodes.** Each recording take uses the same episode fingerprint, so the operator must **reset the run between takes**. Otherwise the second take is rejected as `DUPLICATE_EPISODE`.

**5e. P4/P5 implementation rulings** (2026-11-14, coordinator, from the backend report):
- **Proposal responses:** a rejection is recorded and returned with HTTP 201 and status `REJECTED`, plus `reject_code`. A replay returns 200. A schema violation is 422 and is not recorded.
- **Added values:** reject code `OPERATOR_REJECTED`, response status `EXPIRED`, and an `id` field (`cnd_`/`rsl_`). Operator routes accept either the server ID or the client UUID.
- **Evidence freshness:** the 90 s limit is rechecked at approval. The operator must therefore approve within 90 s of the oldest cited evidence and within 60 s of the candidate's receipt.
- **Close anchoring:** `close_at` is the candidate's receipt time plus the clamped `close_in_s`, so a slow approval never extends betting. An operator override counts from approval and stays within [45, 600].
- **Episodes:** an episode is consumed by a PENDING, SHADOW, OPENED, EXPIRED or operator-rejected candidate. A validation rejection does not consume it, so the worker retries with a new `candidate_id`. Fingerprints are canonicalized: lowercased, with the h2h pair sorted.
- **Approval error mapping:** EXPIRED and INSUFFICIENT_LEAD → 409 `MARKET_CLOSED` (DEADLINE); MARKET_BUSY → 409 `STALE_MARKET`; SOURCE_NOT_LIVE → 409 `SOURCE_STALE`; STALE_EPOCH → 409; UNPAIRED_SIDES → 422. Approval in OFF or SHADOW mode → 403. `details.reject_code` always carries the §9.17 code.
- **Resolutions:** a validation failure is IGNORED with a reason code. Evidence and `media_interval.start_ms` must be ≥ `lock_media_ms`. In AUTOMATIC mode, a YES/NO that comes with contradictions becomes `PENDING_APPROVAL` instead of settling. In SHADOW or OFF mode a decision is RECORDED only. AI resolutions act on AI-origin markets only.
- **Viewer payloads:** `resolution_reason` is null for viewers and shown only to the operator, because it is untrusted model text (D31). Public `opening_evidence_ids` and `resolution_evidence_ids` carry frame `evd_` IDs only.
- **AI mode:** the code default is OFF. Deployment sets `FAZETIME_AI_MODE_DEFAULT=APPROVAL` (D32). A mode change emits `stream.updated`, and a reset keeps the mode.

**6. Persistence.** Store candidates and resolutions with the model, prompt version, evidence IDs and validation result, as `InferenceTrace` rows, with no secrets. Public market fields `criteria.YES` and `criteria.NO` carry the predicates (side-keyed, §9.3).

### 9.18 Stripe test top-up contract (v1, for P6)

The adapter is in `services/api/fazetime_api/integrations/`, pinned to `Stripe-Version: 2026-10-28.endive`. Evidence: `spikes/p6-stripe/README.md`.

**IDs and enums**
- New ID prefix `top`.
- `TopupStatus`: `CREATED | PENDING | CREDITED | FAILED | EXPIRED`.
- `payment_mode` is `STRIPE_TEST` only when both the test secret key (`sk_test_` or `rk_test_`) and `STRIPE_WEBHOOK_SECRET` load. Otherwise it is `UNAVAILABLE`.

**`POST /v1/topups`**
- Request: `{operation_id, amount_minor}`, with `extra="forbid"`. Amounts follow §9.2: presets 500, 1,000 or 5,000, or a custom amount from 500 to 10,000 in steps of 100.
- Response, `TopupReceipt`:
  - `schema_version`, `topup_id`, `operation_id`, `amount_minor`
  - `currency: "usd"`, `status`, `payment_mode`
  - `checkout_url`: only while the top-up is `PENDING`. The client opens it in a new tab. It is never logged.
  - `checkout_expires_at_utc`
  - `replayed`
  - `stream_session_id`: the run the top-up credits. Additive. It lets the UI explain a credit that landed in an archived run.
- Errors:

| Code | When |
|---|---|
| `INVALID_AMOUNT` | Amount outside §9.2 |
| `IDEMPOTENCY_CONFLICT` | Same operation_id, different request |
| `RATE_LIMITED` | Too many requests |
| `FORBIDDEN` | Bots and operators (D30) |
| `CAPABILITY_UNAVAILABLE` | Payments not configured |
| `INTERNAL_ERROR` | The row stays `CREATED`. Retry with the same `operation_id` |

- The server never holds a database transaction during network I/O.

**`GET /v1/topups/{id}`**
- Returns only the caller's own top-up.
- While the top-up is `CREATED` or `PENDING`, the server reconciles with Stripe (throttled to once per 3 s per top-up) and applies the result through the same fulfillment planner.
- A return URL or a browser claim never credits.

**`POST /v1/webhooks/stripe`**
- Takes the raw body. `Stripe-Signature` is verified with a 300 s tolerance, and test mode only: any `livemode=true` event is rejected.
- Valid duplicates, ignored types and mismatches all get 2xx. Mismatches are flagged for review and grant no funds.
- Credits are posted once under `source_key = stripe_topup:<topup_id>` with reason `STRIPE_TEST_TOPUP`.
- `provider_receipts` is unique on (`provider`, `event_id`). `topups` is unique on the session ID and the PaymentIntent ID.
- Payload hashes are stored instead of raw bodies.

**Rules**
- Credits always post to the top-up's own run, even if that run is ARCHIVED (§9.5). A reset never touches pending top-ups.
- A late credit never backdates a wager; the user must confirm a new wager.
- `wallet.changed` is emitted on credit.
- The success and cancel URLs come from server config. Their query parameter (`fazetime_topup=<id>`) is only a polling hint. `fazetime_result=cancel` only changes the wording shown; status always comes from the server.
- Logging: the Stripe client logs at most the `cs_test_` prefix plus 4 characters of a session ID, never the full ID or the Checkout URL.
- The webhook route is fed by the Stripe CLI: `stripe listen --device-name fazetime-api --forward-to <API>/v1/webhooks/stripe`, with the key passed through the environment.


### 9.19 Generic AI market contract (v1 additive, for D37/D39; 2026-11-15)

This is an additive change to §9.17, recorded by the coordinator before integration (D37). `H2H_WINNER_V1` and every §9.17 route keep working unchanged. The design comes from `reports/Game agnostic stream prop bets.md`, and fixture evidence is in `docs/evidence/p4/P4-generic-fixture-replay.md`.

**Template `GENERIC_BINARY_V1`.** One yes/no question about one unit of play (an "episode": a game, round, level, match or run, in any game), or about speech heard during one. The worker's catalogue has four kinds:

| `kind` | Question shape (rendered by worker code, never by the model) | `params` |
|---|---|---|
| `EPISODE_OUTCOME` | "Will the streamer {win_verb} this {unit}?" | `win_verb` ∈ `win`, `clear`, `complete`, `beat`, `survive`, `finish` |
| `END_VALUE_AT_LEAST` | "Will {label} be at least {threshold} when this {unit} ends?" | `label` (1–40 chars), `threshold` (number) |
| `SAY_PHRASE` | 'Will "{phrase}" be heard on stream after betting closes, before this {unit} ends?' (the viewer panel shows only the question, so it states its own window) | `phrase` (1–3 words, letters and apostrophes) |
| `DURATION_OVER` | "Will this {unit} last longer than {m:ss}?" | `duration_s` (integer, 30–3600) |

**1. Candidate changes** (`POST /v1/worker/proposals`). The body is the same as in §9.17, with these differences:
- `template_id`: `"GENERIC_BINARY_V1"`.
- `subjects`:
  - 0 or 1 entries for `GENERIC_BINARY_V1`: the streamer, or one side named on screen;
  - still exactly 2 for `H2H_WINNER_V1`.
- `generic`:
  - **Required** for `GENERIC_BINARY_V1`, and **forbidden** for `H2H_WINNER_V1`.
  - Shape: `{spec_version: "gen-1", kind, unit, params, episode_start_media_ms, success_cue, failure_cue}`.
  - `unit` is 1–20 chars, such as "level".
  - `episode_start_media_ms` is an integer ≥ 0 in the candidate's source epoch.
  - The two cues are each at most 160 chars. They are untrusted model text, stored inert, and never shown to viewers.
  - `params` is exactly the keys in the table for its `kind`.
- `episode_fingerprint`: `gen:<source_epoch>:<episode_start_media_ms>:<kind lowercased>`. It is consumed per run exactly as in §9.17 (`DUPLICATE_EPISODE`).
- `yes`/`no`: labels `Yes`/`No`. The predicates are rendered from the kind by worker code.

**2. Validation.** The order and reject codes are as in §9.17, except the sides check. For `GENERIC_BINARY_V1`, `UNPAIRED_SIDES` is returned unless all of these hold:
- the labels are non-empty and distinct;
- the predicates are non-empty and distinct, case-insensitively;
- `generic.kind` and its `params` are valid;
- the fingerprint starts with `gen:` and ends with `:<kind lowercased>`;
- `subjects` has at most 1 entry.

A missing, extra or malformed `generic` object is a schema error, HTTP 422, and is not recorded.

**3. Storage.** Migration `0006` adds `ai_candidates.generic_json TEXT` (nullable; NULL for H2H). Candidates keep `template_id`.

**4. Timing (D39), for all templates.**
- `ai_close_min_s` becomes **35**: `close_in_s` is clamped to [35, 600], and below 35 is `INSUFFICIENT_LEAD`.
- `min_lead_ms` stays 30 000. The `resolve_in_s` clamp is unchanged at [60, 900].
- The worker suggests `close_in_s = 35` and `resolve_in_s = 335` (35 s of betting plus a 300 s horizon).

**5. Approval anchoring.**
- The API's semantics are unchanged: `close_at` is receipt plus `close_in_s`, and an operator `close_in_s` override counts from approval.
- **When approving a `GENERIC_BINARY_V1` candidate, the operator console sends `close_in_s` equal to the candidate's clamped `close_in_s`,** so viewers get the full window from approval.
- The console's H2H behaviour is unchanged.

**6. Read-side additions.**
- `GET /v1/worker/market` (§9.17 5b) adds:
  - `template_id`: from the market's originating candidate; null for fixture markets.
  - `generic`: the stored object, or null.
- `GET /v1/operator/candidates` adds `template_id` (already stored) and `generic` to each candidate.
- Viewer payloads are unchanged: the question, the labels and `criteria.YES`/`criteria.NO`. `generic` is never sent to viewers.

**7. Worker resolution semantics.** The `POST /v1/worker/resolutions` route is unchanged; this item fixes the worker's evidence rules for generic markets.
- **Two voids apply to every kind:**
  - A worker-side fairness margin of **M = 20 s**: the worker sends `UNRESOLVABLE` when the decisive evidence (the episode end, or the phrase occurrence) is at or before `lock_media_ms + 20 000`.
  - No result by `resolve_by`: the sweeper voids, unchanged.
- **`SAY_PHRASE`:** decided by worker code.
  - A regex over the unprimed transcript after `lock_media_ms + 20 000`, until the episode ends.
  - YES cites the transcript observation.
  - NO needs the episode end with the transcript covering the window.
- **`DURATION_OVER`:** decided by worker code from the episode's start and end media times. It voids within ±15 s of the line, or when the end was not seen as a result.
- **`EPISODE_OUTCOME` and `END_VALUE_AT_LEAST`:**
  - Two extraction reads, by different models (`gemini-3.5-flash-lite` and `gemini-3.1-flash-lite`), on different post-end frames. Code then decides.
  - **`EPISODE_OUTCOME`** needs both reads to agree, plus a printed result word: the generic lexicon, or a word from the frozen cue.
  - **`END_VALUE_AT_LEAST`** needs the two values to agree. It voids within one display unit of the threshold.
  - Disagreement returns `UNRESOLVABLE`.
- All cited evidence is at or after `lock_media_ms`, as §9.17 requires.

**8. Implementation rulings** (2026-11-15, coordinator, from the API engineer's report):
- **Malformed `generic` is a schema error.** Wrong keys or values give 422, not recorded. The item 2 kind/params check is a backstop, re-run on the stored object at approval.
- **All seven `generic` fields are required.** The cues may be empty strings.
- **`subjects` stays required.** Send `[]` for a generic candidate with no named subject.
- **Labels and predicates are compared as H2H compares them:** case-insensitively, ignoring punctuation and spaces. A label with no letters or digits counts as empty.
- **`phrase`:** 1–3 ASCII words separated by single spaces, letters and apostrophes only, at most 80 chars.
- **`threshold`:** an integer or finite float. Booleans and strings are rejected.
- **Fingerprint check:** only the `gen:` prefix and the `:<kind>` suffix are checked, on the lowercased form. The middle parts are not matched against `source_epoch` or `episode_start_media_ms`.
- **Storage guards:** migration 0006 adds a JSON check of at most 4096 bytes on `generic_json`. Triggers require it for GENERIC and forbid it for every other template, and make `template_id` and `generic_json` immutable.
- **Worker-side detection slack (end-to-end finding):** for kinds whose episode end comes from the screen, the worker adds an end-detection slack of 15 s (`FAZETIME_AI_END_DETECTION_SLACK_S`) to the fairness margin. It voids when the detected end is at or before `lock_media_ms` + 20 000 + 15 000, because a result screen trails the decisive moment (in Peggle, by about 12 s). The proposer's minimum expected lead after lock is 40 s.
- **Reader fallback (end-to-end finding):** if a reader's model errors or is cooling down, the other reader model reads that reader's own frames. Two agreeing reads on different frames are still required.
- **Viewer isolation:** viewer snapshots, `/v1/me` and PUBLIC/USER events never carry `generic`, the cues or `template_id`. This is tested.

### 9.20 AI activity feed, result ETA and stream context (v1 additive, owner requests 2026-11-15 ~03:00 CT)

These additions are for operator visibility and viewer UX. None of them changes money, market state or settlement rules.

**1. AI activity feed: WITHDRAWN** (owner, ~03:10 CT: not worth the build time). Nothing below in this item is implemented. The proposer's reasons stay in the worker's `ai_trace.jsonl` on the Pi.

~~AI activity feed: the "thoughts" the advanced console shows.~~
- **`POST /v1/worker/ai-activity`** (MEDIA_WORKER).
  - Body: `{schema_version: 1, stream_id, source_epoch, items[1..50]}`.
  - Each item: `{at_utc, media_ms|null, role: OBSERVER|PROPOSER|RESOLVER|STREAM, outcome (≤40 chars, e.g. ABSTAIN, REJECT:INSUFFICIENT_LEAD, POSTED:PENDING, OBSERVED, READS), kind|null (generic kind), text (≤400 chars), fields (flat object, ≤12 keys, scalar values ≤120 chars)}`.
  - `text` and `fields` are untrusted model output: the proposer's `reason`, the observer's `notable` notes and result text, or the reader texts. They are stored inert.
  - Response `{accepted}`. Rate: at most one request per 2 s per worker; the worker batches.
- **Storage:** the API keeps the newest 300 items per stream in memory only. A restart clears them. No DB table.
- **`GET /v1/operator/ai-activity?limit=100`** (operator only) returns `{items}`, newest first.
- **Never sent to viewers.**

**2. Expected result time.**
- `generic` (§9.19) gains an optional `expected_result_in_s`: an integer from 0 to 900, or null. It is the worker's estimate of seconds from betting close (lock) until the result is known. It comes from the proposer's `seconds_to_outcome` minus the betting window, or from this stream's earlier round durations when there are any.
- The public market view adds **`expected_result_at_utc`** = `close_at_utc` + `expected_result_in_s` (null when unknown, and for H2H and fixture markets).
- **Viewer and console behaviour:** once the market is LOCKED or EVALUATING, and that time has passed with no result yet, the UI shows a pending-result state: **"AI is watching for the result…"** with a subtle animation. This is truthful: the observer keeps sampling the stream. The UI never claims a decision is being made before one exists.

**3. Stream context.**
- The worker reads the Twitch title, category and author from Streamlink's `--json` metadata, at start and then every 5 minutes.
- It adds them to the observer and proposer prompts as **untrusted** context ("Stream title (untrusted): …; Category: …"). The category may seed the activity name.
- Each change is posted as a `STREAM` activity item, so the console shows them.
- The Twitch "About" description is not available from Streamlink and is out of scope.
