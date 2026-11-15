"""Remote speech-to-text engine (D34): the Vultr `fazetime-asr` service over the tailnet, with a circuit breaker
and an in-process fallback to the local engine (tiny.en on the Pi).

Drop-in for `asr.Engine`: `RemoteEngine.transcribe(pcm) -> list[Segment]`, plus `name`. `AsrWorker` calls
`engine.transcribe(w.pcm)` and then reads `engine.name` in the same thread, so `name` always names the engine that
produced the segments just returned: `<server model>@remote` (for example `faster-whisper-small.en-int8@remote`)
or the fallback's own name. Use one RemoteEngine per consumer thread (AsrWorker is single-threaded).

Policy:
* Every remote failure (connect error, timeout, 401/403, 503, other HTTP errors, a malformed or inconsistent
  response) falls back to the local engine for that same window, so there is no transcript hole.
* `failures` consecutive strikes open the circuit for `open_s` seconds; a response slower than `slow_ms` is a
  strike too (its result is still used). 401/403 opens the circuit at once. While open, windows go straight to the
  local engine. After `open_s` one probe request is allowed (half-open): success closes, failure re-opens.
* Segments are returned unfiltered with their compression ratios, so AsrWorker applies exactly the same
  repetition filter, LOW_CONFIDENCE flags and overlap de-duplication as with local ASR.
* The bearer token is never logged, never put in a URL and never shown by repr(). Transcript text is untrusted
  data: it is bounded and validated as data, never interpreted.
"""
from __future__ import annotations

import logging
import math
import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlsplit

import requests

from .asr import Segment

log = logging.getLogger("fazetime.asr_remote")

SR = 16000
MAX_BODY_BYTES = 10 * SR * 2  # server cap: 10 s of 16 kHz mono s16le
MAX_SEGMENTS = 64
MAX_TEXT = 1000
_MODEL_RE = re.compile(r"^[A-Za-z0-9_.:+\-]{1,100}$")


@dataclass
class RemoteSegment(Segment):
    """`asr.Segment` plus the server's segment timing (window-relative milliseconds)."""
    start_ms: int | None = None
    end_ms: int | None = None


class RemoteAsrError(Exception):
    """kind: timeout | connect | transport | unauthorized | busy | rejected | http_<code> | bad_response"""

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(f"{kind}{': ' + detail if detail else ''}")
        self.kind, self.detail = kind, detail


class RemoteAsrUnavailable(RuntimeError):
    """Raised by RemoteEngine.transcribe when the remote failed or the circuit is open and no fallback exists."""


class CircuitBreaker:
    CLOSED, OPEN, HALF_OPEN = "CLOSED", "OPEN", "HALF_OPEN"

    def __init__(self, failures: int = 3, open_s: float = 30.0, clock: Callable[[], float] = time.monotonic):
        assert failures >= 1 and open_s > 0
        self.threshold, self.open_s, self.clock = failures, open_s, clock
        self.state = self.CLOSED
        self.consecutive = 0
        self.opened_at = 0.0
        self.opened_count = 0
        self._probe_in_flight = False
        self._lock = threading.Lock()

    def allow(self) -> bool:
        with self._lock:
            if self.state == self.CLOSED:
                return True
            if self.state == self.OPEN and self.clock() - self.opened_at >= self.open_s:
                self.state = self.HALF_OPEN
            if self.state == self.HALF_OPEN and not self._probe_in_flight:
                self._probe_in_flight = True
                return True
            return False

    def record_success(self):
        with self._lock:
            if self.state != self.CLOSED:
                log.info("remote ASR circuit closed (probe succeeded)")
            self.state, self.consecutive, self._probe_in_flight = self.CLOSED, 0, False

    def record_failure(self, immediate: bool = False) -> bool:
        """Count a strike. Returns True if this strike opened the circuit."""
        with self._lock:
            self.consecutive += 1
            was_open = self.state == self.OPEN
            if immediate or self.state == self.HALF_OPEN or self.consecutive >= self.threshold:
                self.state, self.opened_at, self._probe_in_flight = self.OPEN, self.clock(), False
                if not was_open:
                    self.opened_count += 1
                    return True
            return False

    def is_healthy(self) -> bool:
        with self._lock:
            return self.state == self.CLOSED


def _finite(x, lo: float | None = None, hi: float | None = None) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        raise RemoteAsrError("bad_response", "non-numeric segment field")
    if (lo is not None and x < lo) or (hi is not None and x > hi):
        raise RemoteAsrError("bad_response", "segment field out of range")
    return float(x)


def _int(x, lo: int = 0, hi: int = 2 ** 53) -> int:
    if isinstance(x, bool) or not isinstance(x, int) or not lo <= x <= hi:
        raise RemoteAsrError("bad_response", "bad integer field")
    return x


