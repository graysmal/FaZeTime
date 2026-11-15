"""Database-level guarantees exercised with raw SQL that bypasses the application. Each case asserts the
SPECIFIC trigger/constraint message, so a different failure cannot satisfy it (review M3)."""

from __future__ import annotations

import sqlite3

import pytest

from fazetime_api import db as dbmod
from fazetime_api import timeutil
from fazetime_api.ids import new_id

FROZEN = "market terms are frozen after OPEN"
POOL = "pool totals only grow, and only while OPEN"
APPEND = "append-only|kept for the life of the database|never deleted"


def _fails(h, match: str, sql: str, params: tuple = ()) -> None:
    with pytest.raises(sqlite3.IntegrityError, match=match):
        with h.svc.db.write() as conn:
            conn.execute(sql, params)


@pytest.fixture
def opened(world):
    h, operator, alice, bob = world
    market = h.open_market(operator)
    assert h.wager(alice, market, "YES", 500).status_code == 201
    return h, market, alice, bob


@pytest.fixture
def evaluating(opened):
    h, market, alice, bob = opened
    assert h.wager(bob, market, "NO", 500).status_code == 201
    h.clock.set(timeutil.parse(market["close_at_utc"]))
    h.sweep()
    return h, market, alice, bob


def _row(h, market_id):
    with h.svc.db.read() as conn:
        return conn.execute("SELECT * FROM markets WHERE market_id = ?", (market_id,)).fetchone()


def test_every_connection_has_required_pragmas(tmp_path):
    conn = dbmod.connect(str(tmp_path / "p.db"))
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"  # never WAL (D23)
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 2
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        assert conn.isolation_level is None
    finally:
        conn.close()


def test_open_market_terms_are_frozen_even_with_a_version_bump(opened):
    h, market, *_ = opened
    v = _row(h, market["market_id"])["aggregate_version"]
    _fails(h, FROZEN, "UPDATE markets SET question = 'edited', aggregate_version = ? WHERE market_id = ?",
           (v + 1, market["market_id"]))
    _fails(h, FROZEN, "UPDATE markets SET close_at_utc = '2099-01-01T00:00:00.000Z', aggregate_version = ?"
                      " WHERE market_id = ?", (v + 1, market["market_id"]))


def test_open_pool_cannot_decrease(opened):
    h, market, *_ = opened
    v = _row(h, market["market_id"])["aggregate_version"]
    _fails(h, POOL, "UPDATE markets SET yes_minor = 100, aggregate_version = ? WHERE market_id = ?",
           (v + 1, market["market_id"]))


def test_pool_cannot_change_while_evaluating(evaluating):
    h, market, *_ = evaluating
    row = _row(h, market["market_id"])
    assert row["state"] == "EVALUATING"
    _fails(h, POOL, "UPDATE markets SET yes_minor = ?, aggregate_version = ? WHERE market_id = ?",
           (row["yes_minor"] + 100, row["aggregate_version"] + 1, market["market_id"]))


def _wager_insert(h, market_id, user_id, side, accepted_at):
    """Raw INSERT with a fresh stake transaction, so only the wager trigger under test can fail."""
    with h.svc.db.write() as conn:
        m = conn.execute("SELECT run_id, rules_version, aggregate_version FROM markets WHERE market_id = ?",
                         (market_id,)).fetchone()
        txn = new_id("txn")
        conn.execute("INSERT INTO ledger_transactions (txn_id, run_id, reason, source_key, created_at_utc)"
                     " VALUES (?, ?, 'WAGER_STAKE', ?, ?)", (txn, m["run_id"], f"test:{txn}", accepted_at))
    return (
        "INSERT INTO wagers (wager_id, market_id, run_id, user_id, operation_id, side, amount_minor, is_simulated,"
        " rules_version, status, version, accepted_at_utc, stake_txn_id, market_aggregate_version,"
        " wallet_after_available_minor, wallet_after_in_play_minor, wallet_after_balance_version)"
        " VALUES (?, ?, ?, ?, '00000000-0000-4000-8000-000000000999', ?, 100, 0, ?, 'ACCEPTED', 1, ?, ?, ?, 0, 0, 0)",
        (new_id("wgr"), market_id, m["run_id"], user_id, side, m["rules_version"], accepted_at, txn,
         m["aggregate_version"]),
    )


def test_wager_at_or_after_close_is_rejected_by_trigger(opened):
    h, market, alice, bob = opened
    sql, params = _wager_insert(h, market["market_id"], bob.user_id, "NO", market["close_at_utc"])
    _fails(h, "wager requires an OPEN market of the same run before close_at_utc", sql, params)


