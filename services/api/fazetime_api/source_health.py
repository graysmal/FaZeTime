"""Source health (CONTRACTS §9.4, D29).

The API derives health from worker observations using received_at_utc. P3 supplies observations;
until then there are none, so health is STOPPED with null fields. The pure classifier below is the
threshold rule P3 will feed: LIVE <= 12 s, STALE 12-30 s, STOPPED > 30 s (configurable).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from . import timeutil
from .config import Settings

TWITCH_ORIGINS = frozenset({"AI_APPROVED", "AI_AUTOMATIC"})
FIXTURE_ORIGINS = frozenset({"OPERATOR_FIXTURE", "CANNED_FIXTURE"})


def classify(
    now: datetime,
    *,
    last_media_at: datetime | None,
    last_heartbeat_at: datetime | None,
    gap_reported: bool = False,
    epoch_started: bool = True,
    live_max_s: float = 12.0,
    stale_max_s: float = 30.0,
) -> str:
    if gap_reported:
        return "GAP"
    if last_heartbeat_at is None or (now - last_heartbeat_at).total_seconds() > stale_max_s:
        return "STOPPED"
    if last_media_at is None:
        return "CONNECTING" if epoch_started else "STOPPED"
    age = (now - last_media_at).total_seconds()
    if age <= live_max_s:
        return "LIVE"
    if age <= stale_max_s:
        return "STALE"
    return "STOPPED"


def current(conn: sqlite3.Connection, stream_id: str, now: datetime, settings: Settings) -> dict:
    """P2: no media worker exists yet, so the honest answer is STOPPED with null fields."""
    del conn, stream_id, settings
    return {
        "state": "STOPPED",
        "source_kind": None,
        "source_epoch": None,
        "last_media_at_utc": None,
        "last_transcript_at_utc": None,
        "updated_at_utc": timeutil.fmt(now),
    }
