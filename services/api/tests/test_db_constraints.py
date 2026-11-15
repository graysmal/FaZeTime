"""Database-level guarantees, exercised with raw SQL that bypasses the application (P2 gate:
foreign keys, uniqueness and state constraints have meaningful tests)."""

from __future__ import annotations

import sqlite3

import pytest

from fazetime_api import db as dbmod
from fazetime_api import timeutil


@pytest.fixture
def settled(world):
    h, operator, alice, bob = world
    market = h.open_market(operator)
    h.wager(alice, market, "YES", 500)
    h.wager(bob, market, "NO", 500)
    h.clock.set(timeutil.parse(market["close_at_utc"]))
    h.sweep()
    assert h.settle(operator, market["market_id"], "YES").status_code == 200
    return h, market, alice


def _fails(h, sql, params=()):
    with pytest.raises(sqlite3.DatabaseError):
        with h.svc.db.write() as conn:
            conn.execute(sql, params)


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


def test_ledger_is_append_only(settled):
    h, *_ = settled
    for sql in ("UPDATE ledger_entries SET amount_minor = amount_minor + 1",
                "DELETE FROM ledger_entries",
                "UPDATE ledger_transactions SET reason = 'REFUND'",
                "DELETE FROM ledger_transactions",
                "DELETE FROM events", "UPDATE events SET payload_json = '{}'",
                "DELETE FROM operations", "UPDATE operations SET response_json = '{}'",
                "DELETE FROM audit_log", "DELETE FROM wagers", "DELETE FROM markets"):
        _fails(h, sql)
    assert h.reconcile()["ok"]


def test_user_balance_cannot_go_negative_but_funding_can(settled):
    h, market, alice = settled
    _fails(h, "UPDATE ledger_accounts SET balance_minor = -1, version = version + 1"
              " WHERE kind = 'USER_AVAILABLE' AND user_id = ?", (alice.user_id,))
    _fails(h, "UPDATE ledger_accounts SET balance_minor = -1, version = version + 1 WHERE kind = 'MARKET_ESCROW'")
    with h.svc.db.read() as conn:
        funding = conn.execute("SELECT balance_minor FROM ledger_accounts WHERE kind = 'FUNDING_SOURCE'").fetchone()[0]
    assert funding < 0  # seed grants are funded by a source that may go negative
    _fails(h, "UPDATE ledger_accounts SET balance_minor = 5 WHERE kind = 'USER_AVAILABLE'")  # version must +1


def test_strict_tables_reject_fractional_money(settled):
    h, market, alice = settled
    _fails(h, "INSERT INTO ledger_entries (txn_id, account_id, amount_minor)"
              " SELECT txn_id, 1, 1.5 FROM ledger_transactions LIMIT 1")


def test_market_state_machine_and_terminal_immutability(settled):
    h, market, _ = settled
    mid = market["market_id"]
    _fails(h, "UPDATE markets SET state = 'OPEN', aggregate_version = aggregate_version + 1 WHERE market_id = ?", (mid,))
    _fails(h, "UPDATE markets SET question = 'edited' WHERE market_id = ?", (mid,))
    with h.svc.db.write() as conn:
        row = conn.execute("SELECT run_id FROM markets WHERE market_id = ?", (mid,)).fetchone()
        conn.execute(
            "INSERT INTO markets (market_id, run_id, origin, state, question, yes_label, no_label, rules_version,"
            " aggregate_version, close_in_ms, resolve_in_ms, created_at_utc)"
            " VALUES ('mkt_' || lower(hex(randomblob(16))), ?, 'OPERATOR_FIXTURE', 'DRAFT', 'q', 'Yes', 'No', 1, 1,"
            " 60000, 60000, '2026-11-14T20:00:00.000Z')", (row["run_id"],))
    _fails(h, "UPDATE markets SET state = 'SETTLED', aggregate_version = 2, winning_side = 'YES',"
              " settlement_algorithm = 'x', terminal_at_utc = '2026-11-14T20:00:00.000Z' WHERE state = 'DRAFT'")


def test_one_nonterminal_market_per_run_and_one_active_run(world):
    h, operator, *_ = world
    first = h.open_market(operator)
    second = h.draft(operator)
    _fails(h, "UPDATE markets SET state = 'OPEN', aggregate_version = 2, opened_at_utc = ?, close_at_utc = ?,"
              " resolve_by_utc = ? WHERE market_id = ?",
           (first["opened_at_utc"], first["close_at_utc"], first["resolve_by_utc"], second["market_id"]))
    _fails(h, "INSERT INTO runs (run_id, stream_id, state, ai_mode, seed_grant_minor, created_at_utc)"
              " SELECT 'run_' || lower(hex(randomblob(16))), stream_id, 'ACTIVE', 'OFF', 0, '2026-11-14T20:00:00.000Z'"
              " FROM streams")


def test_wager_backstops_and_foreign_keys(settled):
    h, market, alice = settled
    _fails(h, "UPDATE wagers SET amount_minor = 1")  # immutable after the terminal transition
    _fails(h, "UPDATE wagers SET status = 'ACCEPTED'")
    _fails(h, "INSERT INTO ledger_entries (txn_id, account_id, amount_minor) VALUES ('txn_' || hex(randomblob(16)), 1, 5)")
    _fails(h, "INSERT INTO sessions (session_id, token_hash, user_id, invite_id, created_at_utc, expires_at_utc)"
              " VALUES ('ses_' || lower(hex(randomblob(16))), lower(hex(randomblob(32))), 'usr_' || lower(hex(randomblob(16))),"
              " 'inv_' || lower(hex(randomblob(16))), '2026-11-14T20:00:00.000Z', '2026-11-15T20:00:00.000Z')")
    _fails(h, "UPDATE invite_codes SET used_at_utc = NULL, used_by_user_id = NULL")  # single use
