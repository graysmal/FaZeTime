# Verification and evidence strategy

This is a specification for future checks, not a record of tests already run. [PROJECT_PLAN](../PROJECT_PLAN.md) defines completion gates. Use [PHASE_EVIDENCE](templates/PHASE_EVIDENCE.md) to record actual results. Test what can break the demo or corrupt state; avoid broad infrastructure built only to test itself.

## Layers and ownership

| Layer | What it proves | Owner |
|---|---|---|
| Domain/unit | Integer payout math, raffle intervals, deadlines, state predicates, input validation | Backend |
| Database integration | Actual SQLite locking, duplicate-effect prevention, rollback, restart durability | Backend + reviewer |
| Contract | Pydantic/TypeScript agreement, enums, optional fields, amounts, error semantics | Coordinator + UI/backend |
| Media fixture | Timing, STT quality, frame alignment, model abstention and repeatability | Media-AI |
| Live Twitch | Real delivery, discontinuities, measured delay, no local-file substitution | Media-AI + operator |
| Browser | Twitch SPA mounting, iframe/auth, resize/focus, MV3 lifecycle, reconnect | Extension |
| Provider sandbox | Real Stripe test completion and Chert team-device media/lifecycle | Integrations |
| End-to-end | Whole story on actual machines/network with two clients and reset | Coordinator + reviewer |

Keep tests offline by default. External integration tests are explicitly selected, use only verified demo accounts/recipients and bounded quota, and never run on every edit or every CI job. No test can create paid usage by automatically falling back to another provider.

## Financial and concurrency matrix

| Case | Required assertion |
|---|---|
| Same wager sent twice | One wager and one debit; same receipt returned |
| Same key, changed stake/side | Conflict; original effect remains unchanged |
| Two requests spend last available balance | At most affordable total accepted; no negative user balance |
| Deadline while request waits for DB | Deadline rechecked after acquiring write transaction; late request rejected |
| HTTP response lost after commit | Retry finds committed operation; no second effect |
| API killed before/after settlement commit | All-or-nothing settlement; terminal receipt recoverable |
| Settlement and void race | Exactly one terminal transition and one compatible ledger result |
| Decimal, negative, huge or zero stake | Rejected without mutation |
| Both sides have stake | Total gross returns equals full escrow; fee zero |
| Rounding remainder | Deterministic allocation and exact conservation |
| Empty/one-sided market | Void/refund once, zero raffle weight |
| Duplicate Stripe event | One fulfillment |
| Different Stripe event IDs, same payment | One economic fulfillment |
| Paid redirect forged or repeated | No unverified wallet credit |
| Payment paid after market closes | Wallet may credit; old wager not autoaccepted |
| Prior-run callback after reset | Only original operation/run affected |
| Redemption double click | One debit and same nonfunctional demo code |

Use separate database connections and concurrent tasks to test contention; sequential unit tests cannot establish atomicity. Test the selected SQLite journal/transaction settings, not a different in-memory substitute with different pooling behavior. Inspect the ledger for equal debit/credit totals and reconcile every materialized user balance.

## AI and time matrix

Create a small labeled set from the chosen event template, with at least one clip/segment held out from prompt tuning. The expected result is stored separately from runtime evidence. A fixture may include a full transcript for scoring, but the replay feeder exposes observations only at their causal time.

Cases: clear future event, clear YES, clear NO, no event, event already happened, action already started, unclear pronoun, negated statement, replay, wrong round, scoreboard too small, misleading celebration, no decisive result, speech/frame contradiction, overlapping duplicate transcript, audio-only with missing visual proof, source gap, source epoch mismatch, model delay beyond deadline, malformed JSON, quota rejection, and spoken prompt injection.

Measure raw counts: offered candidates, valid opportunities, invalid opens, correct supported decisions, unsupported settlements, abstentions and late results. Report denominators and the event-template restriction. Require zero unsupported opens/settlements in the release fixture suite, then real Twitch rehearsal; this is a narrow release gate, not a claim of statistical safety on all gameplay.

Measure latency at observable boundaries: broadcast cue, capture receipt, committed transcript, model start/end, backend acceptance, client display. Keep clock-mapping method and sample count. Report p95 only with enough samples to make it meaningful; otherwise show range and worst observed value. A model's numeric confidence is not an accuracy measurement.

Pause/rebuffer one viewer. It must receive server deadlines and fail a late bet even if its video is behind. Demonstrate that local system-clock changes cannot extend betting. Detect when the broadcaster's outcome has occurred before an attempted open; decline/void rather than trusting delayed playback. A prerecorded source makes controlled timing possible but does not eliminate latency arbitrage in a public system.

## Browser and identity checks

Unpacked install; fresh profile; claimed Twitch name separate from authenticated account; one-time invite redemption; session expiration/revocation; wrong-user wallet access; worker/operator authorization; multiple tabs; backgrounded tab; channel SPA navigation; theater mode; resized panel; close/reopen; popup closed; browser/extension update; service worker stopped; socket reconnect; stale snapshot; tunnel hostname changed; capture denied/stopped; iframe refuses load; spoofed postMessage origin/source/type; third-party cookies blocked.

Prefer a few component tests and Playwright tests of a controlled fixture page, plus actual Twitch manual checks. Do not make CI scrape Twitch as the only browser test. Test the real site at rehearsal because a fixture cannot predict Twitch DOM changes or policies. Do not use automated browser changes that disable security as an acceptance environment.

## Raffle and call checks

Known eligible weights produce exact displayed ratios. Splitting a stake leaves odds unchanged. Winning versus losing does not change original stake weight. Bots, top-ups, voids and previous runs are excluded. Zero denominator yields no draw. Pending outcome postpones draw. Concurrent/duplicate triggers produce one snapshot and winner. Inject deterministic draw values only in tests; live randomness remains cryptographic.

Chert checks: phone verification, actual audio exchange, dynamic video card, hangup/line release, second call, group capability where enabled, unanswered/busy/expired-line behavior, uncertain create response reconciled with the same key, unknown participant count labeled, visible phone identity recorded, and no redraw after call failure.

Voice checks: ambiguous amount, ambiguous side, user changes mind, silent/no confirmation, exact confirmation, confirmation after cutoff, insufficient funds, simultaneous browser bet, repeated tool call, stale market card, group audio, phone not bound to user, returned presence before dial, and quota exhaustion. Only explicit valid single-user confirmation can reach the shared wager command. The model saying “placed” cannot substitute for a committed backend receipt.

## Final reviewer checklist

Verify all selected phase gates have actual evidence and commits. Search bundles/config for accidental provider secrets; inspect manifest host permissions and API authentication. Check mode labels, seed/bot labels, current spend/quota, source origin, version pins, reset isolation and accepted fallback wording. Ensure no unresolved blocker is written as complete in README or status. Do not invent test counts; attach the actual command output or concise manual observation.

