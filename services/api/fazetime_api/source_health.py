"""Source health (CONTRACTS §9.4, §9.16 item 5, D29), derived by the API from worker input.

LIVE requires, for the CURRENT epoch: a heartbeat received <= 12 s ago reporting worker_state=LIVE, and
last_media_end_ms having advanced (server receipt time) <= 12 s ago, and asr_backlog_ms <= 12,000.
Otherwise: GAP if the worker reported a discontinuity in this epoch; STOPPED if the heartbeat or the
newest media is older than 30 s (or the worker says STOPPED); CONNECTING for a new epoch without media;
STALE in between. With no worker input at all, health is STOPPED with null fields. All thresholds are
configurable (Settings.health_*). Times are server receipt times, never worker wall clocks.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from . import timeutil
from .config import Settings

TWITCH_ORIGINS = frozenset({"AI_APPROVED", "AI_AUTOMATIC"})
FIXTURE_ORIGINS = frozenset({"OPERATOR_FIXTURE", "CANNED_FIXTURE"})


def _age_s(now: datetime, value: str | None) -> float | None:
    return None if value is None else (now - timeutil.parse(value)).total_seconds()


def classify(
    now: datetime,
    *,
    has_epoch: bool,
    gap_reported: bool,
    heartbeat_at: str | None,
    heartbeat_for_current_epoch: bool,
    worker_state: str | None,
    media_advanced_at: str | None,
    asr_backlog_ms: int | None,
    settings: Settings,
) -> str:
    hb_age = _age_s(now, heartbeat_at)
    if not has_epoch:
        return "CONNECTING" if hb_age is not None and hb_age <= settings.health_stale_max_s else "STOPPED"
    if gap_reported:
        return "GAP"
    if hb_age is None or hb_age > settings.health_stale_max_s:
        return "STOPPED"
    if heartbeat_for_current_epoch and worker_state == "STOPPED":
        return "STOPPED"
    media_age = _age_s(now, media_advanced_at)
    if media_age is None:
        return "CONNECTING"
    if media_age > settings.health_stale_max_s:
        return "STOPPED"
    if (
        heartbeat_for_current_epoch
        and worker_state == "LIVE"
        and hb_age <= settings.health_live_max_s
        and media_age <= settings.health_live_max_s
        and (asr_backlog_ms or 0) <= settings.health_backlog_max_ms
    ):
        return "LIVE"
    return "STALE"


def _state_row(conn: sqlite3.Connection, stream_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM source_state WHERE stream_id = ?", (stream_id,)).fetchone()


def ensure_state(conn: sqlite3.Connection, stream_id: str) -> None:
    conn.execute("INSERT OR IGNORE INTO source_state (stream_id) VALUES (?)", (stream_id,))


def current(conn: sqlite3.Connection, stream_id: str, now: datetime, settings: Settings) -> dict:
    """The SourceHealth payload as of ``now`` (computed on read, so wagers never trust a stale cache)."""
    st = _state_row(conn, stream_id)
    epoch = None
    if st is not None and st["current_source_epoch"] is not None:
        epoch = conn.execute("SELECT * FROM source_epochs WHERE source_epoch = ?",
                             (st["current_source_epoch"],)).fetchone()
    if st is None:
        state = "STOPPED"
    else:
        # Registering an epoch is itself a sign of life: a new epoch is CONNECTING, not STOPPED (§9.4).
        seen = [t for t in (st["last_heartbeat_at_utc"], epoch["registered_at_utc"] if epoch is not None else None) if t]
        state = classify(
            now,
            has_epoch=epoch is not None,
            gap_reported=epoch is not None and epoch["gap_reported_at_utc"] is not None,
            heartbeat_at=max(seen) if seen else None,
            heartbeat_for_current_epoch=epoch is not None and st["heartbeat_epoch"] == epoch["source_epoch"],
            worker_state=st["worker_state"],
            media_advanced_at=st["last_media_advanced_at_utc"],
            asr_backlog_ms=st["asr_backlog_ms"],
            settings=settings,
        )
    return {
        "state": state,
        "source_kind": epoch["source_kind"] if epoch is not None else None,
        "source_epoch": epoch["source_epoch"] if epoch is not None else None,
        "last_media_at_utc": st["last_media_advanced_at_utc"] if st is not None and epoch is not None else None,
        "last_transcript_at_utc": st["last_transcript_at_utc"] if st is not None and epoch is not None else None,
        "updated_at_utc": timeutil.fmt(now),
    }


def refresh(conn: sqlite3.Connection, stream_id: str, now: datetime, settings: Settings) -> bool:
    """Emit one source.health event when the derived state or epoch changed. Caller holds BEGIN IMMEDIATE."""
    from . import events, views  # local import: events -> views -> source_health

    health = current(conn, stream_id, now, settings)
    ensure_state(conn, stream_id)
    st = _state_row(conn, stream_id)
    previous = (st["emitted_state"] or "STOPPED", st["emitted_epoch"])
    if (health["state"], health["source_epoch"]) == previous:
        return False
    run = views.get_active_run(conn, stream_id)
    if run is None:
        return False
    version = int(st["health_version"]) + 1
    conn.execute(
        "UPDATE source_state SET emitted_state = ?, emitted_epoch = ?, health_version = ?, state_changed_at_utc = ?"
        " WHERE stream_id = ?",
        (health["state"], health["source_epoch"], version, timeutil.fmt(now), stream_id),
    )
    events.emit(conn, stream_id=stream_id, run_id=run["run_id"], aggregate_type="SOURCE", aggregate_id=stream_id,
                aggregate_version=version, event_type="source.health", audience="PUBLIC", payload=health, now=now)
    # StreamInfo.wagering_paused (§9.15 item 2) flips when health crosses LIVE under an OPEN Twitch-origin market.
    market = views.nonterminal_market(conn, run["run_id"])
    if market is not None and market["state"] == "OPEN" and market["origin"] in TWITCH_ORIGINS:
        if (previous[0] == "LIVE") != (health["state"] == "LIVE"):
            stream = views.get_stream(conn, stream_id)
            old_version = int(stream["aggregate_version"])
            conn.execute("UPDATE streams SET aggregate_version = ? WHERE stream_id = ? AND aggregate_version = ?",
                         (old_version + 1, stream_id, old_version))
            events.emit_stream(conn, stream_id, now, settings)
    return True
