"""Builders that turn committed rows into §9.13 wire payloads. Read-only; Python-side sums only."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from . import ledger, source_health, timeutil
from .config import Settings
from .schemas import SETTLEMENT_ALGORITHM, UNRESOLVED_REASONS

NONTERMINAL = ("OPEN", "LOCKED", "EVALUATING")
TERMINAL = ("SETTLED", "VOID")


def get_stream(conn: sqlite3.Connection, stream_id: str | None = None) -> sqlite3.Row | None:
    if stream_id is None:
        return conn.execute("SELECT * FROM streams ORDER BY rowid LIMIT 1").fetchone()
    return conn.execute("SELECT * FROM streams WHERE stream_id = ?", (stream_id,)).fetchone()


def get_active_run(conn: sqlite3.Connection, stream_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM runs WHERE stream_id = ? AND state = 'ACTIVE'", (stream_id,)).fetchone()


def get_run(conn: sqlite3.Connection, run_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()


def get_market(conn: sqlite3.Connection, market_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM markets WHERE market_id = ?", (market_id,)).fetchone()


def nonterminal_market(conn: sqlite3.Connection, run_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM markets WHERE run_id = ? AND state IN ('OPEN', 'LOCKED', 'EVALUATING')", (run_id,)
    ).fetchone()


def display_market(conn: sqlite3.Connection, run_id: str) -> sqlite3.Row | None:
    """The nonterminal market, else the latest terminal market in the run, else None (never DRAFT)."""
    row = nonterminal_market(conn, run_id)
    if row is not None:
        return row
    return conn.execute(
        "SELECT * FROM markets WHERE run_id = ? AND state IN ('SETTLED', 'VOID')"
        " ORDER BY terminal_at_utc DESC, rowid DESC LIMIT 1",
        (run_id,),
    ).fetchone()


def max_event_id(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT MAX(event_id) FROM events").fetchone()
    return int(row[0] or 0)


def in_play_minor(conn: sqlite3.Connection, run_id: str, user_id: str) -> int:
    rows = conn.execute(
        "SELECT amount_minor FROM wagers WHERE run_id = ? AND user_id = ? AND status = 'ACCEPTED'", (run_id, user_id)
    ).fetchall()
    return sum(int(r["amount_minor"]) for r in rows)


def wallet_summary(conn: sqlite3.Connection, run_id: str, user_id: str) -> dict:
    acct = ledger.wallet_account(conn, run_id, user_id)
    return {
        "stream_session_id": run_id,
        "available_minor": int(acct["balance_minor"]) if acct else 0,
        "in_play_minor": in_play_minor(conn, run_id, user_id),
        "balance_version": int(acct["version"]) if acct else 0,
        "pending_topup_minor": None,
    }


def _json_or_none(value: str | None):
    return json.loads(value) if value else None


def _frame_ids(refs: list[dict] | None) -> list[str] | None:
    """Public evidence lists carry frame evidence IDs (evd_) only; transcript refs stay operator-side."""
    if refs is None:
        return None
    out: list[str] = []
    for ref in refs:
        evidence_id = ref.get("evidence_id")
        if evidence_id and evidence_id not in out:
            out.append(evidence_id)
    return out


def ai_fields(row: sqlite3.Row, *, viewer: bool) -> dict:
    """§9.17 item 6: criteria.YES / criteria.NO carry the predicates, frozen at OPEN. Null for fixture markets.
    resolution_reason is untrusted model text: operator views only, null in viewer payloads (D31)."""
    return {
        "criteria": _json_or_none(row["criteria_json"]),
        "opening_evidence_ids": _frame_ids(_json_or_none(row["opening_evidence_json"])),
        "resolution_evidence_ids": _frame_ids(_json_or_none(row["resolution_evidence_json"])),
        "resolution_mode": row["resolution_mode"],
        "resolution_reason": None if viewer else row["resolution_reason"],
    }


def public_market(row: sqlite3.Row) -> dict:
    if row["state"] == "DRAFT":
        raise ValueError("DRAFT markets never appear in viewer payloads")
    yes, no = int(row["yes_minor"]), int(row["no_minor"])
    return {
        "market_id": row["market_id"],
        "stream_session_id": row["run_id"],
        "rules_version": int(row["rules_version"]),
        "aggregate_version": int(row["aggregate_version"]),
        "state": row["state"],
        "origin": row["origin"],
        "question": row["question"],
        "yes_label": row["yes_label"],
        "no_label": row["no_label"],
        "opened_at_utc": row["opened_at_utc"],
        "close_at_utc": row["close_at_utc"],
        "resolve_by_utc": row["resolve_by_utc"],
        "locked_at_utc": row["locked_at_utc"],
        "terminal_at_utc": row["terminal_at_utc"],
        "pool": {
            "yes_minor": yes,
            "no_minor": no,
            "total_minor": yes + no,
            "simulated_minor": int(row["simulated_minor"]),
            "wager_count": int(row["wager_count"]),
        },
        "winning_side": row["winning_side"],
        "void_reason": row["void_reason"],
        "settlement_algorithm": row["settlement_algorithm"],
        **ai_fields(row, viewer=True),
    }


def operator_market(row: sqlite3.Row) -> dict:
    """Operator-only view: the PublicMarket fields (DRAFT allowed) plus the draft durations."""
    yes, no = int(row["yes_minor"]), int(row["no_minor"])
    return {
        "market_id": row["market_id"],
        "stream_session_id": row["run_id"],
        "rules_version": int(row["rules_version"]),
        "aggregate_version": int(row["aggregate_version"]),
        "state": row["state"],
        "origin": row["origin"],
        "question": row["question"],
        "yes_label": row["yes_label"],
        "no_label": row["no_label"],
        "opened_at_utc": row["opened_at_utc"],
        "close_at_utc": row["close_at_utc"],
        "resolve_by_utc": row["resolve_by_utc"],
        "locked_at_utc": row["locked_at_utc"],
        "terminal_at_utc": row["terminal_at_utc"],
        "pool": {
            "yes_minor": yes,
            "no_minor": no,
            "total_minor": yes + no,
            "simulated_minor": int(row["simulated_minor"]),
            "wager_count": int(row["wager_count"]),
        },
        "winning_side": row["winning_side"],
        "void_reason": row["void_reason"],
        "settlement_algorithm": row["settlement_algorithm"],
        **ai_fields(row, viewer=False),
        "close_in_s": max(1, int(row["close_in_ms"]) // 1000),
        "resolve_in_s": int(row["resolve_in_ms"]) // 1000,
        "created_at_utc": row["created_at_utc"],
    }


def operator_ai_detail(row: sqlite3.Row) -> dict:
    """Operator-only AI provenance: candidate, full evidence refs (incl. transcript refs), cancellation rules."""
    return {
        "candidate_id": row["candidate_cnd_id"],
        "cancellation_conditions": _json_or_none(row["cancellation_json"]),
        "opening_evidence": _json_or_none(row["opening_evidence_json"]),
        "resolution_id": row["resolution_rsl_id"],
        "resolution_evidence": _json_or_none(row["resolution_evidence_json"]),
    }


def wager_receipt(row: sqlite3.Row, *, replayed: bool = False) -> dict:
    return {
        "schema_version": 1,
        "wager_id": row["wager_id"],
        "operation_id": row["operation_id"],
        "stream_session_id": row["run_id"],
        "market_id": row["market_id"],
        "rules_version": int(row["rules_version"]),
        "side": row["side"],
        "amount_minor": int(row["amount_minor"]),
        "status": row["status"],
        "accepted_at_utc": row["accepted_at_utc"],
        "terminal_at_utc": row["terminal_at_utc"],
        "stake_txn_id": row["stake_txn_id"],
        "terminal_txn_id": row["terminal_txn_id"],
        "payout_minor": row["payout_minor"],
        "refund_minor": row["refund_minor"],
        "market_aggregate_version": int(row["market_aggregate_version"]),
        "wallet_after": {
            "stream_session_id": row["run_id"],
            "available_minor": int(row["wallet_after_available_minor"]),
            "in_play_minor": int(row["wallet_after_in_play_minor"]),
            "balance_version": int(row["wallet_after_balance_version"]),
            "pending_topup_minor": None,
        },
        "replayed": replayed,
    }


def modes(run: sqlite3.Row | None, media_source_kind: str | None = None, payment_mode: str = "UNAVAILABLE") -> dict:
    return {
        "ai_mode": run["ai_mode"] if run is not None else "OFF",
        "payment_mode": payment_mode,  # STRIPE_TEST only when P6 loaded both test secrets (Settings.payment_mode)
        "media_source_kind": media_source_kind,  # the current epoch's source_kind, null without a worker
    }


def pause_state(market: sqlite3.Row | None, health_state: str) -> tuple[bool, str | None]:
    if market is not None and market["state"] == "OPEN" and market["origin"] in source_health.TWITCH_ORIGINS:
        if health_state != "LIVE":
            return True, "SOURCE_NOT_LIVE"
    return False, None


def stream_info(
    conn: sqlite3.Connection, stream: sqlite3.Row, run: sqlite3.Row, now: datetime, settings: Settings
) -> dict:
    health = source_health.current(conn, stream["stream_id"], now, settings)
    paused, reason = pause_state(nonterminal_market(conn, run["run_id"]), health["state"])
    return {
        "stream_id": stream["stream_id"],
        "twitch_channel_login": stream["twitch_channel_login"],
        "stream_session_id": run["run_id"],
        "run_state": run["state"],
        "aggregate_version": int(stream["aggregate_version"]),
        "wagering_paused": paused,
        "wagering_paused_reason": reason,
    }


def my_position(conn: sqlite3.Connection, market: sqlite3.Row, user_id: str) -> dict:
    rows = conn.execute(
        "SELECT * FROM wagers WHERE market_id = ? AND user_id = ? ORDER BY accepted_at_utc, wager_id",
        (market["market_id"], user_id),
    ).fetchall()
    stake_total = sum(int(r["amount_minor"]) for r in rows)
    side = rows[0]["side"] if rows else None
    payout_total = refund_total = None
    if not rows:
        result = "NONE"
    elif market["state"] in NONTERMINAL:
        result = "PENDING"
    elif market["state"] == "SETTLED":
        result = "WON" if side == market["winning_side"] else "LOST"
        payout_total = sum(int(r["payout_minor"] or 0) for r in rows)
    else:
        result = "UNRESOLVED_REFUNDED" if market["void_reason"] in UNRESOLVED_REASONS else "VOID_REFUNDED"
        refund_total = sum(int(r["refund_minor"] or 0) for r in rows)
    return {
        "market_id": market["market_id"],
        "side": side,
        "stake_total_minor": stake_total,
        "result": result,
        "payout_total_minor": payout_total,
        "refund_total_minor": refund_total,
        "wagers": [wager_receipt(r) for r in rows],
    }


def limits(settings: Settings) -> dict:
    lim = settings.limits
    return {
        "stake_min_minor": lim.stake_min_minor,
        "stake_max_minor": lim.stake_max_minor,
        "stake_step_minor": lim.stake_step_minor,
        "stake_default_minor": lim.stake_default_minor,
        "topup_presets_minor": list(lim.topup_presets_minor),
        "topup_min_minor": lim.topup_min_minor,
        "topup_max_minor": lim.topup_max_minor,
        "topup_step_minor": lim.topup_step_minor,
    }


def snapshot(
    conn: sqlite3.Connection, stream: sqlite3.Row, user_id: str, now: datetime, settings: Settings
) -> dict:
    """Built inside ONE read transaction by the caller; event_hwm is the max committed event_id."""
    run = get_active_run(conn, stream["stream_id"])
    if run is None:
        raise LookupError("stream has no active run")
    market = display_market(conn, run["run_id"])
    health = source_health.current(conn, stream["stream_id"], now, settings)
    return {
        "schema_version": 1,
        "server_time_utc": timeutil.fmt(now),
        "event_hwm": max_event_id(conn),
        "stream": stream_info(conn, stream, run, now, settings),
        "modes": modes(run, health["source_kind"], settings.payment_mode),
        "limits": limits(settings),
        "source_health": health,
        "market": public_market(market) if market is not None else None,
        "my_position": my_position(conn, market, user_id) if market is not None else None,
        "wallet": wallet_summary(conn, run["run_id"], user_id),
        "raffle": None,
    }


def me(conn: sqlite3.Connection, principal, now: datetime) -> dict:
    user = conn.execute("SELECT * FROM users WHERE user_id = ?", (principal.user_id,)).fetchone()
    stream = get_stream(conn)
    run = get_active_run(conn, stream["stream_id"]) if stream is not None else None
    current_stream = None
    wallet = None
    if stream is not None and run is not None:
        current_stream = {
            "stream_id": stream["stream_id"],
            "twitch_channel_login": stream["twitch_channel_login"],
            "stream_session_id": run["run_id"],
        }
        wallet = wallet_summary(conn, run["run_id"], principal.user_id) if user["role"] == "VIEWER" else None
    return {
        "schema_version": 1,
        "server_time_utc": timeutil.fmt(now),
        "user": {
            "user_id": user["user_id"],
            "display_name": user["display_name"],
            "claimed_twitch_login": user["claimed_twitch_login"],
            "role": user["role"],
        },
        "session": {"session_id": principal.session_id, "expires_at_utc": principal.session_expires_at_utc},
        "current_stream": current_stream,
        "wallet": wallet,
    }


__all__ = [
    "SETTLEMENT_ALGORITHM",
    "display_market",
    "get_active_run",
    "get_market",
    "get_run",
    "get_stream",
    "me",
    "my_position",
    "operator_market",
    "public_market",
    "snapshot",
    "stream_info",
    "wager_receipt",
    "wallet_summary",
]
