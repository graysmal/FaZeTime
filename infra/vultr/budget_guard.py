#!/usr/bin/env python3
"""FaZeTime Vultr budget guard (DECISIONS D34).

Vultr has no self-service hard spending cap, so this enforces the owner's limit:
$100 total including tax  ->  usage hard stop CAP_USD = $85 pre-tax
(worst-case Texas sales tax 8.25% on 80% of the invoice: 85 * 1.066 = $90.61).

Commands:
  status                     pending charges, fazetime-tagged resources, burn rate, projection to deadline
  check-create PLAN [-n N]   exit 0 only if projected spend incl. N new PLAN instances stays under the cap
  run [--interval S]         poll forever: warn at WARN_USD; destroy every fazetime resource at CAP_USD
                             or at the teardown deadline, then exit
  teardown                   destroy every fazetime resource now

Only resources tagged/labelled "fazetime" are ever touched. Reads VULTR_API_KEY from an env file
(default: the repo's .env.local) and never prints it. Standard library only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.vultr.com/v2"
TAG = "fazetime"
CAP_USD = 85.00
WARN_USD = 70.00
# Sunday 2026-11-15 18:00 America/Chicago (CST, UTC-6) == 2026-11-16 00:00 UTC.
DEADLINE_UTC = dt.datetime(2026, 11, 16, 0, 0, tzinfo=dt.timezone.utc)
LB_HOURLY = 10.0 / 730          # load balancer, approx list price
BLOCK_GB_HOURLY = 0.10 / 730    # block storage per GB, approx list price
SNAPSHOT_GB_HOURLY = 0.05 / 730


def load_key(env_file: Path) -> str:
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[7:]
        if line.startswith("VULTR_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit("VULTR_API_KEY not found in env file")


class Vultr:
    def __init__(self, key: str):
        self._key = key

    def _req(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(API + path, data=data, method=method, headers={
            "Authorization": "Bearer " + self._key,
            "Content-Type": "application/json",
            "User-Agent": "fazetime-budget-guard",
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw) if raw else None
            except Exception:
                return e.code, None

    def get(self, path):
        st, body = self._req("GET", path)
        if st != 200:
            raise RuntimeError(f"GET {path.split('?')[0]} -> {st} {(body or {}).get('error', '')}")
        return body

    def delete(self, path):
        return self._req("DELETE", path)[0]


def plan_hourly(v: Vultr) -> dict[str, float]:
    plans = v.get("/plans?per_page=500&type=all").get("plans", [])
    return {p["id"]: (p.get("hourly_cost") or p.get("monthly_cost", 0) / 730) for p in plans}


def resources(v: Vultr) -> list[dict]:
    hourly = plan_hourly(v)
    out: list[dict] = []
    for i in v.get(f"/instances?tag={TAG}&per_page=500").get("instances", []):
        out.append({"kind": "instance", "id": i["id"], "label": i.get("label"), "plan": i.get("plan"),
                    "hourly": hourly.get(i.get("plan"), 0.0), "status": i.get("status"),
                    "path": f"/instances/{i['id']}"})
    for c in v.get("/kubernetes/clusters?per_page=500").get("vke_clusters", []):
        if (c.get("label") or "").startswith(TAG):
            h = sum(hourly.get(np_.get("plan"), 0.0) * int(np_.get("node_quantity") or 0)
                    for np_ in c.get("node_pools", []))
            out.append({"kind": "vke", "id": c["id"], "label": c.get("label"), "plan": "node pools",
                        "hourly": h, "status": c.get("status"),
                        "path": f"/kubernetes/clusters/{c['id']}/delete-with-linked-resources"})
    for lb in v.get("/load-balancers?per_page=500").get("load_balancers", []):
        if (lb.get("label") or "").startswith(TAG):
            out.append({"kind": "load_balancer", "id": lb["id"], "label": lb.get("label"), "plan": "lb",
                        "hourly": LB_HOURLY, "status": lb.get("status"), "path": f"/load-balancers/{lb['id']}"})
    for b in v.get("/blocks?per_page=500").get("blocks", []):
        if (b.get("label") or "").startswith(TAG):
            out.append({"kind": "block", "id": b["id"], "label": b.get("label"), "plan": f"{b.get('size_gb')}GB",
                        "hourly": BLOCK_GB_HOURLY * float(b.get("size_gb") or 0), "status": b.get("status"),
                        "path": f"/blocks/{b['id']}"})
    for s in v.get("/snapshots?per_page=500").get("snapshots", []):
        if (s.get("description") or "").startswith(TAG):
            gb = float(s.get("size") or 0) / 1e9
            out.append({"kind": "snapshot", "id": s["id"], "label": s.get("description"), "plan": f"{gb:.1f}GB",
                        "hourly": SNAPSHOT_GB_HOURLY * gb, "status": s.get("status"),
                        "path": f"/snapshots/{s['id']}"})
    return out


def account(v: Vultr) -> tuple[float, float]:
    a = v.get("/account")["account"]
    return float(a.get("pending_charges") or 0.0), float(a.get("balance") or 0.0)


def snapshot(v: Vultr, extra_hourly: float = 0.0) -> dict:
    now = dt.datetime.now(dt.timezone.utc)
    pending, balance = account(v)
    res = resources(v)
    burn = sum(r["hourly"] for r in res) + extra_hourly
    hours_left = max(0.0, (DEADLINE_UTC - now).total_seconds() / 3600)
    return {"at_utc": now.isoformat(timespec="seconds"), "pending_usd": round(pending, 4),
            "balance_usd": balance, "burn_usd_per_h": round(burn, 4), "hours_to_deadline": round(hours_left, 2),
            "projected_usd": round(pending + burn * hours_left, 2), "cap_usd": CAP_USD, "warn_usd": WARN_USD,
            "resources": [{k: r[k] for k in ("kind", "label", "plan", "hourly", "status")} for r in res],
            "_res": res}


def destroy_all(v: Vultr, res: list[dict], log) -> None:
    for r in res:
        st = v.delete(r["path"])
        log({"event": "DESTROY", "kind": r["kind"], "label": r["label"], "http": st})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env-file", type=Path, default=Path(__file__).resolve().parents[2] / ".env.local")
    ap.add_argument("--log", type=Path, default=None, help="append JSON lines here as well as stdout")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    cc = sub.add_parser("check-create")
    cc.add_argument("plan")
    cc.add_argument("-n", "--count", type=int, default=1)
    rn = sub.add_parser("run")
    rn.add_argument("--interval", type=int, default=300)
    sub.add_parser("teardown")
    args = ap.parse_args()

    v = Vultr(load_key(args.env_file))

    def log(obj: dict) -> None:
        obj = {"at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), **obj}
        line = json.dumps(obj, default=str)
        print(line, flush=True)
        if args.log:
            with args.log.open("a") as f:
                f.write(line + "\n")

    if args.cmd == "status":
        s = snapshot(v)
        s.pop("_res")
        print(json.dumps(s, indent=1))
        return 0

    if args.cmd == "check-create":
        hourly = plan_hourly(v).get(args.plan)
        if hourly is None:
            print(f"unknown plan {args.plan}")
            return 2
        s = snapshot(v, extra_hourly=hourly * args.count)
        ok = s["projected_usd"] < CAP_USD and s["pending_usd"] < WARN_USD
        print(json.dumps({"plan": args.plan, "count": args.count, "plan_usd_per_h": hourly,
                          "projected_usd_with_new": s["projected_usd"], "cap_usd": CAP_USD,
                          "pending_usd": s["pending_usd"], "ok": ok}, indent=1))
        return 0 if ok else 1

    if args.cmd == "teardown":
        s = snapshot(v)
        destroy_all(v, s["_res"], log)
        log({"event": "TEARDOWN_DONE", "count": len(s["_res"])})
        return 0

    # run
    log({"event": "GUARD_START", "cap_usd": CAP_USD, "warn_usd": WARN_USD, "deadline_utc": DEADLINE_UTC.isoformat()})
    while True:
        try:
            s = snapshot(v)
            res = s.pop("_res")
            now = dt.datetime.now(dt.timezone.utc)
            if s["pending_usd"] >= CAP_USD or now >= DEADLINE_UTC:
                reason = "CAP_REACHED" if s["pending_usd"] >= CAP_USD else "DEADLINE_REACHED"
                log({"event": reason, **{k: s[k] for k in ("pending_usd", "burn_usd_per_h")}})
                destroy_all(v, res, log)
                log({"event": "GUARD_EXIT_AFTER_TEARDOWN"})
                return 0
            level = "WARN" if (s["pending_usd"] >= WARN_USD or s["projected_usd"] >= CAP_USD) else "OK"
            log({"event": level, **{k: s[k] for k in ("pending_usd", "burn_usd_per_h", "projected_usd",
                                                          "hours_to_deadline")}, "n_resources": len(res)})
        except Exception as e:  # never die silently; keep guarding
            log({"event": "ERROR", "error": str(e)[:200]})
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
