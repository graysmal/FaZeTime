"""Manual smoke against a RUNNING API (uvicorn). Tokens/invite codes stay in memory; output is sanitized.

  FAZETIME_DB_PATH=/path/to/smoke.db uv run python -m fazetime_api serve &      # terminal 1
  FAZETIME_DB_PATH=/path/to/smoke.db uv run python scripts/smoke.py             # terminal 2

Sequence: bootstrap operator (CLI) -> enroll operator -> create stream/run -> invites -> enroll 2 viewers
-> WS subscribe -> fixture market DRAFT -> OPEN -> 2 wagers -> wait for sweeper lock -> settle -> snapshots,
ledger reconciliation. TEST MONEY ONLY.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone

import websockets

BASE = os.environ.get("FAZETIME_BASE", "http://127.0.0.1:8000")
WS_BASE = BASE.replace("http://", "ws://").replace("https://", "wss://")


def call(method: str, path: str, token: str | None = None, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read())


def op() -> str:
    return str(uuid.uuid4())


def show(label: str, status: int, value) -> None:
    print(f"{label:<44} HTTP {status}  {value}")


async def collect_ws(ticket: str, stop: asyncio.Event, seen: list) -> None:
    async with websockets.connect(WS_BASE + "/v1/ws", origin="https://www.twitch.tv") as ws:
        await ws.send(json.dumps({"type": "auth", "ticket": ticket}))
        ready = json.loads(await ws.recv())
        seen.append(("ready", ready["event_hwm"]))
        while not stop.is_set():
            try:
                frame = json.loads(await asyncio.wait_for(ws.recv(), timeout=0.5))
            except asyncio.TimeoutError:
                continue
            if frame.get("type") == "event":
                e = frame["event"]
                seen.append((e["event_type"], e["aggregate_version"]))


async def main() -> int:
    out = subprocess.run([sys.executable, "-m", "fazetime_api", "bootstrap-operator"], capture_output=True,
                         text=True, check=True)
    code = out.stdout.strip().splitlines()[-1]  # never printed
    print("bootstrap-operator: invite printed to terminal (redacted here)")
    s, enr = call("POST", "/v1/enroll", body={"invite_code": code, "display_name": "Operator", "device_id": op()})
    show("enroll operator", s, enr["me"]["user"]["role"])
    opr = enr["session_token"]
    s, st = call("POST", "/v1/operator/streams", opr, {"operation_id": op(), "twitch_channel_login": "fazetime_demo"})
    show("create stream/run", s, {"created": st["created"], "run_state": st["stream"]["run_state"]})
    stream_id = st["stream"]["stream_id"]
    viewers = {}
    for name in ("Alice", "Bob"):
        s, inv = call("POST", "/v1/operator/invites", opr, {"operation_id": op(), "role": "VIEWER"})
        s2, e = call("POST", "/v1/enroll", body={"invite_code": inv["invite_code"], "display_name": name,
                                                 "device_id": op()})
        viewers[name] = e["session_token"]
        show(f"invite + enroll {name}", s2, {"role": e["me"]["user"]["role"],
                                             "available_minor": e["me"]["wallet"]["available_minor"]})
    s, t = call("POST", "/v1/ws-ticket", viewers["Alice"], {"stream_id": stream_id})
    stop, seen = asyncio.Event(), []
    ws_task = asyncio.create_task(collect_ws(t["ticket"], stop, seen))
    await asyncio.sleep(0.5)
    s, d = call("POST", "/v1/operator/markets", opr, {"operation_id": op(), "question": "Smoke: will YES win?",
                                                     "close_in_s": 30, "resolve_in_s": 120})
    show("create fixture market", s, {"state": d["market"]["state"], "origin": d["market"]["origin"]})
    market_id = d["market"]["market_id"]
    s, o = call("POST", f"/v1/operator/markets/{market_id}/open", opr, {"operation_id": op()})
    m = o["market"]
    show("open market", s, {"state": m["state"], "close_at_utc": m["close_at_utc"]})
    base = {"stream_session_id": m["stream_session_id"], "market_id": market_id, "rules_version": m["rules_version"]}
    key = op()
    s, w1 = call("POST", "/v1/wagers", viewers["Alice"], {**base, "operation_id": key, "side": "YES", "amount_minor": 500})
    show("Alice wagers YES 500", s, {"status": w1["status"], "available_after": w1["wallet_after"]["available_minor"]})
    s, w1r = call("POST", "/v1/wagers", viewers["Alice"], {**base, "operation_id": key, "side": "YES", "amount_minor": 500})
    show("Alice replays same operation_id", s, {"replayed": w1r["replayed"], "same_wager": w1r["wager_id"] == w1["wager_id"]})
    s, w2 = call("POST", "/v1/wagers", viewers["Bob"], {**base, "operation_id": op(), "side": "NO", "amount_minor": 700})
    show("Bob wagers NO 700", s, {"status": w2["status"], "available_after": w2["wallet_after"]["available_minor"]})
    s, bad = call("POST", "/v1/wagers", viewers["Bob"], {**base, "operation_id": op(), "side": "YES", "amount_minor": 500})
    show("Bob tries other side", s, bad["error"]["code"])
    close_at = datetime.strptime(m["close_at_utc"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    wait = (close_at - datetime.now(timezone.utc)).total_seconds() + 2.5
    print(f"waiting {wait:.1f}s for close_at + sweeper ...")
    time.sleep(max(0.0, wait))
    s, late = call("POST", "/v1/wagers", viewers["Bob"], {**base, "operation_id": op(), "side": "NO", "amount_minor": 100})
    show("late wager after close", s, (late["error"]["code"], late["error"]["details"]["reason"]))
    s, snap = call("GET", f"/v1/streams/{stream_id}/snapshot", viewers["Alice"])
    show("snapshot after lock", s, {"state": snap["market"]["state"], "pool": snap["market"]["pool"]})
    s, st = call("POST", f"/v1/operator/markets/{market_id}/settle", opr, {"operation_id": op(), "winning_side": "YES"})
    show("settle YES", s, {"state": st["market"]["state"], "winning_side": st["market"]["winning_side"]})
    for name in ("Alice", "Bob"):
        s, snap = call("GET", f"/v1/streams/{stream_id}/snapshot", viewers[name])
        pos = snap["my_position"]
        show(f"snapshot {name}", s, {"result": pos["result"], "payout_total_minor": pos["payout_total_minor"],
                                     "available_minor": snap["wallet"]["available_minor"],
                                     "in_play_minor": snap["wallet"]["in_play_minor"], "event_hwm": snap["event_hwm"]})
    s, health = call("GET", "/v1/operator/health", opr)
    show("operator health reconciliation", s, health["reconciliation"])
    show("operator health service", s, {"sqlite": health["service"]["sqlite_version"],
                                        "pragmas": health["service"]["pragmas"],
                                        "sweeper_runs>0": health["sweeper"]["runs"] > 0})
    s, ledger = call("GET", "/v1/operator/ledger", opr)
    show("ledger transactions (reason, entries sum)", s,
         [(t["reason"], sum(e["amount_minor"] for e in t["entries"])) for t in reversed(ledger["transactions"])])
    s, viewer_op = call("GET", "/v1/operator/health", viewers["Alice"])
    show("viewer calls operator route", s, viewer_op["error"]["code"])
    await asyncio.sleep(1.5)
    stop.set()
    await ws_task
    print("Alice WS frames:", seen)
    return 0 if health["reconciliation"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
