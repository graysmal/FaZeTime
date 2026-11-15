"""Minimal tailnet-only HTTP speech-to-text service (D34).

Endpoints:
  POST /v1/transcribe   body: raw 16 kHz mono s16le PCM, at most 10 s (320000 bytes)
                        auth: `Authorization: Bearer <ASR_REMOTE_TOKEN>` (constant-time compare)
                        optional correlation metadata, header or query:
                          X-Source-Epoch / source_epoch, X-Sequence / sequence, X-Media-Start-Ms / media_start_ms
                        optional X-Deadline-Ms (clamped to the server deadline)
                        200 -> {text, segments:[{start_ms,end_ms,text,avg_logprob,no_speech_prob,compression_ratio}],
                                model, compute_ms, queue_ms, ...}
                        401 bad/missing token, 400/411/413 bad body, 503 queue full or deadline exceeded
  GET  /healthz         unauthenticated liveness: {status, model, in_flight, waiting}

Safety properties:
  * binds ONLY to the IPv4 address of the tailnet interface (100.64.0.0/10 on `tailscale0`), else refuses to start;
  * bounded body, bounded concurrency (semaphore), bounded wait queue, per-request deadline, bounded connections;
  * the token is never logged; transcript text is never logged (team content, untrusted data).
"""
from __future__ import annotations

import fcntl
import hmac
import ipaddress
import json
import logging
import os
import re
import socket
import struct
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from . import __version__
from .engine import SR, env_int

log = logging.getLogger("fazetime.asr_remote")

