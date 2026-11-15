"""Market lifecycle: sweeper lock/void/evaluate/timeout, fixture settlement, operator void (§9.3, ECONOMICS §4)."""

from __future__ import annotations

from datetime import timedelta

from fazetime_api import timeutil
from fazetime_api.schemas import StreamSnapshot

from .conftest import op


def _advance_past_close(h, market):
    h.clock.set(timeutil.parse(market["close_at_utc"]))


def _ledger_reasons(h, market_id):
    with h.svc.db.read() as conn:
        rows = conn.execute("SELECT reason FROM ledger_transactions WHERE market_id = ? ORDER BY rowid",
                            (market_id,)).fetchall()
    return [r["reason"] for r in rows]


def test_worked_example_through_the_api(world):
    h, operator, alice, bob = world
    carol = h.viewer(operator, "Carol")
    dave = h.viewer(operator, "Dave")
    market = h.open_market(operator)
    # winners A=100, B=200, C=300 on YES; loser 400 on NO -> payouts 167/333/500 (ECONOMICS §4)
    ra = h.wager(alice, market, "YES", 100).json()
    rb = h.wager(bob, market, "YES", 200).json()
    rc = h.wager(carol, market, "YES", 300).json()
    h.wager(dave, market, "NO", 400)
    _advance_past_close(h, market)
    result = h.sweep()
    assert result["locked_or_voided"] == 1 and result["evaluating"] == 1
    r = h.settle(operator, market["market_id"], "YES")
    assert r.status_code == 200, r.text
    assert r.json()["market"]["state"] == "SETTLED"
    with h.svc.db.read() as conn:
        payouts = {row["wager_id"]: row["payout_minor"] for row in conn.execute(
            "SELECT wager_id, payout_minor FROM wagers WHERE market_id = ?", (market["market_id"],))}
    expected = {100: 167, 200: 333, 300: 500}
    # the extra cent goes to the largest remainder (A, 400); ids are random so check by stake
    assert payouts[ra["wager_id"]] == expected[100]
    assert payouts[rb["wager_id"]] == expected[200]
    assert payouts[rc["wager_id"]] == expected[300]
    assert sum(payouts.values()) == 1000
    assert h.available(alice) == 2000 - 100 + 167
    assert h.available(dave) == 2000 - 400
    snap = h.snapshot(dave)
    StreamSnapshot.model_validate(snap)
    assert snap["my_position"]["result"] == "LOST" and snap["my_position"]["payout_total_minor"] == 0
    snap = h.snapshot(alice)
    assert snap["my_position"]["result"] == "WON" and snap["my_position"]["payout_total_minor"] == 167
    assert snap["market"]["winning_side"] == "YES"
    assert snap["market"]["settlement_algorithm"] == "PARIMUTUEL_FLOOR_REMAINDER_V1"
    assert snap["wallet"]["in_play_minor"] == 0
    assert h.reconcile()["ok"]


def test_duplicate_settlement_never_pays_twice(world):
    h, operator, alice, bob = world
    market = h.open_market(operator)
    h.wager(alice, market, "YES", 500)
    h.wager(bob, market, "NO", 500)
    _advance_past_close(h, market)
    h.sweep()
    key = op()
    assert h.settle(operator, market["market_id"], "YES", key).status_code == 200
    replay = h.settle(operator, market["market_id"], "YES", key)
    assert replay.status_code == 200 and replay.json()["replayed"] is True
    again = h.settle(operator, market["market_id"], "NO")  # new key, terminal market
    assert again.status_code == 409 and again.json()["error"]["code"] == "MARKET_CLOSED"
    assert h.available(alice) == 2500 and h.available(bob) == 1500
    assert _ledger_reasons(h, market["market_id"]).count("PAYOUT") == 1
    assert h.reconcile()["ok"]


def test_empty_pool_voids_at_lock(world):
    h, operator, alice, _ = world
    market = h.open_market(operator)
    _advance_past_close(h, market)
    h.sweep()
    snap = h.snapshot(alice)
    assert snap["market"]["state"] == "VOID" and snap["market"]["void_reason"] == "EMPTY_POOL"
    assert snap["my_position"]["result"] == "NONE"
    assert _ledger_reasons(h, market["market_id"]) == []


