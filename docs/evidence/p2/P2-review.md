# P2 independent review (reviewer subagent, read-only)

- **Phase / scope / date:** P2 backend, `services/api/**`. 2026-11-14 ~21:55 CT.
- **Bound to:** commit `6930352` on `hackathon-build`. Uncommitted P3 edits were landing during the review and are reviewed under P3.
- **Test evidence:** the coordinator's re-run of the P2 tree gave pytest 167 passed, 2 skipped (19.5 s). The worker's manual uvicorn smoke run is recorded in `services/api/README.md`.
- **Verdict:** **accept with explicit limitations.** No Critical or High findings. The traced money paths showed no way to double-debit, double-credit, double-settle, double-refund or overdraw.

**Verified by reading the code**
- **Transactions:** every mutation runs in `BEGIN IMMEDIATE`, and time is read after the lock.
- **No double effects:** a layered defence covers it:
  - operation keys plus a canonical hash;
  - a UNIQUE `source_key`;
  - balance/version compare-and-set;
  - `CHECK >= 0`;
  - terminal-state triggers;
  - an escrow-empty assertion.
- **Deadline:** checked again right before COMMIT, with a trigger as backstop.
- **Settle vs void/timeout:** serialized.
- **Reset:** atomic.
- **Outbox:** written in the mutation's transaction.
- **Authorization:** no client `user_id`; operator-only routes enforced; tokens and tickets stored as SHA-256; the WebSocket ticket is single use with an expiry.

**Findings and disposition**

| ID | Severity | Finding | Disposition |
|---|---|---|---|
| M1 | Medium | Evidence predates the P3 edits | Acceptance is bound to `6930352`. P3 must re-run the full suite on its own tree |
| M2 | Medium | Extension origin is a wildcard (`chrome-extension://*`), and the tests assert it | Fix assigned: exact pinned origin only. CONTRACTS §9.15 item 15 |
| M3 | Medium | Some constraint tests pass for the wrong reason | Fix assigned: match the trigger messages, and add raw-SQL trigger cases |
| L1 | Low | Session revocation is not rechecked on busy sockets | Fix assigned: timer-based recheck |
| L2 | Low | Unmapped 4xx keeps its status | Fix assigned: 422 |
| L3 | Low | Body is buffered before the size check | Fix assigned |
| L4 | Low | Balances can be edited by raw SQL (reconcile detects it) | Optional |
| L5 | Low | Wallet versions jump by more than 1 | Ruled normal (§9.15 item 14), and the client was told |
| L6 | Low | Operators can bet on markets they settle | D30: operators cannot wager |
| L7 | Low | CORS allows twitch.tv although calls come from the background | Config-only |
| L8 | Low | README duplicates the contract rulings | Fix assigned |
| L9 | Low | Minimum-lead recheck is tautological for fixtures | Moves to P4 |

**Still unverified for the P2 gate**
- Two real browsers sharing one state.
- The live-adapter reconnect.
- A run on the Pi.
- WebSocket overflow → resync.
- Deadline behaviour on a real clock.
- Whether the JSON-only operator endpoints are enough for P2's "minimal operator view".
