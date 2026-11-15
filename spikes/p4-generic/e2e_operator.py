#!/usr/bin/env python3
"""Local end-to-end operator stand-in for a TEST_FIXTURE run of the generic AI profile. Never a Twitch gate.

Against a throwaway local API (open access on, never the Pi's demo DB), this script:
- opens the D35 operator session;
- creates the stream and sets APPROVAL mode;
- approves every PENDING AI candidate the way the console does (§9.19 item 5: a GENERIC_BINARY_V1 approval sends
  the candidate's close_in_s, so betting runs from approval);
- approves every PENDING_APPROVAL resolution, logging each decision with its media and wall times;
- writes the stream id to --stream-file so the worker can be started with it.

  python3 -I spikes/p4-generic/e2e_operator.py --api http://127.0.0.1:8010 --stream-file F --log L [--minutes 7]
Tokens stay in this process; nothing secret is printed or logged.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
import uuid


def call(api: str, method: str, path: str, token: str | None = None, body: dict | None = None):
    req = urllib.request.Request(api + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://127.0.0.1:8010")
    ap.add_argument("--stream-file", required=True)
    ap.add_argument("--log", required=True)
    ap.add_argument("--minutes", type=float, default=7.0)
    ap.add_argument("--channel", default="fixture_local")
    a = ap.parse_args()
    log = open(a.log, "a")

    def note(event, **kw):
        rec = {"wall": round(time.time(), 1), "event": event, **kw}
        log.write(json.dumps(rec) + "\n")
        log.flush()
        print(event, json.dumps(kw)[:260], flush=True)

    st, body = call(a.api, "POST", "/v1/open/operator-session", body={"device_id": str(uuid.uuid4())})
    token = body.get("session_token") or body.get("token")
    if st not in (200, 201) or not token:
        raise SystemExit(f"operator session failed: HTTP {st} {list(body)}")
    st, body = call(a.api, "POST", "/v1/operator/streams", token,
                    {"operation_id": str(uuid.uuid4()), "twitch_channel_login": a.channel})
    stream_id = (body.get("stream") or {}).get("stream_id") or body.get("stream_id")
    note("STREAM", http=st, stream_id=stream_id)
    open(a.stream_file, "w").write(stream_id or "")
    st, body = call(a.api, "POST", "/v1/operator/ai-mode", token, {"operation_id": str(uuid.uuid4()), "mode": "APPROVAL"})
    note("AI_MODE", http=st, mode=body.get("mode") or body.get("ai_mode"))
    viewers = {}
    for side in ("YES", "NO"):
        stv, bv = call(a.api, "POST", "/v1/enroll", body={"display_name": f"e2e-{side.lower()}",
                                                          "device_id": str(uuid.uuid4())})
        viewers[side] = bv.get("session_token") or bv.get("token")
        note("VIEWER", http=stv, side=side, ok=bool(viewers[side]))

    def bet_both_sides():
        """Two test viewers stake both sides so the market is not voided EMPTY_POOL at lock (D12)."""
        stv, snap = call(a.api, "GET", f"/v1/streams/{stream_id}/snapshot", viewers["YES"])
        m = (snap or {}).get("market") or {}
        for side, tok in viewers.items():
            stw, bw = call(a.api, "POST", "/v1/wagers", tok,
                           {"operation_id": str(uuid.uuid4()), "stream_session_id": m.get("stream_session_id"),
                            "market_id": m.get("market_id"), "rules_version": m.get("rules_version"),
                            "side": side, "amount_minor": 100})
            note("WAGER", http=stw, side=side, market_id=m.get("market_id"),
                 error=(bw.get("error") or {}).get("code") if isinstance(bw.get("error"), dict) else bw.get("error"))

    seen_c, seen_r = set(), set()
    t_end = time.time() + a.minutes * 60
    while time.time() < t_end:
        st, body = call(a.api, "GET", "/v1/operator/candidates", token)
        for c in body.get("candidates", []) if isinstance(body, dict) else []:
            cid = c.get("id") or c.get("cnd_id")
            if cid in seen_c:
                continue
            if c.get("status") == "PENDING":
                seen_c.add(cid)
                generic = c.get("template_id") == "GENERIC_BINARY_V1"
                close = c.get("close_in_s") if generic else None
                st2, b2 = call(a.api, "POST", f"/v1/operator/candidates/{cid}/approve", token,
                               {"operation_id": str(uuid.uuid4()), "close_in_s": close})
                note("APPROVE_CANDIDATE", http=st2, question=c.get("question"), template=c.get("template_id"),
                     kind=(c.get("generic") or {}).get("kind"), close_in_s=close,
                     market_id=(b2.get("market") or {}).get("market_id") or b2.get("market_id"),
                     error=b2.get("error") or b2.get("code"))
                if st2 == 200:
                    bet_both_sides()
            elif c.get("status") == "REJECTED":
                seen_c.add(cid)
                note("CANDIDATE_REJECTED", question=c.get("question"), code=c.get("reject_code"))
        st, body = call(a.api, "GET", "/v1/operator/resolutions", token)
        for r in body.get("resolutions", []) if isinstance(body, dict) else []:
            rid = r.get("id") or r.get("rsl_id")
            if rid in seen_r:
                continue
            seen_r.add(rid)
            note("RESOLUTION", decision=r.get("decision"), status=r.get("status"), market_id=r.get("market_id"),
                 reason=(r.get("reason") or "")[:160], media_interval=r.get("media_interval"))
            if r.get("status") == "PENDING_APPROVAL":
                st2, b2 = call(a.api, "POST", f"/v1/operator/resolutions/{rid}/approve", token,
                               {"operation_id": str(uuid.uuid4())})
                note("APPROVE_RESOLUTION", http=st2, result=b2.get("status") or b2.get("market", {}).get("state"),
                     error=b2.get("error") or b2.get("code"))
        time.sleep(1.0)
    note("DONE")


if __name__ == "__main__":
    main()
