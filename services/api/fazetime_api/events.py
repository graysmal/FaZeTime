"""Durable domain events (outbox). Rows are inserted in the same transaction as the mutation; the
WebSocket hub only ever reads committed rows (CONTRACTS §7, §9.9)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from . import timeutil, views
from .config import Settings
from .schemas import validate_event_payload


def emit(
    conn: sqlite3.Connection,
    *,
    stream_id: str,
    run_id: str,
    aggregate_type: str,
    aggregate_id: str,
    aggregate_version: int,
    event_type: str,
    audience: str,
    payload: dict,
    now: datetime,
    audience_user_id: str | None = None,
) -> int:
    validate_event_payload(event_type, payload)  # an invalid payload aborts the whole transaction
    cur = conn.execute(
        "INSERT INTO events (stream_id, run_id, aggregate_type, aggregate_id, aggregate_version, event_type,"
        " audience, audience_user_id, occurred_at_utc, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            stream_id,
            run_id,
            aggregate_type,
            aggregate_id,
            aggregate_version,
            event_type,
            audience,
            audience_user_id,
            timeutil.fmt(now),
            json.dumps(payload, separators=(",", ":")),
        ),
    )
    return int(cur.lastrowid)


def stream_id_for_run(conn: sqlite3.Connection, run_id: str) -> str:
    return conn.execute("SELECT stream_id FROM runs WHERE run_id = ?", (run_id,)).fetchone()["stream_id"]


def emit_market(conn: sqlite3.Connection, market_id: str, event_type: str, now: datetime) -> int:
    row = views.get_market(conn, market_id)
    return emit(
        conn,
        stream_id=stream_id_for_run(conn, row["run_id"]),
        run_id=row["run_id"],
        aggregate_type="MARKET",
        aggregate_id=row["market_id"],
        aggregate_version=int(row["aggregate_version"]),
        event_type=event_type,
        audience="PUBLIC",
        payload=views.public_market(row),
        now=now,
    )


def wallet_aggregate_id(run_id: str, user_id: str) -> str:
    """WALLET aggregate id is the user_id (fixture event/wallet_changed). Wallets are per (user, run) and
    balance_version restarts at 1 in a new run, so clients key wallet versions by (stream_session_id,
    aggregate_id) and refetch on a run change (§9.9)."""
    del run_id
    return user_id


def emit_wallet(conn: sqlite3.Connection, run_id: str, user_id: str, now: datetime) -> int:
    summary = views.wallet_summary(conn, run_id, user_id)
    return emit(
        conn,
        stream_id=stream_id_for_run(conn, run_id),
        run_id=run_id,
        aggregate_type="WALLET",
        aggregate_id=wallet_aggregate_id(run_id, user_id),
        aggregate_version=max(1, summary["balance_version"]),
        event_type="wallet.changed",
        audience="USER",
        audience_user_id=user_id,
        payload=summary,
        now=now,
    )


def emit_wager(conn: sqlite3.Connection, wager_id: str, now: datetime) -> int:
    row = conn.execute("SELECT * FROM wagers WHERE wager_id = ?", (wager_id,)).fetchone()
    return emit(
        conn,
        stream_id=stream_id_for_run(conn, row["run_id"]),
        run_id=row["run_id"],
        aggregate_type="WAGER",
        aggregate_id=row["wager_id"],
        aggregate_version=int(row["version"]),
        event_type="wager.updated",
        audience="USER",
        audience_user_id=row["user_id"],
        payload=views.wager_receipt(row),
        now=now,
    )


def emit_stream(conn: sqlite3.Connection, stream_id: str, now: datetime, settings: Settings) -> int:
    stream = views.get_stream(conn, stream_id)
    run = views.get_active_run(conn, stream_id)
    return emit(
        conn,
        stream_id=stream_id,
        run_id=run["run_id"],
        aggregate_type="STREAM",
        aggregate_id=stream_id,
        aggregate_version=int(stream["aggregate_version"]),
        event_type="stream.updated",
        audience="PUBLIC",
        payload={"stream": views.stream_info(conn, stream, run, now, settings),
                 "modes": views.modes(run, payment_mode=settings.payment_mode, open_access=settings.open_access)},
        now=now,
    )


def frame(row: sqlite3.Row) -> dict:
    return {
        "schema_version": 1,
        "event_id": int(row["event_id"]),
        "stream_session_id": row["run_id"],
        "aggregate_type": row["aggregate_type"],
        "aggregate_id": row["aggregate_id"],
        "aggregate_version": int(row["aggregate_version"]),
        "event_type": row["event_type"],
        "audience": row["audience"],
        "occurred_at_utc": row["occurred_at_utc"],
        "payload": json.loads(row["payload_json"]),
    }


def read_after(conn: sqlite3.Connection, after_event_id: int, limit: int = 500) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM events WHERE event_id > ? ORDER BY event_id LIMIT ?", (after_event_id, limit)
    ).fetchall()
