"""Durable market sweeper (CONTRACTS §9.3, D26).

Runs once at startup and then every second. Each step re-checks state and time inside its own
BEGIN IMMEDIATE transaction with conditional UPDATEs, so running it twice changes nothing more.
Wager acceptance never depends on the sweeper: it checks close_at_utc itself.
"""

from __future__ import annotations

import asyncio
import logging

from . import domain, timeutil
from .config import Settings
from .db import Database
from .source_health import TWITCH_ORIGINS

log = logging.getLogger("fazetime.sweeper")


def _ids(db: Database, sql: str, params: tuple = ()) -> list[str]:
    with db.read() as conn:
        return [row[0] for row in conn.execute(sql, params).fetchall()]


def sweep_once(db: Database, clock, settings: Settings) -> dict:
    result = {"locked_or_voided": 0, "evaluating": 0, "timed_out": 0, "source_gap": 0, "errors": 0}

    def step(key: str, market_ids: list[str], fn) -> None:
        for market_id in market_ids:
            try:
                with db.write() as conn:
                    if fn(conn, market_id):
                        result[key] += 1
            except Exception:
                result["errors"] += 1
                log.exception("sweeper step %s failed for %s", key, market_id)

    now_s = timeutil.fmt(clock.now())
    step("locked_or_voided",
         _ids(db, "SELECT market_id FROM markets WHERE state = 'OPEN' AND close_at_utc <= ?", (now_s,)),
         lambda conn, mid: domain.lock_if_due(conn, mid, clock.now()))
    step("evaluating",
         _ids(db, "SELECT market_id FROM markets WHERE state = 'LOCKED'"),
         lambda conn, mid: domain.evaluate_if_locked(conn, mid, clock.now()))
    now_s = timeutil.fmt(clock.now())
    step("timed_out",
         _ids(db, "SELECT market_id FROM markets WHERE state IN ('LOCKED', 'EVALUATING') AND resolve_by_utc <= ?",
              (now_s,)),
         lambda conn, mid: domain.timeout_if_due(conn, mid, clock.now()))
    placeholders = ",".join("?" for _ in TWITCH_ORIGINS)
    step("source_gap",
         _ids(db, f"SELECT market_id FROM markets WHERE state IN ('OPEN', 'LOCKED', 'EVALUATING')"
                  f" AND origin IN ({placeholders})", tuple(sorted(TWITCH_ORIGINS))),
         lambda conn, mid: domain.source_gap_if_needed(conn, mid, clock.now(), settings))
    result["changed"] = sum(v for k, v in result.items() if k != "errors")
    return result


class Sweeper:
    def __init__(self, db: Database, clock, settings: Settings, hub) -> None:
        self.db = db
        self.clock = clock
        self.settings = settings
        self.hub = hub
        self.runs = 0
        self.errors = 0
        self.last_run_at_utc: str | None = None
        self.last_result: dict | None = None

    async def run_once(self) -> dict:
        try:
            result = await asyncio.to_thread(sweep_once, self.db, self.clock, self.settings)
        except Exception:
            self.errors += 1
            log.exception("sweep failed")
            return {"changed": 0, "errors": 1}
        self.runs += 1
        self.errors += result["errors"]
        self.last_run_at_utc = timeutil.fmt(self.clock.now())
        self.last_result = result
        if result["changed"]:
            self.hub.notify()
        return result

    async def run_forever(self) -> None:
        while True:
            await asyncio.sleep(self.settings.sweeper_interval_s)
            await self.run_once()
