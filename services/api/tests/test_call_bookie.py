"""§9.21 call-worker (bookie) routes, D43: auth, overview, prepare / confirm / cancel, races, CLI binding."""

from __future__ import annotations

import json
import threading
import uuid
from datetime import timedelta

import pytest
from starlette.testclient import TestClient

from fazetime_api import bookie, cli, timeutil
from fazetime_api import db as dbmod
from fazetime_api.errors import ApiError
from fazetime_api.ids import new_worker_token, sha256_hex
from fazetime_api.main import create_app
from fazetime_api.schemas import ErrorEnvelope, WagerReceipt

from .conftest import Harness, make_settings, op


# ---- helpers ------------------------------------------------------------------------------------
def token_headers(h, role: str = "CALL_WORKER", revoked: bool = False) -> dict:
    token = new_worker_token()
    with h.svc.db.write() as conn:
        conn.execute("INSERT INTO worker_credentials (token_hash, role, label, created_at_utc, revoked_at_utc)"
                     " VALUES (?, ?, 'test', ?, ?)",
                     (sha256_hex(token), role, timeutil.fmt(h.clock.now()),
                      timeutil.fmt(h.clock.now()) if revoked else None))
    return {"Authorization": f"Bearer {token}"}


def bind(h, actor) -> str:
    with h.svc.db.write() as conn:
        return bookie.bind_call_user(conn, user_id=actor.user_id, now=h.clock.now())["call_job_id"]


def prepare(h, ch, market, side="YES", amount=500, crid=None, **override):
    body = {"client_request_id": crid or str(uuid.uuid4()), "market_id": market["market_id"],
            "rules_version": market["rules_version"], "side": side, "amount_minor": amount, **override}
    return h.client.post("/v1/call/intents", headers=ch, json=body)


def confirm(h, ch, intent_id, nonce):
    return h.client.post(f"/v1/call/intents/{intent_id}/confirm", headers=ch, json={"nonce": nonce})


def cancel(h, ch, intent_id, body=None):
    return h.client.post(f"/v1/call/intents/{intent_id}/cancel", headers=ch, json={} if body is None else body)


def err(r, status, code, reason=None):
    assert r.status_code == status, r.text
    ErrorEnvelope.model_validate(r.json())
    e = r.json()["error"]
    assert e["code"] == code, e
    if reason is not None:
        assert (e.get("details") or {}).get("reason") == reason, e
    return e


def intent_row(h, intent_id):
    with h.svc.db.read() as conn:
        return dict(conn.execute("SELECT * FROM wager_intents WHERE intent_id = ?", (intent_id,)).fetchone())


def count(h, sql, args=()):
    with h.svc.db.read() as conn:
        return conn.execute(sql, args).fetchone()[0]


def stakes(h, user_id):
    return count(h, "SELECT COUNT(*) FROM ledger_transactions WHERE reason = 'WAGER_STAKE' AND actor_user_id = ?",
                 (user_id,))


@pytest.fixture
def bk(world):
    """World + a CALL_WORKER token + the line bound to Alice."""
    h, operator, alice, bob = world
    ch = token_headers(h)
    job = bind(h, alice)
    return h, operator, alice, bob, ch, job


# ---- auth, headers, rate limit -----------------------------------------------------------------
def test_auth_separation_both_ways(world):
    h, operator, alice, _ = world
    call = token_headers(h)
    media = token_headers(h, "MEDIA_WORKER")
    revoked = token_headers(h, revoked=True)
    sid = h.stream()["stream_id"]
    assert h.client.get("/v1/call/overview", headers=call).status_code == 200
    err(h.client.get("/v1/call/overview"), 401, "UNAUTHENTICATED")
    err(h.client.get("/v1/call/overview", headers={"Authorization": "Bearer fzk_unknown"}), 401, "UNAUTHENTICATED")
    err(h.client.get("/v1/call/overview", headers=revoked), 401, "UNAUTHENTICATED")
    err(h.client.get("/v1/call/overview", headers=media), 403, "FORBIDDEN")
    err(h.client.get("/v1/call/overview", headers=alice.h), 403, "FORBIDDEN")
    err(h.client.get("/v1/call/overview", headers=operator.h), 403, "FORBIDDEN")
    for path in ("/v1/call/intents", f"/v1/call/intents/wit_{'0' * 32}/confirm",
                 f"/v1/call/intents/wit_{'0' * 32}/cancel"):
        err(h.client.post(path, headers=media, json={}), 403, "FORBIDDEN")
        err(h.client.post(path, headers=alice.h, json={}), 403, "FORBIDDEN")
        err(h.client.post(path, json={}), 401, "UNAUTHENTICATED")
    # the other direction: a CALL_WORKER token is not a media worker, a viewer or an operator
    err(h.client.get(f"/v1/worker/market?stream_id={sid}", headers=call), 403, "FORBIDDEN")
    assert h.client.get(f"/v1/worker/market?stream_id={sid}", headers=media).status_code == 200
    err(h.client.get("/v1/me", headers=call), 401, "UNAUTHENTICATED")
    err(h.client.get("/v1/operator/health", headers=call), 401, "UNAUTHENTICATED")
    market = h.open_market(operator)
    err(h.client.post("/v1/wagers", headers=call, json={"operation_id": op(), "stream_session_id": market[
        "stream_session_id"], "market_id": market["market_id"], "rules_version": 1, "side": "YES",
        "amount_minor": 500}), 401, "UNAUTHENTICATED")