def parse_response(obj, audio_ms: int, sent: dict) -> tuple[list[RemoteSegment], str, dict]:
    """Validate the server JSON semantically, not just syntactically. Returns (segments, model, timings)."""
    if not isinstance(obj, dict) or not isinstance(obj.get("segments"), list):
        raise RemoteAsrError("bad_response", "missing segments")
    model = obj.get("model")
    if not isinstance(model, str) or not _MODEL_RE.match(model):
        raise RemoteAsrError("bad_response", "bad model id")
    echo = obj.get("request") or {}
    if not isinstance(echo, dict):
        raise RemoteAsrError("bad_response", "bad request echo")
    for k, v in sent.items():  # the response must belong to this request
        if v is not None and echo.get(k) != v:
            raise RemoteAsrError("bad_response", f"request echo mismatch on {k}")
    raw = obj["segments"]
    if len(raw) > MAX_SEGMENTS:
        raise RemoteAsrError("bad_response", "too many segments")
    segs = []
    for s in raw:
        if not isinstance(s, dict) or not isinstance(s.get("text"), str) or len(s["text"]) > MAX_TEXT:
            raise RemoteAsrError("bad_response", "bad segment")
        start, end = _int(s.get("start_ms")), _int(s.get("end_ms"))
        if start > end or end > audio_ms + 1000:
            raise RemoteAsrError("bad_response", "segment timing outside the window")
        segs.append(RemoteSegment(text=s["text"].strip(), avg_logprob=_finite(s.get("avg_logprob"), hi=0.0),
                                  no_speech_prob=_finite(s.get("no_speech_prob"), 0.0, 1.0),
                                  compression_ratio=_finite(s.get("compression_ratio"), 0.0),
                                  start_ms=start, end_ms=end))
    timings = {"compute_ms": _int(obj.get("compute_ms")), "queue_ms": _int(obj.get("queue_ms"))}
    return segs, model, timings


