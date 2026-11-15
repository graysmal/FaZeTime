#!/usr/bin/env python3
"""Stake both sides of the open market with two clearly labelled TEST viewers (test credits only, D01).

A market with an empty or one-sided pool is voided at lock (D12), so a solo live test needs one YES and one NO stake to
exercise AI resolution. Uses open access (D35) on our own API. Session tokens are kept in a mode-600 file and are never
printed.

  python3 -I spikes/p4-generic/stake_both_sides.py --api http://fazetime:8000 --stream-id STR --tokens FILE
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
import uuid


def call(api, method, path, token=None, body=None):
    req = urllib.request.Request(api + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json",
                                          **({"Authorization": f"Bearer {token}"} if token else {})})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", required=True)
    ap.add_argument("--stream-id", required=True)
    ap.add_argument("--tokens", required=True, help="mode-600 JSON file for the two test viewers' session tokens")
    ap.add_argument("--amount", type=int, default=100)
    a = ap.parse_args()
    toks = {}
    if os.path.exists(a.tokens):
        toks = json.load(open(a.tokens))
    for side in ("YES", "NO"):
        if not toks.get(side):
            st, b = call(a.api, "POST", "/v1/enroll", body={"display_name": f"TEST viewer {side}",
                                                              "device_id": str(uuid.uuid4())})
            toks[side] = b.get("session_token") or b.get("token")
            print("enrolled", side, "http", st)
    old = os.umask(0o077)
    try:
        json.dump(toks, open(a.tokens, "w"))
    finally:
        os.umask(old)
    st, snap = call(a.api, "GET", f"/v1/streams/{a.stream_id}/snapshot", toks["YES"])
    m = (snap or {}).get("market") or {}
    if not m.get("market_id"):
        print("no open market", st)
        return
    print("market", m.get("market_id"), m.get("state"), repr(m.get("question")))
    for side, tok in toks.items():
        st, b = call(a.api, "POST", "/v1/wagers", tok, {"operation_id": str(uuid.uuid4()),
                                                        "stream_session_id": m.get("stream_session_id"),
                                                        "market_id": m.get("market_id"),
                                                        "rules_version": m.get("rules_version"), "side": side,
                                                        "amount_minor": a.amount})
        err = b.get("error")
        print("wager", side, "http", st, (err or {}).get("code") if isinstance(err, dict) else "")


if __name__ == "__main__":
    main()
