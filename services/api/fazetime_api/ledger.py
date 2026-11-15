"""Append-only double-entry ledger (ECONOMICS §2, CONTRACTS §9.5/§9.11).

* Each economic movement is one ledger_transactions row with a UNIQUE source_key plus signed
  ledger_entries that sum to exactly zero.
* Account balances are a materialized cache of their entries. Updates are compare-and-set on
  (balance, version) with the new value computed in Python ints; the DB CHECK keeps user wallets
  and escrow >= 0, while the per-run FUNDING_SOURCE may go negative.
* Callers must already hold a BEGIN IMMEDIATE transaction.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from .ids import new_id


class LedgerError(RuntimeError):
    pass


class NegativeBalance(LedgerError):
    pass


def _one(conn: sqlite3.Connection, sql: str, params: tuple) -> sqlite3.Row | None:
    return conn.execute(sql, params).fetchone()


def ensure_account(
    conn: sqlite3.Connection,
    *,
    kind: str,
    run_id: str,
    now: str,
    user_id: str | None = None,
    market_id: str | None = None,
    is_simulated: bool = False,
) -> int:
    if kind == "USER_AVAILABLE":
        row = _one(conn, "SELECT account_id FROM ledger_accounts WHERE kind = ? AND run_id = ? AND user_id = ?",
                   (kind, run_id, user_id))
    elif kind == "MARKET_ESCROW":
        row = _one(conn, "SELECT account_id FROM ledger_accounts WHERE kind = ? AND market_id = ?", (kind, market_id))
    else:
        row = _one(conn, "SELECT account_id FROM ledger_accounts WHERE kind = ? AND run_id = ?", (kind, run_id))
    if row is not None:
        return int(row["account_id"])
    cur = conn.execute(
        "INSERT INTO ledger_accounts (kind, run_id, user_id, market_id, is_simulated, balance_minor, version,"
        " created_at_utc) VALUES (?, ?, ?, ?, ?, 0, 0, ?)",
        (kind, run_id, user_id, market_id, 1 if is_simulated else 0, now),
    )
    return int(cur.lastrowid)


def wallet_account(conn: sqlite3.Connection, run_id: str, user_id: str) -> sqlite3.Row | None:
    return _one(
        conn,
        "SELECT account_id, balance_minor, version, is_simulated FROM ledger_accounts"
        " WHERE kind = 'USER_AVAILABLE' AND run_id = ? AND user_id = ?",
        (run_id, user_id),
    )


def escrow_account(conn: sqlite3.Connection, market_id: str) -> sqlite3.Row | None:
    return _one(
        conn,
        "SELECT account_id, balance_minor, version FROM ledger_accounts WHERE kind = 'MARKET_ESCROW' AND market_id = ?",
        (market_id,),
    )


def source_exists(conn: sqlite3.Connection, source_key: str) -> sqlite3.Row | None:
    return _one(conn, "SELECT txn_id, reason, run_id FROM ledger_transactions WHERE source_key = ?", (source_key,))


def post(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    reason: str,
    source_key: str,
    entries: list[tuple[int, int]],
    now: str,
    market_id: str | None = None,
    actor_user_id: str | None = None,
    operation_id: str | None = None,
    is_simulated: bool = False,
) -> str:
    """Insert one balanced transaction and apply it to account balances. Returns txn_id."""
    if not conn.in_transaction:
        raise LedgerError("ledger.post requires an open BEGIN IMMEDIATE transaction")
    if not entries:
        raise LedgerError("a ledger transaction needs entries")
    for account_id, amount in entries:
        if type(amount) is not int or amount == 0:
            raise LedgerError("entry amounts must be non-zero ints")
    if sum(amount for _, amount in entries) != 0:
        raise LedgerError("ledger transaction is not balanced")
    txn_id = new_id("txn")
    conn.execute(
        "INSERT INTO ledger_transactions (txn_id, run_id, reason, source_key, market_id, actor_user_id, operation_id,"
        " is_simulated, created_at_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (txn_id, run_id, reason, source_key, market_id, actor_user_id, operation_id, 1 if is_simulated else 0, now),
    )
    for account_id, amount in entries:
        conn.execute(
            "INSERT INTO ledger_entries (txn_id, account_id, amount_minor) VALUES (?, ?, ?)",
            (txn_id, account_id, amount),
        )
        acct = _one(conn, "SELECT kind, balance_minor, version FROM ledger_accounts WHERE account_id = ?", (account_id,))
        if acct is None:
            raise LedgerError(f"unknown account {account_id}")
        old_balance, old_version = int(acct["balance_minor"]), int(acct["version"])
        new_balance = old_balance + amount
        if new_balance < 0 and acct["kind"] != "FUNDING_SOURCE":
            raise NegativeBalance(f"account {account_id} would go negative")
        cur = conn.execute(
            "UPDATE ledger_accounts SET balance_minor = ?, version = ?"
            " WHERE account_id = ? AND balance_minor = ? AND version = ?",
            (new_balance, old_version + 1, account_id, old_balance, old_version),
        )
        if cur.rowcount != 1:
            raise LedgerError("concurrent balance change detected")
    return txn_id


def bump_version(conn: sqlite3.Connection, account_id: int) -> int:
    """Advance a wallet's balance_version without a movement (e.g. in_play drops when a stake loses).

    WalletSummary.balance_version must increase whenever any summary field changes, so clients that
    keep the highest version never discard a newer summary.
    """
    acct = _one(conn, "SELECT version FROM ledger_accounts WHERE account_id = ?", (account_id,))
    old_version = int(acct["version"])
    cur = conn.execute(
        "UPDATE ledger_accounts SET version = ? WHERE account_id = ? AND version = ?",
        (old_version + 1, account_id, old_version),
    )
    if cur.rowcount != 1:
        raise LedgerError("concurrent balance change detected")
    return old_version + 1


@dataclass
class Reconciliation:
    ok: bool
    accounts_checked: int = 0
    transactions_checked: int = 0
    markets_checked: int = 0
    problems: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "accounts_checked": self.accounts_checked,
            "transactions_checked": self.transactions_checked,
            "markets_checked": self.markets_checked,
            "problems": self.problems[:50],
        }


def reconcile(conn: sqlite3.Connection) -> Reconciliation:
    """Prove the materialized state agrees with the append-only ledger. Python-side sums only."""
    problems: list[str] = []
    entries_by_account: dict[int, int] = {}
    entries_by_txn: dict[str, int] = {}
    for row in conn.execute("SELECT txn_id, account_id, amount_minor FROM ledger_entries"):
        entries_by_account[row["account_id"]] = entries_by_account.get(row["account_id"], 0) + row["amount_minor"]
        entries_by_txn[row["txn_id"]] = entries_by_txn.get(row["txn_id"], 0) + row["amount_minor"]
    txn_count = 0
    for row in conn.execute("SELECT txn_id FROM ledger_transactions"):
        txn_count += 1
        if row["txn_id"] not in entries_by_txn:
            problems.append(f"transaction {row['txn_id']} has no entries")
        elif entries_by_txn[row["txn_id"]] != 0:
            problems.append(f"transaction {row['txn_id']} is unbalanced")
    accounts = conn.execute("SELECT account_id, kind, market_id, balance_minor FROM ledger_accounts").fetchall()
    for acct in accounts:
        expected = entries_by_account.get(acct["account_id"], 0)
        if acct["balance_minor"] != expected:
            problems.append(f"account {acct['account_id']} balance {acct['balance_minor']} != entries {expected}")
        if acct["kind"] != "FUNDING_SOURCE" and acct["balance_minor"] < 0:
            problems.append(f"account {acct['account_id']} is negative")
    escrow_by_market = {a["market_id"]: a["balance_minor"] for a in accounts if a["kind"] == "MARKET_ESCROW"}
    wagers_by_market: dict[str, list[sqlite3.Row]] = {}
    for w in conn.execute("SELECT market_id, side, amount_minor, status, is_simulated, payout_minor FROM wagers"):
        wagers_by_market.setdefault(w["market_id"], []).append(w)
    markets = conn.execute(
        "SELECT market_id, state, yes_minor, no_minor, simulated_minor, wager_count FROM markets"
    ).fetchall()
    for m in markets:
        ws = wagers_by_market.get(m["market_id"], [])
        yes = sum(w["amount_minor"] for w in ws if w["side"] == "YES")
        no = sum(w["amount_minor"] for w in ws if w["side"] == "NO")
        sim = sum(w["amount_minor"] for w in ws if w["is_simulated"])
        if (yes, no, sim, len(ws)) != (m["yes_minor"], m["no_minor"], m["simulated_minor"], m["wager_count"]):
            problems.append(f"market {m['market_id']} pool totals disagree with wagers")
        open_stakes = sum(w["amount_minor"] for w in ws if w["status"] == "ACCEPTED")
        escrow = escrow_by_market.get(m["market_id"], 0)
        if escrow != open_stakes:
            problems.append(f"market {m['market_id']} escrow {escrow} != accepted stakes {open_stakes}")
        terminal = m["state"] in ("SETTLED", "VOID")
        if terminal and any(w["status"] == "ACCEPTED" for w in ws):
            problems.append(f"terminal market {m['market_id']} still has ACCEPTED wagers")
        if not terminal and any(w["status"] != "ACCEPTED" for w in ws):
            problems.append(f"nonterminal market {m['market_id']} has terminal wagers")
        if m["state"] == "SETTLED":
            paid = sum(w["payout_minor"] or 0 for w in ws)
            if paid != yes + no:
                problems.append(f"settled market {m['market_id']} paid {paid} != pool {yes + no}")
        if m["state"] == "VOID" and any(w["status"] != "REFUNDED" for w in ws):
            problems.append(f"void market {m['market_id']} has unrefunded wagers")
    return Reconciliation(
        ok=not problems,
        accounts_checked=len(accounts),
        transactions_checked=txn_count,
        markets_checked=len(markets),
        problems=problems,
    )
