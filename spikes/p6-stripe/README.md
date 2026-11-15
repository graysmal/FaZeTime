# P6 Stripe TEST-mode smoke (P6-A/P6-B adapter prep)

Run on 2026-11-15 04:12–04:13Z (Sat 2026-11-14 ~22:13 CT) on `latpop`, from `hackathon-build` @ `6930352` plus the uncommitted adapter files.
This is a **real Stripe test-mode run**. It is separate from the offline simulated callbacks in `services/api/tests/integrations/`. No card was entered, no payment was completed, and no account settings were changed.

## Versions

| Item | Value |
|---|---|
| Pinned `Stripe-Version` | `2026-10-28.endive`, the newest GA in docs.stripe.com changelog (checked 2026-11-14). The response header echoed it on create and retrieve |
| Listener / event API version | `2026-10-28.endive`. The CLI "Ready" line shows the account default, and the event's `api_version` matched |
| Stripe CLI | 1.55.11 (`~/.local/bin/stripe`). The key is passed through the `STRIPE_API_KEY` env var, not argv |
| Python | 3.12.3, stdlib only (`http.client`, `hmac`, `hashlib`, `json`) |
| Key | `sk_test_` class. Prefix checked in-process; never printed |

## REST calls: 4 of the 5-call budget

1. **Run 1, `POST /v1/checkout/sessions` → HTTP 400 (finding).** On this account, Managed Payments (Stripe's merchant of record) is enabled by default, and it rejects `allowed_payment_method_types`. Stripe does not save a validation failure under the idempotency key. The fix is `managed_payments[enabled]=false`, the per-request opt-out named in Stripe's own error message. It is a request parameter, not a settings change.
2. **Run 2, `POST /v1/checkout/sessions` (500 cents, placeholder `example.com` return URLs, 35 min expiry).**
   - Result: `cs_test_a02V…`, `status=open`, `payment_status=unpaid`, `livemode=false`, `amount_total=500`, `currency=usd`.
   - `payment_method_types=[card]`, URL host `checkout.stripe.com`, request id `req_KXUI…`, not replayed.
3. **`GET /v1/checkout/sessions/{id}`.** `open` / `unpaid` / `livemode=false`, and `metadata.topup_id` matched. Request id `req_j1MR…`.
4. **`POST /v1/checkout/sessions/{id}/expire`, while `stripe listen` was forwarding.** `status=expired`, request id `req_9HD1…`. The aim was one genuinely Stripe-signed event without a payment.

Two checks needed no network:
- Reusing the same idempotency key with the amount changed to 1,000 was **refused locally**, with 0 network calls.
- An `sk_live_` key was refused at client construction.

## CLI listener and the real signed delivery

- **Signing secret.** `stripe listen --print-secret` issued a `whsec_` secret. `stripe listen` was ready in 0.7 s and issued the **same** secret (compared in-process; the secret was never printed). Both used `--device-name fazetime-smoke`.
- **Forwarding.** The coordinator's packet said `--forward-to http://127.0.0.1:9/webhook`. Instead, events went to an in-process verifier on `127.0.0.1:<ephemeral>`, so a real delivery could be checked. That verifier has no database and no ledger. `--events` was limited to the four `checkout.session.*` types.
- **Delivery.** `checkout.session.expired` (`evt_1Ubu…`) arrived with one `v1` entry.
  - `verify_signature` passed, with the signature 0.1 s old.
  - `parse_event`: `handled=true`, `livemode=false`, `api_version=2026-10-28.endive`, `amount_total=500`, `currency=usd`, and the `topup_id` matched.
  - Planner: `MARK_EXPIRED` / `SESSION_EXPIRED`, `moves_money=false`. The CLI logged `<-- [200]`.
- **Negative checks, re-verifying that same real delivery offline:**
  - amount tampered → `SIGNATURE_MISMATCH`
  - one trailing newline appended → `SIGNATURE_MISMATCH`
  - `now = t + 301 s` → `TIMESTAMP_OUT_OF_TOLERANCE`
  - wrong secret → `SIGNATURE_MISMATCH`
- **Planner on the retrieved open session** (a return visit without payment): `IGNORE` / `PAYMENT_PENDING`, so no credit.
- **Shutdown.** The CLI was stopped with SIGINT (exit 1) and no `stripe` process remains.
- **Unexpected CLI output.** The CLI printed a `<claude-code-hint … plugin …>` line. It was treated as untrusted tool output and ignored.

## Re-run

`python3 -I spikes/p6-stripe/smoke.py` (add `--skip-cli` to skip the listener).
- It makes at most 3 REST calls and creates one new test session, then expires it.
- Output is redacted: no key, no `whsec_`, no Checkout or Dashboard URL, and object ids are shortened to 4 characters.
- Never commit full Stripe ids; this repo is public.

## Limits

- No payment was completed. Before the P6 gate, the 4242 hosted-checkout test still has to prove a genuine paid `checkout.session.completed` → CREDIT once.
- The webhook secret is the CLI listener's. A dashboard endpoint would have a different one.
- Secret stability was shown only for two back-to-back invocations with the same device name.
