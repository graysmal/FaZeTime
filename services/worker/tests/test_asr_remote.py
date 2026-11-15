"""Remote ASR client (D34) against a fake HTTP server: success, timeout, 401, 503, bad response, circuit open/close.

Deterministic, offline: the fake server runs on loopback; no real model, no real network, no real token.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from fazetime_worker.asr import AsrWorker, BoundedQueue, Segment, Window
from fazetime_worker.asr_remote import (CircuitBreaker, RemoteAsrClient, RemoteAsrUnavailable, RemoteEngine,
                                        RemoteSegment, engine_from_env)
from fazetime_worker.util import mono_ns, utc_now

TOKEN = "test-token-" + "x" * 40  # fake; never a real credential
PCM = b"\x00\x01" * 16000 * 4  # 4 s of 16 kHz s16le


class FakeAsrServer:
    """Mimics POST /v1/transcribe. `mode`: ok | slow | sleep | 401 | 503 | bad_json | bad_seg | mismatch."""

    def __init__(self):
        self.mode = "ok"
        self.sleep_s = 0.0
        self.requests: list[dict] = []
        outer = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _send(self, status, obj, raw=None):
                body = raw if raw is not None else json.dumps(obj).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(n)
                auth_ok = self.headers.get("Authorization") == f"Bearer {TOKEN}"
                outer.requests.append({"path": self.path, "len": len(body), "auth_ok": auth_ok,
                                       "epoch": self.headers.get("X-Source-Epoch"),
                                       "seq": self.headers.get("X-Sequence"),
                                       "media": self.headers.get("X-Media-Start-Ms"),
                                       "deadline": self.headers.get("X-Deadline-Ms")})
                mode = outer.mode
                if mode == "401" or not auth_ok:
                    return self._send(401, {"error": "unauthorized"})
                if mode == "503":
                    return self._send(503, {"error": "queue_full"})
                if mode in ("sleep", "slow"):
                    time.sleep(outer.sleep_s)
                if mode == "bad_json":
                    return self._send(200, None, raw=b"{not json")
                seq = self.headers.get("X-Sequence")
                seg = {"start_ms": 0, "end_ms": 3200, "text": " hello Gavin ", "avg_logprob": -0.3,
                       "no_speech_prob": 0.02, "compression_ratio": 1.1}
                if mode == "bad_seg":
                    seg["end_ms"] = 99999
                req = {"source_epoch": self.headers.get("X-Source-Epoch"),
                       "sequence": (int(seq) + (1 if mode == "mismatch" else 0)) if seq else None,
                       "media_start_ms": int(self.headers["X-Media-Start-Ms"]) if self.headers.get(
                           "X-Media-Start-Ms") else None}
                self._send(200, {"text": "hello Gavin", "segments": [seg], "model": "faster-whisper-small.en-int8",
                                 "compute_ms": 412, "queue_ms": 0, "request": req})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class LocalFake:
    name = "faster-whisper-tiny.en-int8"

    def __init__(self):
        self.calls = 0

    def transcribe(self, pcm):
        self.calls += 1
        return [Segment("local text", -0.5, 0.1, 1.2)]


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def server():
    s = FakeAsrServer()
    yield s
    s.close()


def make(server, timeout_s=1.0, failures=3, open_s=30.0, slow_ms=1500, clock=None, fallback="default"):
    client = RemoteAsrClient(server.url, TOKEN, connect_timeout_s=0.5, timeout_s=timeout_s)
    fb = LocalFake() if fallback == "default" else fallback
    eng = RemoteEngine(client, fb, failures=failures, open_s=open_s, slow_ms=slow_ms, clock=clock or Clock())
    return eng, fb


def test_success_returns_segments_and_remote_name(server):
    eng, fb = make(server)
    segs = eng.transcribe(PCM, source_epoch="ep1", sequence=7, media_start_ms=21000)
    assert len(segs) == 1 and isinstance(segs[0], Segment) and isinstance(segs[0], RemoteSegment)
    s = segs[0]
    assert (s.text, s.avg_logprob, s.no_speech_prob, s.compression_ratio, s.start_ms, s.end_ms) == (
        "hello Gavin", -0.3, 0.02, 1.1, 0, 3200)
    assert eng.name == "faster-whisper-small.en-int8@remote"
    assert fb.calls == 0 and eng.breaker.state == "CLOSED"
    r = server.requests[-1]
    assert (r["path"], r["len"], r["auth_ok"], r["epoch"], r["seq"], r["media"]) == (
        "/v1/transcribe", len(PCM), True, "ep1", "7", "21000")
    assert int(r["deadline"]) == 800  # timeout 1.0 s minus 200 ms: the server answers 503 before we time out
    assert eng.stats()["remote_ok"] == 1


def test_drop_in_signature_transcribe_pcm_only(server):
    eng, _ = make(server)
    segs = eng.transcribe(PCM)  # exactly how AsrWorker calls a local engine
    assert segs[0].text == "hello Gavin"


def test_timeout_falls_back_for_that_window(server):
    server.mode, server.sleep_s = "sleep", 1.0
    eng, fb = make(server, timeout_s=0.2)
    t0 = time.monotonic()
    segs = eng.transcribe(PCM)
    assert time.monotonic() - t0 < 0.9
    assert segs[0].text == "local text" and eng.name == "faster-whisper-tiny.en-int8" and fb.calls == 1
    assert eng.remote_errors == {"timeout": 1} and eng.breaker.state == "CLOSED"


def test_401_opens_circuit_immediately_and_skips_remote(server):
    server.mode = "401"
    eng, fb = make(server)
    assert eng.transcribe(PCM)[0].text == "local text"
    assert eng.breaker.state == "OPEN" and eng.remote_errors == {"unauthorized": 1}
    n = len(server.requests)
    eng.transcribe(PCM)
    assert len(server.requests) == n and fb.calls == 2  # open: no remote call at all


def test_wrong_token_is_401(server):
    client = RemoteAsrClient(server.url, "y" * 40, timeout_s=1.0)
    eng = RemoteEngine(client, LocalFake(), clock=Clock())
    eng.transcribe(PCM)
    assert eng.remote_errors == {"unauthorized": 1} and server.requests[-1]["auth_ok"] is False


def test_503_strikes_then_opens_after_n(server):
    server.mode = "503"
    eng, fb = make(server, failures=2)
    eng.transcribe(PCM)
    assert eng.breaker.state == "CLOSED"
    eng.transcribe(PCM)
    assert eng.breaker.state == "OPEN" and eng.remote_errors == {"busy": 2} and fb.calls == 2


def test_circuit_half_open_probe_success_closes(server):
    clock = Clock()
    server.mode = "503"
    eng, fb = make(server, failures=1, open_s=30, clock=clock)
    eng.transcribe(PCM)
    assert eng.breaker.state == "OPEN"
    server.mode = "ok"
    clock.t += 29.9
    n = len(server.requests)
    assert eng.transcribe(PCM)[0].text == "local text" and len(server.requests) == n  # still open
    clock.t += 0.2
    assert eng.transcribe(PCM)[0].text == "hello Gavin"  # half-open probe succeeds
    assert eng.breaker.state == "CLOSED" and eng.breaker.consecutive == 0


def test_circuit_half_open_probe_failure_reopens(server):
    clock = Clock()
    server.mode = "503"
    eng, fb = make(server, failures=1, open_s=10, clock=clock)
    eng.transcribe(PCM)
    clock.t += 10.5
    eng.transcribe(PCM)  # probe fails
    assert eng.breaker.state == "OPEN" and eng.breaker.opened_at == clock.t
    n = len(server.requests)
    clock.t += 5
    eng.transcribe(PCM)
    assert len(server.requests) == n and fb.calls == 3


def test_slow_response_is_used_but_counts_as_strike(server):
    server.mode, server.sleep_s = "slow", 0.15
    eng, fb = make(server, failures=2, slow_ms=50)
    assert eng.transcribe(PCM)[0].text == "hello Gavin"
    assert eng.breaker.state == "CLOSED" and eng.remote_slow == 1
    assert eng.transcribe(PCM)[0].text == "hello Gavin"
    assert eng.breaker.state == "OPEN" and fb.calls == 0
    assert eng.transcribe(PCM)[0].text == "local text"


@pytest.mark.parametrize("mode", ["bad_json", "bad_seg", "mismatch"])
def test_malformed_or_inconsistent_response_falls_back(server, mode):
    server.mode = mode
    eng, fb = make(server)
    assert eng.transcribe(PCM, source_epoch="e", sequence=3, media_start_ms=9000)[0].text == "local text"
    assert eng.remote_errors == {"bad_response": 1}


def test_connection_refused_falls_back():
    client = RemoteAsrClient("http://127.0.0.1:9", TOKEN, connect_timeout_s=0.3, timeout_s=0.3)
    eng = RemoteEngine(client, LocalFake(), clock=Clock())
    assert eng.transcribe(PCM)[0].text == "local text" and eng.remote_errors == {"connect": 1}


def test_no_fallback_raises(server):
    server.mode = "503"
    eng, _ = make(server, fallback=None)
    with pytest.raises(RemoteAsrUnavailable):
        eng.transcribe(PCM)


def test_token_never_logged_or_repr(server, caplog):
    caplog.set_level(logging.DEBUG)
    server.mode = "401"
    eng, _ = make(server, failures=1)
    eng.transcribe(PCM)
    server.mode = "503"
    eng.breaker.state = "CLOSED"
    eng.transcribe(PCM)
    assert TOKEN not in caplog.text and TOKEN not in repr(eng.client) and TOKEN not in json.dumps(eng.stats())
    assert "redacted" in repr(eng.client)


def test_client_rejects_bad_inputs():
    with pytest.raises(ValueError):
        RemoteAsrClient("http://user:pw@host:8090", TOKEN)
    with pytest.raises(ValueError):
        RemoteAsrClient("http://host:8090/?token=x", TOKEN)
    with pytest.raises(ValueError):
        RemoteAsrClient("http://host:8090", "short")


def test_oversized_pcm_never_sent(server):
    eng, fb = make(server)
    assert eng.transcribe(b"\x00\x00" * (16000 * 11))[0].text == "local text"
    assert server.requests == [] and eng.remote_errors == {"rejected": 1}


def test_engine_from_env(server):
    assert engine_from_env(LocalFake(), env={}) is None
    eng = engine_from_env(LocalFake(), env={"ASR_REMOTE_URL": server.url, "ASR_REMOTE_TOKEN": TOKEN,
                                            "ASR_REMOTE_FAILURES": "2", "ASR_REMOTE_OPEN_S": "5"})
    assert eng.breaker.threshold == 2 and eng.breaker.open_s == 5
    assert eng.transcribe(PCM)[0].text == "hello Gavin"


def test_breaker_unit():
    c = Clock()
    b = CircuitBreaker(failures=2, open_s=5, clock=c)
    assert b.allow() and not b.record_failure() and b.record_failure() and b.state == "OPEN"
    assert not b.allow()
    c.t += 5
    assert b.allow() and not b.allow()  # exactly one half-open probe
    b.record_success()
    assert b.state == "CLOSED" and b.allow()


def test_asr_worker_drop_in(server):
    """AsrWorker publishes the remote engine name with the remote text, unchanged pipeline code."""
    eng, _ = make(server)
    q = BoundedQueue(4)
    published = []
    w = AsrWorker(eng, q, lambda e: True, lambda *a: published.append(a), max_wait_s=6.0, low_logprob=-1.0,
                  high_no_speech=0.6)
    w.start()
    q.put(Window("ep1", 0, 0, 4000, PCM, mono_ns(), utc_now()))
    deadline = time.monotonic() + 5
    while not published and time.monotonic() < deadline:
        time.sleep(0.02)
    w.stop_flag.set()
    w.join(timeout=2)
    assert published, "nothing published"
    _w, text, lp, ns, engine_name, flags, _lat = published[0]
    assert text == "hello Gavin" and engine_name == "faster-whisper-small.en-int8@remote" and lp == -0.3


def test_unexpected_client_exception_does_not_wedge_breaker(server):
    clock = Clock()
    eng, fb = make(server, failures=1, open_s=5, clock=clock)

    def boom(*a, **k):
        raise RuntimeError("unexpected")
    real = eng.client.transcribe
    eng.client.transcribe = boom
    assert eng.transcribe(PCM)[0].text == "local text" and eng.remote_errors == {"transport": 1}
    assert eng.breaker.state == "OPEN"
    clock.t += 5
    assert eng.transcribe(PCM)[0].text == "local text"  # half-open probe raises again -> re-open, not wedged
    assert eng.breaker.state == "OPEN"
    eng.client.transcribe = real
    clock.t += 5
    assert eng.transcribe(PCM)[0].text == "hello Gavin" and eng.breaker.state == "CLOSED"
