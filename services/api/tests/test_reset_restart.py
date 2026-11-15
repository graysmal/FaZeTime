"""Run reset (§9.5), restart durability, transaction atomicity, fixture credit idempotency."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from fazetime_api import events as events_mod
from fazetime_api import timeutil
from fazetime_api.main import create_app

from .conftest import Harness, make_settings, op


def _wallet(h, run_id, user_id):
    with h.svc.db.read() as conn:
        row = conn.execute("SELECT available_minor, balance_version FROM wallets WHERE run_id = ? AND user_id = ?",
                           (run_id, user_id)).fetchone()
    return (row["available_minor"], row["balance_version"]) if row else None


def test_reset_voids_refunds_archives_seeds_and_old_keys_replay(world):
    h, operator, alice, bob = world
    market = h.open_market(operator)
    key = op()
    original = h.wager(alice, market, "YES", 500, operation_id=key).json()
    h.wager(bob, market, "NO", 900)
    old_run = market["stream_session_id"]
    stream_id = h.stream()["stream_id"]
    reset_key = op()
    r = h.client.post("/v1/operator/runs/reset", headers=operator.h,
                      json={"operation_id": reset_key, "stream_id": stream_id})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["archived_stream_session_id"] == old_run and body["voided_market_id"] == market["market_id"]
    new_run = body["stream_session_id"]
    assert new_run != old_run and body["stream"]["stream_session_id"] == new_run
    with h.svc.db.read() as conn:
        assert conn.execute("SELECT state FROM runs WHERE run_id = ?", (old_run,)).fetchone()[0] == "ARCHIVED"
        m = conn.execute("SELECT state, void_reason FROM markets WHERE market_id = ?", (market["market_id"],)).fetchone()
        assert (m["state"], m["void_reason"]) == ("VOID", "RUN_RESET")
        refunds = conn.execute("SELECT COUNT(*) FROM ledger_transactions WHERE reason = 'REFUND' AND market_id = ?",
                               (market["market_id"],)).fetchone()[0]
        assert refunds == 2
    assert _wallet(h, old_run, alice.user_id)[0] == 2000 and _wallet(h, old_run, bob.user_id)[0] == 2000
    for actor in (alice, bob, operator):
        assert _wallet(h, new_run, actor.user_id) == (2000, 1)  # fresh SEED_GRANT in the new run
    replay = h.wager(alice, market, "YES", 500, operation_id=key)  # old key replays even after reset
    assert replay.status_code == 200 and {**replay.json(), "replayed": False} == original
    stale = h.wager(alice, market, "YES", 500)
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "WRONG_RUN"
    assert stale.json()["error"]["details"] == {"current_stream_session_id": new_run}
    snap = h.snapshot(alice)
    assert snap["stream"]["stream_session_id"] == new_run and snap["market"] is None
    assert snap["wallet"] == {"stream_session_id": new_run, "available_minor": 2000, "in_play_minor": 0,
                              "balance_version": 1, "pending_topup_minor": None}
    again = h.client.post("/v1/operator/runs/reset", headers=operator.h,
                          json={"operation_id": reset_key, "stream_id": stream_id})
    assert again.status_code == 200 and again.json()["replayed"] is True
    assert h.stream()["run_id"] == new_run  # replay did not reset twice
    assert h.reconcile()["ok"]


def test_restart_preserves_users_balances_events_and_runs_startup_sweep(db_path, clock):
    app = create_app(make_settings(db_path), clock)
    with TestClient(app) as client:
        h = Harness(client, clock)
        operator = h.bootstrap_operator()
        h.create_stream(operator)
        alice, bob = h.viewer(operator, "Alice"), h.viewer(operator, "Bob")
        market = h.open_market(operator)
        h.wager(alice, market, "YES", 500)
        h.wager(bob, market, "NO", 300)
        before_snap = h.snapshot(alice)
        with h.svc.db.read() as conn:
            before_events = [tuple(r) for r in conn.execute("SELECT * FROM events ORDER BY event_id")]
    clock.set(timeutil.parse(market["close_at_utc"]))  # time passes while the API is down
    app2 = create_app(make_settings(db_path), clock)
    with TestClient(app2) as client2:
        h2 = Harness(client2, clock)
        assert h2.available(alice) == 1500 and h2.available(bob) == 1700  # sessions + balances survived
        with h2.svc.db.read() as conn:
            after_events = [tuple(r) for r in conn.execute("SELECT * FROM events ORDER BY event_id")]
        assert after_events[: len(before_events)] == before_events
        snap = h2.snapshot(alice)
        assert snap["market"]["state"] == "EVALUATING"  # startup sweep locked the expired market
        assert snap["event_hwm"] > before_snap["event_hwm"]
        assert h2.settle(operator, market["market_id"], "YES").status_code == 200
        assert h2.available(alice) == 2300
        assert h2.reconcile()["ok"]


def test_crash_before_commit_leaves_no_effect_and_retry_succeeds(world, monkeypatch):
    h, operator, alice, _ = world
    market = h.open_market(operator)
    key = op()
    real_emit = events_mod.emit_wallet

    def boom(*args, **kwargs):
        raise RuntimeError("simulated crash after ledger writes, before COMMIT")

    monkeypatch.setattr(events_mod, "emit_wallet", boom)
    r = h.wager(alice, market, "YES", 500, operation_id=key)
    assert r.status_code == 500 and r.json()["error"]["code"] == "INTERNAL_ERROR"
    assert r.json()["error"]["retryable"] is True and r.json()["error"]["operation_id"] == key
    monkeypatch.setattr(events_mod, "emit_wallet", real_emit)
    assert h.available(alice) == 2000
    with h.svc.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM wagers").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM operations WHERE operation_id = ?", (key,)).fetchone()[0] == 0
    retry = h.wager(alice, market, "YES", 500, operation_id=key)  # same key after a 5xx
    assert retry.status_code == 201 and h.available(alice) == 1500
    assert h.reconcile()["ok"]


def test_duplicate_fixture_credit_changes_balance_once(world):
    h, operator, alice, _ = world
    key = op()
    first = h.credit(operator, alice.user_id, 1000, operation_id=key)
    assert first.status_code == 201 and first.json()["wallet_after"]["available_minor"] == 3000
    second = h.credit(operator, alice.user_id, 1000, operation_id=key)
    assert second.status_code == 200 and second.json()["replayed"] is True
    assert second.json()["txn_id"] == first.json()["txn_id"]
    conflict = h.credit(operator, alice.user_id, 999, operation_id=key)
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert h.available(alice) == 3000
    with h.svc.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM ledger_transactions WHERE reason = 'FIXTURE_CREDIT'").fetchone()[0] == 1
        audits = conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'OP_FIXTURE_CREDIT'").fetchone()[0]
        assert audits == 1
    assert h.reconcile()["ok"]


@pytest.mark.parametrize("amount", [0, -5, 100_001, 1.5, "10"])
def test_fixture_credit_amount_validation(world, amount):
    h, operator, alice, _ = world
    r = h.credit(operator, alice.user_id, amount)
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_AMOUNT"
    assert h.available(alice) == 2000


def test_fixture_credit_respects_balance_cap_and_unknown_user(world):
    h, operator, alice, _ = world
    for _ in range(9):
        assert h.credit(operator, alice.user_id, 100_000).status_code == 201
    capped = h.credit(operator, alice.user_id, 100_000)  # 902,000 + 100,000 > 1,000,000
    assert capped.status_code == 422 and capped.json()["error"]["code"] == "INVALID_AMOUNT"
    missing = h.credit(operator, "usr_" + "0" * 32, 100)
    assert missing.status_code == 404
