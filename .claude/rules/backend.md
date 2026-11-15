---
paths:
  - "services/api/**"
---

# API and ledger constraints

- Root `PROJECT_PLAN.md` is authoritative for phase scope and business choices.
- The Python backend exclusively owns monetary mutations, market transitions, and raffle eligibility snapshots.
- Use the accepted database; migrations and shared schemas have one assigned writer.
- Money is integer minor units. Keep raffle weights separate from balances. No platform fee.
- Transactions must enforce balance, identity, authorization, server cutoff, market version, and idempotency together where required.
- Retry, duplicate webhook, duplicate settlement, and reconnect must not create extra value or repeat side effects.
- LLMs and provider adapters submit validated input; neither directly edits the ledger.
- Persist authoritative state before publishing derived events. Support a fresh snapshot after missed events or restart.
- In-memory fanout is scoped to one process unless shared fanout is explicitly implemented and tested.
- Never persist raw card numbers/CVC. Stripe credentials and webhook processing must remain test-only.
- Eligible cumulative settled stakes determine raffle weights according to the canonical plan; void/refund behavior must be explicit.
- Test races and invariants against the selected real database engine, not only mocks.