TAILNET_V4 = ipaddress.ip_network("100.64.0.0/10")
MAX_BODY_BYTES = 10 * SR * 2  # 10 s of 16 kHz mono s16le
MIN_TOKEN_CHARS = 32
_EPOCH_RE = re.compile(r"^[A-Za-z0-9_.:\-]{1,64}$")
_MAX_INT = 2 ** 53


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def iface_ipv4(iface: str) -> str | None:
    """IPv4 address currently assigned to `iface` (SIOCGIFADDR), or None."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        packed = fcntl.ioctl(s.fileno(), 0x8915, struct.pack("256s", iface[:15].encode()))
        return socket.inet_ntoa(packed[20:24])
    except OSError:
        return None
    finally:
        s.close()


def check_bind_address(host: str, iface: str, iface_lookup=iface_ipv4) -> str:
    """Refuse anything but the tailnet IPv4 of `iface`. Raises SystemExit with the reason."""
    try:
        addr = ipaddress.IPv4Address(host)
    except ValueError:
        raise SystemExit(f"refusing to start: bind host {host!r} is not a literal IPv4 address")
    if addr not in TAILNET_V4:
        raise SystemExit(f"refusing to start: {addr} is outside the tailnet range {TAILNET_V4}")
    actual = iface_lookup(iface)
    if actual != str(addr):
        raise SystemExit(f"refusing to start: {addr} is not the IPv4 of {iface} (found {actual})")
    return str(addr)


@dataclass
class Config:
    host: str
    port: int = 8090
    iface: str = "tailscale0"
    model: str = "small.en"
    threads: int = 8
    concurrency: int = 1
    queue_cap: int = 2
    deadline_ms: int = 2500
    max_connections: int = 8
    models_dir: str | None = None
    token: str = field(default="", repr=False)

    @classmethod
    def from_env(cls) -> "Config":
        token = os.environ.pop("ASR_REMOTE_TOKEN", "")
        return cls(host=os.environ.get("ASR_BIND_HOST", ""), port=env_int("ASR_PORT", 8090),
                   iface=os.environ.get("ASR_BIND_IFACE", "tailscale0"), model=os.environ.get("ASR_MODEL", "small.en"),
                   threads=env_int("ASR_THREADS", 8), concurrency=env_int("ASR_CONCURRENCY", 1),
                   queue_cap=env_int("ASR_QUEUE_CAP", 2), deadline_ms=env_int("ASR_DEADLINE_MS", 2500),
                   max_connections=env_int("ASR_MAX_CONNECTIONS", 8),
                   models_dir=os.environ.get("ASR_MODELS_DIR") or None, token=token)

    def validate(self):
        if len(self.token) < MIN_TOKEN_CHARS:
            raise SystemExit("refusing to start: ASR_REMOTE_TOKEN missing or shorter than 32 characters")
        if not (1 <= self.concurrency <= 2):
            raise SystemExit("ASR_CONCURRENCY must be 1 or 2")
        if not (0 <= self.queue_cap <= 8):
            raise SystemExit("ASR_QUEUE_CAP must be 0..8")
        if not (200 <= self.deadline_ms <= 10000):
            raise SystemExit("ASR_DEADLINE_MS must be 200..10000")


class Admission:
    """`concurrency` slots plus at most `queue_cap` waiters; a waiter gives up at its deadline."""

    def __init__(self, concurrency: int, queue_cap: int):
        self.sem = threading.BoundedSemaphore(concurrency)
        self.queue_cap = queue_cap
        self.lock = threading.Lock()
        self.waiting = 0
        self.in_flight = 0

    def acquire(self, deadline: float) -> str:
        """Returns 'ok', 'queue_full' or 'deadline_exceeded'."""
        if self.sem.acquire(blocking=False):
            with self.lock:
                self.in_flight += 1
            return "ok"
        with self.lock:
            if self.waiting >= self.queue_cap:
                return "queue_full"
            self.waiting += 1
        try:
            ok = self.sem.acquire(timeout=max(0.0, deadline - time.monotonic()))
        finally:
            with self.lock:
                self.waiting -= 1
        if not ok:
            return "deadline_exceeded"
        with self.lock:
            self.in_flight += 1
        return "ok"

    def release(self):
        with self.lock:
            self.in_flight -= 1
        self.sem.release()


class App:
    def __init__(self, cfg: Config, engine):
        self.cfg, self.engine = cfg, engine
        self.admission = Admission(cfg.concurrency, cfg.queue_cap)
        self.started = time.monotonic()
        self._token = cfg.token.encode()
        self.counts: dict[str, int] = {}
        self.counts_lock = threading.Lock()

    def authorized(self, header: str | None) -> bool:
        if not header or not header.startswith("Bearer "):
            hmac.compare_digest(b"x" * len(self._token), self._token)  # keep timing uniform
            return False
        return hmac.compare_digest(header[7:].strip().encode(), self._token)

    def count(self, key: str):
        with self.counts_lock:
            self.counts[key] = self.counts.get(key, 0) + 1


def _meta(handler: "Handler", query: dict) -> dict:
    def pick(hname: str, qname: str):
        v = handler.headers.get(hname)
        if v is None and qname in query:
            v = query[qname][0]
        return v
    epoch = pick("X-Source-Epoch", "source_epoch")
    if epoch is not None and not _EPOCH_RE.match(epoch):
        raise ValueError("source_epoch must match [A-Za-z0-9_.:-]{1,64}")
    out = {"source_epoch": epoch}
    for h, q in (("X-Sequence", "sequence"), ("X-Media-Start-Ms", "media_start_ms")):
        v = pick(h, q)
        if v is not None:
            if not re.fullmatch(r"\d{1,16}", v) or int(v) >= _MAX_INT:
                raise ValueError(f"{q} must be a non-negative integer")
            v = int(v)
        out[q] = v
    return out


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "fazetime-asr/" + __version__
    sys_version = ""
    timeout = 15  # idle keep-alive and slow-body bound (seconds per socket operation)
    app: App  # set on the subclass by make_server()

    def log_request(self, code="-", size="-"):  # replaced by one structured line per request
        pass

    def log_message(self, fmt, *args):  # http.server internals (bad request lines etc.); never includes headers
        log.warning("http: " + fmt, *args)

    def _send_json(self, status: int, obj: dict, close: bool = False, extra: dict | None = None):
        body = json.dumps(obj, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        if close:
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, code: str, close: bool = False, **fields):
        self.app.count(f"{status}_{code}")
        extra = {"WWW-Authenticate": "Bearer"} if status == 401 else ({"Retry-After": "1"} if status == 503 else None)
        self._send_json(status, {"error": code, **fields}, close=close, extra=extra)
        log.info("req status=%d error=%s %s", status, code, " ".join(f"{k}={v}" for k, v in fields.items()))

    def do_GET(self):
        if urlsplit(self.path).path != "/healthz":
            return self._error(404, "not_found")
        a = self.app.admission
        self._send_json(200, {"status": "ok", "model": self.app.engine.name, "concurrency": self.app.cfg.concurrency,
                              "in_flight": a.in_flight, "waiting": a.waiting,
                              "uptime_s": int(time.monotonic() - self.app.started)})

    def do_POST(self):
        t_recv = time.monotonic()
        received_at = utc_now()
        url = urlsplit(self.path)
        if url.path != "/v1/transcribe":
            return self._error(404, "not_found", close=True)
        if not self.app.authorized(self.headers.get("Authorization")):
            return self._error(401, "unauthorized", close=True)  # body never read
        if self.headers.get("Transfer-Encoding"):
            return self._error(411, "content_length_required", close=True)
        try:
            n = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return self._error(411, "content_length_required", close=True)
        if n > MAX_BODY_BYTES:
            return self._error(413, "body_too_large", close=True, max_bytes=MAX_BODY_BYTES)
        if n <= 0 or n % 2:
            return self._error(400, "body_must_be_s16le_pcm", close=True)
        try:
            meta = _meta(self, parse_qs(url.query))
            dl = self.headers.get("X-Deadline-Ms")
            deadline_ms = self.app.cfg.deadline_ms if dl is None else max(100, min(int(dl), self.app.cfg.deadline_ms))
        except ValueError as e:
            return self._error(400, "bad_metadata", close=True, detail=str(e)[:120])
        pcm = self.rfile.read(n)
        if len(pcm) != n:
            return self._error(400, "short_body", close=True)
        deadline = t_recv + deadline_ms / 1000
        t_q = time.monotonic()
        verdict = self.app.admission.acquire(deadline)
        queue_ms = int((time.monotonic() - t_q) * 1000)
        if verdict != "ok":
            return self._error(503, verdict, queue_ms=queue_ms, seq=meta["sequence"])
        try:
            result = self.app.engine.transcribe(pcm)
        except Exception as e:  # model failure: report, do not crash the service
            log.exception("engine failure")
            return self._error(500, "engine_failure", detail=type(e).__name__)
        finally:
            self.app.admission.release()
        total_ms = int((time.monotonic() - t_recv) * 1000)
        if time.monotonic() > deadline:
            return self._error(503, "deadline_exceeded", queue_ms=queue_ms, compute_ms=result.compute_ms,
                               seq=meta["sequence"])
        self.app.count("200")
        self._send_json(200, {"text": result.text, "segments": result.segments_json(), "model": self.app.engine.name,
                              "compute_ms": result.compute_ms, "queue_ms": queue_ms, "total_ms": total_ms,
                              "audio_ms": n // 2 * 1000 // SR, "filtered_repetitive": result.filtered_repetitive,
                              "request": meta, "server_received_at": received_at, "server_sent_at": utc_now()})
        log.info("req status=200 epoch=%s seq=%s media_start_ms=%s audio_ms=%d queue_ms=%d compute_ms=%d segs=%d "
                 "filtered=%d", meta["source_epoch"], meta["sequence"], meta["media_start_ms"], n // 2 * 1000 // SR,
                 queue_ms, result.compute_ms, len(result.segments), result.filtered_repetitive)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 16

    def __init__(self, addr, handler_cls, max_connections: int):
        self.conn_sem = threading.BoundedSemaphore(max_connections)
        super().__init__(addr, handler_cls)

    def process_request(self, request, client_address):
        if not self.conn_sem.acquire(blocking=False):
            try:
                request.sendall(b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            except OSError:
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.conn_sem.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.conn_sem.release()


def make_server(cfg: Config, engine, host: str) -> Server:
    """Build the HTTP server. `main()` validates `host` with check_bind_address() first; tests pass loopback."""
    handler = type("BoundHandler", (Handler,), {"app": App(cfg, engine)})
    return Server((host, cfg.port), handler, cfg.max_connections)


def warm_up(engine):
    import numpy as np
    rng = np.random.default_rng(0)
    noise = (rng.standard_normal(SR) * 0.01).astype(np.float32)
    segs, _ = engine.model.transcribe(noise, language="en", beam_size=5, temperature=0.0, max_new_tokens=4,
                                      vad_filter=False, condition_on_previous_text=False)
    list(segs)


def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(name)s %(message)s")
    logging.getLogger("faster_whisper").setLevel(logging.WARNING)  # per-call INFO lines would flood journald
    cfg = Config.from_env()
    cfg.validate()
    host = check_bind_address(cfg.host, cfg.iface)  # before loading anything: fail fast on a wrong address
    from .engine import WhisperEngine
    engine = WhisperEngine(cfg.model, cfg.threads, cfg.concurrency, cfg.models_dir, local_files_only=True)
    warm_up(engine)
    srv = make_server(cfg, engine, host)
    log.info("listening on %s:%d model=%s threads=%d concurrency=%d queue_cap=%d deadline_ms=%d load_s=%.1f",
             host, cfg.port, engine.name, cfg.threads, cfg.concurrency, cfg.queue_cap, cfg.deadline_ms, engine.load_s)
    srv.serve_forever(poll_interval=0.5)


if __name__ == "__main__":
    main()
