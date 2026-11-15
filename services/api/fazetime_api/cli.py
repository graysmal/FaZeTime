"""Operator CLI. The bootstrap invite code is printed to the terminal (stdout) ONLY; it is never logged.

  uv run python -m fazetime_api bootstrap-operator   # first operator invite (single use, 24 h)
  uv run python -m fazetime_api serve                 # uvicorn, ONE process, FAZETIME_HOST/PORT
  uv run python -m fazetime_api issue-worker-token    # MEDIA_WORKER fzk_ token, printed once
  uv run python -m fazetime_api issue-call-worker-token --label L   # CALL_WORKER fzk_ token (P11), printed once
  uv run python -m fazetime_api revoke-worker-tokens [--role R]     # every worker token, or one role's
  uv run python -m fazetime_api list-viewers          # bindable viewers: user_id, available, display name
  uv run python -m fazetime_api bind-call-user --user-id usr_...    # bind the bookie line (ends any active job)
  uv run python -m fazetime_api end-call-binding      # unbind the bookie line
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


WORKER_ROLES = ("MEDIA_WORKER", "CALL_WORKER")


def _issue_token(args, role: str, env_var: str, host: str) -> int:
    from .ids import new_worker_token, sha256_hex

    db = _db(args)
    now = timeutil.Clock().now()
    token = new_worker_token()
    with db.write() as conn:
        conn.execute("INSERT INTO worker_credentials (token_hash, role, label, created_at_utc) VALUES (?, ?, ?, ?)",
                     (sha256_hex(token), role, args.label, timeutil.fmt(now)))
        domain.audit(conn, actor_user_id=None, actor_kind="CLI", action="CLI_ISSUE_WORKER_TOKEN", now=now,
                     target_type="WORKER_CREDENTIAL", detail={"label": args.label, "role": role})
    # Terminal only: put it in the worker host's env var; never commit or log it.
    print(f"FaZeTime {role} token (shown once; set as {env_var} on the {host}):")
    print(token)
    return 0


def cmd_issue_worker_token(args) -> int:
    return _issue_token(args, "MEDIA_WORKER", "FAZETIME_WORKER_TOKEN", "worker host")


def cmd_issue_call_worker_token(args) -> int:
    """P11 §9.21: a CALL_WORKER fzk_ token for the Chert call agent (/v1/call/* only)."""
    return _issue_token(args, "CALL_WORKER", "FAZETIME_CALL_WORKER_TOKEN", "call-agent host")


def cmd_revoke_worker_tokens(args) -> int:
    db = _db(args)
    now = timeutil.Clock().now()
    role = getattr(args, "role", None)
    with db.write() as conn:
        if role is None:  # default unchanged: every role
            count = conn.execute("UPDATE worker_credentials SET revoked_at_utc = ? WHERE revoked_at_utc IS NULL",
                                 (timeutil.fmt(now),)).rowcount
        else:
            count = conn.execute("UPDATE worker_credentials SET revoked_at_utc = ? WHERE revoked_at_utc IS NULL"
                                 " AND role = ?", (timeutil.fmt(now), role)).rowcount
        domain.audit(conn, actor_user_id=None, actor_kind="CLI", action="CLI_REVOKE_WORKER_TOKENS", now=now,
                     detail={"revoked": count, "role": role})
    print(f"revoked {count} {role + ' ' if role else ''}worker credential(s)")
    return 0


def _printable(text: str) -> str:
    """Display names are user input: never let them write control sequences to the operator's terminal."""
    return "".join(ch if ch.isprintable() else "?" for ch in text)


def cmd_bind_call_user(args) -> int:
    from . import bookie

    db = _db(args)
    now = timeutil.Clock().now()
    try:
        with db.write() as conn:
            result = bookie.bind_call_user(conn, user_id=args.user_id, now=now)
    except bookie.BindingError as exc:
        print(f"bind-call-user refused: {exc}", file=sys.stderr)
        return 1
    if result["ended_call_job_id"]:
        print(f"ended previous call binding {result['ended_call_job_id']}")
    print(f"call line bound: call_job_id={result['call_job_id']} user_id={result['user_id']} run={result['run_id']}")
    return 0


def cmd_end_call_binding(args) -> int:
    from . import bookie

    db = _db(args)
    now = timeutil.Clock().now()
    with db.write() as conn:
        result = bookie.end_call_binding(conn, now=now)
    if result["ended_call_job_id"] is None:
        print("no active call binding")
    else:
        print(f"ended call binding {result['ended_call_job_id']}"
              f" ({len(result['cancelled_intent_ids'])} pending intent(s) cancelled)")
    return 0


def cmd_list_viewers(args) -> int:
    from . import bookie

    db = _db(args)
    with db.read() as conn:
        result = bookie.list_viewers(conn)
    print(f"active run: {result['run_id'] or '(none)'}; call binding: {result['call_job_id'] or '(none)'}")
    print("user_id\tavailable_minor\tbound\tdisplay_name")
    for v in result["viewers"]:
        available = "-" if v["available_minor"] is None else str(v["available_minor"])
        print(f"{v['user_id']}\t{available}\t{'*' if v['bound'] else ''}\t{_printable(v['display_name'])}")
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
    issue = sub.add_parser("issue-worker-token")
    issue.add_argument("--label", default="media-worker")
    issue.set_defaults(fn=cmd_issue_worker_token)
    issue_call = sub.add_parser("issue-call-worker-token")
    issue_call.add_argument("--label", default="call-agent")
    issue_call.set_defaults(fn=cmd_issue_call_worker_token)
    revoke = sub.add_parser("revoke-worker-tokens")
    revoke.add_argument("--role", choices=WORKER_ROLES, help="revoke only this role (default: every role)")
    revoke.set_defaults(fn=cmd_revoke_worker_tokens)
    bind = sub.add_parser("bind-call-user")
    bind.add_argument("--user-id", required=True)
    bind.set_defaults(fn=cmd_bind_call_user)
    sub.add_parser("end-call-binding").set_defaults(fn=cmd_end_call_binding)
    sub.add_parser("list-viewers").set_defaults(fn=cmd_list_viewers)
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
