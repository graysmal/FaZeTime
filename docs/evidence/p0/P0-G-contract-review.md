# P0-G independent contract review (reviewer subagent)

- Phase / task / base SHA / date: P0-G / independent review of CONTRACTS, ECONOMICS, ARCHITECTURE / `6c05030` / 2026-11-14
- Mode: read-only document review. No code exists, and nothing was executed
- Reviewer recommendation: **revise** before P1/P2 run in parallel
- Coordinator spot-check: the cited lines in DEMO_RUNBOOK:37, AI_PIPELINE:26 and :87, and PROJECT_PLAN:110 match the findings
- Disposition: PENDING. To be merged with the planner's P0-G freeze proposal into CONTRACTS v1

## Findings

| ID | Sev | Defect (location) | Required fix |
|---|---|---|---|
| H1 | High | OPEN→LOCKED and LOCKED→EVALUATING have no trigger, owner, time field or restart behaviour (CONTRACTS:29,51; ECONOMICS:29,54,57) | Add `close_at_utc` (exclusive), `resolution_deadline_utc`, and `lock_media_ms` + `source_epoch`. An API-owned durable sweeper performs LOCK, one-sided VOID and deadline VOID, and runs again at startup. Recheck feasibility when DRAFT→OPEN commits. VOID if start or decisive evidence comes before lock + viewer-lead margin |
| H2 | High | The one-sided pool "may" VOID (CONTRACTS:29) but "must" VOID (ECONOMICS:54); settlement has no W>0 guard | Change to "must". Settlement asserts 0<W<T; otherwise VOID + refund in the same transaction |
| H3 | High | Display labels are not bound to YES/NO predicates (CONTRACTS:77,91), so payouts can go to the wrong side | Use a side-keyed `{YES:{label,predicate},NO:{label,predicate}}` everywhere. The validator rejects mismatched pairs |
| H4 | High | Idempotency scope contradicts itself (CONTRACTS:17 per actor vs ECONOMICS:31 implying global). Hash fields, recording of business rejections, retention and the receipt lookup route are undefined. Operator mutations have no operation_id | Unique on (actor, op_type, operation_id) with a canonical payload hash. Record final outcomes, not transient errors. Keep keys for the life of the DB. Add a route for users to look up their own operations. Add operation_id on every operator mutation |
| H5 | High | The reset policy is referenced but never defined (CONTRACTS:105; ECONOMICS:64; ARCHITECTURE:94; DEMO_RUNBOOK:37): are wallets scoped per user or per user+run, and where do late Stripe credits land | Write and freeze the reset/wallet-scope policy before the P2 schema |
| H6 | High | Gap/epoch handling passes between documents and is never defined. Health states have no thresholds or owner (CONTRACTS:35; INGESTION:61; AI_PIPELINE:26,87) | The API derives health from `received_at_utc` + worker heartbeat with numeric thresholds. Any non-LIVE state or epoch change between OPEN and accepted decisive evidence → VOID. The wager guard checks health and epoch |
| M1 | Med | The raffle pause changes frozen market rules (ECONOMICS:68 vs CONTRACTS:33) | Either a recorded OPEN→LOCKED disclosed before opening, or block new markets only. Check it inside the transaction |
| M2 | Med | The draw wake-up after the last market settles is not durable; EMPTY/disarm semantics are undefined (CONTRACTS:39) | Snapshot/draw in the transaction that makes the market terminal, or insert a unique durable job |
| M3 | Med | An interval off-by-one survives the 0 / total−1 tests (ECONOMICS:70,80) | Half-open intervals, `secrets.randbelow(total)`, drop zero-weight users, test `end_i−1` and `end_i` |
| M4 | Med | Call jobs can be duplicated through at-least-once `raffle.drawn`; auto-retry from UNKNOWN can dial twice (CONTRACTS:37,60) | Create the CallJob in the draw transaction, unique on (draw_id, kind). No auto-retry from UNKNOWN until P0-E verifies Chert's dedupe |
| M5 | Med | Two definitions of the resolution deadline (PROJECT_PLAN:158 "void or operator review" vs ECONOMICS:56 "VOID") | Pick one, and say whether it compares evidence media time or commit time |
| M6 | Med | Role and bot flag are not bound to the invite code; single use is not enforced; session recovery is undefined (CONTRACTS:45,72) | Bind role, bot flag and verification status to the code on the server. Conditional-update single use. Reject unknown fields |
| M7 | Med | No max stake/top-up/balance; estimate formula and rounding undefined (CONTRACTS:24; ECONOMICS:15,50) | Freeze MAX_STAKE, MAX_TOPUP and MAX_BALANCE. Do payout arithmetic in Python ints. Estimate = `floor(s*(T+s)/(W_side+s))` |
| M8 | Med | Fields P1 needs are not named: per-side totals, `close_at_utc`, estimate, available vs escrow, receipt, outcome, `void_reason`, own stake/payout. "Unresolved" banner has no state. Can a user bet both sides? | Name them in the v1 schema. Define the "unresolved" display. Decide the both-sides rule |
| L1–L7 | Low | Untyped stable sort ID; unclamped model deadline; presence not keyed (user, device); iframe bridge can't tell content-script messages from page messages by origin; Pi clock step; immutability only in prose; "quote ID" vs intent/nonce drift | Type the IDs; clamp the deadline; key presence on (user, device); use a frame-held secret; require clock sync before OPEN; add conditional UPDATEs and triggers; unify naming |

## Must freeze before P1/P2 parallel work (reviewer list)

1. The wager version check uses an immutable rules version. `market` and `pool` are separate event aggregates.
2. Market time fields, who performs lock and what triggers it, a VOID trigger table + `void_reason` enum, and what DRAFT means.
3. Side-keyed options (H3).
4. Idempotency scope, hash fields, recorded outcomes, retention, and a lookup route.
5. Reset and run-scoped wallet policy.
6. Gap/epoch rule and health thresholds.
7. Amount limits and the estimate formula.
8. Invite code binds role and bot flag.
9. Snapshot and receipt schemas with null handling, plus a failure code for paused acceptance.
10. Owner confirmation of D11 and D12 (P0 question 4).

## Reviewed with no issues

- The ECONOMICS §4 worked example recomputes exactly: 167/333/500 = 1000.
- The remainder rule conserves cents for any W>0.
- Raffle weighting is consistent across P0 question 4, P8, ECONOMICS, D07, D11 and DEMO_RUNBOOK.
- Bots are excluded from the raffle denominator. Settlement and void are mutually exclusive. The outbox is written in the same transaction.
- Stripe dedupe covers both the event and the payment object. A return URL is never wallet authority. The deadline is rechecked after BEGIN IMMEDIATE.
- Wallet routes use the session user. WS tickets are one-use. The call capability is bound to the CallJob.
