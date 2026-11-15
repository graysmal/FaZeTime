"""Operator routes under /v1/operator/* (CONTRACTS §5, §9.7, §9.8).

Every mutation requires an operator session and an operation_id, is idempotent per (operator,
operation_id) with a canonical request hash, and writes an audit row in the same transaction.
No arbitrary SQL, shell, URL fetch or balance-edit console is exposed.
"""

from __future__ import annotations

import json
from typing import Callable

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import auth, db as dbmod, domain, events, ledger, presence, source_health, timeutil, views
from .deps import Services, body_schema, operator_principal, parse_body, svc_of
from .domain import Principal
from .errors import ApiError
from .ids import format_invite_code
from .schemas import (
    ErrorEnvelope,
    OpCreateInvite,
    OpCreateMarket,
    OpCreateStream,
    OpFixtureCredit,
    OpMarketAction,
    OpResetRun,
    OpRevokeSessions,
    OpSettleMarket,
    OpVoidMarket,
)

router = APIRouter(prefix="/v1/operator", tags=["operator"])
ERRORS = {code: {"model": ErrorEnvelope} for code in (401, 403, 404, 409, 422, 429, 500)}


async def _mutation(
    request: Request,
    principal: Principal,
    model: type[BaseModel],
    op_type: str,
    handler: Callable,
    *,
    path: dict | None = None,
    status: int = 201,
    amount_field: str | None = None,
    amount_details: dict | None = None,
    prevalidate: Callable | None = None,
):
    svc: Services = svc_of(request)
    req = await parse_body(request, model, amount_field=amount_field, amount_details=amount_details)
    if prevalidate is not None:
        prevalidate(svc, req)
    payload = {**(path or {}), **req.model_dump(mode="json")}
    req_hash = domain.hash_request(op_type, payload)
    audit_detail = {k: v for k, v in payload.items() if k != "operation_id"}

    def work():
        with svc.db.write() as conn:
            now = svc.clock.now()
            replay = domain.check_replay(conn, principal.user_id, req.operation_id, op_type, req_hash)
            if replay is not None:
                return replay, True, {}
            body, target_type, target_id, first_only = handler(svc, conn, req, now)
            response = {"schema_version": 1, "operation_id": req.operation_id, **body, "replayed": False}
            domain.record_operation(
                conn, actor_user_id=principal.user_id, operation_id=req.operation_id, op_type=op_type,
                req_hash=req_hash, http_status=status, resource_type=target_type, resource_id=target_id,
                response=response, now=now,
            )
            domain.audit(conn, actor_user_id=principal.user_id, actor_kind="OPERATOR", action=op_type, now=now,
                         operation_id=req.operation_id, target_type=target_type, target_id=target_id,
                         detail=audit_detail)
            return response, False, first_only

    response, replayed, first_only = await run_in_threadpool(work)
    if not replayed:
        svc.hub.notify()
    # first_only carries one-time secrets (an invite code); they are never stored or replayed.
    return JSONResponse({**response, **first_only}, status_code=200 if replayed else status,
                        headers={"Cache-Control": "no-store"})


def _stream_info(svc: Services, conn, stream_id: str) -> dict:
    stream = views.get_stream(conn, stream_id)
    run = views.get_active_run(conn, stream_id)
    return views.stream_info(conn, stream, run, svc.clock.now(), svc.settings)


@router.post("/invites", openapi_extra=body_schema(OpCreateInvite), responses=ERRORS)
async def create_invite(request: Request, principal: Principal = Depends(operator_principal)):
    def handler(svc, conn, req: OpCreateInvite, now):
        record, code = auth.create_invite(conn, role=req.role, is_bot=req.is_bot, bind_user_id=req.bind_user_id,
                                          created_by_user_id=principal.user_id, now=now, settings=svc.settings)
        body = {"invite": record, "invite_code": None, "invite_code_note": "shown once; not stored or replayed"}
        return body, "INVITE", record["invite_id"], {"invite_code": format_invite_code(code)}

    return await _mutation(request, principal, OpCreateInvite, "OP_CREATE_INVITE", handler)