def test_opposite_side_wager_is_rejected_by_trigger(opened):
    h, market, alice, _ = opened
    sql, params = _wager_insert(h, market["market_id"], alice.user_id, "NO", market["opened_at_utc"])
    _fails(h, "one side per user per market", sql, params)


def test_foreign_keys_are_enforced(world):
    h, *_ = world
    _fails(h, "FOREIGN KEY constraint failed",
           "INSERT INTO audit_log (actor_user_id, actor_kind, action, created_at_utc) VALUES (?, 'OPERATOR', 'x', ?)",
           (new_id("usr"), "2026-11-14T20:00:00.000Z"))


def test_ledger_and_outbox_are_append_only(evaluating):
    h, *_ = evaluating
    for sql in ("UPDATE ledger_entries SET amount_minor = amount_minor + 1", "DELETE FROM ledger_entries",
                "UPDATE ledger_transactions SET reason = 'REFUND'", "DELETE FROM ledger_transactions",
                "DELETE FROM events", "UPDATE events SET payload_json = '{}'", "DELETE FROM operations",
                "UPDATE operations SET response_json = '{}'", "DELETE FROM audit_log", "DELETE FROM wagers",
                "DELETE FROM markets"):
        _fails(h, APPEND, sql)
    assert h.reconcile()["ok"]


def test_balances_cannot_go_negative_and_versions_must_step(opened):
    h, market, alice, _ = opened
    _fails(h, r"CHECK constraint failed: kind = 'FUNDING_SOURCE' OR balance_minor >= 0",
           "UPDATE ledger_accounts SET balance_minor = -1, version = version + 1"
           " WHERE kind = 'USER_AVAILABLE' AND user_id = ?", (alice.user_id,))
    _fails(h, r"CHECK constraint failed: kind = 'FUNDING_SOURCE' OR balance_minor >= 0",
           "UPDATE ledger_accounts SET balance_minor = -1, version = version + 1 WHERE kind = 'MARKET_ESCROW'")
    _fails(h, "version increments by exactly one", "UPDATE ledger_accounts SET balance_minor = 5 WHERE kind = 'USER_AVAILABLE'")
    with h.svc.db.read() as conn:
        assert conn.execute("SELECT balance_minor FROM ledger_accounts WHERE kind = 'FUNDING_SOURCE'").fetchone()[0] < 0


def test_strict_tables_reject_fractional_money(opened):
    h, *_ = opened
    _fails(h, "cannot store REAL value in INTEGER column ledger_entries.amount_minor",
           "INSERT INTO ledger_entries (txn_id, account_id, amount_minor)"
           " SELECT txn_id, (SELECT account_id FROM ledger_accounts WHERE run_id = t.run_id LIMIT 1), 1.5"
           " FROM ledger_transactions t LIMIT 1")


def test_state_machine_terminal_immutability_and_uniqueness(evaluating):
    h, market, *_ = evaluating
    row = _row(h, market["market_id"])
    _fails(h, "illegal market state transition", "UPDATE markets SET state = 'OPEN', aggregate_version = ?"
                                                 " WHERE market_id = ?", (row["aggregate_version"] + 1, market["market_id"]))
    with h.svc.db.write() as conn:
        conn.execute(
            "INSERT INTO markets (market_id, run_id, origin, state, question, yes_label, no_label, rules_version,"
            " aggregate_version, close_in_ms, resolve_in_ms, created_at_utc) VALUES (?, ?, 'OPERATOR_FIXTURE',"
            " 'DRAFT', 'q', 'Yes', 'No', 1, 1, 60000, 60000, '2026-11-14T20:00:00.000Z')",
            (new_id("mkt"), row["run_id"]))
    _fails(h, "UNIQUE constraint failed: markets.run_id",
           "UPDATE markets SET state = 'OPEN', aggregate_version = 2, opened_at_utc = ?, close_at_utc = ?,"
           " resolve_by_utc = ? WHERE state = 'DRAFT'", (row["opened_at_utc"], row["close_at_utc"], row["resolve_by_utc"]))
    _fails(h, "UNIQUE constraint failed: runs.stream_id",
           "INSERT INTO runs (run_id, stream_id, state, ai_mode, seed_grant_minor, created_at_utc)"
           " SELECT ?, stream_id, 'ACTIVE', 'OFF', 0, '2026-11-14T20:00:00.000Z' FROM streams", (new_id("run"),))
    _fails(h, "invite codes are single use", "UPDATE invite_codes SET used_at_utc = NULL, used_by_user_id = NULL")