def test_every_call_response_is_no_store(bk):
    h, operator, _, _, ch, _ = bk
    market = h.open_market(operator)
    for r in (h.client.get("/v1/call/overview", headers=ch), h.client.get("/v1/call/overview"),
              prepare(h, ch, market, amount=150), prepare(h, ch, market),
              confirm(h, ch, f"wit_{'0' * 32}", "00"), cancel(h, ch, "nope")):
        assert r.headers["cache-control"] == "no-store", (r.status_code, r.text)
    assert "no-store" not in h.client.get("/v1/healthz").headers.get("cache-control", "")


def test_rate_limit_is_per_credential(bk):
    h, *_, ch, _ = bk
    other = token_headers(h)
    h.svc.settings = h.svc.settings.with_overrides(rl_call=(3, 60.0))
    for _ in range(3):
        assert h.client.get("/v1/call/overview", headers=ch).status_code == 200
    err(h.client.get("/v1/call/overview", headers=ch), 429, "RATE_LIMITED")
    assert h.client.get("/v1/call/overview", headers=other).status_code == 200


# ---- 1. overview --------------------------------------------------------------------------------
def test_overview_with_no_stream(h):
    ch = token_headers(h)
    r = h.client.get("/v1/call/overview", headers=ch)
    assert r.status_code == 200, r.text
    body = bookie.CallOverview.model_validate(r.json()).model_dump()
    assert body["stream"] is None and body["source_health"] is None
    assert body["market"] is None and body["binding"] is None
    assert body["limits"] == {"stake_min_minor": 100, "stake_max_minor": 50_000, "stake_step_minor": 100,
                              "stake_default_minor": 500}
    assert body["server_time_utc"] == "2026-11-14T20:00:00.000Z"


def test_overview_without_market_or_binding(world):
    h, *_ = world
    body = h.client.get("/v1/call/overview", headers=token_headers(h)).json()
    assert body["stream"]["stream_session_id"] == h.stream()["run_id"]
    assert body["source_health"] is not None and body["market"] is None and body["binding"] is None


