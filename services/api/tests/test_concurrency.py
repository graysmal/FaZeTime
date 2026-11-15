"""Races against the real SQLite engine with separate connections per thread (TEST_STRATEGY matrix)."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from fazetime_api import domain, timeutil
from fazetime_api.domain import Principal
from fazetime_api.errors import ApiError
from fazetime_api.schemas import WagerRequest

from .conftest import op


def _principal(h, actor) -> Principal:
    with h.svc.db.read() as conn:
        row = conn.execute("SELECT role, is_bot FROM users WHERE user_id = ?", (actor.user_id,)).fetchone()
    return Principal(actor.user_id, row["role"], bool(row["is_bot"]), actor.session_id, "2099-01-01T00:00:00.000Z")


def _race(h, principal, market, amounts, side="YES"):
    """Start len(amounts) threads at a barrier; each runs place_wager in its own BEGIN IMMEDIATE."""
    barrier = threading.Barrier(len(amounts))
    results: list[str] = []
    lock = threading.Lock()

    def worker(amount):
        req = WagerRequest(operation_id=op(), stream_session_id=market["stream_session_id"],
                           market_id=market["market_id"], rules_version=1, side=side, amount_minor=amount)
        barrier.wait()
        try:
            with h.svc.db.write() as conn:  # a fresh connection per thread
                domain.place_wager(conn, principal=principal, req=req, clock=h.clock, settings=h.svc.settings)
            outcome = "ok"
        except ApiError as exc:
            outcome = exc.code
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=worker, args=(a,)) for a in amounts]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return results


def test_two_concurrent_wagers_cannot_overdraw_repeated(world):
    h, operator, alice, _ = world
    market = h.open_market(operator)
    principal = _principal(h, alice)
    for i in range(15):
        before = h.available(alice)
        assert before == (2000 if i == 0 else 1200)
        results = _race(h, principal, market, [1200, 1200])
        assert sorted(results) == ["INSUFFICIENT_FUNDS", "ok"], results
        assert h.available(alice) == before - 1200
        assert h.credit(operator, alice.user_id, 1200 - h.available(alice)).status_code == 201
    assert h.reconcile()["ok"]


def test_many_concurrent_wagers_spend_at_most_the_balance(world):
    h, operator, alice, _ = world
    market = h.open_market(operator)
    results = _race(h, _principal(h, alice), market, [500] * 10)
    assert results.count("ok") == 4 and results.count("INSUFFICIENT_FUNDS") == 6
    assert h.available(alice) == 0
    assert h.snapshot(alice)["market"]["pool"]["yes_minor"] == 2000
    assert h.reconcile()["ok"]


def test_concurrent_http_wagers_cannot_overdraw(world):
    h, operator, alice, _ = world
    market = h.open_market(operator)
    with ThreadPoolExecutor(max_workers=6) as pool:
        codes = list(pool.map(lambda _: h.wager(alice, market, "YES", 500).status_code, range(6)))
    assert codes.count(201) == 4 and codes.count(409) == 2, codes
    assert h.available(alice) == 0
    assert h.reconcile()["ok"]


def test_concurrent_replays_of_one_key_debit_once(world):
    h, operator, alice, _ = world
    market = h.open_market(operator)
    key = op()
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda _: h.wager(alice, market, "YES", 500, operation_id=key), range(8)))
    assert sorted(r.status_code for r in responses) == [200] * 7 + [201]
    assert len({r.json()["wager_id"] for r in responses}) == 1
    assert h.available(alice) == 1500


def test_wagers_racing_the_lock(world):
    h, operator, alice, bob = world
    users = [alice, bob] + [h.viewer(operator, f"V{i}") for i in range(8)]
    market = h.open_market(operator)
    close_at = timeutil.parse(market["close_at_utc"])
    h.clock.set(close_at - timedelta(milliseconds=5))
    principals = [_principal(h, u) for u in users]
    barrier = threading.Barrier(len(users) + 1)
    outcomes: dict[str, str] = {}

    def bettor(i, principal):
        req = WagerRequest(operation_id=op(), stream_session_id=market["stream_session_id"],
                           market_id=market["market_id"], rules_version=1, side="YES" if i % 2 else "NO",
                           amount_minor=500)
        barrier.wait()
        try:
            with h.svc.db.write() as conn:
                domain.place_wager(conn, principal=principal, req=req, clock=h.clock, settings=h.svc.settings)
            outcomes[principal.user_id] = "ok"
        except ApiError as exc:
            outcomes[principal.user_id] = exc.code

    def closer():
        barrier.wait()
        for _ in range(5):
            h.clock.advance(ms=1)
        h.sweep()

    threads = [threading.Thread(target=bettor, args=(i, p)) for i, p in enumerate(principals)]
    threads.append(threading.Thread(target=closer))
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    h.sweep()
    accepted = [uid for uid, o in outcomes.items() if o == "ok"]
    assert set(outcomes.values()) <= {"ok", "MARKET_CLOSED"}
    with h.svc.db.read() as conn:
        wagers = conn.execute("SELECT accepted_at_utc, amount_minor FROM wagers WHERE market_id = ?",
                              (market["market_id"],)).fetchall()
        m = conn.execute("SELECT * FROM markets WHERE market_id = ?", (market["market_id"],)).fetchone()
    assert len(wagers) == len(accepted)
    assert all(timeutil.parse(w["accepted_at_utc"]) < close_at for w in wagers)
    assert m["yes_minor"] + m["no_minor"] == 500 * len(accepted)  # the locked pool is exactly the accepted set
    assert m["state"] in ("EVALUATING", "VOID")
    assert h.reconcile()["ok"]


def test_settle_and_void_race_has_one_terminal_outcome(world):
    h, operator, alice, bob = world
    for _ in range(5):
        market = h.open_market(operator)
        h.wager(alice, market, "YES", 500)
        h.wager(bob, market, "NO", 500)
        h.clock.set(timeutil.parse(market["close_at_utc"]))
        h.sweep()
        barrier = threading.Barrier(2)
        outcomes = []

        def settle():
            barrier.wait()
            try:
                with h.svc.db.write() as conn:
                    domain.settle_fixture_market(conn, market_id=market["market_id"], winning_side="YES",
                                                 now=h.clock.now())
                outcomes.append("settled")
            except ApiError as exc:
                outcomes.append(exc.code)

        def void():
            barrier.wait()
            try:
                with h.svc.db.write() as conn:
                    domain.operator_void(conn, market_id=market["market_id"], now=h.clock.now())
                outcomes.append("voided")
            except ApiError as exc:
                outcomes.append(exc.code)

        threads = [threading.Thread(target=settle), threading.Thread(target=void)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert sorted(outcomes) in (["MARKET_CLOSED", "settled"], ["MARKET_CLOSED", "voided"]), outcomes
        assert h.reconcile()["ok"]
