"""Presence heartbeats (P2-C). Server-stamped last_seen; aggregated per (user, stream); TTL 45 s.

Multiple tabs/devices never create users or wallets and never touch the ledger or raffle weight.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from . import timeutil, views
from .config import Settings
from .domain import Principal
from .errors import ApiError
from .schemas import PresenceHeartbeat


def heartbeat(conn: sqlite3.Connection, *, principal: Principal, req: PresenceHeartbeat, now: datetime,
              settings: Settings) -> dict:
    stream = views.get_stream(conn, req.stream_id)
    run = views.get_active_run(conn, req.stream_id) if stream is not None else None
    if stream is None or run is None:
        raise ApiError("NOT_FOUND", "Unknown stream.")
    now_s = timeutil.fmt(now)
    conn.execute(
        "INSERT INTO presence (user_id, device_id, stream_id, session_id, run_id, tab_instance_id,"
        " observed_channel_login, page_visibility, player_state, extension_version, first_seen_utc,"
        " last_seen_utc, heartbeat_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)"
        " ON CONFLICT (user_id, device_id, stream_id) DO UPDATE SET session_id = excluded.session_id,"
        " run_id = excluded.run_id, tab_instance_id = excluded.tab_instance_id,"
        " observed_channel_login = excluded.observed_channel_login, page_visibility = excluded.page_visibility,"
        " player_state = excluded.player_state, extension_version = excluded.extension_version,"
        " last_seen_utc = excluded.last_seen_utc, heartbeat_count = presence.heartbeat_count + 1",
        (principal.user_id, req.device_id, req.stream_id, principal.session_id, run["run_id"], req.tab_instance_id,
         req.observed_channel_login, req.page_visibility, req.player_state, req.extension_version, now_s, now_s),
    )
    return {
        "schema_version": 1,
        "server_time_utc": now_s,
        "last_seen_utc": now_s,
        "presence_state": "PRESENT",
        "heartbeat_interval_ms": settings.presence_heartbeat_interval_ms,
        "presence_ttl_ms": settings.presence_ttl_ms,
        "current_stream_session_id": run["run_id"],
    }


def summary(conn: sqlite3.Connection, stream_id: str, now: datetime, settings: Settings) -> dict:
    """Aggregate per user: PRESENT iff any device heartbeat is younger than the TTL (computed on read)."""
    cutoff = timeutil.fmt(now - timedelta(milliseconds=settings.presence_ttl_ms))
    rows = conn.execute(
        "SELECT p.user_id, u.display_name, u.is_bot, p.device_id, p.last_seen_utc, p.page_visibility,"
        " p.player_state FROM presence p JOIN users u ON u.user_id = p.user_id WHERE p.stream_id = ?"
        " ORDER BY p.user_id, p.last_seen_utc DESC",
        (stream_id,),
    ).fetchall()
    users: dict[str, dict] = {}
    for r in rows:
        entry = users.get(r["user_id"])
        if entry is None:  # first row per user is its freshest heartbeat
            entry = users[r["user_id"]] = {
                "user_id": r["user_id"], "display_name": r["display_name"], "is_bot": bool(r["is_bot"]),
                "last_seen_utc": r["last_seen_utc"], "page_visibility": r["page_visibility"],
                "player_state": r["player_state"], "devices": 0, "fresh_devices": 0,
            }
        entry["devices"] += 1
        if r["last_seen_utc"] > cutoff:
            entry["fresh_devices"] += 1
    for entry in users.values():
        entry["presence_state"] = "PRESENT" if entry["fresh_devices"] else "ABSENT"
    listed = list(users.values())
    return {
        "ttl_ms": settings.presence_ttl_ms,
        "present_users": sum(1 for u in listed if u["presence_state"] == "PRESENT"),
        "users": listed,
        "note": "presence = extension reports the channel open; not proof of attention",
    }
