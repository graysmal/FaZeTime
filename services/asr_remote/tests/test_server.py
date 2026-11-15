"""Server tests with a stub engine on loopback (no model). main() itself always enforces the tailnet bind check."""
from __future__ import annotations

import http.client
import json
import threading
import time
from types import SimpleNamespace

import pytest

from fazetime_asr_remote.engine import DECODE_KW, FORBIDDEN_KW, Result, build_result
from fazetime_asr_remote.server import Config, check_bind_address, make_server

TOKEN = "t" * 43  # fake
PCM = b"\x00\x01" * 16000 * 4


class StubEngine:
    name = "faster-whisper-stub-int8"

    def __init__(self, delay_s=0.0):
        self.delay_s = delay_s

    def transcribe(self, pcm):
        time.sleep(self.delay_s)
        raw = [SimpleNamespace(start=0.0, end=2.5, text=" hi there ", avg_logprob=-0.2, no_speech_prob=0.01,
                               compression_ratio=1.2),
               SimpleNamespace(start=2.5, end=3.9, text="ok ok ok ok ok ok ok ok", avg_logprob=-0.4,
                               no_speech_prob=0.02, compression_ratio=3.1)]
        return build_result(raw, int(self.delay_s * 1000))


@pytest.fixture
def srv(request):
    delay, queue_cap, deadline = getattr(request, "param", (0.0, 2, 2500))
    cfg = Config(host="127.0.0.1", port=0, queue_cap=queue_cap, deadline_ms=deadline, token=TOKEN)
    s = make_server(cfg, StubEngine(delay), "127.0.0.1")
    t = threading.Thread(target=s.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    t.start()
    yield s.server_address[1]
    s.shutdown()
    s.server_close()


def post(port, body=PCM, token=TOKEN, headers=None, path="/v1/transcribe"):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    h = {"Content-Type": "application/octet-stream", **(headers or {})}
    if token is not None:
        h["Authorization"] = f"Bearer {token}"
    c.request("POST", path, body=body, headers=h)
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, (json.loads(data) if data else None)


def test_decoding_policy_matches_pi_worker():
    assert DECODE_KW == dict(language="en", beam_size=5, vad_filter=True, temperature=0.0, max_new_tokens=64,
                             condition_on_previous_text=False)
    assert not any(k in DECODE_KW for k in FORBIDDEN_KW)


def test_success_filters_repetition_but_returns_all_segments(srv):
    status, obj = post(srv, headers={"X-Source-Epoch": "ep-1", "X-Sequence": "5", "X-Media-Start-Ms": "15000"})
    assert status == 200
    assert obj["text"] == "hi there" and obj["filtered_repetitive"] == 1 and len(obj["segments"]) == 2
    assert obj["segments"][0] == {"start_ms": 0, "end_ms": 2500, "text": "hi there", "avg_logprob": -0.2,
                                  "no_speech_prob": 0.01, "compression_ratio": 1.2}
    assert obj["request"] == {"source_epoch": "ep-1", "sequence": 5, "media_start_ms": 15000}
    assert obj["model"] == "faster-whisper-stub-int8" and obj["audio_ms"] == 4000
    assert {"compute_ms", "queue_ms", "server_received_at", "server_sent_at"} <= obj.keys()


def test_query_metadata(srv):
    status, obj = post(srv, path="/v1/transcribe?source_epoch=abc&sequence=2&media_start_ms=6000")
    assert status == 200 and obj["request"] == {"source_epoch": "abc", "sequence": 2, "media_start_ms": 6000}


@pytest.mark.parametrize("token", [None, "wrong" * 10, TOKEN + "x"])
def test_auth_required(srv, token):
    assert post(srv, token=token)[0] == 401


def test_body_limits(srv):
    assert post(srv, body=b"\x00" * (320000 + 2))[0] == 413
    assert post(srv, body=b"\x00" * 3)[0] == 400
    assert post(srv, headers={"X-Sequence": "-1"})[0] == 400
    assert post(srv, headers={"X-Source-Epoch": "bad epoch!"})[0] == 400
    assert post(srv, path="/v2/other")[0] == 404


def test_healthz_unauthenticated(srv):
    c = http.client.HTTPConnection("127.0.0.1", srv, timeout=5)
    c.request("GET", "/healthz")
    r = c.getresponse()
    obj = json.loads(r.read())
    assert r.status == 200 and obj["status"] == "ok" and "token" not in json.dumps(obj).lower()


@pytest.mark.parametrize("srv", [(0.6, 0, 5000)], indirect=True)
def test_queue_full_is_503(srv):
    results = []
    t = threading.Thread(target=lambda: results.append(post(srv)[0]))
    t.start()
    time.sleep(0.2)  # first request holds the only slot; queue_cap=0
    assert post(srv)[0] == 503
    t.join()
    assert results == [200]


@pytest.mark.parametrize("srv", [(0.5, 2, 300)], indirect=True)
def test_deadline_exceeded_is_503(srv):
    status, obj = post(srv)
    assert status == 503 and obj["error"] == "deadline_exceeded"


@pytest.mark.parametrize("srv", [(0.0, 2, 2500)], indirect=True)
def test_keep_alive_two_requests_one_connection(srv):
    c = http.client.HTTPConnection("127.0.0.1", srv, timeout=5)
    for _ in range(2):
        c.request("POST", "/v1/transcribe", body=PCM, headers={"Authorization": f"Bearer {TOKEN}"})
        r = c.getresponse()
        assert r.status == 200
        r.read()
    c.close()


@pytest.mark.parametrize("host", ["0.0.0.0", "127.0.0.1", "216.128.140.52", "::", "fazetime-asr", "100.91.148.71"])
def test_bind_check_refuses_non_tailnet(host):
    with pytest.raises(SystemExit):
        check_bind_address(host, "tailscale0", iface_lookup=lambda _i: "100.91.148.70")


def test_bind_check_accepts_tailnet_iface_address():
    assert check_bind_address("100.91.148.70", "tailscale0", iface_lookup=lambda _i: "100.91.148.70") == "100.91.148.70"
    with pytest.raises(SystemExit):  # interface down / missing
        check_bind_address("100.91.148.70", "tailscale0", iface_lookup=lambda _i: None)


def test_config_refuses_missing_token():
    with pytest.raises(SystemExit):
        Config(host="100.91.148.70", token="short").validate()
    assert "t" * 43 not in repr(Config(host="h", token="t" * 43))


def test_build_result_bounds():
    raw = [SimpleNamespace(start=0, end=1, text="x" * 2000, avg_logprob=-0.1, no_speech_prob=0.0,
                           compression_ratio=1.0)] * 50
    r = build_result(raw, 5)
    assert isinstance(r, Result) and len(r.segments) == 32 and len(r.segments[0].text) == 500 and len(r.text) == 1000
