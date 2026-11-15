"""Pure Stripe top-up fulfillment planner (P6-B). No database, no I/O, no clock, no money authority.

The backend calls ``plan_fulfillment`` (webhook) or ``plan_reconciliation`` (server-side retrieve
after a return visit or poll) INSIDE its BEGIN IMMEDIATE transaction, after loading the inputs in
that same transaction:

* ``record``: the topups row, looked up by ``metadata.topup_id`` and falling back to
  ``stripe_session_id``, or None.
* ``event_already_processed``: whether provider_receipts already holds (``stripe``, event id).
* Optionally the wallet's ``available_minor`` and the §9.2 cap.

It then applies the returned plan in the same transaction: an optional receipt row, a conditional
status UPDATE, and for CREDIT one ``STRIPE_TEST_TOPUP`` ledger transaction plus a wallet event.
The planner never reads user or amount from the provider object. It credits ``record.amount_minor``
to ``record.user_id`` in ``record.run_id``, so a payment completing after a reset credits the
original, archived run (CONTRACTS §9.5), never the new one.

Uniqueness keys the backend MUST enforce. They make a planner bypass or a race harmless:

1. ``provider_receipts`` PRIMARY KEY (provider, event_id): one processing per Stripe event, across
   retries and restarts.
2. ``topups.stripe_session_id`` UNIQUE and ``topups.stripe_payment_intent_id`` UNIQUE: one top-up
   per underlying paid object, so different event ids for the same session (completed plus
   async_payment_succeeded, or a retrieve) cannot credit twice.
3. ``ledger_transactions.source_key = 'stripe_topup:<topup_id>'`` (already UNIQUE): one credit per
   top-up, even if the planner were bypassed.
4. Status changes are conditional, ``UPDATE topups ... WHERE topup_id = ? AND status IN
   plan.from_statuses``, and must touch exactly one row.

A checkout return-URL visit never credits by itself. The browser's claim is ignored; only a
server-side retrieve passed through ``plan_reconciliation`` can, and it applies the same rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .stripe_webhook import (
    CHECKOUT_ASYNC_FAILED,
    CHECKOUT_ASYNC_SUCCEEDED,
    CHECKOUT_COMPLETED,
    CHECKOUT_EXPIRED,
    CheckoutSessionFacts,
    StripeEvent,
)

PROVIDER = "stripe"
LEDGER_REASON = "STRIPE_TEST_TOPUP"
RETRIEVED = "reconcile.retrieved_session"  # pseudo event type for plan_reconciliation


class TopupStatus(str, Enum):
    CREATED = "CREATED"  # internal intent stored; Checkout Session not yet confirmed created
    PENDING = "PENDING"  # session created; awaiting a verified provider-paid state
    CREDITED = "CREDITED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


OPEN_STATUSES: tuple[str, ...] = (TopupStatus.CREATED.value, TopupStatus.PENDING.value)
TERMINAL_STATUSES: tuple[str, ...] = (TopupStatus.CREDITED.value, TopupStatus.FAILED.value, TopupStatus.EXPIRED.value)


class Action(str, Enum):
    CREDIT = "CREDIT"  # post exactly one STRIPE_TEST_TOPUP transaction, status -> CREDITED
    NOOP_DUPLICATE = "NOOP_DUPLICATE"  # already processed or already credited: acknowledge, no effect
    MISMATCH_REVIEW = "MISMATCH_REVIEW"  # contradicts the stored intent: no funds, flag for review
    IGNORE = "IGNORE"  # not ours, not handled, or not yet paid: no effect
    MARK_FAILED = "MARK_FAILED"  # status -> FAILED (async payment failed)
    MARK_EXPIRED = "MARK_EXPIRED"  # status -> EXPIRED (Stripe says the session expired)


@dataclass(frozen=True, slots=True)
class TopupRecord:
    """The backend's stored intent. Amount, currency, user and run were decided by the server."""

    topup_id: str
    user_id: str
    run_id: str
    amount_minor: int
    currency: str
    status: str
    stripe_session_id: str | None = None
    stripe_payment_intent_id: str | None = None
    run_state: str | None = None  # ACTIVE | ARCHIVED (informational; crediting never changes the run)


@dataclass(frozen=True, slots=True)
class FulfillmentPlan:
    action: Action
    reason: str  # stable machine code, safe to log
    detail: str  # short human text; no secrets, no customer data
    topup_id: str | None = None  # only when a stored record matched
    user_id: str | None = None
    run_id: str | None = None
    amount_minor: int | None = None  # CREDIT only
    ledger_reason: str | None = None  # CREDIT only: STRIPE_TEST_TOPUP
    ledger_source_key: str | None = None  # CREDIT only: stripe_topup:<topup_id>
    from_statuses: tuple[str, ...] = ()  # conditional-UPDATE guard
    to_status: str | None = None
    bind_session_id: str | None = None  # store if the record had none yet
    bind_payment_intent_id: str | None = None
    flag_review: bool = False  # set topups.review_reason (first write wins); never changes status
    record_receipt: bool = False  # insert the provider_receipts row for this event id
    event_id: str | None = None
    event_type: str | None = None
    session_id: str | None = None
    credits_archived_run: bool = False

    @property
    def moves_money(self) -> bool:
        return self.action is Action.CREDIT


