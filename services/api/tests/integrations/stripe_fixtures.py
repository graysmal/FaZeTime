"""Offline Stripe fixtures. Every id, secret and key here is fake and labelled FIXTURE; nothing touches Stripe.

These are simulated callbacks, distinct from the real test-mode smoke run in spikes/p6-stripe/.
"""

from __future__ import annotations

import json

from fazetime_api.integrations.stripe_webhook import StripeEvent, build_test_signature_header, construct_event

SECRET = "whsec" "_FIXTUREfixtureFIXTUREfixture0000"
OTHER_SECRET = "whsec" "_FIXTUREotherOTHERotherOTHER1111"
FAKE_KEY = "sk" "_test_FIXTUREfixtureFIXTUREfixture"
NOW = 1_800_000_000
TOPUP_ID = "top_" + "a1" * 16
OTHER_TOPUP_ID = "top_" + "b2" * 16
USER_ID = "usr_" + "c3" * 16
OTHER_USER_ID = "usr_" + "d4" * 16
RUN_ID = "run_" + "e5" * 16
SESSION_ID = "cs_test_FIXTURE0000000000000001"
OTHER_SESSION_ID = "cs_test_FIXTURE0000000000000002"
PI_ID = "pi_FIXTURE0000000000000001"
API_VERSION = "2026-10-28.endive"


def session_obj(**overrides) -> dict:
    """A trimmed but realistic checkout.session object (fields per the 2026-10-28.endive reference)."""
    base = {
        "id": SESSION_ID,
        "object": "checkout.session",
        "amount_subtotal": 500,
        "amount_total": 500,
        "client_reference_id": TOPUP_ID,
        "created": NOW - 60,
        "currency": "usd",
        "customer": None,
        "customer_details": {"email": "fan@example.invalid", "name": "Fixture Fan"},
        "expires_at": NOW + 86_340,
        "livemode": False,
        "metadata": {"topup_id": TOPUP_ID},
        "mode": "payment",
        "payment_intent": PI_ID,
        "payment_method_types": ["card"],
        "payment_status": "paid",
        "status": "complete",
        "success_url": "https://example.com/fazetime-test/success",
        "ui_mode": "hosted_page",
        "url": None,
    }
    base.update(overrides)
    return base


def event_body(event_type: str, obj: dict, *, event_id: str = "evt_FIXTURE0000000000000001",
               livemode: bool = False, created: int = NOW, api_version: str | None = API_VERSION) -> bytes:
    doc = {
        "id": event_id,
        "object": "event",
        "api_version": api_version,
        "created": created,
        "data": {"object": obj},
        "livemode": livemode,
        "pending_webhooks": 1,
        "request": {"id": None, "idempotency_key": None},
        "type": event_type,
    }
    return json.dumps(doc, separators=(",", ":")).encode("utf-8")


def signed_header(body: bytes, secret: str = SECRET, ts: int = NOW) -> str:
    return build_test_signature_header(body, secret, ts)


def verified_event(event_type: str, obj: dict | None = None, *, event_id: str = "evt_FIXTURE0000000000000001",
                   **kwargs) -> StripeEvent:
    body = event_body(event_type, obj if obj is not None else session_obj(), event_id=event_id, **kwargs)
    return construct_event(body, signed_header(body), SECRET, now=NOW)
