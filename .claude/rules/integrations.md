---
paths:
  - "services/calls/**"
  - "services/api/integrations/**"
---

# Provider integration constraints

- Verify sponsor/API capabilities with current documentation and an actual-account spike.
- Chert's free 24-hour access is time bounded; expose expiration/unavailability explicitly.
- Human-to-human FaceTime bridging must be proved. Two separate calls do not prove a bridge.
- Calls may target only confirmed demo participants under the agreed demo trigger.
- Stripe is test mode only. Use hosted/tokenized card collection and verified authoritative callbacks.
- Deduplicate callbacks and outbound call requests durably. Unknown or reordered events must not mutate funds incorrectly.
- Provider adapters invoke backend domain commands; only the backend owns balances and ledger transactions.
- A voice wager requires an explicit, unambiguous confirmation and server revalidation of market, side, amount, balance, and cutoff.
- Never silently charge a saved card when a voice wager lacks funds.
- Keep secrets and full phone numbers out of logs; distinguish fixtures from real provider evidence.
- Coordinate API integration edits with the backend owner; do not concurrently change shared schemas or migrations.