@router.post("/streams", openapi_extra=body_schema(OpCreateStream), responses=ERRORS)
async def create_stream(request: Request, principal: Principal = Depends(operator_principal)):
    def handler(svc, conn, req: OpCreateStream, now):
        stream, created = domain.create_stream_if_absent(conn, twitch_channel_login=req.twitch_channel_login,
                                                         now=now, settings=svc.settings)
        body = {"created": created, "stream": _stream_info(svc, conn, stream["stream_id"])}
        return body, "STREAM", stream["stream_id"], {}

    return await _mutation(request, principal, OpCreateStream, "OP_CREATE_STREAM", handler)


@router.post("/runs/reset", openapi_extra=body_schema(OpResetRun), responses=ERRORS)
async def reset_run(request: Request, principal: Principal = Depends(operator_principal)):
    def handler(svc, conn, req: OpResetRun, now):
        result = domain.reset_run(conn, stream_id=req.stream_id, now=now, settings=svc.settings)
        body = {**result, "stream": _stream_info(svc, conn, req.stream_id)}
        return body, "RUN", result["stream_session_id"], {}

    return await _mutation(request, principal, OpResetRun, "OP_RESET_RUN", handler)


@router.post("/credits", openapi_extra=body_schema(OpFixtureCredit), responses=ERRORS)
async def fixture_credit(request: Request, principal: Principal = Depends(operator_principal)):
    svc = svc_of(request)
    details = {"min_minor": 1, "max_minor": svc.settings.fixture_credit_max_minor, "step_minor": 1}

    def prevalidate(svc, req: OpFixtureCredit):
        if not (1 <= req.amount_minor <= svc.settings.fixture_credit_max_minor):
            raise ApiError("INVALID_AMOUNT", "Fixture credit amount out of range.", details=details,
                           operation_id=req.operation_id)

    def handler(svc, conn, req: OpFixtureCredit, now):
        body = domain.fixture_credit(conn, actor_user_id=principal.user_id, operation_id=req.operation_id,
                                     user_id=req.user_id, amount_minor=req.amount_minor, now=now,
                                     settings=svc.settings)
        body["memo"] = req.memo
        body["label"] = "FIXTURE_CREDIT (demo funds, not a payment)"
        return body, "LEDGER_TRANSACTION", body["txn_id"], {}

    return await _mutation(request, principal, OpFixtureCredit, "OP_FIXTURE_CREDIT", handler,
                           amount_field="amount_minor", amount_details=details, prevalidate=prevalidate)


@router.post("/markets", openapi_extra=body_schema(OpCreateMarket), responses=ERRORS)
async def create_market(request: Request, principal: Principal = Depends(operator_principal)):
    def handler(svc, conn, req: OpCreateMarket, now):
        row = domain.create_fixture_market(
            conn, actor_user_id=principal.user_id, question=req.question, yes_label=req.yes_label,
            no_label=req.no_label, close_in_s=req.close_in_s, resolve_in_s=req.resolve_in_s, now=now,
            settings=svc.settings,
        )
        return {"market": views.operator_market(row)}, "MARKET", row["market_id"], {}

    return await _mutation(request, principal, OpCreateMarket, "OP_CREATE_FIXTURE_MARKET", handler)


@router.post("/markets/{market_id}/open", openapi_extra=body_schema(OpMarketAction), responses=ERRORS)
async def open_market(market_id: str, request: Request, principal: Principal = Depends(operator_principal)):
    def handler(svc, conn, req, now):
        row = domain.open_market(conn, market_id=market_id, now=now, settings=svc.settings)
        return {"market": views.operator_market(row)}, "MARKET", market_id, {}

    return await _mutation(request, principal, OpMarketAction, "OP_OPEN_MARKET", handler,
                           path={"market_id": market_id}, status=200)