def ledger_source_key(topup_id: str) -> str:
    return f"stripe_topup:{topup_id}"


def _binding_mismatch(record: TopupRecord, s: CheckoutSessionFacts) -> tuple[str, str] | None:
    if s.topup_id != record.topup_id:
        return "TOPUP_ID_MISMATCH", "metadata.topup_id does not name this top-up"
    if s.client_reference_id is not None and s.client_reference_id != record.topup_id:
        return "CLIENT_REFERENCE_MISMATCH", "client_reference_id does not name this top-up"
    if record.stripe_session_id is not None and record.stripe_session_id != s.session_id:
        return "SESSION_MISMATCH", "event names a different Checkout Session than the one stored"
    if (record.stripe_payment_intent_id is not None and s.payment_intent_id is not None
            and record.stripe_payment_intent_id != s.payment_intent_id):
        return "PAYMENT_INTENT_MISMATCH", "event names a different PaymentIntent than the one stored"
    if s.mode is not None and s.mode != "payment":
        return "MODE_MISMATCH", "session is not a one-time payment"
    if s.currency is None or s.currency != record.currency.lower():
        return "CURRENCY_MISMATCH", "session currency differs from the stored top-up"
    if s.amount_total is None or s.amount_total != record.amount_minor:
        return "AMOUNT_MISMATCH", "session amount_total differs from the stored top-up"
    return None


def _plan_session(
    record: TopupRecord | None,
    s: CheckoutSessionFacts,
    kind: str,
    common: dict,
    *,
    requester_user_id: str | None,
    wallet_available_minor: int | None,
    available_max_minor: int | None,
) -> FulfillmentPlan:
    if record is None:
        return FulfillmentPlan(Action.IGNORE, "UNKNOWN_TOPUP", "no stored top-up matches this session", **common)
    owner = dict(common, topup_id=record.topup_id, user_id=record.user_id, run_id=record.run_id)
    if requester_user_id is not None and requester_user_id != record.user_id:
        # Never flag review here: a stranger must not be able to block someone else's top-up.
        return FulfillmentPlan(Action.IGNORE, "REQUESTER_NOT_OWNER", "top-up belongs to another user", **common)
    mismatch = _binding_mismatch(record, s)
    if mismatch is not None:
        return FulfillmentPlan(Action.MISMATCH_REVIEW, mismatch[0], mismatch[1], flag_review=True, **owner)

    paid = s.is_paid
    claims_paid = paid or s.payment_status == "paid"
    status = record.status
    if status == TopupStatus.CREDITED.value:
        contradicts = kind in (CHECKOUT_ASYNC_FAILED, CHECKOUT_EXPIRED) or (kind == RETRIEVED and s.status == "expired")
        if contradicts:
            return FulfillmentPlan(Action.MISMATCH_REVIEW, "CONTRADICTS_CREDITED",
                                   "failure or expiry reported for an already credited top-up", flag_review=True, **owner)
        return FulfillmentPlan(Action.NOOP_DUPLICATE, "ALREADY_CREDITED", "this top-up was already credited once", **owner)
    if status in (TopupStatus.FAILED.value, TopupStatus.EXPIRED.value):
        if claims_paid:
            return FulfillmentPlan(Action.MISMATCH_REVIEW, f"CONTRADICTS_{status}",
                                   f"paid state reported for a top-up already marked {status}", flag_review=True, **owner)
        return FulfillmentPlan(Action.NOOP_DUPLICATE, "ALREADY_TERMINAL", f"top-up is already {status}", **owner)
    if status not in OPEN_STATUSES:
        return FulfillmentPlan(Action.MISMATCH_REVIEW, "UNKNOWN_RECORD_STATUS", "stored top-up status is not recognised",
                               flag_review=True, **owner)

    bind = dict(
        bind_session_id=s.session_id if record.stripe_session_id is None else None,
        bind_payment_intent_id=(s.payment_intent_id if record.stripe_payment_intent_id is None else None),
    )

    def credit() -> FulfillmentPlan:
        if (wallet_available_minor is not None and available_max_minor is not None
                and wallet_available_minor + record.amount_minor > available_max_minor):
            return FulfillmentPlan(Action.MISMATCH_REVIEW, "BALANCE_CAP_EXCEEDED",
                                   "credit would exceed the available-balance cap", flag_review=True, **owner)
        return FulfillmentPlan(
            Action.CREDIT, "PAID", "verified provider-paid state for the stored top-up",
            amount_minor=record.amount_minor, ledger_reason=LEDGER_REASON,
            ledger_source_key=ledger_source_key(record.topup_id), from_statuses=OPEN_STATUSES,
            to_status=TopupStatus.CREDITED.value, credits_archived_run=record.run_state == "ARCHIVED",
            **bind, **owner,
        )

    def mark(action: Action, to_status: TopupStatus, reason: str, detail: str) -> FulfillmentPlan:
        if claims_paid:
            return FulfillmentPlan(Action.MISMATCH_REVIEW, "CONTRADICTORY_EVENT",
                                   "failure or expiry reported together with a paid state", flag_review=True, **owner)
        return FulfillmentPlan(action, reason, detail, from_statuses=OPEN_STATUSES, to_status=to_status.value,
                               **bind, **owner)

    if kind == CHECKOUT_COMPLETED:
        if paid:
            return credit()
        if s.payment_status == "unpaid":
            return FulfillmentPlan(Action.IGNORE, "AWAITING_ASYNC_PAYMENT",
                                   "session completed but not paid yet; wait for async_payment_succeeded", **owner)
        return FulfillmentPlan(Action.MISMATCH_REVIEW, "UNEXPECTED_PAYMENT_STATUS",
                               "completed session is neither paid nor unpaid", flag_review=True, **owner)
    if kind == CHECKOUT_ASYNC_SUCCEEDED:
        if paid:
            return credit()
        return FulfillmentPlan(Action.MISMATCH_REVIEW, "UNEXPECTED_PAYMENT_STATUS",
                               "async success without a paid, complete session", flag_review=True, **owner)
    if kind == CHECKOUT_ASYNC_FAILED:
        return mark(Action.MARK_FAILED, TopupStatus.FAILED, "ASYNC_PAYMENT_FAILED", "delayed payment failed; no credit")
    if kind == CHECKOUT_EXPIRED:
        return mark(Action.MARK_EXPIRED, TopupStatus.EXPIRED, "SESSION_EXPIRED", "Checkout Session expired unpaid")
    if kind == RETRIEVED:
        if paid:
            return credit()
        if s.status == "expired":
            return mark(Action.MARK_EXPIRED, TopupStatus.EXPIRED, "SESSION_EXPIRED", "Checkout Session expired unpaid")
        if s.status == "open":
            return FulfillmentPlan(Action.IGNORE, "PAYMENT_PENDING", "session is still open and unpaid", **owner)
        if s.status == "complete" and s.payment_status == "unpaid":
            return FulfillmentPlan(Action.IGNORE, "AWAITING_ASYNC_PAYMENT", "completed but not paid yet", **owner)
        return FulfillmentPlan(Action.MISMATCH_REVIEW, "UNEXPECTED_SESSION_STATE",
                               "retrieved session state is not recognised", flag_review=True, **owner)
    return FulfillmentPlan(Action.IGNORE, "UNHANDLED_EVENT_TYPE", "event type has no money effect", **common)


