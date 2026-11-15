"""P11 inbound-call bookie (CONTRACTS §9.21, D43): CALL_WORKER routes under /v1/call/* and the CLI binding helpers.

The Chert call agent can read the stream, the run's nonterminal market, pool estimates and the bound user's
wallet, and can prepare, confirm or cancel a wager intent. It never names a user. The backend binds the caller to
the one ACTIVE call job, which an operator creates with the CLI on the API host. There is no HTTP route for it, so
D35 open access cannot reach it. Call audio is never identity proof.

A confirm commits through ``domain.place_wager`` as the bound user, using the intent's server ``operation_id``.
The §9.6 check order, §9.7 idempotency, the close recheck and the ledger rules are therefore exactly those of a
viewer wager, and its errors roll the transaction back unchanged. Estimates are pari-mutuel
(``settlement.estimate_gross_return``), never fixed odds. Test money only. Model output never reaches this module:
the agent's code sends validated fields, and the nonce never passes through the model.
"""

from __future__ import annotations

import hmac
import json
import re
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import StrictBool, StrictInt, StringConstraints
from starlette.datastructures import MutableHeaders

from . import domain, ledger, settlement, source_health, timeutil, views
from .deps import Services, body_schema, parse_body, svc_of
from .domain import Principal
from .errors import ApiError
from .ids import id_pattern, new_id, request_hash, sha256_hex
from .schemas import (
    CUuid,
    ErrorEnvelope,
    MarketId,
    Minor,
    MyPosition,
    NonNeg,
    Pool,
    Pos,
    Side,
    SourceHealth,
    StreamInfo,
    Strict,
    Utc,
    WagerReceipt,
    WagerRequest,
    WalletSummary,
)
from .worker import WorkerPrincipal, credential_principal

router = APIRouter(prefix="/v1/call", tags=["call-worker"])
ERRORS = {code: {"model": ErrorEnvelope} for code in (401, 403, 404, 409, 422, 429, 500)}

INTENT_TTL_S = 90  # §9.21 item 2: expires_at_utc = min(now + 90 s, close_at_utc)
TOO_CLOSE_S = 15  # §9.21 item 2: fewer than 15 s before close -> MARKET_CLOSED reason TOO_CLOSE (refuse, never backdate)
INTENT_STATUSES = ("PENDING", "CONFIRMED", "CANCELLED", "EXPIRED")
_INTENT_ID = re.compile(id_pattern("wit"))
_USER_ID = re.compile(id_pattern("usr"))

CallJobId = Annotated[str, StringConstraints(pattern=id_pattern("cjb"))]
IntentId = Annotated[str, StringConstraints(pattern=id_pattern("wit"))]
IntentStatus = Literal["PENDING", "CONFIRMED", "CANCELLED", "EXPIRED"]


# ---- requests -----------------------------------------------------------------------------------
class IntentRequest(Strict):
    client_request_id: CUuid
    market_id: MarketId
    rules_version: Pos
    side: Side
    amount_minor: StrictInt


class ConfirmRequest(Strict):
    nonce: Annotated[str, StringConstraints(min_length=1, max_length=128)]


class CancelRequest(Strict):
    pass


# ---- responses (validated before they leave the transaction) ------------------------------------
class Estimate(Strict):
    side: Side
    stake_minor: Minor
    est_gross_return_minor: Minor


class CallLimits(Strict):
    stake_min_minor: Minor
    stake_max_minor: Minor
    stake_step_minor: Pos
    stake_default_minor: Minor


class CallMarket(Strict):
    market_id: MarketId
    rules_version: Pos
    aggregate_version: Pos
    state: Literal["OPEN", "LOCKED", "EVALUATING"]
    question: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    yes_label: Annotated[str, StringConstraints(min_length=1, max_length=40)]
    no_label: Annotated[str, StringConstraints(min_length=1, max_length=40)]
    close_at_utc: Utc
    seconds_to_close: NonNeg | None
    pool: Pool
    estimates: list[Estimate]


