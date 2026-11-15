# Shared contract specification

Version: proposed v1. This is a design contract to freeze in P0, not generated OpenAPI or application code. [PROJECT_PLAN](../PROJECT_PLAN.md) is authoritative. The coordinator owns contract edits; implementers propose changes before changing both sides independently. Backend Pydantic/OpenAPI will become the executable schema; generated TypeScript types should derive from it.

## 1. Canonical vocabulary

Use these exact wire names after P0 review. Narrative references to run/session/epoch map here; do not create duplicate competing identifiers.

| Field | Meaning |
|---|---|
| `schema_version` | Envelope contract version; initially 1 |
| `stream_id` | Stable internal identity for the single Twitch channel |
| `stream_session_id` | One explicit demo/broadcast accounting run; also called demo run in prose |
| `source_epoch` | New ID on ingest restart, seek/loop, adapter change or discontinuity recovery; formerly described as ingest session |
| `sequence` | Monotonic integer within source epoch |
| `market_id`, `market_version` | Immutable market identity and monotonic state version |
| `operation_id` | Durable client-generated economic idempotency key, scoped to authenticated actor/type |
| `event_id` | Durable domain-event cursor; not the provider webhook event ID |
| `amount_minor` | Integer demo currency units, 100 units per displayed demo dollar |
| `server_time_utc` | RFC 3339 UTC timestamp from authoritative API; display local time separately |
| `media_start_ms`, `media_end_ms` | Decode positions in named source epoch, not epoch/Unix time |
| `received_at_utc` | Backend receipt time; distinct from when action happened at source |

All records that can outlive a reset carry `stream_session_id` where applicable. Phone/call identity uses opaque internal user IDs, never an LLM-inferred name. Integers crossing TypeScript must stay within JSON safe-integer limits; reject unreasonable amounts well below that bound.

## 2. State machines

Market states: `DRAFT`, `OPEN`, `LOCKED`, `EVALUATING`, `SETTLED`, `VOID`.
Normal transitions: DRAFT→OPEN→LOCKED→EVALUATING→SETTLED. Any accepted but not terminal market can become VOID under its fixed cancellation policy. Empty/one-sided pools may become VOID at lock. A rejected candidate is not a market and has no ledger effects. No reopen, post-bet question edit, or terminal-to-terminal change.

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
| `POST /v1/wagers` | operation_id, market_id/version, side YES/NO, amount_minor; atomic acceptance or typed failure |
| `POST /v1/topups` | operation_id + amount_minor; server-fixed currency and allowlisted Stripe return path; returns Checkout URL/intent |
| `GET /v1/topups/{id}` | Own authoritative fulfillment status; useful when redirect/webhook lag |
| `POST /v1/redemptions` | operation_id + fixed catalog item ID; transactionally debit, generate demo code once |
| `GET /v1/raffle` | Current eligible weight/total, snapshot when drawn, winner display label; no full phone lists |

Never accept client-supplied user_id as authority for a wallet action. Market version mismatches yield `STALE_MARKET`; the client refreshes and obtains new user intent where needed. UI estimates are not accepted settlement terms. To avoid spurious failures from pool updates, distinguish market state/rule version from pool/event version, or document exactly which version the wager precondition checks. Freeze that choice before implementation.

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