@router.post("/markets/{market_id}/settle", openapi_extra=body_schema(OpSettleMarket), responses=ERRORS)
async def settle_market(market_id: str, request: Request, principal: Principal = Depends(operator_principal)):
    def handler(svc, conn, req: OpSettleMarket, now):
        row = domain.settle_fixture_market(conn, market_id=market_id, winning_side=req.winning_side, now=now)
        return {"market": views.operator_market(row)}, "MARKET", market_id, {}

    return await _mutation(request, principal, OpSettleMarket, "OP_SETTLE_FIXTURE_MARKET", handler,
                           path={"market_id": market_id}, status=200)


@router.post("/markets/{market_id}/void", openapi_extra=body_schema(OpVoidMarket), responses=ERRORS)
async def void_market(market_id: str, request: Request, principal: Principal = Depends(operator_principal)):
    def handler(svc, conn, req: OpVoidMarket, now):
        row = domain.operator_void(conn, market_id=market_id, now=now)
        return {"market": views.operator_market(row)}, "MARKET", market_id, {}

    return await _mutation(request, principal, OpVoidMarket, "OP_VOID_MARKET", handler,
                           path={"market_id": market_id}, status=200)


@router.post("/sessions/revoke", openapi_extra=body_schema(OpRevokeSessions), responses=ERRORS)
async def revoke_sessions(request: Request, principal: Principal = Depends(operator_principal)):
    def handler(svc, conn, req: OpRevokeSessions, now):
        if conn.execute("SELECT 1 FROM users WHERE user_id = ?", (req.user_id,)).fetchone() is None:
            raise ApiError("NOT_FOUND", "Unknown user.")
        count = auth.revoke_user_sessions(conn, req.user_id, now)
        return {"user_id": req.user_id, "revoked_sessions": count}, "USER", req.user_id, {}

    return await _mutation(request, principal, OpRevokeSessions, "OP_REVOKE_SESSIONS", handler, status=200)


def _wallet_rows(conn, run_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT u.user_id, u.display_name, u.role, u.is_bot, a.balance_minor, a.version"
        " FROM ledger_accounts a JOIN users u ON u.user_id = a.user_id"
        " WHERE a.kind = 'USER_AVAILABLE' AND a.run_id = ? ORDER BY u.user_id",
        (run_id,),
    ).fetchall()
    return [
        {
            "user_id": r["user_id"],
            "display_name": r["display_name"],
            "role": r["role"],
            "is_bot": bool(r["is_bot"]),
            "available_minor": int(r["balance_minor"]),
            "in_play_minor": views.in_play_minor(conn, run_id, r["user_id"]),
            "balance_version": int(r["version"]),
        }
        for r in rows
    ]


