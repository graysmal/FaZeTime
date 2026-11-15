"""In-process WebSocket fanout (one API process, CONTRACTS §9.9).

A single dispatcher task reads COMMITTED outbox rows after its cursor and offers them to subscribers.
Mutations call ``notify()`` after commit (thread-safe); a 1 s poll guarantees delivery even if a
notification is missed. Delivery is at least once; clients dedupe by aggregate_version.
Subscribers register on the event loop, receiving every event after ``cursor`` at registration,
which is also the ``ready.event_hwm`` they are sent.
"""

from __future__ import annotations

import asyncio
import logging

from . import events
from .db import Database

log = logging.getLogger("fazetime.hub")


def origin_allowed(origin: str | None, allowlist: tuple[str, ...]) -> bool:
    """Exact match only (review M2): no wildcards, so an unpinned extension ID is rejected."""
    return bool(origin) and "*" not in origin and origin in allowlist


class Subscriber:
    def __init__(self, *, user_id: str, role: str, stream_id: str, maxsize: int = 1000) -> None:
        self.user_id = user_id
        self.role = role
        self.stream_id = stream_id
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self.overflowed = False

    def wants(self, row) -> bool:
        if row["stream_id"] != self.stream_id:
            return False
        audience = row["audience"]
        if audience == "PUBLIC":
            return True
        if audience == "USER":
            return row["audience_user_id"] == self.user_id
        return audience == "OPERATOR" and self.role == "OPERATOR"

    def offer(self, row, frame: dict) -> None:
        if not self.wants(row):
            return
        try:
            self.queue.put_nowait({"type": "event", "event": frame})
        except asyncio.QueueFull:
            self.overflowed = True

    def control(self, message: dict) -> None:
        try:
            self.queue.put_nowait(message)
        except asyncio.QueueFull:
            self.overflowed = True


class Hub:
    def __init__(self, db: Database, poll_interval_s: float = 1.0) -> None:
        self.db = db
        self.poll_interval_s = poll_interval_s
        self.cursor = 0
        self.subscribers: set[Subscriber] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake: asyncio.Event | None = None
        self._task: asyncio.Task | None = None
        self.dispatched = 0

    def _max_event_id(self) -> int:
        with self.db.read() as conn:
            return int(conn.execute("SELECT COALESCE(MAX(event_id), 0) FROM events").fetchone()[0])

    def _read_after(self, cursor: int):
        with self.db.read() as conn:
            return events.read_after(conn, cursor)

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._wake = asyncio.Event()
        self.cursor = await asyncio.to_thread(self._max_event_id)
        self._task = asyncio.create_task(self._run(), name="fazetime-hub")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    def notify(self) -> None:
        """Thread-safe wake-up after a commit. Never required for correctness (1 s poll)."""
        loop, wake = self._loop, self._wake
        if loop is None or wake is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(wake.set)
        except RuntimeError:
            pass

    def register(self, subscriber: Subscriber) -> int:
        self.subscribers.add(subscriber)
        return self.cursor

    def unregister(self, subscriber: Subscriber) -> None:
        self.subscribers.discard(subscriber)

    async def _run(self) -> None:
        assert self._wake is not None
        while True:
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.poll_interval_s)
            except TimeoutError:
                pass
            self._wake.clear()
            try:
                while True:
                    rows = await asyncio.to_thread(self._read_after, self.cursor)
                    if not rows:
                        break
                    for row in rows:
                        frame = events.frame(row)
                        for subscriber in list(self.subscribers):
                            subscriber.offer(row, frame)
                        self.cursor = int(row["event_id"])
                        self.dispatched += 1
            except asyncio.CancelledError:
                raise
            except Exception:  # keep fanning out; snapshots remain authoritative
                log.exception("hub dispatch failed; retrying")
                await asyncio.sleep(self.poll_interval_s)
