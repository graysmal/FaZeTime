"""In-memory sliding-window rate limiter. Valid only because there is exactly one API process."""

from __future__ import annotations

import threading
import time
from collections import deque

from .errors import ApiError


class RateLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hits: dict[tuple, deque[float]] = {}

    def check(self, key: tuple, limit: int, window_s: float) -> None:
        now = time.monotonic()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - window_s:
                hits.popleft()
            if len(hits) >= limit:
                retry_ms = int((hits[0] + window_s - now) * 1000) + 1
                raise ApiError("RATE_LIMITED", "Too many requests; retry later with the same operation_id.",
                               retry_after_ms=max(1, retry_ms))
            hits.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