class CallBinding(Strict):
    call_job_id: CallJobId
    wallet: WalletSummary
    position: MyPosition | None


class CallOverview(Strict):
    schema_version: Literal[1]
    server_time_utc: Utc
    stream: StreamInfo | None
    source_health: SourceHealth | None
    limits: CallLimits
    market: CallMarket | None
    binding: CallBinding | None


class IntentResponse(Strict):
    schema_version: Literal[1]
    intent_id: IntentId
    nonce: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")] | None
    status: IntentStatus
    market_id: MarketId
    question: str
    side: Side
    side_label: str
    amount_minor: Minor
    est_gross_return_minor: Minor
    pool: Pool
    close_at_utc: Utc
    expires_at_utc: Utc
    wallet_available_minor: Minor


class ConfirmResponse(Strict):
    schema_version: Literal[1]
    intent_id: IntentId
    status: Literal["CONFIRMED"]
    receipt: WagerReceipt
    replayed: StrictBool


class CancelResponse(Strict):
    schema_version: Literal[1]
    intent_id: IntentId
    status: Literal["CANCELLED", "EXPIRED"]


# ---- auth, headers ------------------------------------------------------------------------------
def call_worker_principal(request: Request) -> WorkerPrincipal:
    """CALL_WORKER fzk_ tokens only: MEDIA_WORKER and valid sessions are 403, anything else 401 (§9.21 Auth)."""
    return credential_principal(request, "CALL_WORKER")


class NoStoreMiddleware:
    """§9.21: every /v1/call/* response, errors included, carries Cache-Control: no-store."""

    def __init__(self, app, prefix: str = "/v1/call/") -> None:
        self.app = app
        self.prefix = prefix

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope.get("path", "").startswith(self.prefix):
            return await self.app(scope, receive, send)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["Cache-Control"] = "no-store"
            await send(message)

        await self.app(scope, receive, send_wrapper)


def _rate_limit(svc: Services, worker: WorkerPrincipal) -> None:
    svc.limiter.check(("call", worker.credential_id), *svc.settings.rl_call)


