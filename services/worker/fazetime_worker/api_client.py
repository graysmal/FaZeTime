"""Worker -> API client for CONTRACTS §9.16, plus an ordered, bounded uplink with idempotent retries.

* One ordered queue: an epoch registration always precedes that epoch's observations, and a GAP item of
  the old epoch precedes the next epoch's registration.
* Retries resend the identical body: (source_epoch, sequence) is the dedupe key for observations and
  frame evidence, and source_epoch for registration. Only network errors, timeouts, 5xx and 429 retry.
* 409 STALE_EPOCH drops the affected items (they can never be accepted). Other 4xx are logged and dropped.
* The bearer token is only ever placed in the Authorization header; it is never logged or written.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import requests

from .util import mono_ns, utc_now

log = logging.getLogger("fazetime.uplink")
RETRY_STATUSES = {429, 500, 502, 503, 504}


@dataclass
class ApiResult:
    status: int | None  # None = network error / timeout
    body: dict | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status is not None and 200 <= self.status < 300

    @property
    def code(self) -> str | None:
        try:
            return (self.body or {}).get("error", {}).get("code")
        except AttributeError:
            return None

    @property
    def retryable(self) -> bool:
        return self.status is None or self.status in RETRY_STATUSES

    def retry_after_s(self) -> float | None:
        try:
            ms = (self.body or {}).get("error", {}).get("retry_after_ms")
            return None if ms is None else max(0.0, ms / 1000)
        except AttributeError:
            return None


class ApiClient:
    def __init__(self, base: str, token: str, timeout_s: float = 10.0):
        self.base = base.rstrip("/")
        self._token = token
        self.timeout = timeout_s
        self.session = requests.Session()
        self.session.trust_env = False  # no proxy env vars for a tailnet-local API

    def __repr__(self) -> str:
        return f"ApiClient(base={self.base!r}, token=<redacted>)"

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"}

    def _result(self, r: requests.Response) -> ApiResult:
        try:
            body = r.json()
        except ValueError:
            body = None
        return ApiResult(r.status_code, body)

    def post_json(self, path: str, body: dict) -> ApiResult:
        try:
            r = self.session.post(self.base + path, json=body, headers=self._headers(), timeout=self.timeout)
            return self._result(r)
        except requests.RequestException as exc:
            return ApiResult(None, None, type(exc).__name__)

    def get_json(self, path: str, bearer: str | None = None) -> ApiResult:
        """GET with the worker token, or with an explicit read-only session bearer (snapshot fallback)."""
        headers = {"Authorization": f"Bearer {bearer}"} if bearer else self._headers()
        try:
            return self._result(self.session.get(self.base + path, headers=headers, timeout=self.timeout))
        except requests.RequestException as exc:
            return ApiResult(None, None, type(exc).__name__)

    def post_evidence(self, meta: dict, jpeg: bytes) -> ApiResult:
        files = {"meta": (None, json.dumps(meta, separators=(",", ":")), "application/json"),
                 "file": ("frame.jpg", jpeg, "image/jpeg")}
        try:
            r = self.session.post(self.base + "/v1/worker/evidence", files=files, headers=self._headers(),
                                  timeout=self.timeout)
            return self._result(r)
        except requests.RequestException as exc:
            return ApiResult(None, None, type(exc).__name__)


# ---- uplink operations ------------------------------------------------------------------------------
@dataclass
class RegisterEpoch:
    body: dict


@dataclass
class ObservationOp:
    epoch: str
    item: dict


@dataclass
class FrameOp:
    epoch: str
    sequence: int
    media_ms: int
    width: int
    height: int
    jpeg: bytes
    captured_at_utc: str
    flags: list = field(default_factory=list)


class DryRunClient:
    """No API configured: records what would be sent (bounded JSONL on the worker host)."""

    def __init__(self, path: Path):
        self.path = path
        self.f = open(path, "a", buffering=1, encoding="utf-8")
        self.n = 0
        self.epochs: set[str] = set()

    def post_json(self, path: str, body: dict) -> ApiResult:
        if path.endswith("/epochs"):
            self.epochs.add(body["source_epoch"])
        if self.n < 200_000:
            self.f.write(json.dumps({"route": path, "body": body}, separators=(",", ":")) + "\n")
            self.n += 1
        if path.endswith("/heartbeat"):
            return ApiResult(200, {"server_time_utc": utc_now(), "stream_session_id": None,
                                   "current_source_epoch": body.get("source_epoch")})
        if path.endswith("/observations"):
            return ApiResult(200, {"accepted": len(body["items"]), "duplicates": 0, "rejected": []})
        if path.endswith(("/proposals", "/resolutions")):  # dry-run: recorded above, never opened or settled
            return ApiResult(200, {"status": "DRY_RUN", "reject_code": None, "market_id": None})
        return ApiResult(201, {"source_epoch": body.get("source_epoch"), "created": True})

    def get_json(self, path: str, bearer: str | None = None) -> ApiResult:
        return ApiResult(404, {"error": {"code": "NOT_FOUND"}})

    def post_evidence(self, meta: dict, jpeg: bytes) -> ApiResult:
        return ApiResult(201, {"evidence_id": "evd_" + hashlib.sha256(jpeg).hexdigest()[:32], "deduped": False})


class Uplink(threading.Thread):
    def __init__(self, client, stream_id: str, max_queue: int = 2000, batch_max: int = 50,
                 batch_wait_s: float = 1.0, max_backoff_s: float = 10.0, sleep=time.sleep,
                 item_max_s: float = 120.0, register_max_s: float = 600.0):
        super().__init__(daemon=True, name="uplink")
        self.client, self.stream_id = client, stream_id
        self.max_queue, self.batch_max, self.batch_wait_s = max_queue, batch_max, batch_wait_s
        self.max_backoff_s = max_backoff_s
        self.item_max_s, self.register_max_s = item_max_s, register_max_s
        self.sleep = sleep
        self.q: deque = deque()
        self.cv = threading.Condition()
        self.stop_flag = threading.Event()
        self.registered: set[str] = set()
        self.sent_current_epoch: str | None = None  # last epoch registered, in uplink order
        self.latest_epoch: str | None = None  # newest epoch handed to the uplink
        self.stats = {"epochs_registered": 0, "obs_accepted": 0, "obs_duplicates": 0, "obs_rejected": 0,
                      "frames_uploaded": 0, "frames_deduped": 0, "retries": 0, "dropped_overflow": 0,
                      "dropped_stale_epoch": 0, "dropped_4xx": 0, "batches": 0}
        self.last_error: str | None = None
        self.server_current_epoch: str | None = None
        self.stream_session_id: str | None = None
        self.idle = threading.Event()
        self.idle.set()

    # ---- producer side ----------------------------------------------------------------------------
    def put(self, op):
        with self.cv:
            if isinstance(op, RegisterEpoch):
                self.latest_epoch = op.body["source_epoch"]
            self.q.append(op)
            while len(self.q) > self.max_queue:
                # drop the oldest non-registration op; never drop an epoch registration
                for i, old in enumerate(self.q):
                    if not isinstance(old, RegisterEpoch):
                        del self.q[i]
                        self.stats["dropped_overflow"] += 1
                        break
                else:
                    break
            self.idle.clear()
            self.cv.notify()

    def depth(self) -> int:
        with self.cv:
            return len(self.q)

    def is_registered(self, epoch: str | None) -> bool:
        return epoch is not None and epoch in self.registered

    # ---- consumer side -----------------------------------------------------------------------------
    def _send(self, fn, *args, epoch: str | None = None, max_s: float = 120.0) -> ApiResult:
        """Call with bounded retries (same body every time). Gives up after `max_s`, on stop, or when the
        epoch has been superseded locally (its data can no longer be accepted)."""
        delay = 0.5
        t_end = mono_ns() + int(max_s * 1e9)
        while True:
            res = fn(*args)
            if res.ok or not res.retryable:
                return res
            self.last_error = f"{res.status or res.error} {res.code or ''}".strip()
            if self.stop_flag.is_set() or mono_ns() >= t_end or (epoch is not None and self._superseded(epoch)):
                log.error("uplink giving up after retries: %s", self.last_error)
                return res
            self.stats["retries"] += 1
            wait = min(res.retry_after_s() or delay, self.max_backoff_s)
            log.warning("uplink retry in %.1fs after %s", wait, self.last_error)
            self.sleep(wait)
            delay = min(delay * 2, self.max_backoff_s)

    def _superseded(self, epoch: str) -> bool:
        """True if, in uplink order, a newer epoch registration has already been sent. Ops queued before
        that registration are still valid for their epoch (the server's current epoch until then)."""
        return epoch != self.sent_current_epoch

    def run(self):
        while True:
            with self.cv:
                while not self.q and not self.stop_flag.is_set():
                    self.idle.set()
                    self.cv.wait(0.5)
                if not self.q and self.stop_flag.is_set():
                    self.idle.set()
                    return
                op = self.q.popleft()
            try:
                if isinstance(op, RegisterEpoch):
                    self._do_register(op)
                elif isinstance(op, FrameOp):
                    self._do_frame(op)
                elif isinstance(op, ObservationOp):
                    self._do_observations(op)
            except Exception:
                log.exception("uplink op failed")

    def _do_register(self, op: RegisterEpoch):
        res = self._send(self.client.post_json, "/v1/worker/epochs", op.body, max_s=self.register_max_s)
        epoch = op.body["source_epoch"]
        if res.ok:
            self.registered.add(epoch)
            self.sent_current_epoch = epoch
            self.stats["epochs_registered"] += 1
            body = res.body or {}
            self.server_current_epoch = body.get("current_source_epoch", epoch)
            self.stream_session_id = body.get("stream_session_id", self.stream_session_id)
            log.info("registered epoch %s reason=%s voided_market=%s", epoch, op.body["reason"],
                     body.get("voided_market_id"))
        else:
            self.last_error = f"register {res.status} {res.code}"
            log.error("epoch registration failed: %s %s", res.status, res.code)

    def _do_frame(self, op: FrameOp):
        if self._superseded(op.epoch):
            self.stats["dropped_stale_epoch"] += 1
            return
        meta = {"source_epoch": op.epoch, "sequence": op.sequence, "kind": "FRAME", "media_ms": op.media_ms,
                "width": op.width, "height": op.height, "sha256": hashlib.sha256(op.jpeg).hexdigest()}
        res = self._send(self.client.post_evidence, meta, op.jpeg, epoch=op.epoch, max_s=self.item_max_s)
        if not res.ok:
            self._drop(res, 1)
            return
        body = res.body or {}
        self.stats["frames_deduped" if body.get("deduped") else "frames_uploaded"] += 1
        item = {"sequence": op.sequence, "kind": "FRAME", "media_start_ms": op.media_ms, "media_end_ms": op.media_ms,
                "captured_at_utc": op.captured_at_utc, "source_wall_time_utc": None,
                "quality_flags": [f for f in op.flags if f in ALLOWED_FLAGS], "transcript": None,
                "evidence_id": body["evidence_id"], "gap": None}
        with self.cv:  # the FRAME observation goes out with the next batch of this epoch
            self.q.appendleft(ObservationOp(op.epoch, item))

    def _do_observations(self, first: ObservationOp):
        epoch = first.epoch
        items = [first.item]
        deadline = mono_ns() + int(self.batch_wait_s * 1e9)
        while len(items) < self.batch_max:
            with self.cv:
                if self.q and isinstance(self.q[0], ObservationOp) and self.q[0].epoch == epoch:
                    items.append(self.q.popleft().item)
                    continue
                if self.q or mono_ns() >= deadline or self.stop_flag.is_set():
                    break  # a different op is next (keep order) or the batch window closed
                self.cv.wait(max(0.0, (deadline - mono_ns()) / 1e9))
        if self._superseded(epoch):
            self.stats["dropped_stale_epoch"] += len(items)
            return
        body = {"stream_id": self.stream_id, "source_epoch": epoch, "items": items}
        res = self._send(self.client.post_json, "/v1/worker/observations", body, epoch=epoch, max_s=self.item_max_s)
        self.stats["batches"] += 1
        if not res.ok:
            self._drop(res, len(items))
            return
        b = res.body or {}
        self.stats["obs_accepted"] += int(b.get("accepted", 0))
        self.stats["obs_duplicates"] += int(b.get("duplicates", 0))
        rejected = b.get("rejected") or []
        self.stats["obs_rejected"] += len(rejected)
        if rejected:
            log.warning("observations rejected: %s", rejected[:5])

    def _drop(self, res: ApiResult, n: int):
        if res.code == "STALE_EPOCH":
            self.stats["dropped_stale_epoch"] += n
        else:
            self.stats["dropped_4xx"] += n
        self.last_error = f"{res.status} {res.code}"
        log.error("uplink dropped %d item(s): %s %s", n, res.status, res.code)

    def heartbeat(self, body: dict) -> ApiResult:
        """Sent directly (not queued): heartbeats are periodic and supersede each other."""
        res = self.client.post_json("/v1/worker/heartbeat", body)
        if res.ok and res.body:
            self.server_current_epoch = res.body.get("current_source_epoch")
            self.stream_session_id = res.body.get("stream_session_id", self.stream_session_id)
        elif not res.ok:
            self.last_error = f"heartbeat {res.status or res.error} {res.code or ''}".strip()
        return res

    def drain(self, timeout_s: float) -> bool:
        return self.idle.wait(timeout_s)

    def stop(self):
        self.stop_flag.set()
        with self.cv:
            self.cv.notify_all()


ALLOWED_FLAGS = {"PARTIAL", "CLOSED_BY_GAP", "CLOSED_BY_PTS_DISCONTINUITY", "CLOSED_BY_STOP", "AFTER_GAP",
                 "DRAINED_AFTER_STOP", "LATE_SPLIT", "PTS_UNKNOWN", "IN_DISCONTINUITY_HOLE", "LOW_CONFIDENCE",
                 "DEDUPED_OVERLAP"}
