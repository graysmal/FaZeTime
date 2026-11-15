"""Viewer HTTP surface (CONTRACTS §4, §9.6-§9.9, §9.13)."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from . import auth, domain, presence, timeutil, views
from .deps import body_schema, client_key, parse_body, session_principal, svc_of, viewer_principal
from .domain import Principal
from .errors import ApiError
from .schemas import (
    EnrollRequest,
    EnrollResponse,
    ErrorEnvelope,
    Me,
    PresenceAck,
    PresenceHeartbeat,
    StreamSnapshot,
    WagerReceipt,
    WagerRequest,
    WsTicketRequest,
    WsTicketResponse,
)

router = APIRouter()
ERRORS = {code: {"model": ErrorEnvelope} for code in (401, 403, 404, 409, 422, 429, 500, 503)}


@router.get("/healthz", tags=["meta"])
def healthz(request: Request) -> dict:
    """Unauthenticated liveness only; operator health is /v1/operator/health."""
    return {"ok": True, "schema_version": 1, "server_time_utc": timeutil.fmt(svc_of(request).clock.now())}


@router.post("/v1/enroll", status_code=201, tags=["viewer"], openapi_extra=body_schema(EnrollRequest),
             responses={201: {"model": EnrollResponse}, **ERRORS})
async def enroll(request: Request):
    svc = svc_of(request)
    svc.limiter.check(("enroll", client_key(request)), *svc.settings.rl_enroll)
    req = await parse_body(request, EnrollRequest)

    def work():
        with svc.db.write() as conn:
            body = auth.enroll(conn, req=req, now=svc.clock.now(), settings=svc.settings)
            EnrollResponse.model_validate(body)
            return body

    body = await run_in_threadpool(work)
    svc.hub.notify()
    return JSONResponse(body, status_code=201, headers={"Cache-Control": "no-store"})


@router.get("/v1/me", response_model=Me, tags=["viewer"], responses=ERRORS)
def me(request: Request, principal: Principal = Depends(viewer_principal)):
    svc = svc_of(request)
    with svc.db.read() as conn:
        return views.me(conn, principal, svc.clock.now())


@router.get("/v1/streams/{stream_id}/snapshot", response_model=StreamSnapshot, tags=["viewer"], responses=ERRORS)
def snapshot(stream_id: str, request: Request, principal: Principal = Depends(viewer_principal)):
    svc = svc_of(request)
    with svc.db.read() as conn:  # one read transaction: event_hwm matches the state it describes
        stream = views.get_stream(conn, stream_id)
        if stream is None or views.get_active_run(conn, stream_id) is None:
            raise ApiError("NOT_FOUND", "Unknown stream.")
        return views.snapshot(conn, stream, principal.user_id, svc.clock.now(), svc.settings)


@router.post("/v1/wagers", status_code=201, tags=["viewer"], openapi_extra=body_schema(WagerRequest),
             responses={201: {"model": WagerReceipt}, 200: {"model": WagerReceipt}, **ERRORS})
async def place_wager(request: Request, principal: Principal = Depends(viewer_principal)):
    svc = svc_of(request)
    lim = svc.settings.limits
    amount_details = {"min_minor": lim.stake_min_minor, "max_minor": lim.stake_max_minor,
                      "step_minor": lim.stake_step_minor}
    # §9.6 order before the transaction: authentication (dependency), rate limit, validation.
    svc.limiter.check(("wager", principal.user_id), *svc.settings.rl_wager)
    req = await parse_body(request, WagerRequest, amount_field="amount_minor", amount_details=amount_details)
    amount = req.amount_minor
    if amount < lim.stake_min_minor or amount > lim.stake_max_minor or amount % lim.stake_step_minor != 0:
        raise ApiError("INVALID_AMOUNT", "Stake is outside the allowed range or step.", details=amount_details,
                       operation_id=req.operation_id)

    def work():
        with svc.db.write() as conn:
            return domain.place_wager(conn, principal=principal, req=req, clock=svc.clock, settings=svc.settings)

    receipt, replayed = await run_in_threadpool(work)
    if not replayed:
        svc.hub.notify()
    return JSONResponse(receipt, status_code=200 if replayed else 201)


@router.get("/v1/operations/{operation_id}", tags=["viewer"], responses={200: {"model": WagerReceipt}, **ERRORS})
def get_operation(operation_id: str, request: Request, principal: Principal = Depends(session_principal)):
    """The caller's own committed receipt; another actor's key is NOT_FOUND (§9.7)."""
    svc = svc_of(request)
    with svc.db.read() as conn:
        row = conn.execute(
            "SELECT response_json FROM operations WHERE actor_user_id = ? AND operation_id = ?",
            (principal.user_id, operation_id),
        ).fetchone()
    if row is None:
        raise ApiError("NOT_FOUND", "No committed operation with that id for this session's user.")
    body = json.loads(row["response_json"])
    body["replayed"] = True
    return JSONResponse(body)


@router.post("/v1/ws-ticket", tags=["viewer"], openapi_extra=body_schema(WsTicketRequest),
             responses={200: {"model": WsTicketResponse}, **ERRORS})
async def ws_ticket(request: Request, principal: Principal = Depends(viewer_principal)):
    svc = svc_of(request)
    svc.limiter.check(("ws-ticket", principal.user_id), *svc.settings.rl_ws_ticket)
    req = await parse_body(request, WsTicketRequest)

    def work():
        with svc.db.write() as conn:
            return auth.issue_ws_ticket(conn, principal=principal, stream_id=req.stream_id,
                                        now=svc.clock.now(), settings=svc.settings)

    body = await run_in_threadpool(work)
    return JSONResponse(body, headers={"Cache-Control": "no-store"})


@router.post("/v1/presence", tags=["viewer"], openapi_extra=body_schema(PresenceHeartbeat),
             responses={200: {"model": PresenceAck}, **ERRORS})
async def presence_heartbeat(request: Request, principal: Principal = Depends(viewer_principal)):
    """Per-device/tab heartbeat; the server stamps last_seen. Keyed by session user + device_id (§9.13 I)."""
    svc = svc_of(request)
    svc.limiter.check(("presence", principal.user_id), *svc.settings.rl_presence)
    req = await parse_body(request, PresenceHeartbeat)

    def work():
        with svc.db.write() as conn:
            return presence.heartbeat(conn, principal=principal, req=req, now=svc.clock.now(), settings=svc.settings)

    return JSONResponse(await run_in_threadpool(work))


def _unavailable(feature: str) -> ApiError:
    return ApiError("CAPABILITY_UNAVAILABLE", f"{feature} is not available in this build (payment_mode UNAVAILABLE).")


@router.post("/v1/topups", tags=["viewer"], responses=ERRORS)
def create_topup(principal: Principal = Depends(viewer_principal)):
    raise _unavailable("Stripe test top-up (P6)")


@router.get("/v1/topups/{topup_id}", tags=["viewer"], responses=ERRORS)
def get_topup(topup_id: str, principal: Principal = Depends(viewer_principal)):
    raise _unavailable("Stripe test top-up (P6)")


@router.post("/v1/redemptions", tags=["viewer"], responses=ERRORS)
def create_redemption(principal: Principal = Depends(viewer_principal)):
    raise _unavailable("Demo redemption (P6)")


@router.get("/v1/raffle", tags=["viewer"], responses=ERRORS)
def get_raffle(principal: Principal = Depends(viewer_principal)):
    raise _unavailable("Raffle (P8)")
