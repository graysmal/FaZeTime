"""End-to-end check of the bookie desk against a throwaway local FaZeTime API (CONTRACTS 9.21).

Usage (from services/call-agent): .venv/bin/python scripts/bookie_e2e_local.py

Starts services/api on 127.0.0.1:18000 with a temporary data dir and open access, creates
a stream, enrolls a viewer, binds the line to it and mints a CALL_WORKER token with the
real CLI, opens a 10-minute market, then drives the agent's BookieDesk exactly as the
voice tools do (odds, prepare, readback + spoken yes, confirm) and checks the result in
the viewer's own snapshot. Negative cases: confirm without a yes, repeat confirm, cancel,
other side. Touches nothing outside the temp dir; prints no tokens.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from bookie_desk import BookieDesk, FazetimeClient  # noqa: E402

API_DIR = HERE.parent / "api"
PY = str(API_DIR / ".venv" / "bin" / "python")
PORT = 18000
BASE = f"http://127.0.0.1:{PORT}"


def http(method: str, path: str, body: dict | None = None, token: str | None = None) -> dict:
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def cli(env: dict, *args: str) -> str:
    return subprocess.run([PY, "-m", "fazetime_api", *args], cwd=API_DIR, env=env, capture_output=True, text=True, check=True).stdout


def check(cond: bool, what: str) -> None:
    print(("PASS " if cond else "FAIL ") + what)
    if not cond:
        raise SystemExit(1)


async def drive(token: str, snapshot) -> None:
    desk = BookieDesk(FazetimeClient(BASE, token), single_caller=lambda: True)
    odds = await desk.odds()
    print("odds:", odds)
    check("Gavin" in odds and "Estimated returns" in odds and "available" in odds, "overview describes market, estimates and wallet")

    before = snapshot()
    out = await desk.prepare("Gavin", 10)
    print("prepare:", out)
    check(out.startswith("PENDING"), "prepare returns a pending intent, not a bet")
    check(snapshot()["my_position"]["stake_total_minor"] == before["my_position"]["stake_total_minor"], "prepare moves no money")

    out = await desk.confirm()
    check(out.startswith("NOT CONFIRMED"), "confirm without a readback and yes is refused")

    await asyncio.sleep(1.6)
    desk.on_agent_state("speaking", "listening")  # readback finished
    await asyncio.sleep(0.1)
    desk.on_user_final("yeah lock it in")
    out = await desk.confirm()
    print("confirm:", out)
    check(out.startswith("CONFIRMED"), "confirm after readback and a clear yes places the bet")
    after = snapshot()
    check(after["my_position"]["stake_total_minor"] == before["my_position"]["stake_total_minor"] + 1000, "exactly $10 staked")
    check(after["wallet"]["available_minor"] == before["wallet"]["available_minor"] - 1000, "wallet debited exactly once")

    out = await desk.confirm()
    check(out.startswith("NOT CONFIRMED"), "a second confirm cannot place another bet")
    check(snapshot()["my_position"]["stake_total_minor"] == after["my_position"]["stake_total_minor"], "still exactly one stake")

    out = await desk.prepare("yes", 5)
    check(out.startswith("PENDING"), "second prepare")
    out = await desk.cancel()
    check(out.startswith("Cancelled"), "cancel")
    check(snapshot()["my_position"]["stake_total_minor"] == after["my_position"]["stake_total_minor"], "cancel moves no money")

    out = await desk.prepare("Neville", 5)
    print("other side:", out)
    check("other side" in out, "betting the other side is refused (SIDE_CONFLICT)")

    out = await desk.prepare("yes", 1_000_000)
    check(out.startswith("That amount") or "Not enough" in out, "oversized stake refused")
    await desk.aclose()


def main() -> None:
    tmp = tempfile.mkdtemp(prefix="bookie-e2e-")
    env = {**os.environ, "FAZETIME_DATA_DIR": tmp, "FAZETIME_OPEN_ACCESS": "1", "FAZETIME_HOST": "127.0.0.1", "FAZETIME_PORT": str(PORT)}
    server = subprocess.Popen([PY, "-m", "fazetime_api", "serve", "--host", "127.0.0.1", "--port", str(PORT)],
                              cwd=API_DIR, env=env, stdout=subprocess.DEVNULL, stderr=open(Path(tmp) / "server.log", "w"))
    try:
        for _ in range(100):
            try:
                http("GET", "/healthz")
                break
            except Exception:
                time.sleep(0.1)
        op = http("POST", "/v1/open/operator-session", {"device_id": str(uuid.uuid4())})["session_token"]
        stream = http("POST", "/v1/operator/streams", {"operation_id": str(uuid.uuid4()), "twitch_channel_login": "fazegavin1234"}, op)
        stream_id = (stream.get("stream") or stream).get("stream_id")
        viewer = http("POST", "/v1/enroll", {"display_name": "Phone Bettor", "device_id": str(uuid.uuid4())})
        vtok, user_id = viewer["session_token"], viewer["me"]["user"]["user_id"]
        print(cli(env, "bind-call-user", "--user-id", user_id).strip())
        m = re.search(r"fzk_[A-Za-z0-9_-]{20,}", cli(env, "issue-call-worker-token", "--label", "e2e"))
        check(bool(m), "CALL_WORKER token minted")
        mk = http("POST", "/v1/operator/markets", {"operation_id": str(uuid.uuid4()), "question": "Will FaZeGavin win the next 1v1 round?",
                                                   "yes_label": "Gavin", "no_label": "Neville", "close_in_s": 600, "resolve_in_s": 1200}, op)["market"]
        if mk.get("state") == "DRAFT":
            http("POST", f"/v1/operator/markets/{mk['market_id']}/open", {"operation_id": str(uuid.uuid4())}, op)

        def snapshot():
            return http("GET", f"/v1/streams/{stream_id}/snapshot", token=vtok)

        asyncio.run(drive(m.group(0), snapshot))
        print("ALL PASS")
    finally:
        server.terminate()
        server.wait(timeout=10)


if __name__ == "__main__":
    main()
