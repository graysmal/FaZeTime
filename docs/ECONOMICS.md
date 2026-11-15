# Demo wallet, pari-mutuel settlement, and raffle accounting

This is a design specification, not an implemented system. The canonical execution order, phase gates, and progress belong to [PROJECT_PLAN.md](../PROJECT_PLAN.md), especially phases 2, 5, 6, 8, 9, and 11. Do not maintain a second phase checklist here. Integration boundaries appear in [INTEGRATIONS.md](INTEGRATIONS.md).

## 1. Confirmed economic model

The owner selected a hackathon demonstration using simulated balances, Stripe test mode, pari-mutuel payouts, and **no pool fee**. There is no cash withdrawal, real payment, actual merchandise redemption, or prize fulfillment. The two team iPhones demonstrate the proposed creator interaction. UI dollar notation represents demo dollars and must be labeled accordingly.

Raffle probability is each eligible user's cumulative qualifying wager spend during the current stream session divided by all eligible users' qualifying spend. Use integer cents directly as weights. There is no ticket conversion, minimum ticket threshold, multiplier, payout-based bonus, or separate points economy. Spend means stake committed to a settled, nonvoid market, independent of whether that stake won. Top-ups are not spend. Re-wagering prior winnings creates additional spend if the later wager settles normally; this follows cumulative wager volume rather than net loss. Do not describe this metric as money deposited or money lost.

Scripted bots may wager using separately seeded demo funds and participate normally in market pools and payouts. They never receive raffle weight and never trigger calls. Their pool contributions must be identified as simulated in the operator interface. Bots are not hidden evidence of real fan engagement or revenue.

## 2. Units and account boundaries

All economic amounts use nonnegative integer minor units, with a single demo currency. Store 500 for five demo dollars. Never calculate balances, pool ratios, payouts, or raffle weights using binary floating-point arithmetic. Display formatting is a presentation concern. The wager endpoint rejects zero, negative, fractional-cent, excessive, and malformed amounts before changing state.

Use a small append-only ledger that can explain every balance. Recommended accounts are user available balance, one escrow account per market, a demo-funding source, and a redemption sink. A complete enterprise accounting framework is unnecessary, but every movement needs a stable operation ID, reason, source reference, amount, timestamp, and equal debit/credit effect. A materialized balance is a cache of ledger movements, not an independently editable truth.

Initial phase-1 local mocks are deliberately disposable. Phase-2 server seed grants are labeled demo funding. Phase-6 successful Stripe test payments generate a distinct `stripe_test_topup` source. Never represent a seed grant or mock dialog as a real Stripe integration. Coupon generation moves demo balance to the redemption sink once and produces a nonfunctional code; the interface must not imply an actual retailer accepted it.

## 3. Wager acceptance and time

Use the market state machine:

`DRAFT → OPEN → LOCKED → EVALUATING → SETTLED or VOID`.

A rejected draft never becomes a financial event. A locked market never reopens because a browser clock, voice transcript, payment result, or delayed model answer claims the bet began earlier. The server's acceptance time and persisted market version determine eligibility. Client countdowns are estimates for display.

Authenticate first, then acquire SQLite write access with BEGIN IMMEDIATE or the equivalent verified transaction pattern from ARCHITECTURE.md. Inside the transaction resolve the idempotency key, check the market/session and state, recheck the server deadline after write access is acquired, validate side/stake, conditionally debit sufficient available balance, credit escrow, insert the wager and persist its outgoing event. SQLite has a single writer; do not assume SELECT FOR UPDATE or per-row locks. If the owner later selects PostgreSQL, document its row-lock ordering separately. Verify the actual selected engine with concurrent requests.

A retry with the same key and same payload returns the original receipt. Reusing that key with a different amount, user, side, or market is a conflict. Two independent operations can both be valid intentions, but they cannot both spend the same balance. Do not use an in-process lock as the only protection against concurrent workers or restart.

Do not allow wager editing, cancellation, cashout, or side switching in this demo. If the UI permits another wager, it is a new operation and a new stake, accepted under the same current deadline. One open market per stream remains the narrow scope.

## 4. Exact settlement

Before settlement, acquire the selected database's write transaction, conditionally claim the market's nonterminal state/version, and establish the accepted wager set. Let `T` be total accepted stake, and `W` total accepted stake on the winning side. Fee is exactly zero, so the distributable pool is `T`.

For each winning wager with stake `s`, compute:

- Initial gross payout: integer division `s × T / W`, rounded down.
- Remainder numerator: `(s × T) mod W`.
- Unallocated cents: `T` minus the sum of initial gross payouts.
- Give one additional cent to each winner in descending remainder order until no cents remain; break equal remainders by stable wager ID ascending.

Persist the algorithm version and final payout per wager. Sorting and tie-breaking must be stable across process restarts. A payout includes the returned principal. Net profit is gross payout minus original stake; never add principal to gross a second time.

