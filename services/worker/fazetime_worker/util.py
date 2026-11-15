"""Small shared helpers: canonical UTC strings, IDs, per-epoch sequences, /proc sampling."""
from __future__ import annotations

import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone

UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
EPOCH_RE = re.compile(r"^ep_[0-9a-f]{32}$")
STREAM_RE = re.compile(r"^str_[0-9a-f]{32}$")
URL_QUERY_RE = re.compile(r"(https?://[^\s?\"'<>]+)\?[^\s\"'<>]*")
CLK_TCK = os.sysconf("SC_CLK_TCK")


def fmt_utc(dt: datetime) -> str:
    """CONTRACTS §9.1: RFC 3339 UTC with exactly three fractional digits and Z (floored to ms)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def utc_now() -> str:
    return fmt_utc(datetime.now(timezone.utc))


def mono_ns() -> int:
    return time.monotonic_ns()


def new_epoch_id() -> str:
    return f"ep_{uuid.uuid4().hex}"


def redact_urls(line: str) -> str:
    """Never keep signed playback URLs (query strings) in logs."""
    return URL_QUERY_RE.sub(r"\1?<redacted>", line)


class EpochSequencer:
    """`sequence` is a positive integer, strictly increasing per source_epoch (CONTRACTS §9.1, §9.16).

    A sequence is never reused within an epoch, and an epoch is never resumed: once a newer epoch has
    been opened, `next()` for an older epoch raises, so stale temporal context cannot be emitted.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next: dict[str, int] = {}
        self._current: str | None = None
        self._closed: set[str] = set()

    def open(self, epoch: str) -> None:
        with self._lock:
            if epoch in self._next or epoch in self._closed:
                raise ValueError(f"epoch {epoch} was already opened")
            if self._current is not None:
                self._closed.add(self._current)
                self._next.pop(self._current, None)
            self._current = epoch
            self._next[epoch] = 1

    @property
    def current(self) -> str | None:
        return self._current

    def is_current(self, epoch: str) -> bool:
        return epoch == self._current

    def next(self, epoch: str) -> int:
        with self._lock:
            if epoch != self._current:
                raise StaleEpochError(epoch)
            seq = self._next[epoch]
            self._next[epoch] = seq + 1
            return seq


class StaleEpochError(RuntimeError):
    pass


def read_proc(pid: int):
    """(cpu_ticks, rss_kib, hwm_kib) for a pid, or None if it is gone."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            s = f.read()
        rest = s[s.rindex(")") + 2:].split()
        ticks = int(rest[11]) + int(rest[12])
        rss = hwm = None
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    rss = int(line.split()[1])
                elif line.startswith("VmHWM:"):
                    hwm = int(line.split()[1])
        return ticks, rss, hwm
    except (FileNotFoundError, ProcessLookupError, ValueError, IndexError):
        return None


class CpuMeter:
    """Per-process CPU% (100 = one core) between successive samples."""

    def __init__(self) -> None:
        self._prev: dict[int, tuple[int, int]] = {}

    def sample(self, pid: int) -> dict | None:
        r = read_proc(pid)
        if r is None:
            self._prev.pop(pid, None)
            return None
        ticks, rss, hwm = r
        now = mono_ns()
        cpu = None
        if pid in self._prev:
            pt, pn = self._prev[pid]
            if now > pn:
                cpu = round((ticks - pt) / CLK_TCK / ((now - pn) / 1e9) * 100, 1)
        self._prev[pid] = (ticks, now)
        return {"cpu_pct": cpu, "rss_mib": round(rss / 1024, 1) if rss else None,
                "hwm_mib": round(hwm / 1024, 1) if hwm else None}


def loadavg() -> list[float]:
    with open("/proc/loadavg") as f:
        return [float(x) for x in f.read().split()[:3]]