# ---- shared reads -------------------------------------------------------------------------------
def active_job(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM call_jobs WHERE state = 'ACTIVE'").fetchone()


def effective_status(intent: sqlite3.Row, now: datetime) -> str:
    """A PENDING intent at or after expires_at_utc is EXPIRED, whether or not the row has been marked yet."""
    if intent["status"] == "PENDING" and now >= timeutil.parse(intent["expires_at_utc"]):
        return "EXPIRED"
    return intent["status"]


def _pool(market: sqlite3.Row) -> dict:
    yes, no = int(market["yes_minor"]), int(market["no_minor"])
    return {"yes_minor": yes, "no_minor": no, "total_minor": yes + no,
            "simulated_minor": int(market["simulated_minor"]), "wager_count": int(market["wager_count"])}


def _estimate(market: sqlite3.Row, side: str, stake_minor: int) -> int:
    """§9.6 estimate for one more stake on ``side`` against the current pool. Integers only; an estimate."""
    yes, no = int(market["yes_minor"]), int(market["no_minor"])
    return settlement.estimate_gross_return(stake_minor, yes + no, yes if side == "YES" else no)


def overview_payload(conn: sqlite3.Connection, now: datetime, settings) -> dict:
    """§9.21 item 1, inside ONE read transaction held by the caller. No user ID or display name."""
    stream = views.get_stream(conn)
    run = views.get_active_run(conn, stream["stream_id"]) if stream is not None else None
    lim = settings.limits
    market_row = views.nonterminal_market(conn, run["run_id"]) if run is not None else None
    market = None
    if market_row is not None:
        seconds = None
        if market_row["state"] == "OPEN":
            remaining = timeutil.parse(market_row["close_at_utc"]) - now
            seconds = max(0, remaining // timedelta(seconds=1))
        stakes = (lim.stake_default_minor, 2 * lim.stake_default_minor)
        market = {
            "market_id": market_row["market_id"],
            "rules_version": int(market_row["rules_version"]),
            "aggregate_version": int(market_row["aggregate_version"]),
            "state": market_row["state"],
            "question": market_row["question"],
            "yes_label": market_row["yes_label"],
            "no_label": market_row["no_label"],
            "close_at_utc": market_row["close_at_utc"],
            "seconds_to_close": seconds,
            "pool": _pool(market_row),
            "estimates": [{"side": side, "stake_minor": stake, "est_gross_return_minor": _estimate(market_row, side, stake)}
                          for side in ("YES", "NO") for stake in stakes],
        }
    job = active_job(conn)
    binding = None
    # A binding from an archived run (operator reset) bets nowhere: prepare refuses it with
    # WRONG_RUN, so show no binding rather than the old run's wallet. Rebind to fix.
    if job is not None and run is not None and job["run_id"] == run["run_id"]:
        position = None
        if market_row is not None and market_row["run_id"] == job["run_id"]:
            position = views.my_position(conn, market_row, job["user_id"])
        binding = {"call_job_id": job["call_job_id"],
                   "wallet": views.wallet_summary(conn, job["run_id"], job["user_id"]),
                   "position": position}
    body = {
        "schema_version": 1,
        "server_time_utc": timeutil.fmt(now),
        "stream": views.stream_info(conn, stream, run, now, settings) if run is not None else None,
        "source_health": source_health.current(conn, stream["stream_id"], now, settings) if stream is not None else None,
        "limits": {"stake_min_minor": lim.stake_min_minor, "stake_max_minor": lim.stake_max_minor,
                   "stake_step_minor": lim.stake_step_minor, "stake_default_minor": lim.stake_default_minor},
        "market": market,
        "binding": binding,
    }
    CallOverview.model_validate(body)
    return body


def _audit(conn, action: str, now: datetime, intent_id: str, detail: dict, operation_id: str | None = None) -> None:
    domain.audit(conn, actor_user_id=None, actor_kind="SYSTEM", action=action, now=now, operation_id=operation_id,
                 target_type="WAGER_INTENT", target_id=intent_id, detail=detail)


def _settle_pending(conn: sqlite3.Connection, call_job_id: str, now: datetime) -> list[str]:
    """Mark the job's due PENDING intents EXPIRED and cancel the rest. Returns the cancelled intent IDs."""
    now_s = timeutil.fmt(now)
    conn.execute("UPDATE wager_intents SET status = 'EXPIRED', terminal_at_utc = ?"
                 " WHERE call_job_id = ? AND status = 'PENDING' AND expires_at_utc <= ?", (now_s, call_job_id, now_s))
    cancelled = [r["intent_id"] for r in conn.execute(
        "SELECT intent_id FROM wager_intents WHERE call_job_id = ? AND status = 'PENDING'", (call_job_id,))]
    conn.execute("UPDATE wager_intents SET status = 'CANCELLED', terminal_at_utc = ?"
                 " WHERE call_job_id = ? AND status = 'PENDING'", (now_s, call_job_id))
    return cancelled


def _intent_on_active_job(conn: sqlite3.Connection, intent_id: str) -> sqlite3.Row:
    """§9.21 items 3/4: an unknown intent, or one not on the ACTIVE binding, is 404."""
    if not _INTENT_ID.fullmatch(intent_id):
        raise ApiError("NOT_FOUND", "Unknown intent.")
    intent = conn.execute(
        "SELECT i.* FROM wager_intents i JOIN call_jobs j ON j.call_job_id = i.call_job_id"
        " WHERE i.intent_id = ? AND j.state = 'ACTIVE'", (intent_id,)).fetchone()
    if intent is None:
        raise ApiError("NOT_FOUND", "Unknown intent.")
    return intent


# ---- 2. prepare ---------------------------------------------------------------------------------
def prepare_intent(svc: Services, req: IntentRequest, credential_id: int) -> tuple[dict, bool]:
    """Returns (body, created). One write transaction; no economic effect (§9.21 item 2)."""
    with svc.db.write() as conn:
        now = svc.clock.now()  # read after BEGIN IMMEDIATE acquired the write lock
        job = active_job(conn)
        if job is None:
            raise ApiError("FORBIDDEN", "No viewer account is bound to the call line.",
                           details={"reason": "NO_CALL_BINDING"})
        domain.check_stake_limits(req.amount_minor, svc.settings)
        req_hash = request_hash({"op_type": "CALL_INTENT", "request": req.model_dump(mode="json")})
        existing = conn.execute("SELECT * FROM wager_intents WHERE call_job_id = ? AND client_request_id = ?",
                                (job["call_job_id"], req.client_request_id)).fetchone()
        if existing is not None:
            if existing["request_hash"] != req_hash:
                raise ApiError("IDEMPOTENCY_CONFLICT",
                               "This client_request_id was already used for a different intent; nothing was changed.")
            body = json.loads(existing["quote_json"])
            body["nonce"] = None  # the nonce is shown once, on the first 201
            body["status"] = effective_status(existing, now)
            IntentResponse.model_validate(body)
            return body, False
        # The place_wager pre-checks, same order and codes, plus TOO_CLOSE; nothing is written if any fails.
        _, market, wallet, close_at = domain.wager_prechecks(
            conn, user_id=job["user_id"], stream_session_id=job["run_id"], market_id=req.market_id,
            rules_version=req.rules_version, side=req.side, amount_minor=req.amount_minor, now=now,
            settings=svc.settings, min_remaining_ms=TOO_CLOSE_S * 1000,
        )
        superseded = _settle_pending(conn, job["call_job_id"], now)
        intent_id = new_id("wit")
        nonce = secrets.token_hex(16)  # 128-bit; only its SHA-256 is stored
        operation_id = str(uuid.uuid4())  # becomes the wager's operation_id on confirm
        expires_at = min(now + timedelta(seconds=INTENT_TTL_S), close_at)
        est = _estimate(market, req.side, req.amount_minor)
        body = {
            "schema_version": 1,
            "intent_id": intent_id,
            "nonce": None,
            "status": "PENDING",
            "market_id": market["market_id"],
            "question": market["question"],
            "side": req.side,
            "side_label": market["yes_label"] if req.side == "YES" else market["no_label"],
            "amount_minor": req.amount_minor,
            "est_gross_return_minor": est,
            "pool": _pool(market),
            "close_at_utc": market["close_at_utc"],
            "expires_at_utc": timeutil.fmt(expires_at),
            "wallet_available_minor": int(wallet["balance_minor"]),
        }
        IntentResponse.model_validate(body)
        conn.execute(
            "INSERT INTO wager_intents (intent_id, call_job_id, client_request_id, request_hash, user_id, run_id,"
            " market_id, rules_version, side, amount_minor, operation_id, nonce_hash, quoted_aggregate_version,"
            " est_gross_return_minor, quote_json, status, created_at_utc, expires_at_utc)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?)",
            (intent_id, job["call_job_id"], req.client_request_id, req_hash, job["user_id"], job["run_id"],
             market["market_id"], int(market["rules_version"]), req.side, req.amount_minor, operation_id,
             sha256_hex(nonce), int(market["aggregate_version"]), est, json.dumps(body, separators=(",", ":")),
             timeutil.fmt(now), body["expires_at_utc"]),
        )
        _audit(conn, "CALL_INTENT_PREPARED", now, intent_id,
               {"credential_id": credential_id, "call_job_id": job["call_job_id"], "intent_id": intent_id,
                "market_id": market["market_id"], "side": req.side, "amount_minor": req.amount_minor,
                "superseded_intent_ids": superseded})
    return {**body, "nonce": nonce}, True


# ---- 3. confirm ---------------------------------------------------------------------------------
def _stored_receipt(conn: sqlite3.Connection, intent: sqlite3.Row) -> dict:
    """The receipt exactly as first returned (the operations row of the bound user's WAGER), replayed=true."""
    row = conn.execute("SELECT response_json FROM operations WHERE actor_user_id = ? AND operation_id = ?"
                       " AND op_type = 'WAGER'", (intent["user_id"], intent["operation_id"])).fetchone()
    if row is not None:
        receipt = json.loads(row["response_json"])
    else:  # unreachable: confirm records the operation in the same transaction; keep the replay safe anyway
        receipt = views.wager_receipt(conn.execute("SELECT * FROM wagers WHERE wager_id = ?",
                                                   (intent["wager_id"],)).fetchone())
    receipt["replayed"] = True
    return receipt


def confirm_intent(svc: Services, intent_id: str, req: ConfirmRequest, credential_id: int) -> tuple[dict, bool]:
    """Returns (body, replayed). ONE write transaction. place_wager errors are never caught here: they roll the
    whole transaction back (the intent stays PENDING) and reach the caller unchanged (§9.21 item 3)."""
    with svc.db.write() as conn:
        now = svc.clock.now()
        intent = _intent_on_active_job(conn, intent_id)
        if not hmac.compare_digest(sha256_hex(req.nonce), intent["nonce_hash"]):
            raise ApiError("FORBIDDEN", "That confirmation does not match this intent.",
                           details={"reason": "NONCE_MISMATCH"})
        if intent["status"] == "CONFIRMED":
            body = {"schema_version": 1, "intent_id": intent_id, "status": "CONFIRMED",
                    "receipt": _stored_receipt(conn, intent), "replayed": True}
            ConfirmResponse.model_validate(body)
            return body, True
        status = effective_status(intent, now)
        if status != "PENDING":
            raise ApiError("STALE_MARKET", "This intent is no longer active; prepare a fresh one.",
                           details={"reason": "INTENT_INACTIVE", "status": status})
        market = views.get_market(conn, intent["market_id"])
        quoted, current = int(intent["est_gross_return_minor"]), _estimate(market, intent["side"], int(intent["amount_minor"]))
        if current < quoted:
            raise ApiError("STALE_MARKET", "The pool moved and the estimated return fell; re-quote and confirm again.",
                           details={"reason": "QUOTE_MOVED", "quoted_est_gross_return_minor": quoted,
                                    "current_est_gross_return_minor": current})
        user = conn.execute("SELECT user_id, role, is_bot FROM users WHERE user_id = ?", (intent["user_id"],)).fetchone()
        principal = Principal(user["user_id"], user["role"], bool(user["is_bot"]), intent["call_job_id"],
                              intent["expires_at_utc"])
        wager_req = WagerRequest(operation_id=intent["operation_id"], stream_session_id=intent["run_id"],
                                 market_id=intent["market_id"], rules_version=int(intent["rules_version"]),
                                 side=intent["side"], amount_minor=int(intent["amount_minor"]))
        receipt, replayed = domain.place_wager(conn, principal=principal, req=wager_req, clock=svc.clock,
                                               settings=svc.settings)
        cur = conn.execute(
            "UPDATE wager_intents SET status = 'CONFIRMED', wager_id = ?, terminal_at_utc = ?"
            " WHERE intent_id = ? AND status = 'PENDING'",
            (receipt["wager_id"], timeutil.fmt(svc.clock.now()), intent_id),
        )
        if cur.rowcount != 1:
            raise domain.ConcurrentChange(f"intent {intent_id} was not PENDING at confirm")
        _audit(conn, "CALL_INTENT_CONFIRMED", now, intent_id,
               {"credential_id": credential_id, "call_job_id": intent["call_job_id"], "intent_id": intent_id,
                "wager_id": receipt["wager_id"]}, operation_id=intent["operation_id"])
        body = {"schema_version": 1, "intent_id": intent_id, "status": "CONFIRMED", "receipt": receipt,
                "replayed": replayed}
        ConfirmResponse.model_validate(body)
        # Last statement before COMMIT, as in place_wager: the commit time must still be < close_at_utc (§9.3).
        if not replayed and svc.clock.now() >= timeutil.parse(market["close_at_utc"]):
            raise ApiError("MARKET_CLOSED", "Betting closed at close_at_utc.",
                           details={"state": market["state"], "close_at_utc": market["close_at_utc"],
                                    "reason": "DEADLINE"})
    return body, replayed


# ---- 4. cancel ----------------------------------------------------------------------------------
def cancel_intent(svc: Services, intent_id: str, credential_id: int) -> dict:
    with svc.db.write() as conn:
        now = svc.clock.now()
        intent = _intent_on_active_job(conn, intent_id)
        if intent["status"] == "CONFIRMED":
            raise ApiError("STALE_MARKET", "This intent was already confirmed; a placed bet cannot be cancelled.",
                           details={"reason": "ALREADY_CONFIRMED"})
        status = effective_status(intent, now)
        if intent["status"] == "PENDING":
            status = "EXPIRED" if status == "EXPIRED" else "CANCELLED"
            cur = conn.execute("UPDATE wager_intents SET status = ?, terminal_at_utc = ?"
                               " WHERE intent_id = ? AND status = 'PENDING'", (status, timeutil.fmt(now), intent_id))
            if cur.rowcount != 1:
                raise domain.ConcurrentChange(f"intent {intent_id} was not PENDING at cancel")
            _audit(conn, "CALL_INTENT_CANCELLED" if status == "CANCELLED" else "CALL_INTENT_EXPIRED", now, intent_id,
                   {"credential_id": credential_id, "call_job_id": intent["call_job_id"], "intent_id": intent_id})
        body = {"schema_version": 1, "intent_id": intent_id, "status": status}
        CancelResponse.model_validate(body)
    return body


# ---- routes (§9.6 order before the transaction: authentication, rate limit, validation) ---------
@router.get("/overview", responses={200: {"model": CallOverview}, **ERRORS})
def call_overview(request: Request, worker: WorkerPrincipal = Depends(call_worker_principal)):
    svc: Services = svc_of(request)
    _rate_limit(svc, worker)
    with svc.db.read() as conn:  # one read transaction
        body = overview_payload(conn, svc.clock.now(), svc.settings)
    return JSONResponse(body)


@router.post("/intents", status_code=201, openapi_extra=body_schema(IntentRequest),
             responses={201: {"model": IntentResponse}, 200: {"model": IntentResponse}, **ERRORS})
async def call_prepare(request: Request, worker: WorkerPrincipal = Depends(call_worker_principal)):
    svc: Services = svc_of(request)
    _rate_limit(svc, worker)
    req = await parse_body(request, IntentRequest, amount_field="amount_minor",
                           amount_details=domain.stake_limit_details(svc.settings))
    body, created = await run_in_threadpool(prepare_intent, svc, req, worker.credential_id)
    return JSONResponse(body, status_code=201 if created else 200)


@router.post("/intents/{intent_id}/confirm", status_code=201, openapi_extra=body_schema(ConfirmRequest),
             responses={201: {"model": ConfirmResponse}, 200: {"model": ConfirmResponse}, **ERRORS})
async def call_confirm(intent_id: str, request: Request, worker: WorkerPrincipal = Depends(call_worker_principal)):
    svc: Services = svc_of(request)
    _rate_limit(svc, worker)
    req = await parse_body(request, ConfirmRequest)
    body, replayed = await run_in_threadpool(confirm_intent, svc, intent_id, req, worker.credential_id)
    if not replayed:
        svc.hub.notify()  # after COMMIT: the normal pool, wager and wallet events reach the bound viewer
    return JSONResponse(body, status_code=200 if replayed else 201)


@router.post("/intents/{intent_id}/cancel", openapi_extra=body_schema(CancelRequest),
             responses={200: {"model": CancelResponse}, **ERRORS})
async def call_cancel(intent_id: str, request: Request, worker: WorkerPrincipal = Depends(call_worker_principal)):
    svc: Services = svc_of(request)
    _rate_limit(svc, worker)
    await parse_body(request, CancelRequest)
    body = await run_in_threadpool(cancel_intent, svc, intent_id, worker.credential_id)
    return JSONResponse(body)


# ---- CLI helpers (API host only; each CLI command writes its own audit row) ----------------------
class BindingError(ValueError):
    """A bind-call-user precondition failed. The message is safe to print on the operator's terminal."""


def _end_active(conn: sqlite3.Connection, now: datetime) -> tuple[str | None, list[str]]:
    job = active_job(conn)
    if job is None:
        return None, []
    cancelled = _settle_pending(conn, job["call_job_id"], now)
    cur = conn.execute("UPDATE call_jobs SET state = 'ENDED', ended_at_utc = ? WHERE call_job_id = ? AND state = 'ACTIVE'",
                       (timeutil.fmt(now), job["call_job_id"]))
    if cur.rowcount != 1:
        raise domain.ConcurrentChange("call job was not ACTIVE")
    return job["call_job_id"], cancelled


def bind_call_user(conn: sqlite3.Connection, *, user_id: str, now: datetime) -> dict:
    """End any ACTIVE job, then bind the line to ``user_id`` for the active run. Caller holds BEGIN IMMEDIATE."""
    if not isinstance(user_id, str) or not _USER_ID.fullmatch(user_id):
        raise BindingError("user_id must look like usr_<32 lowercase hex>")
    stream = views.get_stream(conn)
    run = views.get_active_run(conn, stream["stream_id"]) if stream is not None else None
    if run is None:
        raise BindingError("no active run; an operator must create the stream first")
    user = conn.execute("SELECT user_id, role, is_bot FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if user is None or user["role"] != "VIEWER" or user["is_bot"]:
        raise BindingError("the user must be an existing non-bot VIEWER (D30)")
    if ledger.wallet_account(conn, run["run_id"], user_id) is None:
        raise BindingError("the user has no wallet in the active run")
    ended, cancelled = _end_active(conn, now)
    call_job_id = new_id("cjb")
    conn.execute("INSERT INTO call_jobs (call_job_id, user_id, run_id, kind, state, created_by, created_at_utc)"
                 " VALUES (?, ?, ?, 'BOUND_LINE', 'ACTIVE', 'CLI', ?)",
                 (call_job_id, user_id, run["run_id"], timeutil.fmt(now)))
    domain.audit(conn, actor_user_id=None, actor_kind="CLI", action="CLI_BIND_CALL_USER", now=now,
                 target_type="CALL_JOB", target_id=call_job_id,
                 detail={"user_id": user_id, "run_id": run["run_id"], "ended_call_job_id": ended,
                         "cancelled_intent_ids": cancelled})
    return {"call_job_id": call_job_id, "user_id": user_id, "run_id": run["run_id"], "ended_call_job_id": ended}


def end_call_binding(conn: sqlite3.Connection, *, now: datetime) -> dict:
    ended, cancelled = _end_active(conn, now)
    domain.audit(conn, actor_user_id=None, actor_kind="CLI", action="CLI_END_CALL_BINDING", now=now,
                 target_type="CALL_JOB", target_id=ended, detail={"cancelled_intent_ids": cancelled})
    return {"ended_call_job_id": ended, "cancelled_intent_ids": cancelled}


def list_viewers(conn: sqlite3.Connection) -> dict:
    """Non-bot VIEWERs (the only bindable users) with their available balance in the active run."""
    stream = views.get_stream(conn)
    run = views.get_active_run(conn, stream["stream_id"]) if stream is not None else None
    job = active_job(conn)
    rows = conn.execute("SELECT user_id, display_name FROM users WHERE role = 'VIEWER' AND is_bot = 0"
                        " ORDER BY created_at_utc, user_id").fetchall()
    viewers = []
    for row in rows:
        wallet = ledger.wallet_account(conn, run["run_id"], row["user_id"]) if run is not None else None
        viewers.append({
            "user_id": row["user_id"],
            "display_name": row["display_name"],
            "available_minor": int(wallet["balance_minor"]) if wallet is not None else None,
            "bound": job is not None and job["user_id"] == row["user_id"],
        })
    return {"run_id": run["run_id"] if run is not None else None,
            "call_job_id": job["call_job_id"] if job is not None else None, "viewers": viewers}