class RemoteAsrClient:
    """HTTP client for POST /v1/transcribe. Raises RemoteAsrError; never retries (the engine falls back)."""

    def __init__(self, base_url: str, token: str, *, connect_timeout_s: float = 1.0, timeout_s: float = 2.5,
                 session: requests.Session | None = None):
        u = urlsplit(base_url)
        if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password or u.query or u.fragment:
            raise ValueError("remote ASR URL must be http(s)://host[:port] without credentials, query or fragment")
        if not token or len(token) < 32:
            raise ValueError("remote ASR token missing or too short")
        self.base_url = base_url.rstrip("/")
        self.connect_timeout_s, self.timeout_s = connect_timeout_s, timeout_s
        # Ask the server to give up slightly before our read timeout, so a late answer arrives as a fast 503.
        self.deadline_ms = max(200, int(timeout_s * 1000) - 200)
        self.__token = token
        self.session = session or requests.Session()

    def __repr__(self):
        return f"RemoteAsrClient({self.base_url!r}, token=<redacted>, timeout_s={self.timeout_s})"

    def _auth(self) -> dict:
        return {"Authorization": f"Bearer {self.__token}"}

    def transcribe(self, pcm: bytes, *, source_epoch: str | None = None, sequence: int | None = None,
                   media_start_ms: int | None = None) -> tuple[list[RemoteSegment], str, dict]:
        if not pcm or len(pcm) % 2 or len(pcm) > MAX_BODY_BYTES:
            raise RemoteAsrError("rejected", "pcm must be 1..320000 bytes of s16le")
        headers = {**self._auth(), "Content-Type": "application/octet-stream", "X-Deadline-Ms": str(self.deadline_ms)}
        sent = {"source_epoch": source_epoch, "sequence": sequence, "media_start_ms": media_start_ms}
        for h, v in (("X-Source-Epoch", source_epoch), ("X-Sequence", sequence), ("X-Media-Start-Ms", media_start_ms)):
            if v is not None:
                headers[h] = str(v)
        t0 = time.monotonic()
        try:
            r = self.session.post(f"{self.base_url}/v1/transcribe", data=pcm, headers=headers,
                                  timeout=(self.connect_timeout_s, self.timeout_s))
        except requests.exceptions.Timeout:
            raise RemoteAsrError("timeout") from None
        except requests.exceptions.ConnectionError as e:
            raise RemoteAsrError("connect", type(e).__name__) from None
        except requests.exceptions.RequestException as e:
            raise RemoteAsrError("transport", type(e).__name__) from None
        rtt_ms = int((time.monotonic() - t0) * 1000)
        if r.status_code != 200:
            kind = {401: "unauthorized", 403: "unauthorized", 503: "busy", 400: "rejected", 411: "rejected",
                    413: "rejected"}.get(r.status_code, f"http_{r.status_code}")
            code = ""
            try:
                code = str(r.json().get("error", ""))[:40]
            except ValueError:
                pass
            raise RemoteAsrError(kind, code)
        try:
            obj = r.json()
        except ValueError:
            raise RemoteAsrError("bad_response", "not json") from None
        segs, model, timings = parse_response(obj, len(pcm) // 2 * 1000 // SR, sent)
        return segs, model, timings | {"rtt_ms": rtt_ms}

    def healthz(self) -> dict:
        r = self.session.get(f"{self.base_url}/healthz", timeout=(self.connect_timeout_s, self.timeout_s))
        r.raise_for_status()
        return r.json()


class RemoteEngine:
    """asr.Engine backed by the remote service, falling back to `fallback` (a local engine) when unhealthy."""

    def __init__(self, client: RemoteAsrClient, fallback=None, *, failures: int = 3, open_s: float = 30.0,
                 slow_ms: int = 1800, clock: Callable[[], float] = time.monotonic):
        self.client, self.fallback = client, fallback
        self.breaker = CircuitBreaker(failures, open_s, clock)
        self.slow_ms = slow_ms
        self.name = fallback.name if fallback is not None else "remote-asr"
        self.remote_ok = 0
        self.remote_slow = 0
        self.remote_errors: dict[str, int] = {}
        self.fallback_calls = 0
        self.last_rtt_ms: int | None = None
        self.last_remote_model: str | None = None

    def transcribe(self, pcm: bytes, *, source_epoch: str | None = None, sequence: int | None = None,
                   media_start_ms: int | None = None) -> list[Segment]:
        if self.breaker.allow():
            try:
                segs, model, t = self.client.transcribe(pcm, source_epoch=source_epoch, sequence=sequence,
                                                        media_start_ms=media_start_ms)
            except Exception as e:  # any client failure (including an unexpected one) must not wedge the breaker
                if not isinstance(e, RemoteAsrError):
                    e = RemoteAsrError("transport", type(e).__name__)
                self.remote_errors[e.kind] = self.remote_errors.get(e.kind, 0) + 1
                opened = self.breaker.record_failure(immediate=e.kind == "unauthorized")
                if opened:
                    log.warning("remote ASR unhealthy (%s); circuit open for %.0f s, using %s", e, self.breaker.open_s,
                                self.fallback.name if self.fallback is not None else "no fallback")
                else:
                    log.info("remote ASR call failed (%s); this window uses the local engine", e)
            else:
                self.last_rtt_ms, self.last_remote_model = t["rtt_ms"], model
                if t["rtt_ms"] > self.slow_ms:
                    self.remote_slow += 1
                    if self.breaker.record_failure():
                        log.warning("remote ASR slow (%d ms > %d ms); circuit open for %.0f s", t["rtt_ms"],
                                    self.slow_ms, self.breaker.open_s)
                else:
                    self.breaker.record_success()
                self.remote_ok += 1
                self.name = f"{model}@remote"
                return segs
        if self.fallback is None:
            raise RemoteAsrUnavailable("remote ASR unavailable and no local fallback configured")
        self.fallback_calls += 1
        self.name = self.fallback.name
        return self.fallback.transcribe(pcm)

    def transcribe_window(self, w) -> list[Segment]:
        """Same as transcribe(w.pcm) but also sends the window's epoch/index/media position for server logs."""
        return self.transcribe(w.pcm, source_epoch=w.epoch, sequence=w.index, media_start_ms=w.media_start_ms)

    def stats(self) -> dict:
        return {"remote_state": self.breaker.state, "remote_ok": self.remote_ok, "remote_slow": self.remote_slow,
                "remote_errors": dict(self.remote_errors), "remote_circuit_opened": self.breaker.opened_count,
                "fallback_calls": self.fallback_calls, "last_rtt_ms": self.last_rtt_ms,
                "remote_model": self.last_remote_model}


def engine_from_env(fallback=None, env=None) -> RemoteEngine | None:
    """Build a RemoteEngine from env; None when ASR_REMOTE_URL is unset (local ASR only).

    ASR_REMOTE_URL          e.g. http://100.91.148.70:8090 (tailnet only)
    ASR_REMOTE_TOKEN        bearer token (secret: .env.local / ~/fazetime-data/worker.env, never logged)
    ASR_REMOTE_TIMEOUT_S    read timeout, default 2.5 (measured Pi->VM p95 1.2-1.3 s, max 1.55 s, via DERP)
    ASR_REMOTE_CONNECT_S    connect timeout, default 1.0
    ASR_REMOTE_SLOW_MS      a slower response is a breaker strike, default 1800
    ASR_REMOTE_FAILURES     consecutive strikes that open the circuit, default 3
    ASR_REMOTE_OPEN_S       seconds the circuit stays open before a probe, default 30
    """
    env = os.environ if env is None else env
    url = (env.get("ASR_REMOTE_URL") or "").strip()
    if not url or url.lower() == "none":
        return None
    client = RemoteAsrClient(url, env.get("ASR_REMOTE_TOKEN", ""),
                             connect_timeout_s=float(env.get("ASR_REMOTE_CONNECT_S", 1.0)),
                             timeout_s=float(env.get("ASR_REMOTE_TIMEOUT_S", 2.5)))
    return RemoteEngine(client, fallback, failures=int(env.get("ASR_REMOTE_FAILURES", 3)),
                        open_s=float(env.get("ASR_REMOTE_OPEN_S", 30.0)),
                        slow_ms=int(env.get("ASR_REMOTE_SLOW_MS", 1800)))
