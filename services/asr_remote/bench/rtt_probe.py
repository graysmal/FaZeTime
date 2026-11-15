#!/usr/bin/env python3
"""Pi -> VM round trip for 4 s chunks over the tailnet (D34). Run on the Pi with the worker venv python.

Reads `ASR_REMOTE_TOKEN=...` (or the bare token) from stdin so it never appears in argv or shell history.
Prints timing statistics only, never transcript text.
Usage: python -I rtt_probe.py URL AUDIO_DIR [N] < token_line
"""
from __future__ import annotations

import json
import sys
import time
import wave
from pathlib import Path

import requests


def pctl(xs, q):
    xs = sorted(xs)
    if not xs:
        return None
    k = (len(xs) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo), 1)


def main():
    url, audio_dir = sys.argv[1].rstrip("/"), Path(sys.argv[2])
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 25
    token = sys.stdin.readline().strip().split("=", 1)[-1]
    files = sorted(audio_dir.glob("a_1cca078b_*.wav"))[:n]
    chunks = []
    for f in files:
        with wave.open(str(f), "rb") as w:
            pcm = w.readframes(w.getnframes())
        chunks.append((f.stem, pcm[: 4 * 16000 * 2]))
    s = requests.Session()
    hz = []
    for _ in range(20):
        t = time.perf_counter()
        s.get(f"{url}/healthz", timeout=(2, 5)).raise_for_status()
        hz.append((time.perf_counter() - t) * 1000)
    auth_checks = {}
    for label, hdr in (("no_token", {}), ("wrong_token", {"Authorization": "Bearer " + "w" * 43})):
        r = s.post(f"{url}/v1/transcribe", data=chunks[0][1], timeout=(2, 5),
                   headers={"Content-Type": "application/octet-stream", **hdr})
        auth_checks[label] = r.status_code
    s = requests.Session()  # the server closes the connection after a 401
    rtt, comp, queue, net, statuses = [], [], [], [], {}
    words, segs_total = 0, 0
    for i, (stem, pcm) in enumerate(chunks):
        t = time.perf_counter()
        r = s.post(f"{url}/v1/transcribe", data=pcm, timeout=(2, 5),
                   headers={"Authorization": f"Bearer {token}", "Content-Type": "application/octet-stream",
                            "X-Source-Epoch": "rtt-probe", "X-Sequence": str(i), "X-Media-Start-Ms": str(i * 4000)})
        el = (time.perf_counter() - t) * 1000
        statuses[r.status_code] = statuses.get(r.status_code, 0) + 1
        if r.status_code == 200:
            o = r.json()
            rtt.append(el)
            comp.append(o["compute_ms"])
            queue.append(o["queue_ms"])
            net.append(el - o["compute_ms"] - o["queue_ms"])
            words += len(o["text"].split())
            segs_total += len(o["segments"])
            model = o["model"]
        time.sleep(0.3)
    print(json.dumps({"url": url, "model": locals().get("model"), "n": len(chunks),
                      "body_bytes": len(chunks[0][1]) if chunks else 0, "statuses": statuses,
                      "auth_checks": auth_checks, "words_returned": words, "segments_returned": segs_total,
                      "healthz_ms": {"p50": pctl(hz, .5), "p95": pctl(hz, .95), "max": round(max(hz), 1)},
                      "rtt_ms": {"p50": pctl(rtt, .5), "p95": pctl(rtt, .95), "max": round(max(rtt), 1) if rtt else None},
                      "server_compute_ms": {"p50": pctl(comp, .5), "p95": pctl(comp, .95)},
                      "server_queue_ms": {"p50": pctl(queue, .5), "p95": pctl(queue, .95)},
                      "network_and_http_overhead_ms": {"p50": pctl(net, .5), "p95": pctl(net, .95)}}))


if __name__ == "__main__":
    main()
