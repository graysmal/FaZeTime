"""Authoritative server time. Wire/storage format: UTC RFC 3339, exactly 3 fractional digits, 'Z'."""

from __future__ import annotations

import re
import threading
from datetime import datetime, timedelta, timezone

UTC_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
_UTC_RE = re.compile(UTC_PATTERN)


def floor_ms(dt: datetime) -> datetime:
    return dt.replace(microsecond=(dt.microsecond // 1000) * 1000)


def fmt(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise ValueError("naive datetimes are not allowed")
    dt = floor_ms(dt.astimezone(timezone.utc))
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse(value: str) -> datetime:
    if not _UTC_RE.match(value):
        raise ValueError(f"not a canonical UTC timestamp: {value!r}")
    return datetime.strptime(value[:-1] + "000", "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=timezone.utc)


class Clock:
    """Real clock, truncated to milliseconds so comparisons match the stored precision."""

    def now(self) -> datetime:
        return floor_ms(datetime.now(timezone.utc))


class FakeClock(Clock):
    """Deterministic clock for tests. Thread-safe."""

    def __init__(self, start: datetime | str = "2026-11-14T20:00:00.000Z") -> None:
        self._lock = threading.Lock()
        self._now = parse(start) if isinstance(start, str) else floor_ms(start)

    def now(self) -> datetime:
        with self._lock:
            return self._now

    def set(self, value: datetime | str) -> None:
        with self._lock:
            self._now = parse(value) if isinstance(value, str) else floor_ms(value)

    def advance(self, seconds: float = 0.0, ms: int = 0) -> datetime:
        with self._lock:
            self._now = self._now + timedelta(seconds=seconds, milliseconds=ms)
            return self._now