def test_one_sided_pool_voids_at_lock_with_exact_refunds(world):
    h, operator, alice, bob = world
    market = h.open_market(operator)
    h.wager(alice, market, "YES", 700)
    h.wager(alice, market, "YES", 300)
    h.wager(bob, market, "YES", 1200)
    _advance_past_close(h, market)
    h.sweep()
    snap = h.snapshot(alice)
    assert snap["market"]["state"] == "VOID" and snap["market"]["void_reason"] == "ONE_SIDED_POOL"
    assert snap["market"]["locked_at_utc"] is not None
    assert snap["my_position"]["result"] == "VOID_REFUNDED" and snap["my_position"]["refund_total_minor"] == 1000
    assert h.available(alice) == 2000 and h.available(bob) == 2000
    assert _ledger_reasons(h, market["market_id"]).count("REFUND") == 3
    assert h.reconcile()["ok"]


def test_sweeper_is_idempotent_and_timeout_refunds_once(world):
    h, operator, alice, bob = world
    market = h.open_market(operator, close_in_s=60, resolve_in_s=60)
    h.wager(alice, market, "YES", 500)
    h.wager(bob, market, "NO", 800)
    _advance_past_close(h, market)
    first = h.sweep()
    assert first["changed"] == 2
    second = h.sweep()
    assert second["changed"] == 0
    assert h.snapshot(alice)["market"]["state"] == "EVALUATING"
    h.clock.set(timeutil.parse(market["resolve_by_utc"]) - timedelta(milliseconds=1))
    assert h.sweep()["changed"] == 0
    h.clock.set(timeutil.parse(market["resolve_by_utc"]))  # resolve_by is exclusive too
    assert h.sweep()["timed_out"] == 1
    assert h.sweep()["changed"] == 0
    snap = h.snapshot(bob)
    assert snap["market"]["void_reason"] == "RESOLUTION_TIMEOUT"
    assert snap["my_position"]["result"] == "UNRESOLVED_REFUNDED"
    assert h.available(alice) == 2000 and h.available(bob) == 2000
    assert _ledger_reasons(h, market["market_id"]).count("REFUND") == 2
    late = h.settle(operator, market["market_id"], "YES")
    assert late.status_code == 409 and late.json()["error"]["code"] == "MARKET_CLOSED"
    assert h.reconcile()["ok"]


def test_settle_requires_evaluating_and_before_deadline(world):
    h, operator, alice, bob = world
    market = h.open_market(operator, close_in_s=60, resolve_in_s=60)
    h.wager(alice, market, "YES", 500)
    h.wager(bob, market, "NO", 500)
    early = h.settle(operator, market["market_id"], "YES")
    assert early.status_code == 409 and early.json()["error"]["details"]["reason"] == "STATE"
    _advance_past_close(h, market)
    h.sweep()
    h.clock.set(timeutil.parse(market["resolve_by_utc"]))  # deadline reached, sweeper not yet run
    late = h.settle(operator, market["market_id"], "YES")
    assert late.status_code == 409 and late.json()["error"]["details"]["reason"] == "DEADLINE"
    assert h.available(alice) == 1500


def test_operator_void_refunds_and_blocks_new_market_until_terminal(world):
    h, operator, alice, bob = world
    market = h.open_market(operator)
    h.wager(alice, market, "YES", 500)
    second = h.draft(operator)
    blocked = h.client.post(f"/v1/operator/markets/{second['market_id']}/open", headers=operator.h,
                            json={"operation_id": op()})
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "STALE_MARKET"
    r = h.client.post(f"/v1/operator/markets/{market['market_id']}/void", headers=operator.h,
                      json={"operation_id": op(), "note": "demo cancel"})
    assert r.status_code == 200 and r.json()["market"]["void_reason"] == "OPERATOR_CANCELLED"
    assert h.available(alice) == 2000
    assert h.open(operator, second["market_id"])["state"] == "OPEN"
    assert h.reconcile()["ok"]


def test_fixture_market_timing_validation(world):
    h, operator, *_ = world
    r = h.client.post("/v1/operator/markets", headers=operator.h,
                      json={"operation_id": op(), "question": "Too soon?", "close_in_s": 5, "resolve_in_s": 30})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_FAILED"


def test_bot_stakes_are_simulated_in_pool(world):
    h, operator, alice, _ = world
    bot = h.viewer(operator, "Bot1", is_bot=True)
    market = h.open_market(operator)
    h.wager(alice, market, "YES", 500)
    h.wager(bot, market, "NO", 700)
    pool = h.snapshot(alice)["market"]["pool"]
    assert pool == {"yes_minor": 500, "no_minor": 700, "total_minor": 1200, "simulated_minor": 700, "wager_count": 2}