Worked example: total pool is 1,000 cents. Winning wagers are A=100 cents, B=200 cents, and C=300 cents, so `W=600`. Initial payouts are 166, 333, and 500 cents, totaling 999. Their remainder numerators are 400, 200, and 0. A receives the remaining cent. Final payouts are 167, 333, and 500, totaling exactly 1,000. Net profits are 67, 133, and 200 cents. The 400 cents staked on the losing side receives zero. The ledger has moved the entire escrow balance to winners without creating or destroying a cent.

Pool proportions are participation measures, not model-estimated probabilities. The UI may show an estimated gross payout calculated from the current pool including the proposed stake, but must label it estimated until the market locks. Later accepted bets can change it. Do not promise fixed odds or a guaranteed return from a pre-close quote.

Recommended edge semantics for this demo are intentionally explicit:

- If either side has zero accepted stake at lock, VOID the market and refund every stake. This avoids a trivial one-sided pool and the undefined case of no winning stake.
- If there are no wagers, mark the economic event void/empty with no transfer and no raffle weight.
- If evidence does not support an unambiguous result before the configured resolution deadline, VOID and refund once.
- If the stream restarts, the event definition becomes invalid, or its outcome occurred before safe closure, VOID instead of inventing a result.
- A void market contributes no cumulative raffle spend and no fee.

For the demo's small number of users, settlement can atomically write every payout and mark the market terminal in one transaction. Unique operation IDs such as one settlement ID and one payout source per wager prevent duplicate effects. A crash before commit leaves no settlement; a crash after commit is recovered as completed. Broadcast notifications follow persisted outbox events and cannot determine whether settlement happened.

## 5. Raffle snapshot and draw

Each stream session has an explicit immutable ID. A prerecorded video looping does not silently reset accounting. The operator must begin a new demo session explicitly, with new market and raffle IDs and isolated balances/records as the reset policy specifies.

For an eligible real demo user `u`, calculate `weight(u)` as the sum of that user's accepted stake cents in SETTLED, nonvoid markets belonging to this session. Exclude bot accounts, seed grants, deposits, coupon redemption, failed wagers, refunded/voided wagers, and previous-session activity. A winning user's weight is its original stake, not its payout. Aggregate directly in cents; never round each wager into tickets.

When the operator arms a draw and the finalized transcript detects the configured “Raffle” cue, first pause new market creation and new wager acceptance for the draw boundary. If any wager remains unresolved, defer the draw until the associated market settles or voids. Do not let a late settlement change an already advertised snapshot. Snapshot eligible users and weights transactionally after the unresolved check. Persist the snapshot hash, session ID, raffle ID, and trigger evidence.

If total weight is zero, produce a no-eligible-entries result and do not call anyone. Otherwise draw a cryptographically secure uniform integer from zero inclusive to total weight exclusive. Sort users by stable ID, assign cumulative intervals, and select the interval containing the draw. Store the draw value, total, chosen user, and algorithm version. An implementation should use a standard bounded secure-random facility, not `random()` or modulo reduction of an arbitrary random byte string.

Example: users wagered 1,000, 2,000, and 7,000 qualifying cents. Their probabilities are 10%, 20%, and 70%. A bot's 9,000 cents may have affected market payouts but contributes nothing to this denominator.

Selection and calling are separate durable operations. A failed or unanswered call does not change the winner or trigger a redraw. Preserve “winner selected; call pending/failed” and use the approved manual fallback. Do not silently exclude a real winner because their phone is temporarily unavailable. Prepare the demo accounts and devices before the draw. A scripted rehearsal winner is allowed only in an explicit visible rehearsal mode and cannot masquerade as a random draw.

## 6. Verification obligations

Tests should prove meaningful invariants: sum of final payouts equals escrow; a repeated close/settlement does not duplicate credits; duplicate payment events grant one top-up; two concurrent wagers cannot overspend; late browser/voice wagers fail; void restores original stakes once; one-sided pools void; rounding is deterministic; bot stakes affect pools but not raffle; a draw waits for unresolved wagers; zero weight produces no winner; repeated cue recognition selects once; and a call failure preserves the winner.

Use a small fixture with known integer payouts and raffle intervals. Do not test a cryptographic RNG by asserting a particular live winner. Verify interval selection with injected deterministic draw values, including zero and `total-1`. Keep deterministic test randomness separate from the real demo draw adapter.

## 7. Sources and authority

Economic rules above are owner decisions or explicit project design recommendations. They are not claims that a payment provider or raffle platform supplies them. Stripe's operational semantics are documented at [webhooks](https://docs.stripe.com/webhooks), [idempotent requests](https://docs.stripe.com/api/idempotent_requests), and [test transactions](https://docs.stripe.com/testing), checked 2026-11-14. No production financial service is authorized by this plan.