def plan_fulfillment(
    record: TopupRecord | None,
    event: StripeEvent,
    *,
    event_already_processed: bool = False,
    wallet_available_minor: int | None = None,
    available_max_minor: int | None = None,
) -> FulfillmentPlan:
    """Decide the effect of one VERIFIED webhook event (verify_signature + parse_event first)."""
    common = dict(event_id=event.event_id, event_type=event.type,
                  session_id=event.session.session_id if event.session is not None else None)
    if event_already_processed:
        return FulfillmentPlan(Action.NOOP_DUPLICATE, "DUPLICATE_EVENT", "this event id was already processed",
                               topup_id=record.topup_id if record is not None else None, **common)
    common["record_receipt"] = True
    if event.livemode or (event.session is not None and event.session.livemode):
        return FulfillmentPlan(Action.IGNORE, "LIVEMODE_REJECTED", "live-mode data never moves demo funds", **common)
    if not event.handled:
        return FulfillmentPlan(Action.IGNORE, "UNHANDLED_EVENT_TYPE", "event type has no money effect", **common)
    return _plan_session(record, event.session, event.type, common, requester_user_id=None,
                         wallet_available_minor=wallet_available_minor, available_max_minor=available_max_minor)


def plan_reconciliation(
    record: TopupRecord | None,
    session: CheckoutSessionFacts,
    *,
    requester_user_id: str | None,
    wallet_available_minor: int | None = None,
    available_max_minor: int | None = None,
) -> FulfillmentPlan:
    """Same rules for a session the SERVER retrieved from Stripe (a return visit or a status poll).

    There is no provider event id, so there is no receipt row. Exactly-once still holds through the
    record status, the session uniqueness and the ledger source key.
    """
    common = dict(event_type=RETRIEVED, session_id=session.session_id)
    if session.livemode:
        return FulfillmentPlan(Action.IGNORE, "LIVEMODE_REJECTED", "live-mode data never moves demo funds", **common)
    return _plan_session(record, session, RETRIEVED, common, requester_user_id=requester_user_id,
                         wallet_available_minor=wallet_available_minor, available_max_minor=available_max_minor)
