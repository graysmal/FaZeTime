"""P6-C/D Stripe TEST-mode top-ups through the real API, real SQLite and a fake Stripe transport (CONTRACTS §9.18).

Simulated provider only: FakeStripe stands in for api.stripe.com, and webhooks are signed locally with a fixture
secret. The real test-mode evidence is in spikes/p6-stripe/README.md.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import uuid
from pathlib import Path
from urllib.parse import parse_qsl

import pytest

from fazetime_api import db as dbmod
from fazetime_api import ledger, topups
from fazetime_api.integrations import stripe_client as sc
from fazetime_api.integrations import stripe_webhook as sw
from fazetime_api.integrations.stripe_fulfillment import Action
from fazetime_api.schemas import ErrorEnvelope, TopupReceipt

from .conftest import op
from .integrations.stripe_fixtures import FAKE_KEY, OTHER_SECRET, SECRET, event_body

MIGRATIONS = Path(dbmod.__file__).parent / "migrations"


@pytest.fixture(autouse=True)
def _topups_schema(monkeypatch):
    """Until 0004_ai.sql lands, the top-up DDL is staged as 0005_topups.sql.staged (the migrator ignores it).

    These tests append it as the next contiguous migration. Once it is renamed to 0005_topups.sql, this is a no-op.
    """
    real = dbmod._migration_files

    def patched():
        files = real()
        if any(name.endswith("_topups.sql") for _, name, _ in files):
            return files
        sql = (MIGRATIONS / "0005_topups.sql.staged").read_text(encoding="utf-8")
        return [*files, (len(files) + 1, f"{len(files) + 1:04d}_topups.sql", sql)]

    monkeypatch.setattr(dbmod, "_migration_files", patched)


class FakeStripe:
    """In-memory stand-in for api.stripe.com: Checkout create (idempotent by key), retrieve, expire. Test-only."""

    def __init__(self) -> None:
        self.sessions: dict[str, dict] = {}
        self.by_key: dict[str, tuple[str, bytes]] = {}
        self.calls: list[tuple[str, str, str | None]] = []
        self.faults: list = []  # an exception, "lose_response", or a raw (status, headers, body) reply
        self.lock = threading.Lock()

    def __call__(self, method, path, headers, body, timeout):
        with self.lock:
            self.calls.append((method, path, headers.get("Idempotency-Key")))
            fault = self.faults.pop(0) if self.faults else None
        if isinstance(fault, BaseException):
            raise fault
        if isinstance(fault, tuple):
            return fault
        reply = self._handle(method, path, headers, body)
        if fault == "lose_response":
            raise TimeoutError("Stripe executed the request but the response was lost")
        return reply

    def _handle(self, method, path, headers, body):
        hdrs = {"request-id": "req_FIXTURE" + uuid.uuid4().hex[:8], "stripe-version": headers["Stripe-Version"]}
        with self.lock:
            if method == "POST" and path == "/v1/checkout/sessions":
                key = headers["Idempotency-Key"]
                if key in self.by_key:
                    sid, original = self.by_key[key]
                    if original != body:
                        return 400, hdrs, json.dumps({"error": {"type": "idempotency_error", "message": "x"}}).encode()
                    return 200, {**hdrs, "idempotent-replayed": "true"}, json.dumps(self.sessions[sid]).encode()
                p = dict(parse_qsl(body.decode()))
                sid = "cs_test_FIXTURE" + uuid.uuid4().hex
                self.sessions[sid] = {
                    "id": sid, "object": "checkout.session", "livemode": False, "mode": p["mode"],
                    "amount_total": int(p["line_items[0][price_data][unit_amount]"]),
                    "currency": p["line_items[0][price_data][currency]"],
                    "client_reference_id": p["client_reference_id"], "metadata": {"topup_id": p["metadata[topup_id]"]},
                    "status": "open", "payment_status": "unpaid", "payment_intent": None,
                    "payment_method_types": [p["allowed_payment_method_types[0]"]],
                    "url": f"https://checkout.stripe.com/c/pay/{sid}#fidFIXTURE", "expires_at": 1_794_787_200,
                    "customer_details": None,
                }
                self.by_key[key] = (sid, body)
                return 200, hdrs, json.dumps(self.sessions[sid]).encode()
            m = re.fullmatch(r"/v1/checkout/sessions/(cs_test_\w+?)(/expire)?", path)
            if m and m.group(1) in self.sessions:
                doc = self.sessions[m.group(1)]
                if m.group(2):
                    doc.update(status="expired")
                return 200, hdrs, json.dumps(doc).encode()
        return 404, hdrs, json.dumps({"error": {"type": "invalid_request_error", "message": "no such session"}}).encode()

    def pay(self, sid: str) -> dict:
        self.sessions[sid].update(status="complete", payment_status="paid", payment_intent="pi_FIXTURE" + sid[-16:])
        return self.sessions[sid]

    def count(self, method: str, prefix: str) -> int:
        return sum(1 for m, p, _ in self.calls if m == method and p.startswith(prefix))


@pytest.fixture
def pay(world):
    h, operator, alice, bob = world
    stripe = FakeStripe()
    topups.configure(h.app, topups.Payments(sc.StripeTestClient(FAKE_KEY, transport=stripe, max_network_retries=0),
                                            SECRET))
    return h, operator, alice, bob, stripe


# ---- helpers -------------------------------------------------------------------------------------
def create(h, actor, amount: int = 500, operation_id: str | None = None):
    return h.client.post("/v1/topups", headers=actor.h,
                         json={"operation_id": operation_id or op(), "amount_minor": amount})


def created(h, actor, stripe, amount: int = 500) -> tuple[dict, str]:
    r = create(h, actor, amount)
    assert r.status_code == 201, r.text
    body = r.json()
    return body, row(h, body["topup_id"])["stripe_session_id"]


def ts(h) -> int:
    return int(h.clock.now().timestamp())


def deliver(h, event_type: str, obj: dict, event_id: str | None = None, *, secret: str = SECRET,
            livemode: bool = False, signed_at: int | None = None, body: bytes | None = None,
            header: str | None = None):
    body = body or event_body(event_type, obj, event_id=event_id or "evt_FIXTURE" + uuid.uuid4().hex,
                              livemode=livemode, created=ts(h))
    if header is None:
        header = sw.build_test_signature_header(body, secret, ts(h) if signed_at is None else signed_at)
    return h.client.post("/v1/webhooks/stripe", content=body,
                         headers={"Stripe-Signature": header, "Content-Type": "application/json"})


def row(h, topup_id: str) -> dict:
    with h.svc.db.read() as conn:
        return dict(conn.execute("SELECT * FROM topups WHERE topup_id = ?", (topup_id,)).fetchone())


def credit_txns(h, topup_id: str) -> list[dict]:
    with h.svc.db.read() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM ledger_transactions WHERE source_key = ?",
                                              (f"stripe_topup:{topup_id}",))]


def receipts(h) -> list[dict]:
    with h.svc.db.read() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM provider_receipts ORDER BY rowid")]


def error(r, status: int, code: str) -> dict:
    assert r.status_code == status, r.text
    ErrorEnvelope.model_validate(r.json())
    assert r.json()["error"]["code"] == code
    return r.json()["error"]


# ---- create / replay / conflict ------------------------------------------------------------------
def test_create_returns_pending_receipt_and_stores_only_references(pay):
    h, _, alice, _, stripe = pay
    r = create(h, alice, 1_000)
    assert r.status_code == 201, r.text
    body = TopupReceipt.model_validate(r.json()).model_dump()
    assert (body["status"], body["payment_mode"], body["currency"], body["amount_minor"]) == ("PENDING", "STRIPE_TEST",
                                                                                              "usd", 1_000)
    assert body["checkout_url"].startswith("https://checkout.stripe.com/") and body["replayed"] is False
    assert body["stream_session_id"] == h.stream()["run_id"] and body["checkout_expires_at_utc"]
    stored = row(h, body["topup_id"])
    assert stored["status"] == "PENDING" and stored["stripe_session_id"] in stripe.sessions
    assert stored["stripe_idempotency_key"] == f"fazetime:topup:{body['topup_id']}"
    assert [c for c in stripe.calls if c[0] == "POST"] == [("POST", "/v1/checkout/sessions",
                                                             stored["stripe_idempotency_key"])]
    assert h.available(alice) == 2_000  # nothing credited before a verified paid state
    assert r.headers["cache-control"] == "no-store"


def test_replay_returns_the_same_receipt_without_calling_stripe(pay):
    h, _, alice, _, stripe = pay
    key = op()
    first, second = create(h, alice, 500, key), create(h, alice, 500, key)
    assert (first.status_code, second.status_code) == (201, 200)
    assert second.json()["replayed"] is True
    assert {k: v for k, v in second.json().items() if k != "replayed"} == \
           {k: v for k, v in first.json().items() if k != "replayed"}
    assert stripe.count("POST", "/v1/checkout/sessions") == 1


def test_same_operation_with_a_different_amount_conflicts(pay):
    h, _, alice, _, stripe = pay
    key = op()
    assert create(h, alice, 500, key).status_code == 201
    error(create(h, alice, 1_000, key), 409, "IDEMPOTENCY_CONFLICT")
    with h.svc.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM topups").fetchone()[0] == 1
    assert stripe.count("POST", "/v1/checkout/sessions") == 1


def test_operation_ids_are_not_shared_between_wagers_and_topups(pay):
    h, operator, alice, _, _ = pay
    market = h.open_market(operator)
    shared = op()
    assert h.wager(alice, market, "YES", 500, operation_id=shared).status_code == 201
    error(create(h, alice, 500, shared), 409, "IDEMPOTENCY_CONFLICT")
    other = op()
    assert create(h, alice, 500, other).status_code == 201
    error(h.wager(alice, market, "YES", 500, operation_id=other), 409, "IDEMPOTENCY_CONFLICT")


@pytest.mark.parametrize("amount", [0, -500, 100, 400, 550, 10_100, 20_000, "500", 500.5, True])
def test_disallowed_amounts_are_invalid_amount_and_never_reach_stripe(pay, amount):
    h, _, alice, _, stripe = pay
    err = error(h.client.post("/v1/topups", headers=alice.h, json={"operation_id": op(), "amount_minor": amount}),
                422, "INVALID_AMOUNT")
    assert err["details"] == {"min_minor": 500, "max_minor": 10_000, "step_minor": 100}
    assert stripe.calls == []


def test_client_supplied_user_or_currency_is_a_validation_failure(pay):
    h, _, alice, bob, stripe = pay
    for extra in ({"user_id": bob.user_id}, {"currency": "eur"}, {"success_url": "https://evil.example/"}):
        body = {"operation_id": op(), "amount_minor": 500, **extra}
        error(h.client.post("/v1/topups", headers=alice.h, json=body), 422, "VALIDATION_FAILED")
    assert stripe.calls == []


def test_operators_and_bots_are_forbidden_d30(pay):
    h, operator, alice, _, stripe = pay
    bot = h.viewer(operator, "Bot", is_bot=True)
    for actor in (operator, bot):
        error(create(h, actor), 403, "FORBIDDEN")
        error(h.client.get("/v1/topups/top_" + "0" * 32, headers=actor.h), 403, "FORBIDDEN")
    assert stripe.calls == []


def test_without_both_secrets_payments_are_unavailable(world):
    h, _, alice, _ = world
    assert topups.payment_mode(h.svc) == "UNAVAILABLE"
    error(create(h, alice), 503, "CAPABILITY_UNAVAILABLE")
    error(h.client.get("/v1/topups/top_" + "0" * 32, headers=alice.h), 503, "CAPABILITY_UNAVAILABLE")
    assert h.client.post("/v1/webhooks/stripe", content=b"{}", headers={"Stripe-Signature": "t=1,v1=x"}).status_code == 503
    client = sc.StripeTestClient(FAKE_KEY, transport=FakeStripe())
    topups.configure(h.app, topups.Payments(client, None))  # key without signing secret
    assert topups.payment_mode(h.svc) == "UNAVAILABLE"
    topups.configure(h.app, topups.Payments(client, SECRET))
    assert topups.payment_mode(h.svc) == "STRIPE_TEST"


def test_build_payments_needs_opt_in_and_both_secrets(tmp_path, monkeypatch):
    from fazetime_api.config import Settings

    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    env = tmp_path / ".env.local"
    env.write_text(f"STRIPE_SECRET_KEY={FAKE_KEY}\n")
    assert topups.build_payments(Settings(stripe_env_file=str(env))).mode == "UNAVAILABLE"  # not opted in
    assert topups.build_payments(Settings(payments_enabled=True, stripe_env_file=str(env))).mode == "UNAVAILABLE"
    env.write_text(f"STRIPE_SECRET_KEY={FAKE_KEY}\nSTRIPE_WEBHOOK_SECRET={SECRET}\n")
    assert topups.build_payments(Settings(payments_enabled=True, stripe_env_file=str(env))).mode == "STRIPE_TEST"
    env.write_text("STRIPE_SECRET_KEY=" + "sk" + "_live_FIXTUREfixtureFIXTUREfixture" + f"\nSTRIPE_WEBHOOK_SECRET={SECRET}\n")
    assert topups.build_payments(Settings(payments_enabled=True, stripe_env_file=str(env))).mode == "UNAVAILABLE"


# ---- provider failures during creation -----------------------------------------------------------
def test_lost_response_leaves_created_and_the_retry_reuses_the_same_session(pay):
    h, _, alice, _, stripe = pay
    stripe.faults = ["lose_response"]  # Stripe created the session, the reply never arrived
    key = op()
    err = error(create(h, alice, 500, key), 500, "INTERNAL_ERROR")
    assert err["retryable"] is True and err["operation_id"] == key
    with h.svc.db.read() as conn:
        pending = dict(conn.execute("SELECT * FROM topups").fetchone())
    assert pending["status"] == "CREATED" and pending["stripe_session_id"] is None
    r = create(h, alice, 500, key)
    assert r.status_code == 200 and r.json()["status"] == "PENDING" and r.json()["replayed"] is True
    assert len(stripe.sessions) == 1 and row(h, pending["topup_id"])["stripe_session_id"] in stripe.sessions
    keys = [k for m, p, k in stripe.calls if m == "POST"]
    assert keys == [pending["stripe_idempotency_key"]] * 2


def test_unreachable_stripe_then_retry_creates_one_session(pay):
    h, _, alice, _, stripe = pay
    stripe.faults = [ConnectionRefusedError("down")]
    key = op()
    error(create(h, alice, 500, key), 500, "INTERNAL_ERROR")
    assert stripe.sessions == {}
    assert create(h, alice, 500, key).json()["status"] == "PENDING"
    assert len(stripe.sessions) == 1


def test_stripe_rejection_marks_the_topup_failed(pay):
    h, _, alice, _, stripe = pay
    rejection = json.dumps({"error": {"type": "invalid_request_error", "message": "rejected"}}).encode()
    stripe.faults = [(400, {"request-id": "req_FIXTURE"}, rejection)]
    key = op()
    error(create(h, alice, 500, key), 503, "CAPABILITY_UNAVAILABLE")
    replay = create(h, alice, 500, key).json()
    assert replay["status"] == "FAILED" and replay["checkout_url"] is None
    assert row(h, replay["topup_id"])["review_reason"] == "CHECKOUT_INVALID_REQUEST"


# ---- webhook -------------------------------------------------------------------------------------
def test_paid_webhook_credits_once_in_the_topup_run_and_emits_wallet_changed(pay):
    h, _, alice, _, stripe = pay
    body, sid = created(h, alice, stripe, 1_000)
    r = deliver(h, "checkout.session.completed", stripe.pay(sid))
    assert r.status_code == 200 and r.json() == {"received": True}
    stored = row(h, body["topup_id"])
    assert stored["status"] == "CREDITED" and stored["stripe_payment_intent_id"].startswith("pi_")
    assert stored["checkout_url"] is None and stored["terminal_at_utc"]
    (txn,) = credit_txns(h, body["topup_id"])
    assert (txn["reason"], txn["run_id"], txn["txn_id"]) == ("STRIPE_TEST_TOPUP", body["stream_session_id"],
                                                             stored["credited_txn_id"])
    assert h.available(alice) == 3_000
    with h.svc.db.read() as conn:
        ev = conn.execute("SELECT * FROM events WHERE event_type = 'wallet.changed' AND audience_user_id = ?"
                          " ORDER BY event_id DESC LIMIT 1", (alice.user_id,)).fetchone()
    assert ev["audience"] == "USER" and json.loads(ev["payload_json"])["available_minor"] == 3_000
    (rec,) = receipts(h)
    assert (rec["outcome"], rec["reason"], rec["topup_id"]) == ("CREDIT", "PAID", body["topup_id"])
    assert re.fullmatch(r"[0-9a-f]{64}", rec["payload_sha256"])
    assert h.reconcile()["ok"]
    get = h.client.get(f"/v1/topups/{body['topup_id']}", headers=alice.h).json()
    assert get["status"] == "CREDITED" and get["checkout_url"] is None


def test_duplicate_event_and_the_same_session_under_a_new_event_id_never_credit_twice(pay):
    h, _, alice, _, stripe = pay
    body, sid = created(h, alice, stripe)
    paid = stripe.pay(sid)
    for _ in range(3):  # Stripe retries reuse the event id
        assert deliver(h, "checkout.session.completed", paid, "evt_FIXTUREdup0000000001").status_code == 200
    assert deliver(h, "checkout.session.async_payment_succeeded", paid, "evt_FIXTUREdup0000000002").status_code == 200
    assert len(credit_txns(h, body["topup_id"])) == 1 and h.available(alice) == 2_500
    assert [(r["event_id"], r["outcome"], r["reason"]) for r in receipts(h)] == [
        ("evt_FIXTUREdup0000000001", "CREDIT", "PAID"),
        ("evt_FIXTUREdup0000000002", "NOOP_DUPLICATE", "ALREADY_CREDITED"),
    ]


def test_tampered_wrongly_signed_stale_and_unsigned_deliveries_are_rejected(pay):
    h, _, alice, _, stripe = pay
    body, sid = created(h, alice, stripe)
    good = event_body("checkout.session.completed", stripe.pay(sid), event_id="evt_FIXTUREsig0000000001",
                      created=ts(h))
    header = sw.build_test_signature_header(good, SECRET, ts(h))
    tampered = good.replace(b'"amount_total":500', b'"amount_total":50000')
    assert tampered != good
    for kwargs in (dict(body=tampered, header=header), dict(body=good, header=header.replace("v1=", "v0=")),
                   dict(body=good, secret=OTHER_SECRET), dict(body=good, signed_at=ts(h) - 301),
                   dict(body=good, header=""), dict(body=good, header="garbage")):
        assert deliver(h, "checkout.session.completed", {}, **kwargs).status_code == 400
    assert receipts(h) == [] and credit_txns(h, body["topup_id"]) == [] and row(h, body["topup_id"])["status"] == "PENDING"
    assert deliver(h, "checkout.session.completed", {}, body=good, header=header).status_code == 200  # the original
    assert h.available(alice) == 2_500


def test_livemode_events_are_rejected(pay):
    h, _, alice, _, stripe = pay
    body, sid = created(h, alice, stripe)
    assert deliver(h, "checkout.session.completed", stripe.pay(sid), livemode=True).status_code == 400
    assert deliver(h, "checkout.session.completed", {**stripe.sessions[sid], "livemode": True}).status_code == 400
    assert receipts(h) == [] and credit_txns(h, body["topup_id"]) == []


def test_mismatch_is_acknowledged_flagged_and_grants_nothing(pay):
    h, _, alice, _, stripe = pay
    body, sid = created(h, alice, stripe)
    forged = {**stripe.pay(sid), "amount_total": 5_000}
    assert deliver(h, "checkout.session.completed", forged).status_code == 200
    stored = row(h, body["topup_id"])
    assert (stored["status"], stored["review_reason"]) == ("PENDING", "AMOUNT_MISMATCH")
    assert [(r["outcome"], r["reason"]) for r in receipts(h)] == [("MISMATCH_REVIEW", "AMOUNT_MISMATCH")]
    assert credit_txns(h, body["topup_id"]) == [] and h.available(alice) == 2_000


def test_unknown_types_and_unknown_topups_are_ignored(pay):
    h, _, alice, _, stripe = pay
    created(h, alice, stripe)
    assert deliver(h, "payment_intent.succeeded", {"id": "pi_FIXTURE1", "object": "payment_intent",
                                                   "livemode": False}).status_code == 200
    stranger = {**next(iter(stripe.sessions.values())), "id": "cs_test_FIXTUREstranger", "status": "complete",
                "payment_status": "paid", "metadata": {"topup_id": "top_" + "9" * 32},
                "client_reference_id": "top_" + "9" * 32}
    assert deliver(h, "checkout.session.completed", stranger).status_code == 200
    assert [(r["outcome"], r["reason"], r["topup_id"]) for r in receipts(h)] == [
        ("IGNORE", "UNHANDLED_EVENT_TYPE", None), ("IGNORE", "UNKNOWN_TOPUP", None)]
    assert h.available(alice) == 2_000


def test_expired_topup_is_marked_and_cannot_be_credited_later(pay):
    h, _, alice, _, stripe = pay
    body, sid = created(h, alice, stripe)
    stripe.sessions[sid].update(status="expired")
    assert deliver(h, "checkout.session.expired", stripe.sessions[sid]).status_code == 200
    stored = row(h, body["topup_id"])
    assert stored["status"] == "EXPIRED" and stored["terminal_at_utc"] and stored["checkout_url"] is None
    get = h.client.get(f"/v1/topups/{body['topup_id']}", headers=alice.h).json()
    assert get["status"] == "EXPIRED" and get["checkout_url"] is None
    late = {**stripe.sessions[sid], "status": "complete", "payment_status": "paid"}
    assert deliver(h, "checkout.session.completed", late).status_code == 200
    assert credit_txns(h, body["topup_id"]) == [] and row(h, body["topup_id"])["review_reason"] == "CONTRADICTS_EXPIRED"


def test_async_payment_failure_marks_failed(pay):
    h, _, alice, _, stripe = pay
    body, sid = created(h, alice, stripe)
    unpaid = {**stripe.sessions[sid], "status": "complete", "payment_status": "unpaid"}
    assert deliver(h, "checkout.session.completed", unpaid).status_code == 200
    assert row(h, body["topup_id"])["status"] == "PENDING"
    assert deliver(h, "checkout.session.async_payment_failed", unpaid).status_code == 200
    assert row(h, body["topup_id"])["status"] == "FAILED" and h.available(alice) == 2_000


# ---- GET reconciliation --------------------------------------------------------------------------
def test_return_visit_without_payment_never_credits_and_polling_is_throttled(pay):
    h, _, alice, _, stripe = pay
    body, _ = created(h, alice, stripe)
    url = f"/v1/topups/{body['topup_id']}"
    first = h.client.get(url, headers=alice.h).json()
    assert first["status"] == "PENDING" and first["checkout_url"] == body["checkout_url"]
    h.client.get(url, headers=alice.h)
    assert stripe.count("GET", "/v1/checkout/sessions/") == 1  # within 3 s: served from the database
    h.clock.advance(seconds=3.1)
    h.client.get(url, headers=alice.h)
    assert stripe.count("GET", "/v1/checkout/sessions/") == 2
    assert h.available(alice) == 2_000 and credit_txns(h, body["topup_id"]) == []


def test_get_reconciles_a_paid_session_once_then_the_late_webhook_is_a_noop(pay):
    h, _, alice, _, stripe = pay
    body, sid = created(h, alice, stripe)
    paid = stripe.pay(sid)  # the webhook is "delayed": not delivered yet
    got = h.client.get(f"/v1/topups/{body['topup_id']}", headers=alice.h).json()
    assert got["status"] == "CREDITED" and h.available(alice) == 2_500
    h.clock.advance(seconds=10)
    assert h.client.get(f"/v1/topups/{body['topup_id']}", headers=alice.h).json()["status"] == "CREDITED"
    assert stripe.count("GET", "/v1/checkout/sessions/") == 1  # terminal: no more provider calls
    assert deliver(h, "checkout.session.completed", paid).status_code == 200
    assert [(r["outcome"], r["reason"]) for r in receipts(h)] == [("NOOP_DUPLICATE", "ALREADY_CREDITED")]
    assert len(credit_txns(h, body["topup_id"])) == 1 and h.available(alice) == 2_500
    assert h.reconcile()["ok"]


def test_get_is_owner_only(pay):
    h, _, alice, bob, stripe = pay
    body, _ = created(h, alice, stripe)
    error(h.client.get(f"/v1/topups/{body['topup_id']}", headers=bob.h), 404, "NOT_FOUND")
    error(h.client.get("/v1/topups/not-an-id", headers=alice.h), 404, "NOT_FOUND")
    assert stripe.count("GET", "/v1/checkout/sessions/") == 0


def test_operation_lookup_returns_the_stored_intent(pay):
    h, _, alice, _, stripe = pay
    key = op()
    topup_id = create(h, alice, 500, key).json()["topup_id"]
    r = h.client.get(f"/v1/operations/{key}", headers=alice.h)
    assert r.status_code == 200 and r.json()["topup_id"] == topup_id and r.json()["replayed"] is True


# ---- runs, races, storage ------------------------------------------------------------------------
def test_payment_completing_after_reset_credits_the_archived_run_only(pay):
    h, operator, alice, _, stripe = pay
    body, sid = created(h, alice, stripe)
    old_run = body["stream_session_id"]
    r = h.client.post("/v1/operator/runs/reset", headers=operator.h,
                      json={"operation_id": op(), "stream_id": h.stream()["stream_id"]})
    assert r.status_code in (200, 201), r.text
    new_run = h.stream()["run_id"]
    assert new_run != old_run
    assert row(h, body["topup_id"])["status"] == "PENDING"  # the reset never touches pending top-ups
    assert deliver(h, "checkout.session.completed", stripe.pay(sid)).status_code == 200
    (txn,) = credit_txns(h, body["topup_id"])
    assert txn["run_id"] == old_run
    with h.svc.db.read() as conn:
        assert int(ledger.wallet_account(conn, old_run, alice.user_id)["balance_minor"]) == 2_500
        assert int(ledger.wallet_account(conn, new_run, alice.user_id)["balance_minor"]) == 2_000
        ev = conn.execute("SELECT run_id FROM events WHERE event_type = 'wallet.changed' AND audience_user_id = ?"
                          " ORDER BY event_id DESC LIMIT 1", (alice.user_id,)).fetchone()
    assert ev["run_id"] == old_run
    assert h.available(alice) == 2_000  # the current run's wallet is unchanged
    assert h.reconcile()["ok"]


def test_concurrent_webhook_and_reconcile_credit_exactly_once(pay):
    h, _, alice, _, stripe = pay
    rounds = 6
    for _ in range(rounds):
        body, sid = created(h, alice, stripe)
        paid = stripe.pay(sid)
        event = sw.parse_event(event_body("checkout.session.completed", paid,
                                          event_id="evt_FIXTURE" + uuid.uuid4().hex, created=ts(h)))
        facts = sw.session_facts_from_object(paid)
        barrier = threading.Barrier(2)
        plans: list = []

        def webhook():
            barrier.wait()
            plans.append(topups.apply_webhook_event(h.svc, event))

        def poll():
            barrier.wait()
            plans.append(topups.reconcile_retrieved(h.svc, body["topup_id"], alice.user_id, facts)[1])

        threads = [threading.Thread(target=webhook), threading.Thread(target=poll)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        assert sorted(p.action.value for p in plans) == ["CREDIT", "NOOP_DUPLICATE"]
        assert len(credit_txns(h, body["topup_id"])) == 1
    assert h.available(alice) == 2_000 + rounds * 500
    assert h.reconcile()["ok"]


def test_database_backstops_are_forward_only_and_append_only(pay):
    h, _, alice, _, stripe = pay
    body, sid = created(h, alice, stripe)
    assert deliver(h, "checkout.session.completed", stripe.pay(sid)).status_code == 200
    conn = h.svc.db.connect()
    try:
        for sql in ("UPDATE topups SET amount_minor = 5000",
                    "UPDATE topups SET status = 'PENDING'",
                    "UPDATE topups SET stripe_session_id = 'cs_test_FIXTUREother'",
                    "UPDATE provider_receipts SET outcome = 'IGNORE'",
                    "DELETE FROM provider_receipts",
                    "DELETE FROM topups"):
            with pytest.raises(sqlite3.DatabaseError):
                conn.execute(sql)
        seed = conn.execute("SELECT txn_id FROM ledger_transactions WHERE reason = 'SEED_GRANT' LIMIT 1").fetchone()
        r2 = create(h, alice, 500).json()
        with pytest.raises(sqlite3.DatabaseError):  # a credit must be the top-up's own STRIPE_TEST_TOPUP txn
            conn.execute("UPDATE topups SET status = 'CREDITED', credited_txn_id = ?, terminal_at_utc = 'x'"
                         " WHERE topup_id = ?", (seed["txn_id"], r2["topup_id"]))
        columns = [c[1] for c in conn.execute("PRAGMA table_info(provider_receipts)")]
        assert "payload_sha256" in columns and not any("body" in c or "payload_json" in c for c in columns)
    finally:
        conn.close()


def test_logs_never_contain_checkout_urls_keys_or_secrets(pay, caplog):
    caplog.set_level(logging.DEBUG)
    h, _, alice, _, stripe = pay
    body, sid = created(h, alice, stripe)
    deliver(h, "checkout.session.completed", stripe.pay(sid))
    h.client.get(f"/v1/topups/{body['topup_id']}", headers=alice.h)
    text = caplog.text
    assert "checkout.stripe.com/c/pay" not in text and FAKE_KEY not in text and SECRET not in text
    assert any("stripe webhook checkout.session.completed" in m for m in caplog.messages)
    assert Action.CREDIT.value in text