@router.get("/health", responses=ERRORS)
def health(request: Request, principal: Principal = Depends(operator_principal)):
    """Sanitized inspection: run, markets (incl. DRAFT), pools, wallets, reconciliation, recent events."""
    svc: Services = svc_of(request)
    now = svc.clock.now()
    with svc.db.read() as conn:
        pragmas = {
            "journal_mode": conn.execute("PRAGMA journal_mode").fetchone()[0],
            "synchronous": conn.execute("PRAGMA synchronous").fetchone()[0],
            "foreign_keys": conn.execute("PRAGMA foreign_keys").fetchone()[0],
            "busy_timeout": conn.execute("PRAGMA busy_timeout").fetchone()[0],
        }
        migrations = [dict(r) for r in conn.execute("SELECT version, name FROM schema_migrations ORDER BY version")]
        stream = views.get_stream(conn)
        run = views.get_active_run(conn, stream["stream_id"]) if stream is not None else None
        body = {
            "schema_version": 1,
            "server_time_utc": timeutil.fmt(now),
            "service": {
                "process_started_at_utc": svc.started_at_utc,
                "sqlite_version": dbmod.sqlite_version(),
                "pragmas": pragmas,
                "migrations": migrations,
                "db_path": svc.db.path,
                "mode_labels": ["TEST MONEY ONLY", "payment_mode UNAVAILABLE", "ai_mode OFF",
                                "fixture markets are OPERATOR_FIXTURE"],
            },
            "sweeper": {
                "enabled": svc.settings.sweeper_enabled,
                "runs": svc.sweeper.runs,
                "errors": svc.sweeper.errors,
                "last_run_at_utc": svc.sweeper.last_run_at_utc,
                "last_result": svc.sweeper.last_result,
            },
            "websocket": {"subscribers": len(svc.hub.subscribers), "dispatch_cursor": svc.hub.cursor,
                          "dispatched": svc.hub.dispatched},
            "event_hwm": views.max_event_id(conn),
            "stream": None,
            "run": None,
            "source_health": None,
            "markets": [],
            "wallets": [],
            "funding_source_minor": None,
            "presence": None,
            "reconciliation": ledger.reconcile(conn).as_dict(),
            "recent_events": [events.frame(r) for r in conn.execute(
                "SELECT * FROM events ORDER BY event_id DESC LIMIT 25").fetchall()],
            "recent_audit": [
                {**dict(r), "detail": json.loads(r["detail_json"])}
                for r in conn.execute(
                    "SELECT audit_id, actor_user_id, actor_kind, action, operation_id, target_type, target_id,"
                    " detail_json, created_at_utc FROM audit_log ORDER BY audit_id DESC LIMIT 20").fetchall()
            ],
            "counts": {
                "users": conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
                "runs": conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0],
                "archived_runs": conn.execute("SELECT COUNT(*) FROM runs WHERE state = 'ARCHIVED'").fetchone()[0],
            },
        }
        for audit_row in body["recent_audit"]:
            audit_row.pop("detail_json", None)
        if stream is not None and run is not None:
            body["stream"] = views.stream_info(conn, stream, run, now, svc.settings)
            body["run"] = dict(run)
            body["source_health"] = source_health.current(conn, stream["stream_id"], now, svc.settings)
            body["markets"] = [views.operator_market(r) for r in conn.execute(
                "SELECT * FROM markets WHERE run_id = ? ORDER BY rowid DESC LIMIT 10", (run["run_id"],)).fetchall()]
            body["wallets"] = _wallet_rows(conn, run["run_id"])
            funding = conn.execute(
                "SELECT balance_minor FROM ledger_accounts WHERE kind = 'FUNDING_SOURCE' AND run_id = ?",
                (run["run_id"],)).fetchone()
            body["funding_source_minor"] = int(funding["balance_minor"]) if funding else 0
        body["presence"] = presence.summary(conn, stream["stream_id"], now, svc.settings) if stream is not None else None
    return JSONResponse(body)


@router.get("/ledger", responses=ERRORS)
def ledger_view(request: Request, run_id: str | None = None, limit: int = 200,
                principal: Principal = Depends(operator_principal)):
    """Append-only ledger transactions with their entries (newest first)."""
    svc: Services = svc_of(request)
    limit = max(1, min(int(limit), 1000))
    with svc.db.read() as conn:
        if run_id is None:
            stream = views.get_stream(conn)
            run = views.get_active_run(conn, stream["stream_id"]) if stream is not None else None
            run_id = run["run_id"] if run is not None else None
        txns = conn.execute(
            "SELECT * FROM ledger_transactions WHERE run_id = ? ORDER BY rowid DESC LIMIT ?", (run_id, limit)
        ).fetchall() if run_id else []
        out = []
        for t in txns:
            entries = conn.execute(
                "SELECT e.amount_minor, a.kind, a.user_id, a.market_id FROM ledger_entries e"
                " JOIN ledger_accounts a ON a.account_id = e.account_id WHERE e.txn_id = ? ORDER BY e.entry_id",
                (t["txn_id"],),
            ).fetchall()
            out.append({**dict(t), "is_simulated": bool(t["is_simulated"]),
                        "entries": [dict(e) for e in entries]})
        return JSONResponse({"schema_version": 1, "stream_session_id": run_id,
                             "reconciliation": ledger.reconcile(conn).as_dict(), "transactions": out})
