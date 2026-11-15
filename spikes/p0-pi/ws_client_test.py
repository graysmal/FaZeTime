#!/usr/bin/env python3
"""P0-F laptop-side client: WebSocket RTT, 2-minute true-idle hold, and server-restart reconnect.

Spike code only. Client keepalive pings are disabled (ping_interval=None), matching a browser, which never
initiates pings. Durations use this host's monotonic clock only; nothing is compared across machines.
The --restart-cmd is a shell command (e.g. an ssh call) that restarts the server on the Pi; its own
round trip is included in the close-detection time.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import time
from datetime import datetime, timezone

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed


def utc():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def pctl(xs, q):
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def stats(rtts):
    ms = [r * 1000 for r in rtts]
    return {"n": len(ms), "p50_ms": round(pctl(ms, .5), 1), "p95_ms": round(pctl(ms, .95), 1),
            "min_ms": round(min(ms), 1), "max_ms": round(max(ms), 1)}


async def rtt_burst(ws, n, tag, pad):
    rtts = []
    for i in range(n):
        msg = json.dumps({"tag": tag, "seq": i, "pad": "x" * pad})
        t = time.perf_counter()
        await ws.send(msg)
        echo = await asyncio.wait_for(ws.recv(), timeout=10)
        rtts.append(time.perf_counter() - t)
        assert echo == msg, "echo mismatch"
    return rtts


async def open_ws(url):
    t = time.perf_counter()
    ws = await connect(url, ping_interval=None, open_timeout=10, close_timeout=5)
    return ws, time.perf_counter() - t


async def main(a):
    rep = {"url": a.url, "started_utc": utc(), "client_ping_interval": None, "payload_pad_bytes": a.pad}
    ws, t_conn = await open_ws(a.url)
    rep["connect_s"] = round(t_conn, 3)
    rep["rtt_20"] = stats(await rtt_burst(ws, a.n, "burst", a.pad))
    print("rtt_20", rep["rtt_20"], flush=True)

    # true idle hold: no client pings, no server pings (server started with --ping-interval 0)
    t = time.perf_counter()
    await asyncio.sleep(a.idle_s)
    rep["idle_held_s"] = round(time.perf_counter() - t, 1)
    try:
        rep["after_idle"] = stats(await rtt_burst(ws, 5, "after_idle", a.pad))
        rep["after_idle"]["ok"] = True
    except (ConnectionClosed, asyncio.TimeoutError, OSError) as e:
        rep["after_idle"] = {"ok": False, "error": repr(e)}
    print("after_idle", rep["after_idle"], flush=True)

    # restart: issue restart command, measure close detection and reconnect on this host only
    if a.restart_cmd:
        t0 = time.perf_counter()
        proc = subprocess.Popen(a.restart_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True)
        close_code = close_reason = None
        try:
            await asyncio.wait_for(ws.recv(), timeout=30)
            close_code = "no close: unexpected message"
        except ConnectionClosed as e:
            close_code, close_reason = (e.rcvd.code, e.rcvd.reason) if e.rcvd else ("no close frame", None)
        except asyncio.TimeoutError:
            close_code = "not detected within 30 s"
        t_closed = time.perf_counter()
        attempts, ws2, last_err = 0, None, None
        while time.perf_counter() - t_closed < 60:
            attempts += 1
            try:
                ws2, _ = await open_ws(a.url)
                break
            except (OSError, asyncio.TimeoutError, Exception) as e:  # noqa: BLE001 - record and retry
                last_err = type(e).__name__
                await asyncio.sleep(a.retry_s)
        t_re = time.perf_counter()
        out = proc.communicate(timeout=30)[0]
        rep["restart"] = {"close_code": close_code, "close_reason": close_reason,
                          "issue_to_close_detected_s": round(t_closed - t0, 3),
                          "close_to_reconnected_s": round(t_re - t_closed, 3) if ws2 else None,
                          "reconnect_attempts": attempts, "last_connect_error": last_err,
                          "restart_cmd_rc": proc.returncode, "restart_cmd_output_tail": out.strip()[-300:]}
        if ws2:
            rep["after_restart"] = stats(await rtt_burst(ws2, 5, "after_restart", a.pad))
            await ws2.close()
        print("restart", rep["restart"], rep.get("after_restart"), flush=True)
    else:
        await ws.close()
    rep["finished_utc"] = utc()
    if a.out:
        with open(a.out, "w") as f:
            json.dump(rep, f, indent=1)
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="ws://fazetime:8787/ws")
    p.add_argument("--n", type=int, default=20)
    p.add_argument("--pad", type=int, default=256)
    p.add_argument("--idle-s", type=float, default=120)
    p.add_argument("--restart-cmd", default="")
    p.add_argument("--retry-s", type=float, default=0.25)
    p.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "out",
                                                 "ws_client_test.json"))
    asyncio.run(main(p.parse_args()))
