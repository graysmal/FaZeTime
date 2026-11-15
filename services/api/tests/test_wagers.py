"""POST /v1/wagers: acceptance, check order, deadline exclusivity, idempotency (§9.6, §9.7, §9.10)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from fazetime_api import timeutil
from fazetime_api.schemas import ErrorEnvelope, StreamSnapshot, WagerReceipt

from .conftest import op


def _err(r, status, code):
    assert r.status_code == status, r.text
    body = r.json()
    ErrorEnvelope.model_validate(body)
    assert body["error"]["code"] == code, body
    assert body["error"]["request_id"].startswith("req_")
    assert r.headers["x-request-id"] == body["error"]["request_id"]
    return body["error"]


def test_accept_debits_available_and_builds_receipt(world):
    h, operator, alice, bob = world
    market = h.open_market(operator)
    r = h.wager(alice, market, "YES", 500)
    assert r.status_code == 201, r.text
    receipt = WagerReceipt.model_validate(r.json())
    assert receipt.replayed is False and receipt.status == "ACCEPTED"
    assert receipt.wallet_after.available_minor == 1500 and receipt.wallet_after.in_play_minor == 500
    snap = h.snapshot(alice)
    StreamSnapshot.model_validate(snap)
    assert snap["market"]["pool"] == {"yes_minor": 500, "no_minor": 0, "total_minor": 500,
                                      "simulated_minor": 0, "wager_count": 1}
    assert snap["my_position"]["result"] == "PENDING" and snap["my_position"]["stake_total_minor"] == 500
    assert snap["wallet"]["available_minor"] == 1500
    assert h.reconcile()["ok"]


def test_replay_same_key_returns_same_receipt_without_double_debit(world):
    h, operator, alice, _ = world
    market = h.open_market(operator)
    key = op()
    first = h.wager(alice, market, "YES", 500, operation_id=key)
    assert first.status_code == 201
    second = h.wager(alice, market, "YES", 500, operation_id=key)
    assert second.status_code == 200
    assert second.json()["replayed"] is True
    assert {**second.json(), "replayed": False} == first.json()
    assert h.available(alice) == 1500
    lookup = h.client.get(f"/v1/operations/{key}", headers=alice.h)
    assert lookup.status_code == 200 and lookup.json()["wager_id"] == first.json()["wager_id"]
    assert h.snapshot(alice)["market"]["pool"]["wager_count"] == 1


def test_same_key_different_body_is_conflict_with_no_effect(world):
    h, operator, alice, _ = world
    market = h.open_market(operator)
    key = op()
    assert h.wager(alice, market, "YES", 500, operation_id=key).status_code == 201
    err = _err(h.wager(alice, market, "YES", 600, operation_id=key), 409, "IDEMPOTENCY_CONFLICT")
    assert err["operation_id"] == key and err["retryable"] is False
    _err(h.wager(alice, market, "NO", 500, operation_id=key), 409, "IDEMPOTENCY_CONFLICT")
    assert h.available(alice) == 1500


def test_other_users_identical_key_is_independent(world):
    h, operator, alice, bob = world
    market = h.open_market(operator)
    key = op()
    a = h.wager(alice, market, "YES", 500, operation_id=key)
    b = h.wager(bob, market, "YES", 500, operation_id=key)
    assert a.status_code == 201 and b.status_code == 201
    assert a.json()["wager_id"] != b.json()["wager_id"]
    assert h.available(alice) == 1500 and h.available(bob) == 1500


def test_business_rejection_is_not_cached(world):
    h, operator, alice, _ = world
    market = h.open_market(operator)
    key = op()
    err = _err(h.wager(alice, market, "YES", 2500, operation_id=key), 409, "INSUFFICIENT_FUNDS")
    assert err["details"] == {"available_minor": 2000, "requested_minor": 2500}
    assert h.client.get(f"/v1/operations/{key}", headers=alice.h).status_code == 404  # nothing recorded
    assert h.credit(operator, alice.user_id, 1000).status_code == 201  # fixture top-up
    retry = h.wager(alice, market, "YES", 2500)  # NEW key for the new user intent
    assert retry.status_code == 201, retry.text
    assert h.available(alice) == 500
    assert h.reconcile()["ok"]


def test_deadline_is_exclusive(world):
    h, operator, alice, bob = world
    market = h.open_market(operator, close_in_s=60)
    close_at = timeutil.parse(market["close_at_utc"])
    h.clock.set(close_at - timedelta(milliseconds=1))
    assert h.wager(alice, market, "YES", 500).status_code == 201
    h.clock.set(close_at)  # exactly at close_at: rejected even though the sweeper has not run
    err = _err(h.wager(bob, market, "NO", 500), 409, "MARKET_CLOSED")
    assert err["details"]["reason"] == "DEADLINE" and err["details"]["state"] == "OPEN"
    h.sweep()
    err = _err(h.wager(bob, market, "NO", 500), 409, "MARKET_CLOSED")
    assert err["details"]["reason"] == "STATE"
    assert h.available(bob) == 2000


def test_side_conflict_and_same_side_topup_wager(world):
    h, operator, alice, _ = world
    market = h.open_market(operator)
    assert h.wager(alice, market, "YES", 500).status_code == 201
    assert h.wager(alice, market, "YES", 300).status_code == 201  # same side, new operation: allowed
    err = _err(h.wager(alice, market, "NO", 500), 409, "SIDE_CONFLICT")
    assert err["details"] == {"existing_side": "YES"}
    assert h.available(alice) == 1200


def test_stale_market_and_wrong_run(world):
    h, operator, alice, _ = world
    market = h.open_market(operator)
    err = _err(h.wager(alice, market, "YES", 500, rules_version=2), 409, "STALE_MARKET")
    assert err["details"] == {"current_market_id": market["market_id"], "current_rules_version": 1}
    _err(h.wager(alice, market, "YES", 500, market_id="mkt_" + "0" * 32), 409, "STALE_MARKET")
    err = _err(h.wager(alice, market, "YES", 500, stream_session_id="run_" + "0" * 32), 409, "WRONG_RUN")
    assert err["details"] == {"current_stream_session_id": market["stream_session_id"]}
    draft = h.draft(operator)
    _err(h.wager(alice, {**market, "market_id": draft["market_id"]}, "YES", 500), 409, "STALE_MARKET")


@pytest.mark.parametrize("amount", [0, -100, 150, 50_100, 99, 500.0, 500.5, "500", True, None, 10**30])
def test_invalid_amounts_rejected_before_any_mutation(world, amount):
    h, operator, alice, _ = world
    market = h.open_market(operator)
    err = _err(h.wager(alice, market, "YES", amount), 422, "INVALID_AMOUNT")
    assert err["details"] == {"min_minor": 100, "max_minor": 50000, "step_minor": 100}
    assert h.available(alice) == 2000


def test_body_with_user_id_is_validation_failed(world):
    h, operator, alice, bob = world
    market = h.open_market(operator)
    err = _err(h.wager(alice, market, "YES", 500, user_id=bob.user_id), 422, "VALIDATION_FAILED")
    assert {"loc": ["body", "user_id"], "msg": "Extra inputs are not permitted"} in err["details"]["fields"]
    assert h.available(bob) == 2000 and h.available(alice) == 2000


def test_malformed_body_and_check_order_auth_first(world):
    h, operator, alice, _ = world
    r = h.client.post("/v1/wagers", content=b"{not json", headers={"Content-Type": "application/json"})
    _err(r, 401, "UNAUTHENTICATED")  # authentication precedes validation
    r = h.client.post("/v1/wagers", content=b"{not json", headers={**alice.h, "Content-Type": "application/json"})
    _err(r, 422, "VALIDATION_FAILED")


def test_rate_limit_precedes_validation(db_path, clock):
    from starlette.testclient import TestClient

    from fazetime_api.main import create_app

    from .conftest import Harness, make_settings

    app = create_app(make_settings(db_path, rl_wager=(2, 60.0)), clock)
    with TestClient(app) as client:
        h = Harness(client, clock)
        operator = h.bootstrap_operator()
        h.create_stream(operator)
        alice = h.viewer(operator, "Alice")
        market = h.open_market(operator)
        assert h.wager(alice, market, "YES", 500).status_code == 201
        assert h.wager(alice, market, "YES", 0).status_code == 422
        r = h.wager(alice, market, "YES", 0)
        err = _err(r, 429, "RATE_LIMITED")
        assert err["retryable"] is True and err["retry_after_ms"] > 0 and int(r.headers["retry-after"]) >= 1
