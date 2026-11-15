#!/usr/bin/env python3
"""Provision the FaZeTime remote speech-to-text VM on Vultr (DECISIONS D34). Idempotent.

1. budget check (refuses if projected spend to the teardown deadline would exceed the cap)
2. ensure SSH key 'fazetime-latpop' (public key only)
3. ensure firewall group 'fazetime-asr': inbound TCP 22 only from the given /32 (venue NAT IP)
4. ensure ONE instance labelled 'fazetime-asr' (tag 'fazetime', no backups, no DDoS add-on, no IPv6)
5. wait until it is active/running/ok and print id + public IPv4

Usage: python3 -I provision_asr.py --ssh-pubkey ~/.ssh/mykey.pub --allow-ip 129.107.192.104
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("budget_guard", HERE / "budget_guard.py")
bg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bg)

PLAN = "voc-c-8c-16gb-150s-amd"
REGION = "dfw"
OS_ID = 2284  # Ubuntu 24.04 LTS x64
LABEL = "fazetime-asr"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", type=Path, default=HERE.parents[1] / ".env.local")
    ap.add_argument("--ssh-pubkey", type=Path, required=True)
    ap.add_argument("--allow-ip", required=True, help="IPv4 allowed to reach SSH (venue NAT IP)")
    args = ap.parse_args()
    v = bg.Vultr(bg.load_key(args.env_file))

    existing = [i for i in v.get(f"/instances?tag={bg.TAG}&per_page=500").get("instances", [])
                if i.get("label") == LABEL]
    if not existing:
        hourly = bg.plan_hourly(v)[PLAN]
        s = bg.snapshot(v, extra_hourly=hourly)
        print(json.dumps({"budget_check": {k: s[k] for k in ("pending_usd", "projected_usd", "cap_usd")}}))
        if not (s["projected_usd"] < bg.CAP_USD and s["pending_usd"] < bg.WARN_USD):
            print("REFUSED: projected spend would exceed the cap")
            return 1

    # SSH key (public only)
    keys = v.get("/ssh-keys?per_page=500").get("ssh_keys", [])
    key = next((k for k in keys if k.get("name") == "fazetime-latpop"), None)
    if not key:
        st, body = v._req("POST", "/ssh-keys", {"name": "fazetime-latpop",
                                                "ssh_key": args.ssh_pubkey.read_text().strip()})
        assert st in (200, 201), f"ssh-key create -> {st} {body}"
        key = body["ssh_key"]
    print("ssh key id:", key["id"][:8] + "…")

    # Firewall group: SSH from the venue IP only
    fws = v.get("/firewalls?per_page=500").get("firewall_groups", [])
    fw = next((f for f in fws if f.get("description") == LABEL), None)
    if not fw:
        st, body = v._req("POST", "/firewalls", {"description": LABEL})
        assert st in (200, 201), f"firewall create -> {st} {body}"
        fw = body["firewall_group"]
        st, body = v._req("POST", f"/firewalls/{fw['id']}/rules", {
            "ip_type": "v4", "protocol": "tcp", "subnet": args.allow_ip, "subnet_size": 32,
            "port": "22", "notes": "venue ssh (temporary)"})
        assert st in (200, 201), f"firewall rule -> {st} {body}"
    print("firewall group id:", fw["id"][:8] + "…")

    if existing:
        inst = existing[0]
        print("instance already exists, reusing")
    else:
        st, body = v._req("POST", "/instances", {
            "region": REGION, "plan": PLAN, "os_id": OS_ID, "label": LABEL, "hostname": LABEL,
            "tags": [bg.TAG], "sshkey_id": [key["id"]], "firewall_group_id": fw["id"],
            "backups": "disabled", "enable_ipv6": False, "ddos_protection": False,
            "activation_email": False})
        assert st in (200, 201, 202), f"instance create -> {st} {body}"
        inst = body["instance"]
        print("instance created:", inst["id"][:8] + "…")

    for _ in range(90):  # up to ~7.5 min
        i = v.get(f"/instances/{inst['id']}")["instance"]
        if i.get("status") == "active" and i.get("power_status") == "running" and i.get("server_status") == "ok":
            print(json.dumps({"ready": True, "id": i["id"], "main_ip": i.get("main_ip"), "plan": i.get("plan"),
                              "tags": i.get("tags"), "status": i.get("status")}))
            return 0
        time.sleep(5)
    print(json.dumps({"ready": False, "status": i.get("status"), "server_status": i.get("server_status")}))
    return 2


if __name__ == "__main__":
    sys.exit(main())