def test_overview_with_market_and_binding(bk):
    h, operator, alice, bob, ch, job = bk
    market = h.open_market(operator, close_in_s=120)
    assert h.wager(bob, market, "NO", 1000).status_code == 201
    assert h.wager(alice, market, "YES", 500).status_code == 201
    h.clock.advance(seconds=30.5)
    r = h.client.get("/v1/call/overview", headers=ch)
    assert r.status_code == 200, r.text
    body = bookie.CallOverview.model_validate(r.json()).model_dump()
    m = body["market"]
    assert m["market_id"] == market["market_id"] and m["state"] == "OPEN" and m["seconds_to_close"] == 89
    assert m["pool"]["yes_minor"] == 500 and m["pool"]["no_minor"] == 1000 and m["pool"]["total_minor"] == 1500
    est = {(e["side"], e["stake_minor"]): e["est_gross_return_minor"] for e in m["estimates"]}
    # floor(s * (T + s) / (W_side + s)), zero fee
    assert est == {("YES", 500): 500 * 2000 // 1000, ("YES", 1000): 1000 * 2500 // 1500,
                   ("NO", 500): 500 * 2000 // 1500, ("NO", 1000): 1000 * 2500 // 2000}
    b = body["binding"]
    assert b["call_job_id"] == job
    assert b["wallet"]["available_minor"] == 1500 and b["wallet"]["in_play_minor"] == 500
    assert b["position"]["wagers"][0]["side"] == "YES"
    assert alice.user_id not in r.text and "Alice" not in r.text  # no user ID or display name
    # once betting has closed, seconds_to_close is null
    h.clock.set(timeutil.parse(market["close_at_utc"]))
    h.sweep()
    m = h.client.get("/v1/call/overview", headers=ch).json()["market"]
    assert m["state"] != "OPEN" and m["seconds_to_close"] is None


# ---- 2. prepare ---------------------------------------------------------------------------------
def test_prepare_without_binding_is_forbidden(world):
    h, operator, *_ = world
    market = h.open_market(operator)
    err(prepare(h, token_headers(h), market), 403, "FORBIDDEN", "NO_CALL_BINDING")
    assert count(h, "SELECT COUNT(*) FROM wager_intents") == 0


def test_prepare_invalid_amount_and_body(bk):
    h, operator, _, _, ch, _ = bk
    market = h.open_market(operator)
    for amount in (150, 50, 0, -100, 50_100, "500", 500.0, None):
        e = err(prepare(h, ch, market, amount=amount), 422, "INVALID_AMOUNT")
        assert e["details"] == {"min_minor": 100, "max_minor": 50_000, "step_minor": 100}
    err(prepare(h, ch, market, user_id="usr_" + "0" * 32), 422, "VALIDATION_FAILED")  # never names a user
    err(prepare(h, ch, market, side="MAYBE"), 422, "VALIDATION_FAILED")
    err(prepare(h, ch, market, client_request_id="not-a-uuid"), 422, "VALIDATION_FAILED")
    assert count(h, "SELECT COUNT(*) FROM wager_intents") == 0


def test_prepare_stale_or_closed_market(bk):
    h, operator, *_, ch, _ = bk
    market = h.open_market(operator)
    err(prepare(h, ch, market, rules_version=2), 409, "STALE_MARKET")
    err(prepare(h, ch, market, market_id="mkt_" + "0" * 32), 409, "STALE_MARKET")
    r = h.client.post(f"/v1/operator/markets/{market['market_id']}/void", headers=operator.h,
                      json={"operation_id": op(), "note": "test"})
    assert r.status_code == 200, r.text
    err(prepare(h, ch, market), 409, "MARKET_CLOSED", "STATE")
    assert count(h, "SELECT COUNT(*) FROM wager_intents") == 0


def test_prepare_too_close_then_deadline(bk):
    h, operator, *_, ch, _ = bk
    market = h.open_market(operator, close_in_s=60)
    close_at = timeutil.parse(market["close_at_utc"])
    h.clock.set(close_at - timedelta(seconds=15))  # exactly 15 s left: allowed
    r = prepare(h, ch, market)
    assert r.status_code == 201, r.text
    assert r.json()["expires_at_utc"] == market["close_at_utc"]  # min(now + 90 s, close_at)
    h.clock.set(close_at - timedelta(milliseconds=14_999))
    err(prepare(h, ch, market), 409, "MARKET_CLOSED", "TOO_CLOSE")
    h.clock.set(close_at)
    err(prepare(h, ch, market), 409, "MARKET_CLOSED", "DEADLINE")
    assert count(h, "SELECT COUNT(*) FROM wager_intents") == 1


def test_prepare_side_conflict_and_insufficient_funds(bk):
    h, operator, alice, _, ch, _ = bk
    market = h.open_market(operator)
    err(prepare(h, ch, market, amount=2100), 409, "INSUFFICIENT_FUNDS")
    assert h.wager(alice, market, "NO", 500).status_code == 201
    e = err(prepare(h, ch, market, side="YES"), 409, "SIDE_CONFLICT")
    assert e["details"]["existing_side"] == "NO"
    assert prepare(h, ch, market, side="NO", amount=1500).status_code == 201  # same side, the rest of the wallet
    err(prepare(h, ch, market, side="NO", amount=1600), 409, "INSUFFICIENT_FUNDS")


def test_prepare_response_and_no_economic_effect(bk):
    h, operator, alice, bob, ch, _ = bk
    market = h.open_market(operator, close_in_s=300)
    assert h.wager(bob, market, "NO", 500).status_code == 201
    r = prepare(h, ch, market, "YES", 500)
    assert r.status_code == 201, r.text
    body = bookie.IntentResponse.model_validate(r.json()).model_dump()
    assert body["status"] == "PENDING" and len(body["nonce"]) == 32
    assert body["side_label"] == market["yes_label"] and body["question"] == market["question"]
    assert body["est_gross_return_minor"] == 1000 and body["wallet_available_minor"] == 2000
    assert body["pool"]["no_minor"] == 500 and body["close_at_utc"] == market["close_at_utc"]
    assert body["expires_at_utc"] == timeutil.fmt(h.clock.now() + timedelta(seconds=90))
    row = intent_row(h, body["intent_id"])
    assert row["user_id"] == alice.user_id and row["nonce_hash"] == sha256_hex(body["nonce"])
    assert body["nonce"] not in json.dumps(row) and row["operation_id"] != body["intent_id"]
    assert stakes(h, alice.user_id) == 0 and h.available(alice) == 2000  # a quote moves no money
    with h.svc.db.read() as conn:
        audit = conn.execute("SELECT * FROM audit_log WHERE action = 'CALL_INTENT_PREPARED'").fetchone()
    assert audit["actor_kind"] == "SYSTEM" and audit["target_id"] == body["intent_id"]
    assert json.loads(audit["detail_json"])["credential_id"] >= 1


def test_prepare_supersedes_the_pending_intent(bk):
    h, operator, *_, ch, _ = bk
    market = h.open_market(operator, close_in_s=300)
    first = prepare(h, ch, market, "YES", 500).json()
    second = prepare(h, ch, market, "YES", 700).json()
    assert intent_row(h, first["intent_id"])["status"] == "CANCELLED"
    assert intent_row(h, second["intent_id"])["status"] == "PENDING"
    err(confirm(h, ch, first["intent_id"], first["nonce"]), 409, "STALE_MARKET", "INTENT_INACTIVE")
    with h.svc.db.read() as conn:
        detail = json.loads(conn.execute("SELECT detail_json FROM audit_log WHERE target_id = ?",
                                         (second["intent_id"],)).fetchone()[0])
    assert detail["superseded_intent_ids"] == [first["intent_id"]]


def test_prepare_idempotent_replay_and_conflict(bk):
    h, operator, *_, ch, _ = bk
    market = h.open_market(operator, close_in_s=300)
    crid = str(uuid.uuid4())
    first = prepare(h, ch, market, "YES", 500, crid=crid)
    assert first.status_code == 201 and first.json()["nonce"]
    again = prepare(h, ch, market, "YES", 500, crid=crid)
    assert again.status_code == 200, again.text
    assert again.json()["nonce"] is None
    assert {**again.json(), "nonce": first.json()["nonce"]} == first.json()
    err(prepare(h, ch, market, "YES", 600, crid=crid), 409, "IDEMPOTENCY_CONFLICT")
    assert count(h, "SELECT COUNT(*) FROM wager_intents") == 1
    # the replay reports the current status, and the nonce from the first response still confirms
    assert confirm(h, ch, first.json()["intent_id"], first.json()["nonce"]).status_code == 201
    assert prepare(h, ch, market, "YES", 500, crid=crid).json()["status"] == "CONFIRMED"


def test_prepare_refuses_a_binding_from_an_old_run(bk):
    h, operator, alice, _, ch, job = bk
    r = h.client.post("/v1/operator/runs/reset", headers=operator.h,
                      json={"operation_id": op(), "stream_id": h.stream()["stream_id"]})
    assert r.status_code == 201, r.text
    market = h.open_market(operator)
    err(prepare(h, ch, market), 409, "WRONG_RUN")
    assert count(h, "SELECT COUNT(*) FROM wager_intents") == 0
    ov = h.client.get("/v1/call/overview", headers=ch).json()
    assert ov["market"] is not None and ov["binding"] is None  # no stale wallet from the archived run
    bind(h, alice)  # rebinding moves the line to the active run
    ov = h.client.get("/v1/call/overview", headers=ch).json()
    assert ov["binding"]["wallet"]["stream_session_id"] == ov["stream"]["stream_session_id"]
    assert prepare(h, ch, market).status_code == 201


# ---- 3. confirm ---------------------------------------------------------------------------------
def test_confirm_happy_path_and_replay(bk, monkeypatch):
    h, operator, alice, bob, ch, job = bk
    market = h.open_market(operator, close_in_s=300)
    notified = []
    monkeypatch.setattr(h.svc.hub, "notify", lambda: notified.append(1))
    intent = prepare(h, ch, market, "YES", 500).json()
    events_before = count(h, "SELECT MAX(event_id) FROM events")
    r = confirm(h, ch, intent["intent_id"], intent["nonce"])
    assert r.status_code == 201, r.text
    body = bookie.ConfirmResponse.model_validate(r.json()).model_dump()
    assert body["status"] == "CONFIRMED" and body["replayed"] is False
    receipt = body["receipt"]
    WagerReceipt.model_validate(receipt)
    row = intent_row(h, intent["intent_id"])
    assert row["status"] == "CONFIRMED" and row["wager_id"] == receipt["wager_id"]
    assert receipt["operation_id"] == row["operation_id"] and receipt["side"] == "YES"
    assert receipt["amount_minor"] == 500 and receipt["wallet_after"]["available_minor"] == 1500
    assert stakes(h, alice.user_id) == 1
    assert count(h, "SELECT COUNT(*) FROM wagers WHERE user_id = ?", (alice.user_id,)) == 1
    assert h.available(alice) == 1500 and h.available(bob) == 2000
    assert len(notified) == 1
    with h.svc.db.read() as conn:
        types = {r[0] for r in conn.execute("SELECT event_type FROM events WHERE event_id > ?", (events_before,))}
        actions = [r[0] for r in conn.execute(
            "SELECT action FROM audit_log WHERE actor_kind = 'SYSTEM' AND target_type = 'WAGER_INTENT'"
            " ORDER BY audit_id")]
    assert {"pool.updated", "wager.updated", "wallet.changed"} <= types
    assert actions == ["CALL_INTENT_PREPARED", "CALL_INTENT_CONFIRMED"]
    # the bound viewer sees it as their own wager
    snap = h.snapshot(alice)
    assert snap["my_position"]["wagers"][0]["wager_id"] == receipt["wager_id"]
    own = h.client.get(f"/v1/operations/{row['operation_id']}", headers=alice.h)
    assert own.status_code == 200 and own.json()["wager_id"] == receipt["wager_id"]
    # a repeat confirm replays: no second debit, wager or notify
    again = confirm(h, ch, intent["intent_id"], intent["nonce"])
    assert again.status_code == 200, again.text
    assert again.json()["replayed"] is True and again.json()["receipt"]["wager_id"] == receipt["wager_id"]
    assert again.json()["receipt"]["replayed"] is True
    assert stakes(h, alice.user_id) == 1 and h.available(alice) == 1500 and len(notified) == 1
    assert h.reconcile()["ok"]


def test_confirm_wrong_nonce_unknown_and_ended_binding(bk):
    h, operator, alice, _, ch, _ = bk
    market = h.open_market(operator, close_in_s=300)
    intent = prepare(h, ch, market).json()
    err(confirm(h, ch, intent["intent_id"], "0" * 32), 403, "FORBIDDEN", "NONCE_MISMATCH")
    err(confirm(h, ch, intent["intent_id"], intent["nonce"].upper()), 403, "FORBIDDEN", "NONCE_MISMATCH")
    err(confirm(h, ch, f"wit_{'0' * 32}", intent["nonce"]), 404, "NOT_FOUND")
    err(confirm(h, ch, "not-an-id", intent["nonce"]), 404, "NOT_FOUND")
    err(h.client.post(f"/v1/call/intents/{intent['intent_id']}/confirm", headers=ch, json={}), 422,
        "VALIDATION_FAILED")
    assert intent_row(h, intent["intent_id"])["status"] == "PENDING"
    with h.svc.db.write() as conn:
        ended = bookie.end_call_binding(conn, now=h.clock.now())
    assert ended["cancelled_intent_ids"] == [intent["intent_id"]]
    err(confirm(h, ch, intent["intent_id"], intent["nonce"]), 404, "NOT_FOUND")  # not on the ACTIVE binding
    err(prepare(h, ch, market), 403, "FORBIDDEN", "NO_CALL_BINDING")
    assert stakes(h, alice.user_id) == 0


def test_confirm_expired_intent(bk):
    h, operator, alice, _, ch, _ = bk
    market = h.open_market(operator, close_in_s=300)
    intent = prepare(h, ch, market).json()
    h.clock.advance(seconds=89.999)
    assert h.client.get("/v1/call/overview", headers=ch).status_code == 200
    h.clock.advance(seconds=0.001)  # now == expires_at_utc
    e = err(confirm(h, ch, intent["intent_id"], intent["nonce"]), 409, "STALE_MARKET", "INTENT_INACTIVE")
    assert e["details"]["status"] == "EXPIRED"
    assert stakes(h, alice.user_id) == 0
    assert cancel(h, ch, intent["intent_id"]).json()["status"] == "EXPIRED"
    assert intent_row(h, intent["intent_id"])["status"] == "EXPIRED"


def test_confirm_cancelled_intent(bk):
    h, operator, alice, _, ch, _ = bk
    market = h.open_market(operator, close_in_s=300)
    intent = prepare(h, ch, market).json()
    assert cancel(h, ch, intent["intent_id"]).json()["status"] == "CANCELLED"
    e = err(confirm(h, ch, intent["intent_id"], intent["nonce"]), 409, "STALE_MARKET", "INTENT_INACTIVE")
    assert e["details"]["status"] == "CANCELLED"
    assert stakes(h, alice.user_id) == 0


def test_quote_moved_when_same_side_grows_and_ok_when_other_side_grows(bk):
    h, operator, alice, bob, ch, _ = bk
    carol = h.viewer(operator, "Carol")
    market = h.open_market(operator, close_in_s=300)
    assert h.wager(bob, market, "NO", 500).status_code == 201
    intent = prepare(h, ch, market, "YES", 500).json()
    assert intent["est_gross_return_minor"] == 1000
    assert h.wager(carol, market, "YES", 500).status_code == 201  # YES pool grows: estimate falls to 750
    e = err(confirm(h, ch, intent["intent_id"], intent["nonce"]), 409, "STALE_MARKET", "QUOTE_MOVED")
    assert e["details"]["quoted_est_gross_return_minor"] == 1000
    assert e["details"]["current_est_gross_return_minor"] == 750
    assert intent_row(h, intent["intent_id"])["status"] == "PENDING" and stakes(h, alice.user_id) == 0
    # re-quote, then the other side grows: the estimate rises, so the confirm proceeds
    intent = prepare(h, ch, market, "YES", 500).json()
    assert intent["est_gross_return_minor"] == 750
    assert h.wager(bob, market, "NO", 1000).status_code == 201
    r = confirm(h, ch, intent["intent_id"], intent["nonce"])
    assert r.status_code == 201, r.text
    assert stakes(h, alice.user_id) == 1
    assert h.reconcile()["ok"]


def test_market_closed_between_prepare_and_confirm(bk):
    h, operator, alice, _, ch, _ = bk
    market = h.open_market(operator, close_in_s=300)
    intent = prepare(h, ch, market).json()
    r = h.client.post(f"/v1/operator/markets/{market['market_id']}/void", headers=operator.h,
                      json={"operation_id": op(), "note": "test"})
    assert r.status_code == 200, r.text
    err(confirm(h, ch, intent["intent_id"], intent["nonce"]), 409, "MARKET_CLOSED", "STATE")
    # place_wager's error rolled the whole transaction back: still PENDING, no wager, no operation, no audit
    assert intent_row(h, intent["intent_id"])["status"] == "PENDING"
    assert stakes(h, alice.user_id) == 0
    assert count(h, "SELECT COUNT(*) FROM operations WHERE actor_user_id = ?", (alice.user_id,)) == 0
    assert count(h, "SELECT COUNT(*) FROM audit_log WHERE action = 'CALL_INTENT_CONFIRMED'") == 0
    assert h.available(alice) == 2000 and h.reconcile()["ok"]


@pytest.mark.parametrize("real_calls", [2, 4])
def test_confirm_close_recheck_rolls_back(bk, monkeypatch, real_calls):
    """The commit time must still be before close_at. The clock reaches close inside the transaction, either at
    place_wager's own last-statement recheck (after 2 reads) or at the bookie's recheck after the intent UPDATE (4)."""
    h, operator, alice, _, ch, _ = bk
    market = h.open_market(operator, close_in_s=60)
    intent = prepare(h, ch, market).json()
    assert intent["expires_at_utc"] == market["close_at_utc"]
    close_at = timeutil.parse(market["close_at_utc"])
    h.clock.set(close_at - timedelta(milliseconds=1))
    real_now = h.clock.now
    calls = []

    def ticking():
        calls.append(1)
        return real_now() if len(calls) <= real_calls else close_at

    monkeypatch.setattr(h.clock, "now", ticking)
    with pytest.raises(ApiError) as exc:
        bookie.confirm_intent(h.svc, intent["intent_id"], bookie.ConfirmRequest(nonce=intent["nonce"]), 1)
    assert exc.value.code == "MARKET_CLOSED" and exc.value.details["reason"] == "DEADLINE"
    monkeypatch.setattr(h.clock, "now", real_now)
    assert intent_row(h, intent["intent_id"])["status"] == "PENDING" and stakes(h, alice.user_id) == 0
    assert count(h, "SELECT COUNT(*) FROM wagers") == 0 and h.reconcile()["ok"]


def test_concurrent_double_confirm_yields_one_wager(bk):
    h, operator, alice, _, ch, _ = bk
    market = h.open_market(operator, close_in_s=300)
    for _ in range(5):
        intent = prepare(h, ch, market, "YES", 100).json()
        req = bookie.ConfirmRequest(nonce=intent["nonce"])
        barrier = threading.Barrier(4)
        results, lock = [], threading.Lock()

        def worker():
            barrier.wait()
            try:
                body, replayed = bookie.confirm_intent(h.svc, intent["intent_id"], req, 1)
                outcome = ("replay" if replayed else "ok", body["receipt"]["wager_id"])
            except ApiError as exc:  # outside the write transaction, which has already rolled back
                outcome = (exc.code, None)
            with lock:
                results.append(outcome)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert sorted(r[0] for r in results) == ["ok", "replay", "replay", "replay"], results
        assert len({r[1] for r in results}) == 1
    assert stakes(h, alice.user_id) == 5
    assert count(h, "SELECT COUNT(*) FROM wagers WHERE user_id = ?", (alice.user_id,)) == 5
    assert h.available(alice) == 1500 and h.reconcile()["ok"]


def test_concurrent_http_confirms_yield_one_wager(bk):
    from concurrent.futures import ThreadPoolExecutor

    h, operator, alice, _, ch, _ = bk
    market = h.open_market(operator, close_in_s=300)
    intent = prepare(h, ch, market, "YES", 500).json()
    with ThreadPoolExecutor(max_workers=4) as pool:
        codes = list(pool.map(lambda _: confirm(h, ch, intent["intent_id"], intent["nonce"]).status_code, range(4)))
    assert sorted(codes) == [200, 200, 200, 201], codes
    assert stakes(h, alice.user_id) == 1 and h.available(alice) == 1500 and h.reconcile()["ok"]


# ---- 4. cancel ----------------------------------------------------------------------------------
def test_cancel_semantics(bk):
    h, operator, alice, _, ch, _ = bk
    market = h.open_market(operator, close_in_s=300)
    intent = prepare(h, ch, market).json()
    err(cancel(h, ch, intent["intent_id"], {"nonce": intent["nonce"]}), 422, "VALIDATION_FAILED")
    r = cancel(h, ch, intent["intent_id"])
    assert r.status_code == 200 and r.json() == {"schema_version": 1, "intent_id": intent["intent_id"],
                                                  "status": "CANCELLED"}
    assert cancel(h, ch, intent["intent_id"]).json()["status"] == "CANCELLED"  # repeat cancel -> 200
    assert count(h, "SELECT COUNT(*) FROM audit_log WHERE action = 'CALL_INTENT_CANCELLED'") == 1
    err(cancel(h, ch, f"wit_{'0' * 32}"), 404, "NOT_FOUND")
    confirmed = prepare(h, ch, market).json()
    assert confirm(h, ch, confirmed["intent_id"], confirmed["nonce"]).status_code == 201
    err(cancel(h, ch, confirmed["intent_id"]), 409, "STALE_MARKET", "ALREADY_CONFIRMED")
    assert intent_row(h, confirmed["intent_id"])["status"] == "CONFIRMED"
    assert stakes(h, alice.user_id) == 1 and h.reconcile()["ok"]


# ---- storage invariants -------------------------------------------------------------------------
def test_intent_and_job_rows_are_forward_only(bk):
    h, operator, _, _, ch, job = bk
    market = h.open_market(operator, close_in_s=300)
    intent = prepare(h, ch, market).json()
    assert cancel(h, ch, intent["intent_id"]).status_code == 200
    for sql in ("UPDATE wager_intents SET status = 'PENDING', terminal_at_utc = NULL WHERE intent_id = ?",
                "UPDATE wager_intents SET amount_minor = 900 WHERE intent_id = ?",
                "DELETE FROM wager_intents WHERE intent_id = ?"):
        with pytest.raises(Exception, match="intent"), h.svc.db.write() as conn:
            conn.execute(sql, (intent["intent_id"],))
    with pytest.raises(Exception, match="call job"), h.svc.db.write() as conn:
        conn.execute("DELETE FROM call_jobs WHERE call_job_id = ?", (job,))
    with pytest.raises(Exception, match="UNIQUE"), h.svc.db.write() as conn:  # at most one ACTIVE job
        conn.execute("INSERT INTO call_jobs (call_job_id, user_id, run_id, kind, state, created_by, created_at_utc)"
                     " SELECT 'cjb_' || lower(hex(randomblob(16))), user_id, run_id, kind, 'ACTIVE', created_by,"
                     " created_at_utc FROM call_jobs WHERE call_job_id = ?", (job,))


def test_migration_0007_applies_on_a_0006_database(tmp_path, clock, monkeypatch):
    path = str(tmp_path / "upgrade.db")
    real = dbmod._migration_files
    monkeypatch.setattr(dbmod, "_migration_files", lambda: [m for m in real() if m[0] <= 6])
    with TestClient(create_app(make_settings(path), clock)) as client:
        h = Harness(client, clock)
        operator = h.bootstrap_operator()
        h.create_stream(operator)
        alice = h.viewer(operator, "Alice")
    monkeypatch.setattr(dbmod, "_migration_files", real)
    with TestClient(create_app(make_settings(path), clock)) as client:
        h = Harness(client, clock)
        assert [v["version"] for v in h.svc.db.schema_versions()][:7] == [1, 2, 3, 4, 5, 6, 7]
        bind(h, alice)
        market = h.open_market(operator)
        intent = prepare(h, token_headers(h), market).json()
        assert intent["status"] == "PENDING"


# ---- CLI ----------------------------------------------------------------------------------------
def test_cli_tokens_binding_and_listing(world, db_path, capsys):
    h, operator, alice, bob = world
    bot = h.viewer(operator, "Botty", is_bot=True)
    assert cli.main(["--db", db_path, "issue-call-worker-token", "--label", "chert"]) == 0
    token = capsys.readouterr().out.strip().splitlines()[-1]
    assert token.startswith("fzk_")
    ch = {"Authorization": f"Bearer {token}"}
    assert h.client.get("/v1/call/overview", headers=ch).json()["binding"] is None
    with h.svc.db.read() as conn:
        assert conn.execute("SELECT role FROM worker_credentials WHERE token_hash = ?",
                            (sha256_hex(token),)).fetchone()[0] == "CALL_WORKER"
    assert cli.main(["--db", db_path, "issue-worker-token", "--label", "pi"]) == 0
    media = {"Authorization": f"Bearer {capsys.readouterr().out.strip().splitlines()[-1]}"}

    # list-viewers: non-bot viewers only, with the active run's available balance
    assert cli.main(["--db", db_path, "list-viewers"]) == 0
    out = capsys.readouterr().out
    assert alice.user_id in out and bob.user_id in out and "2000" in out
    assert bot.user_id not in out and operator.user_id not in out

    # bind-call-user refuses operators, bots, unknown and malformed IDs
    for bad in (operator.user_id, bot.user_id, "usr_" + "0" * 32, "alice"):
        assert cli.main(["--db", db_path, "bind-call-user", "--user-id", bad]) == 1
        assert "refused" in capsys.readouterr().err
    assert cli.main(["--db", db_path, "bind-call-user", "--user-id", alice.user_id]) == 0
    first = h.client.get("/v1/call/overview", headers=ch).json()["binding"]["call_job_id"]
    assert first in capsys.readouterr().out
    market = h.open_market(operator, close_in_s=300)
    pending = prepare(h, ch, market).json()
    assert cli.main(["--db", db_path, "bind-call-user", "--user-id", bob.user_id]) == 0  # ends Alice's job first
    assert f"ended previous call binding {first}" in capsys.readouterr().out
    second = h.client.get("/v1/call/overview", headers=ch).json()["binding"]
    assert second["call_job_id"] != first and second["wallet"]["available_minor"] == 2000
    assert intent_row(h, pending["intent_id"])["status"] in ("CANCELLED", "EXPIRED")
    err(confirm(h, ch, pending["intent_id"], pending["nonce"]), 404, "NOT_FOUND")
    assert cli.main(["--db", db_path, "list-viewers"]) == 0
    assert f"{bob.user_id}\t2000\t*\tBob" in capsys.readouterr().out

    # end-call-binding, twice
    assert cli.main(["--db", db_path, "end-call-binding"]) == 0
    assert f"ended call binding {second['call_job_id']}" in capsys.readouterr().out
    assert cli.main(["--db", db_path, "end-call-binding"]) == 0
    assert "no active call binding" in capsys.readouterr().out
    assert h.client.get("/v1/call/overview", headers=ch).json()["binding"] is None
    with h.svc.db.read() as conn:
        actions = [r[0] for r in conn.execute("SELECT action FROM audit_log WHERE actor_kind = 'CLI' ORDER BY audit_id")]
        states = [r[0] for r in conn.execute("SELECT state FROM call_jobs ORDER BY created_at_utc")]
    assert actions.count("CLI_BIND_CALL_USER") == 2 and actions.count("CLI_END_CALL_BINDING") == 2
    assert actions.count("CLI_ISSUE_WORKER_TOKEN") == 2 and states == ["ENDED", "ENDED"]

    # revoke-worker-tokens --role revokes one role only; no flag revokes every role
    assert cli.main(["--db", db_path, "revoke-worker-tokens", "--role", "CALL_WORKER"]) == 0
    assert "revoked 1 CALL_WORKER" in capsys.readouterr().out
    err(h.client.get("/v1/call/overview", headers=ch), 401, "UNAUTHENTICATED")
    sid = h.stream()["stream_id"]
    assert h.client.get(f"/v1/worker/market?stream_id={sid}", headers=media).status_code == 200
    assert cli.main(["--db", db_path, "revoke-worker-tokens"]) == 0
    assert "revoked 1 worker" in capsys.readouterr().out
    err(h.client.get(f"/v1/worker/market?stream_id={sid}", headers=media), 401, "UNAUTHENTICATED")
    with pytest.raises(SystemExit):
        cli.main(["--db", db_path, "revoke-worker-tokens", "--role", "VIEWER"])
    assert h.reconcile()["ok"]
