"""Stripe TEST-mode top-ups (P6-C/D, CONTRACTS §9.18): routes plus the apply-in-transaction code.

* ``POST /v1/topups``
  1. txn 1 (BEGIN IMMEDIATE): store the intent as CREATED, with its operations row.
  2. Network, no transaction held: create the Checkout Session, reusing the same Stripe idempotency key on
     every retry.
  3. txn 2: bind the session and move to PENDING. This is a conditional update on CREATED.
* ``POST /v1/webhooks/stripe``: raw bytes, then verify the signature (300 s tolerance), then parse. Then ONE
  BEGIN IMMEDIATE: check the receipt, look up the top-up, ``plan_fulfillment``, insert the receipt, apply.
* ``GET /v1/topups/{id}``: the caller's own row. While it is CREATED or PENDING (throttled to once per 3 s),
  retrieve the session over the network with no transaction held. Then ONE BEGIN IMMEDIATE:
  ``plan_reconciliation`` and the same apply code. A return URL or browser claim never credits.

Money moves only in ``_apply``, inside the caller's BEGIN IMMEDIATE:
* one ``ledger.post`` with reason STRIPE_TEST_TOPUP and ``source_key = stripe_topup:<topup_id>``, into the
  top-up's OWN run, even if that run is ARCHIVED;
* the conditional status UPDATE;
* ``wallet.changed``.
A reset never touches top-ups.

Never logged: the Checkout URL, the key, the signing secret, request headers or bodies.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from . import domain, events, ledger, timeutil
from .config import Settings
from .deps import body_schema, parse_body, read_capped, session_principal, svc_of
from .domain import Principal
from .errors import ApiError
from .ids import new_id
from .integrations import stripe_client as sc
from .integrations import stripe_fulfillment as sf
from .integrations import stripe_webhook as sw
from .schemas import ErrorEnvelope, TopupReceipt, TopupRequest

log = logging.getLogger("fazetime.topups")

router = APIRouter()
ERRORS = {code: {"model": ErrorEnvelope} for code in (401, 403, 404, 409, 422, 429, 500, 503)}
OP_TYPE = "TOPUP_CREATE"
TOPUP_ID_RE = re.compile(r"^top_[0-9a-f]{32}$")
OPEN = ("CREATED", "PENDING")
_ROW_SQL = (
    "SELECT t.*, r.state AS run_state, s.twitch_channel_login AS channel FROM topups t"
    " JOIN runs r ON r.run_id = t.run_id JOIN streams s ON s.stream_id = r.stream_id"
)


# ------------------------------------------------------------------------------------------------
# Payments capability (payment_mode)
# ------------------------------------------------------------------------------------------------
@dataclass
class Payments:
    client: sc.StripeTestClient | None
    webhook_secret: str | None = field(default=None, repr=False)
    last_reconcile: dict = field(default_factory=dict, repr=False)  # topup_id -> server time of last retrieve
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def mode(self) -> str:
        return "STRIPE_TEST" if self.client is not None and self.webhook_secret else "UNAVAILABLE"


def build_payments(settings: Settings) -> Payments:
    """STRIPE_TEST only when BOTH a test-mode secret key and a whsec_ signing secret load (§9.18)."""
    if not settings.payments_enabled:
        return Payments(None)
    try:
        key = sc.load_test_secret_key(env_file=settings.stripe_env_file)
        secret = sw.require_webhook_secret(
            sc.read_secret(sw.WEBHOOK_SECRET_ENV_NAME, env_file=settings.stripe_env_file))
    except (sc.StripeError, sw.WebhookError) as exc:
        log.warning("payment_mode UNAVAILABLE: %s", getattr(exc, "code", type(exc).__name__))  # never the values
        return Payments(None)
    client = sc.StripeTestClient(key, timeout_s=settings.stripe_timeout_s, max_network_retries=1,
                                 limits=settings.limits)
    log.info("payment_mode STRIPE_TEST (%s key, Stripe-Version %s)", client.key_kind, client.api_version)
    return Payments(client, secret)


def install(app: FastAPI) -> None:
    """Called once from main.create_app: loads the capability and mounts the routes."""
    app.state.svc.payments = build_payments(app.state.svc.settings)
    app.include_router(router)


def configure(app: FastAPI, payments: Payments) -> None:
    """Tests and tools: swap the adapter (for example a client with a fake transport)."""
    app.state.svc.payments = payments


def payment_mode(svc) -> str:
    """'STRIPE_TEST' or 'UNAVAILABLE', for snapshot modes and operator health."""
    payments = getattr(svc, "payments", None)
    return payments.mode if isinstance(payments, Payments) else "UNAVAILABLE"


def _payments(svc) -> Payments:
    payments = getattr(svc, "payments", None)
    if not isinstance(payments, Payments) or payments.mode != "STRIPE_TEST":
        raise ApiError("CAPABILITY_UNAVAILABLE", "Stripe test top-ups are not configured (payment_mode UNAVAILABLE).")
    return payments


def topup_principal(principal: Principal = Depends(session_principal)) -> Principal:
    """D30: only human VIEWER accounts top up. Operators and bots are FORBIDDEN."""
    if principal.role != "VIEWER" or principal.is_bot:
        raise ApiError("FORBIDDEN", "Only human viewer accounts can top up (operators and bots cannot).")
    return principal


# ------------------------------------------------------------------------------------------------
# Views and helpers
# ------------------------------------------------------------------------------------------------
def return_urls(settings: Settings, channel: str, topup_id: str) -> tuple[str, str]:
    """Server-configured return URLs. The query parameter is only a polling hint; it never credits."""
    def fill(template: str) -> str:
        return template.replace("{channel}", channel).replace("{topup_id}", topup_id)

    return fill(settings.topup_success_url), fill(settings.topup_cancel_url)


def receipt(row, *, payment_mode: str, replayed: bool) -> dict:
    status = row["status"]
    body = {
        "schema_version": 1,
        "topup_id": row["topup_id"],
        "operation_id": row["operation_id"],
        "stream_session_id": row["run_id"],
        "amount_minor": int(row["amount_minor"]),
        "currency": row["currency"],
        "status": status,
        "payment_mode": payment_mode,
        "checkout_url": row["checkout_url"] if status == "PENDING" else None,
        "checkout_expires_at_utc": row["checkout_expires_at_utc"],
        "replayed": replayed,
    }
    TopupReceipt.model_validate(body)
    return body


def _row(conn: sqlite3.Connection, where: str, params: tuple) -> sqlite3.Row | None:
    return conn.execute(f"{_ROW_SQL} WHERE {where}", params).fetchone()


def _record(row: sqlite3.Row | None) -> sf.TopupRecord | None:
    if row is None:
        return None
    return sf.TopupRecord(
        topup_id=row["topup_id"], user_id=row["user_id"], run_id=row["run_id"],
        amount_minor=int(row["amount_minor"]), currency=row["currency"], status=row["status"],
        stripe_session_id=row["stripe_session_id"], stripe_payment_intent_id=row["stripe_payment_intent_id"],
        run_state=row["run_state"],
    )


def _wallet_available(conn: sqlite3.Connection, row: sqlite3.Row | None) -> int | None:
    if row is None:
        return None
    acct = ledger.wallet_account(conn, row["run_id"], row["user_id"])
    return int(acct["balance_minor"]) if acct is not None else None


def _utc_from_unix(value: int | None) -> str | None:
    return timeutil.fmt(datetime.fromtimestamp(value, tz=timezone.utc)) if value else None


# ------------------------------------------------------------------------------------------------
# Applying a plan (caller holds BEGIN IMMEDIATE)
# ------------------------------------------------------------------------------------------------
def _transition(conn: sqlite3.Connection, plan: sf.FulfillmentPlan, now_s: str, credited_txn_id: str | None = None):
    marks = ",".join("?" * len(plan.from_statuses))
    cur = conn.execute(
        "UPDATE topups SET status = ?, credited_txn_id = COALESCE(?, credited_txn_id),"
        " stripe_session_id = COALESCE(stripe_session_id, ?),"
        " stripe_payment_intent_id = COALESCE(stripe_payment_intent_id, ?),"
        f" checkout_url = NULL, updated_at_utc = ?, terminal_at_utc = ? WHERE topup_id = ? AND status IN ({marks})",
        (plan.to_status, credited_txn_id, plan.bind_session_id, plan.bind_payment_intent_id, now_s, now_s,
         plan.topup_id, *plan.from_statuses),
    )
    if cur.rowcount != 1:
        raise domain.ConcurrentChange(f"top-up {plan.topup_id} was not in {plan.from_statuses}")


def apply_plan(conn: sqlite3.Connection, plan: sf.FulfillmentPlan, now: datetime) -> str | None:
    """Apply one planner decision. Returns the ledger txn_id for CREDIT, else None."""
    now_s = timeutil.fmt(now)
    if plan.action is sf.Action.CREDIT:
        wallet_id = ledger.ensure_account(conn, kind="USER_AVAILABLE", run_id=plan.run_id, user_id=plan.user_id,
                                          now=now_s)
        funding_id = ledger.ensure_account(conn, kind="FUNDING_SOURCE", run_id=plan.run_id, now=now_s)
        txn_id = ledger.post(
            conn, run_id=plan.run_id, reason=plan.ledger_reason, source_key=plan.ledger_source_key,
            entries=[(funding_id, -plan.amount_minor), (wallet_id, plan.amount_minor)], now=now_s,
            actor_user_id=plan.user_id,
        )
        _transition(conn, plan, now_s, credited_txn_id=txn_id)
        events.emit_wallet(conn, plan.run_id, plan.user_id, now)
        return txn_id
    if plan.action in (sf.Action.MARK_FAILED, sf.Action.MARK_EXPIRED):
        _transition(conn, plan, now_s)
    elif plan.action is sf.Action.MISMATCH_REVIEW and plan.flag_review and plan.topup_id is not None:
        conn.execute("UPDATE topups SET review_reason = COALESCE(review_reason, ?), updated_at_utc = ?"
                     " WHERE topup_id = ?", (plan.reason, now_s, plan.topup_id))
        log.warning("top-up %s flagged for review: %s", plan.topup_id, plan.reason)
    return None


def apply_webhook_event(svc, event: sw.StripeEvent) -> sf.FulfillmentPlan:
    """One BEGIN IMMEDIATE for a VERIFIED event: receipt check, lookup, plan, receipt row, apply."""
    now = svc.clock.now()
    with svc.db.write() as conn:
        seen = conn.execute("SELECT 1 FROM provider_receipts WHERE provider = 'stripe' AND event_id = ?",
                            (event.event_id,)).fetchone() is not None
        row = None
        s = event.session
        if s is not None:
            if s.topup_id and TOPUP_ID_RE.fullmatch(s.topup_id):
                row = _row(conn, "t.topup_id = ?", (s.topup_id,))
            if row is None:
                row = _row(conn, "t.stripe_session_id = ?", (s.session_id,))
        plan = sf.plan_fulfillment(_record(row), event, event_already_processed=seen,
                                   wallet_available_minor=_wallet_available(conn, row),
                                   available_max_minor=svc.settings.limits.available_max_minor)
        if plan.record_receipt:
            conn.execute(
                "INSERT INTO provider_receipts (provider, event_id, event_type, livemode, object_id, topup_id, outcome,"
                " reason, payload_sha256, stripe_created, received_at_utc) VALUES ('stripe', ?, ?, 0, ?, ?, ?, ?, ?, ?, ?)",
                (event.event_id, event.type, plan.session_id, plan.topup_id, plan.action.value, plan.reason,
                 event.payload_sha256, event.created, timeutil.fmt(now)),
            )
        apply_plan(conn, plan, now)
    return plan


def reconcile_retrieved(svc, topup_id: str, user_id: str, facts) -> tuple[dict, sf.FulfillmentPlan]:
    """One BEGIN IMMEDIATE for a session the SERVER retrieved: plan_reconciliation plus the same apply code."""
    now = svc.clock.now()
    with svc.db.write() as conn:
        row = _row(conn, "t.topup_id = ?", (topup_id,))
        plan = sf.plan_reconciliation(_record(row), facts, requester_user_id=user_id,
                                      wallet_available_minor=_wallet_available(conn, row),
                                      available_max_minor=svc.settings.limits.available_max_minor)
        apply_plan(conn, plan, now)
        return dict(_row(conn, "t.topup_id = ?", (topup_id,))), plan


# ------------------------------------------------------------------------------------------------
# Creation (txn 1, network, txn 2)
# ------------------------------------------------------------------------------------------------
def _record_intent(svc, principal: Principal, req: TopupRequest, req_hash: str, api_version: str):
    now = svc.clock.now()
    now_s = timeutil.fmt(now)
    with svc.db.write() as conn:
        row = _row(conn, "t.user_id = ? AND t.operation_id = ?", (principal.user_id, req.operation_id))
        if row is not None:
            if row["request_hash"] != req_hash:
                raise ApiError("IDEMPOTENCY_CONFLICT", "This operation_id was already used for a different top-up;"
                               " nothing was changed.", operation_id=req.operation_id)
            return dict(row), True
        if conn.execute("SELECT 1 FROM operations WHERE actor_user_id = ? AND operation_id = ?",
                        (principal.user_id, req.operation_id)).fetchone() is not None:
            raise ApiError("IDEMPOTENCY_CONFLICT", "This operation_id was already used for a different request;"
                           " nothing was changed.", operation_id=req.operation_id)
        stream, run = domain.require_active_run(conn)
        topup_id = new_id("top")
        success, cancel = return_urls(svc.settings, stream["twitch_channel_login"], topup_id)
        params = sc.build_checkout_params(req.amount_minor, topup_id, success, cancel, limits=svc.settings.limits)
        conn.execute(
            "INSERT INTO topups (topup_id, user_id, run_id, operation_id, request_hash, amount_minor, currency, status,"
            " stripe_idempotency_key, stripe_request_sha256, created_at_utc, updated_at_utc)"
            " VALUES (?, ?, ?, ?, ?, ?, 'usd', 'CREATED', ?, ?, ?, ?)",
            (topup_id, principal.user_id, run["run_id"], req.operation_id, req_hash, req.amount_minor,
             sc.topup_idempotency_key(topup_id), sc.checkout_request_fingerprint(params, api_version), now_s, now_s),
        )
        row = _row(conn, "t.topup_id = ?", (topup_id,))
        domain.record_operation(conn, actor_user_id=principal.user_id, operation_id=req.operation_id,
                                op_type=OP_TYPE, req_hash=req_hash, http_status=201, resource_type="TOPUP",
                                resource_id=topup_id, response=receipt(row, payment_mode="STRIPE_TEST",
                                                                       replayed=False), now=now)
        return dict(row), False


def _bind_session(svc, topup_id: str, session: sc.CheckoutSession) -> dict:
    now_s = timeutil.fmt(svc.clock.now())
    with svc.db.write() as conn:
        conn.execute(
            "UPDATE topups SET status = 'PENDING', stripe_session_id = ?, checkout_url = ?, checkout_expires_at_utc = ?,"
            " updated_at_utc = ? WHERE topup_id = ? AND status = 'CREATED'",
            (session.session_id, session.url, _utc_from_unix(session.expires_at), now_s, topup_id),
        )  # 0 rows: a concurrent retry or a webhook already advanced it; the re-read below shows the truth
        return dict(_row(conn, "t.topup_id = ?", (topup_id,)))


def _mark_create_failed(svc, topup_id: str, reason: str) -> dict:
    now_s = timeutil.fmt(svc.clock.now())
    with svc.db.write() as conn:
        conn.execute("UPDATE topups SET status = 'FAILED', review_reason = COALESCE(review_reason, ?),"
                     " updated_at_utc = ?, terminal_at_utc = ? WHERE topup_id = ? AND status = 'CREATED'",
                     (reason[:64], now_s, now_s, topup_id))
        return dict(_row(conn, "t.topup_id = ?", (topup_id,)))


def _stripe_failure(exc: sc.StripeError, operation_id: str) -> tuple[ApiError, str | None]:
    """Map an adapter error to (§9.10 error, review reason if the top-up must become FAILED)."""
    if isinstance(exc, sc.StripeRateLimited):
        return ApiError("RATE_LIMITED", "The payment provider is busy; retry with the same operation_id.",
                        retry_after_ms=2_000, operation_id=operation_id), None
    if isinstance(exc, (sc.StripeNetworkError, sc.StripeApiError, sc.StripeConflict)):
        return ApiError("INTERNAL_ERROR", "The payment provider did not confirm the checkout; retry with the same"
                        " operation_id.", operation_id=operation_id), None
    if isinstance(exc, (sc.StripeInvalidRequest, sc.StripeResponseError)):
        return ApiError("CAPABILITY_UNAVAILABLE", "Stripe rejected the test checkout; this top-up is FAILED.",
                        operation_id=operation_id), f"CHECKOUT_{exc.code}"
    if isinstance(exc, (sc.StripeConfigError, sc.StripeAuthenticationError, sc.StripePermissionError,
                        sc.StripeLivemodeRefused)):
        return ApiError("CAPABILITY_UNAVAILABLE", "Stripe test top-ups are unavailable right now.",
                        operation_id=operation_id), None
    return ApiError("INTERNAL_ERROR", "Top-up could not be created; retry with the same operation_id.",
                    operation_id=operation_id), None


async def _create_session(svc, payments: Payments, row: dict) -> dict:
    success, cancel = return_urls(svc.settings, row["channel"], row["topup_id"])
    params = sc.build_checkout_params(int(row["amount_minor"]), row["topup_id"], success, cancel,
                                      limits=svc.settings.limits)
    if sc.checkout_request_fingerprint(params, payments.client.api_version) != row["stripe_request_sha256"]:
        log.error("top-up %s: Checkout parameters changed since the intent was stored; not reusing its key",
                  row["topup_id"])
        raise ApiError("INTERNAL_ERROR", "Top-up configuration changed; ask the operator.",
                       operation_id=row["operation_id"])
    try:
        session = await run_in_threadpool(payments.client.create_checkout_session, int(row["amount_minor"]),
                                          row["topup_id"], success, cancel, row["stripe_idempotency_key"])
    except sc.StripeError as exc:
        err, review = _stripe_failure(exc, row["operation_id"])
        log.warning("top-up %s: Stripe create failed %s http=%s request_id=%s", row["topup_id"], exc.code,
                    exc.http_status, exc.request_id)
        if review is not None:
            await run_in_threadpool(_mark_create_failed, svc, row["topup_id"], review)
        raise err from None
    return await run_in_threadpool(_bind_session, svc, row["topup_id"], session)


# ------------------------------------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------------------------------------
@router.post("/v1/topups", status_code=201, tags=["viewer"], openapi_extra=body_schema(TopupRequest),
             responses={201: {"model": TopupReceipt}, **ERRORS})
async def create_topup(request: Request, principal: Principal = Depends(topup_principal)):
    svc = svc_of(request)
    payments = _payments(svc)
    svc.limiter.check(("topup", principal.user_id), *svc.settings.rl_topup)
    lim = svc.settings.limits
    details = {"min_minor": lim.topup_min_minor, "max_minor": lim.topup_max_minor, "step_minor": lim.topup_step_minor}
    req = await parse_body(request, TopupRequest, amount_field="amount_minor", amount_details=details)
    try:
        sc.validate_topup_amount(req.amount_minor, lim)
    except sc.StripeAmountNotAllowed:
        raise ApiError("INVALID_AMOUNT", "Top-up must be a preset or a custom amount within the published limits.",
                       details=details, operation_id=req.operation_id) from None
    req_hash = domain.hash_request(OP_TYPE, req.model_dump(mode="json"))
    row, replayed = await run_in_threadpool(_record_intent, svc, principal, req, req_hash, payments.client.api_version)
    if row["status"] == "CREATED":
        row = await _create_session(svc, payments, row)
    body = receipt(row, payment_mode=payments.mode, replayed=replayed)
    return JSONResponse(body, status_code=200 if replayed else 201, headers={"Cache-Control": "no-store"})


def _read_own(svc, topup_id: str, user_id: str) -> dict | None:
    with svc.db.read() as conn:
        row = _row(conn, "t.topup_id = ? AND t.user_id = ?", (topup_id, user_id))
        return dict(row) if row is not None else None


def _reconcile_due(svc, payments: Payments, topup_id: str) -> bool:
    now = svc.clock.now()
    with payments.lock:
        last = payments.last_reconcile.get(topup_id)
        if last is not None and (now - last).total_seconds() < svc.settings.topup_reconcile_min_interval_s:
            return False
        payments.last_reconcile[topup_id] = now
        if len(payments.last_reconcile) > 10_000:
            payments.last_reconcile.pop(next(iter(payments.last_reconcile)))
        return True


@router.get("/v1/topups/{topup_id}", tags=["viewer"], responses={200: {"model": TopupReceipt}, **ERRORS})
async def get_topup(topup_id: str, request: Request, principal: Principal = Depends(topup_principal)):
    svc = svc_of(request)
    payments = _payments(svc)
    if not TOPUP_ID_RE.fullmatch(topup_id):
        raise ApiError("NOT_FOUND", "No top-up with that id for this user.")
    row = await run_in_threadpool(_read_own, svc, topup_id, principal.user_id)
    if row is None:
        raise ApiError("NOT_FOUND", "No top-up with that id for this user.")
    if row["status"] in OPEN and row["stripe_session_id"] and _reconcile_due(svc, payments, topup_id):
        try:
            session = await run_in_threadpool(payments.client.retrieve_session, row["stripe_session_id"])
        except sc.StripeError as exc:
            log.warning("top-up %s: reconcile retrieve failed %s request_id=%s", topup_id, exc.code, exc.request_id)
            session = None
        if session is not None:
            row, plan = await run_in_threadpool(reconcile_retrieved, svc, topup_id, principal.user_id, session.facts)
            if plan.action is not sf.Action.IGNORE:
                log.info("top-up %s reconciled: %s/%s", topup_id, plan.action.value, plan.reason)
            if plan.moves_money or plan.to_status is not None:
                svc.hub.notify()
    return JSONResponse(receipt(row, payment_mode=payments.mode, replayed=False), headers={"Cache-Control": "no-store"})


@router.post("/v1/webhooks/stripe", include_in_schema=False)
async def stripe_webhook(request: Request):
    """Authenticated by the Stripe-Signature HMAC alone (no session). Fed by `stripe listen --forward-to`."""
    svc = svc_of(request)
    payments = getattr(svc, "payments", None)
    if not isinstance(payments, Payments) or payments.mode != "STRIPE_TEST":
        return JSONResponse({"received": False}, status_code=503)
    raw = await read_capped(request, sw.MAX_EVENT_BYTES)  # raw bytes: never parsed before verification
    try:
        sw.verify_signature(raw, request.headers.get("stripe-signature", ""), payments.webhook_secret,
                            tolerance_s=sw.DEFAULT_TOLERANCE_S, now=svc.clock.now().timestamp())
        event = sw.parse_event(raw)
    except sw.WebhookError as exc:  # includes LivemodeEventRejected
        log.warning("stripe webhook rejected: %s", exc.code)
        return JSONResponse({"received": False}, status_code=400)
    plan = await run_in_threadpool(apply_webhook_event, svc, event)
    log.info("stripe webhook %s %s -> %s/%s", event.type, event.event_id, plan.action.value, plan.reason)
    if plan.moves_money or plan.to_status is not None:
        svc.hub.notify()
    return JSONResponse({"received": True}, status_code=200)
