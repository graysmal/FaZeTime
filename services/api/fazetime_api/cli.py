"""Operator CLI. The bootstrap invite code is printed to the terminal (stdout) ONLY; it is never logged.

  uv run python -m fazetime_api bootstrap-operator   # first operator invite (single use, 24 h)
  uv run python -m fazetime_api serve                 # uvicorn, ONE process, FAZETIME_HOST/PORT
  uv run python -m fazetime_api reconcile             # ledger reconciliation as JSON
  uv run python -m fazetime_api backup PATH           # online backup via sqlite3 backup API
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from . import auth, domain, ledger, timeutil
from .config import load_settings
from .db import Database
from .ids import format_invite_code


def _db(args) -> Database:
    settings = load_settings()
    db = Database(args.db or settings.db_path)
    db.migrate()
    return db


def cmd_bootstrap(args) -> int:
    settings = load_settings()
    db = _db(args)
    now = timeutil.Clock().now()
    with db.write() as conn:
        operators = conn.execute("SELECT COUNT(*) FROM users WHERE role = 'OPERATOR'").fetchone()[0]
        record, code = auth.create_invite(conn, role="OPERATOR", is_bot=False, bind_user_id=None,
                                          created_by_user_id=None, now=now, settings=settings)
        domain.audit(conn, actor_user_id=None, actor_kind="CLI", action="CLI_BOOTSTRAP_OPERATOR_INVITE", now=now,
                     target_type="INVITE", target_id=record["invite_id"], detail={"role": "OPERATOR"})
    if operators:
        print(f"note: {operators} operator account(s) already exist; this creates another invite.", file=sys.stderr)
    # Terminal only. Do not redirect into files that are committed or shared.
    print("FaZeTime operator invite (single use, expires " + record["expires_at_utc"] + "):")
    print(format_invite_code(code))
    return 0


def cmd_reconcile(args) -> int:
    db = _db(args)
    with db.read() as conn:
        result = ledger.reconcile(conn).as_dict()
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


def cmd_backup(args) -> int:
    db = _db(args)
    db.backup(args.dest)
    print(f"backup written to {args.dest}")
    return 0


def cmd_serve(args) -> int:
    import uvicorn

    settings = load_settings()
    host = args.host or settings.host
    port = args.port or settings.port
    if host in ("0.0.0.0", "::") and not args.allow_all_interfaces:
        print("refusing to bind all interfaces; pass a tailnet/LAN IP or --allow-all-interfaces", file=sys.stderr)
        return 2
    logging.basicConfig(level=settings.log_level)
    uvicorn.run("fazetime_api.main:create_app", factory=True, host=host, port=port, workers=1,
                proxy_headers=False, log_level=settings.log_level.lower())
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fazetime_api")
    parser.add_argument("--db", help="SQLite path (default FAZETIME_DB_PATH or var/fazetime.db)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("bootstrap-operator").set_defaults(fn=cmd_bootstrap)
    sub.add_parser("reconcile").set_defaults(fn=cmd_reconcile)
    backup = sub.add_parser("backup")
    backup.add_argument("dest")
    backup.set_defaults(fn=cmd_backup)
    serve = sub.add_parser("serve")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.add_argument("--allow-all-interfaces", action="store_true")
    serve.set_defaults(fn=cmd_serve)
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
