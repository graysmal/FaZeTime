"""Demo helpers for the phone bookie, using the existing FaZeTime HTTP API (stdlib only).

  python3 scripts/demo_market.py enroll --name "Phone Bettor"      # prints the new viewer's user_id
  python3 scripts/demo_market.py open --minutes 15 [--question ...] [--yes ...] [--no ...]
  python3 scripts/demo_market.py settle --market mkt_... --side YES|NO
  python3 scripts/demo_market.py void --market mkt_...

- `open`, `settle` and `void` act as the operator through the D35 open-access operator
  session (POST /v1/open/operator-session), exactly as the operator console does.
- `enroll` creates a VIEWER by name (open access), which gets the normal seed grant.
- Session tokens stay in memory and are never printed. Test credits only.
- A long-window operator market is a fixture: say so when presenting it (D31).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import uuid

BASE = os.environ.get("FAZETIME_API_BASE", "http://fazetime:8000").rstrip("/")


def call(method: str, path: str, body: dict | None = None, token: str | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        try:
            err = json.load(e).get("error", {})
        except Exception:
            err = {}
        sys.exit(f"{method} {path} -> HTTP {e.code} {err.get('code')} {err.get('message', '')} {err.get('details') or ''}")


def operator_token() -> str:
    return call("POST", "/v1/open/operator-session", {"device_id": str(uuid.uuid4())})["session_token"]


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("enroll")
    e.add_argument("--name", default="Phone Bettor")
    o = sub.add_parser("open")
    o.add_argument("--minutes", type=float, default=15)
    o.add_argument("--question", default="Will FaZeGavin win the next 1v1 round?")
    o.add_argument("--yes", default="Gavin")
    o.add_argument("--no", default="Neville")
    s = sub.add_parser("settle")
    s.add_argument("--market", required=True)
    s.add_argument("--side", choices=["YES", "NO"], required=True)
    v = sub.add_parser("void")
    v.add_argument("--market", required=True)
    a = ap.parse_args()

    if a.cmd == "enroll":
        r = call("POST", "/v1/enroll", {"display_name": a.name, "device_id": str(uuid.uuid4())})
        me = r.get("me") or {}
        user = me.get("user") or {}
        wallet = me.get("wallet") or {}
        print(f"enrolled {user.get('display_name')!r}: user_id {user.get('user_id')}, available {wallet.get('available_minor')} minor")
        return

    tok = operator_token()
    if a.cmd == "open":
        close_s = int(a.minutes * 60)
        created = call("POST", "/v1/operator/markets", {
            "operation_id": str(uuid.uuid4()), "question": a.question, "yes_label": a.yes, "no_label": a.no,
            "close_in_s": close_s, "resolve_in_s": close_s + 600,
        }, tok)["market"]
        mid = created["market_id"]
        if created.get("state") == "DRAFT":
            created = call("POST", f"/v1/operator/markets/{mid}/open", {"operation_id": str(uuid.uuid4())}, tok)["market"]
        print(f"market {mid}: state {created.get('state')}, closes {created.get('close_at_utc')}")
    elif a.cmd == "settle":
        m = call("POST", f"/v1/operator/markets/{a.market}/settle",
                 {"operation_id": str(uuid.uuid4()), "winning_side": a.side, "note": "phone bookie demo"}, tok)["market"]
        print(f"market {a.market}: state {m.get('state')}")
    elif a.cmd == "void":
        m = call("POST", f"/v1/operator/markets/{a.market}/void",
                 {"operation_id": str(uuid.uuid4()), "note": "phone bookie demo"}, tok)["market"]
        print(f"market {a.market}: state {m.get('state')}")


if __name__ == "__main__":
    main()
