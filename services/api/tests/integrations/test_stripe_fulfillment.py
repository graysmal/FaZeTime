"""P6-B pure fulfillment planner: exactly-once credit, mismatches, ordering and duplicates (offline)."""

from __future__ import annotations

import itertools
from dataclasses import replace

import pytest

from fazetime_api.integrations.stripe_fulfillment import (
    LEDGER_REASON,
    OPEN_STATUSES,
    Action,
    FulfillmentPlan,
    TopupRecord,
    ledger_source_key,
    plan_fulfillment,
    plan_reconciliation,
)
from fazetime_api.integrations.stripe_webhook import (
    CHECKOUT_ASYNC_FAILED,
    CHECKOUT_ASYNC_SUCCEEDED,
    CHECKOUT_COMPLETED,
    CHECKOUT_EXPIRED,
    StripeEvent,
    session_facts_from_object,
)

from .stripe_fixtures import (
    OTHER_SESSION_ID,
    OTHER_TOPUP_ID,
    OTHER_USER_ID,
    PI_ID,
    RUN_ID,
    SESSION_ID,
    TOPUP_ID,
    USER_ID,
    session_obj,
    verified_event,
)

PAID = dict(status="complete", payment_status="paid")
UNPAID_COMPLETE = dict(status="complete", payment_status="unpaid", payment_intent=PI_ID)
EXPIRED = dict(status="expired", payment_status="unpaid", payment_intent=None)
OPEN = dict(status="open", payment_status="unpaid", payment_intent=None)


def record(**overrides) -> TopupRecord:
    base = dict(topup_id=TOPUP_ID, user_id=USER_ID, run_id=RUN_ID, amount_minor=500, currency="usd",
                status="PENDING", stripe_session_id=SESSION_ID, stripe_payment_intent_id=None, run_state="ACTIVE")
    base.update(overrides)
    return TopupRecord(**base)


def ev(event_type: str, event_id: str = "evt_FIXTURE0000000000000001", **session_overrides) -> StripeEvent:
    return verified_event(event_type, session_obj(**session_overrides), event_id=event_id)


def facts(**session_overrides):
    return session_facts_from_object(session_obj(**session_overrides))


def assert_no_money(plan: FulfillmentPlan) -> None:
    assert plan.action is not Action.CREDIT and not plan.moves_money
    assert plan.amount_minor is None and plan.ledger_source_key is None and plan.ledger_reason is None


# ---- the happy path ------------------------------------------------------------------------------
def test_completed_and_paid_credits_the_stored_amount_to_the_stored_user_and_run():
    plan = plan_fulfillment(record(), ev(CHECKOUT_COMPLETED, **PAID))
    assert plan.action is Action.CREDIT and plan.reason == "PAID" and plan.moves_money
    assert (plan.topup_id, plan.user_id, plan.run_id, plan.amount_minor) == (TOPUP_ID, USER_ID, RUN_ID, 500)
    assert plan.ledger_reason == LEDGER_REASON == "STRIPE_TEST_TOPUP"
    assert plan.ledger_source_key == ledger_source_key(TOPUP_ID) == f"stripe_topup:{TOPUP_ID}"
    assert plan.from_statuses == OPEN_STATUSES == ("CREATED", "PENDING") and plan.to_status == "CREDITED"
    assert plan.record_receipt is True and plan.event_id == "evt_FIXTURE0000000000000001"
    assert plan.bind_session_id is None and plan.bind_payment_intent_id == PI_ID
    assert plan.credits_archived_run is False and plan.flag_review is False


def test_created_record_without_a_session_binds_it_on_credit():
    plan = plan_fulfillment(record(status="CREATED", stripe_session_id=None), ev(CHECKOUT_COMPLETED, **PAID))
    assert plan.action is Action.CREDIT and plan.bind_session_id == SESSION_ID


# ---- mismatches never grant funds ----------------------------------------------------------------
@pytest.mark.parametrize("session_overrides, reason", [
    ({"amount_total": 5_000}, "AMOUNT_MISMATCH"),
    ({"amount_total": 499}, "AMOUNT_MISMATCH"),
    ({"amount_total": None}, "AMOUNT_MISMATCH"),
    ({"currency": "eur"}, "CURRENCY_MISMATCH"),
    ({"currency": None}, "CURRENCY_MISMATCH"),
    ({"metadata": {"topup_id": OTHER_TOPUP_ID}}, "TOPUP_ID_MISMATCH"),
    ({"metadata": {}}, "TOPUP_ID_MISMATCH"),
    ({"client_reference_id": OTHER_TOPUP_ID}, "CLIENT_REFERENCE_MISMATCH"),
    ({"id": OTHER_SESSION_ID}, "SESSION_MISMATCH"),
    ({"mode": "subscription"}, "MODE_MISMATCH"),
])
def test_mismatches_go_to_review_without_funds(session_overrides, reason):
    plan = plan_fulfillment(record(), ev(CHECKOUT_COMPLETED, **{**PAID, **session_overrides}))
    assert plan.action is Action.MISMATCH_REVIEW and plan.reason == reason and plan.flag_review
    assert plan.to_status is None and plan.record_receipt is True
    assert_no_money(plan)


def test_payment_intent_mismatch_goes_to_review():
    plan = plan_fulfillment(record(stripe_payment_intent_id="pi_FIXTUREother000000001"), ev(CHECKOUT_COMPLETED, **PAID))
    assert plan.action is Action.MISMATCH_REVIEW and plan.reason == "PAYMENT_INTENT_MISMATCH"
    assert_no_money(plan)


def test_currency_comparison_uses_the_stored_record_not_the_event():
    plan = plan_fulfillment(record(currency="eur"), ev(CHECKOUT_COMPLETED, **PAID))
    assert plan.action is Action.MISMATCH_REVIEW and plan.reason == "CURRENCY_MISMATCH"


def test_user_mismatch_on_reconciliation_is_ignored_and_never_flags_someone_elses_topup():
    plan = plan_reconciliation(record(), facts(**PAID), requester_user_id=OTHER_USER_ID)
    assert plan.action is Action.IGNORE and plan.reason == "REQUESTER_NOT_OWNER"
    assert plan.flag_review is False and plan.topup_id is None and plan.user_id is None
    assert_no_money(plan)


def test_user_and_amount_are_never_taken_from_provider_data():
    event = ev(CHECKOUT_COMPLETED, **PAID, metadata={"topup_id": TOPUP_ID, "user_id": OTHER_USER_ID,
                                                     "amount_minor": "5000", "run_id": "run_" + "f" * 32})
    plan = plan_fulfillment(record(), event)
    assert plan.action is Action.CREDIT
    assert (plan.user_id, plan.run_id, plan.amount_minor) == (USER_ID, RUN_ID, 500)


def test_balance_cap_goes_to_review_instead_of_crediting():
    plan = plan_fulfillment(record(), ev(CHECKOUT_COMPLETED, **PAID), wallet_available_minor=999_600,
                            available_max_minor=1_000_000)
    assert plan.action is Action.MISMATCH_REVIEW and plan.reason == "BALANCE_CAP_EXCEEDED"
    ok = plan_fulfillment(record(), ev(CHECKOUT_COMPLETED, **PAID), wallet_available_minor=999_500,
                          available_max_minor=1_000_000)
    assert ok.action is Action.CREDIT


# ---- duplicates and distinct event ids for the same payment --------------------------------------
def test_duplicate_event_id_is_a_noop_even_while_pending():
    plan = plan_fulfillment(record(), ev(CHECKOUT_COMPLETED, **PAID), event_already_processed=True)
    assert plan.action is Action.NOOP_DUPLICATE and plan.reason == "DUPLICATE_EVENT"
    assert plan.record_receipt is False  # the receipt already exists
    assert_no_money(plan)


def test_same_session_through_different_event_ids_credits_once():
    first = plan_fulfillment(record(), ev(CHECKOUT_COMPLETED, "evt_FIXTUREa0000000000001", **PAID))
    assert first.action is Action.CREDIT
    credited = record(status="CREDITED", stripe_payment_intent_id=PI_ID)
    for later in (ev(CHECKOUT_COMPLETED, "evt_FIXTUREb0000000000002", **PAID),
                  ev(CHECKOUT_ASYNC_SUCCEEDED, "evt_FIXTUREc0000000000003", **PAID)):
        plan = plan_fulfillment(credited, later)
        assert plan.action is Action.NOOP_DUPLICATE and plan.reason == "ALREADY_CREDITED"
        assert_no_money(plan)
    plan = plan_reconciliation(credited, facts(**PAID), requester_user_id=USER_ID)
    assert plan.action is Action.NOOP_DUPLICATE and plan.reason == "ALREADY_CREDITED"


# ---- unknown types, unknown top-ups, livemode ----------------------------------------------------
@pytest.mark.parametrize("event_type", ["payment_intent.succeeded", "charge.succeeded", "checkout.session.created"])
def test_unknown_types_are_ignored_with_no_money_effect(event_type):
    event = verified_event(event_type, {"id": "obj_FIXTURE", "object": "whatever", "livemode": False})
    plan = plan_fulfillment(record(), event)
    assert plan.action is Action.IGNORE and plan.reason == "UNHANDLED_EVENT_TYPE" and plan.record_receipt
    assert plan.to_status is None and not plan.flag_review
    assert_no_money(plan)


def test_unknown_topup_is_ignored_and_reveals_nothing():
    plan = plan_fulfillment(None, ev(CHECKOUT_COMPLETED, **PAID))
    assert plan.action is Action.IGNORE and plan.reason == "UNKNOWN_TOPUP" and plan.record_receipt
    assert plan.topup_id is None and plan.user_id is None
    assert_no_money(plan)


def test_livemode_data_is_ignored_defensively_even_if_parsing_was_bypassed():
    good = ev(CHECKOUT_COMPLETED, **PAID)
    forged = StripeEvent(good.event_id, good.type, True, good.created, good.api_version, good.session,
                         good.payload_sha256)
    plan = plan_fulfillment(record(), forged)
    assert plan.action is Action.IGNORE and plan.reason == "LIVEMODE_REJECTED"
    assert_no_money(plan)
    live_facts = replace(good.session, livemode=True)
    assert plan_reconciliation(record(), live_facts, requester_user_id=USER_ID).reason == "LIVEMODE_REJECTED"


# ---- unpaid, async, expiry -----------------------------------------------------------------------
def test_completed_but_unpaid_never_credits():
    plan = plan_fulfillment(record(), ev(CHECKOUT_COMPLETED, **UNPAID_COMPLETE))
    assert plan.action is Action.IGNORE and plan.reason == "AWAITING_ASYNC_PAYMENT" and plan.to_status is None
    assert_no_money(plan)


@pytest.mark.parametrize("overrides", [
    {"status": "complete", "payment_status": "no_payment_required"},
    {"status": "open", "payment_status": "paid"},
    {"status": "complete", "payment_status": None},
])
def test_completed_in_odd_states_goes_to_review(overrides):
    plan = plan_fulfillment(record(), ev(CHECKOUT_COMPLETED, **overrides))
    assert plan.action is Action.MISMATCH_REVIEW and plan.reason == "UNEXPECTED_PAYMENT_STATUS"
    assert_no_money(plan)


def test_async_success_credits_after_an_unpaid_completion():
    waiting = plan_fulfillment(record(), ev(CHECKOUT_COMPLETED, "evt_FIXTUREa0000000000001", **UNPAID_COMPLETE))
    assert waiting.action is Action.IGNORE
    plan = plan_fulfillment(record(), ev(CHECKOUT_ASYNC_SUCCEEDED, "evt_FIXTUREb0000000000002", **PAID))
    assert plan.action is Action.CREDIT and plan.amount_minor == 500


def test_async_success_without_paid_state_goes_to_review():
    plan = plan_fulfillment(record(), ev(CHECKOUT_ASYNC_SUCCEEDED, **UNPAID_COMPLETE))
    assert plan.action is Action.MISMATCH_REVIEW
    assert_no_money(plan)


def test_async_failure_marks_failed_and_later_events_cannot_credit():
    plan = plan_fulfillment(record(), ev(CHECKOUT_ASYNC_FAILED, **UNPAID_COMPLETE))
    assert plan.action is Action.MARK_FAILED and plan.to_status == "FAILED" and plan.from_statuses == OPEN_STATUSES
    assert_no_money(plan)
    failed = record(status="FAILED")
    late_completion = plan_fulfillment(failed, ev(CHECKOUT_COMPLETED, "evt_FIXTUREb0000000000002", **UNPAID_COMPLETE))
    assert late_completion.action is Action.NOOP_DUPLICATE and late_completion.reason == "ALREADY_TERMINAL"
    contradiction = plan_fulfillment(failed, ev(CHECKOUT_ASYNC_SUCCEEDED, "evt_FIXTUREc0000000000003", **PAID))
    assert contradiction.action is Action.MISMATCH_REVIEW and contradiction.reason == "CONTRADICTS_FAILED"
    assert_no_money(contradiction)


def test_expiry_marks_expired_and_binds_a_missing_session():
    plan = plan_fulfillment(record(status="CREATED", stripe_session_id=None), ev(CHECKOUT_EXPIRED, **EXPIRED))
    assert plan.action is Action.MARK_EXPIRED and plan.to_status == "EXPIRED" and plan.bind_session_id == SESSION_ID
    assert_no_money(plan)


def test_expiry_or_failure_after_credit_is_a_contradiction_without_clawback():
    credited = record(status="CREDITED")
    for event in (ev(CHECKOUT_EXPIRED, **EXPIRED), ev(CHECKOUT_ASYNC_FAILED, **UNPAID_COMPLETE)):
        plan = plan_fulfillment(credited, event)
        assert plan.action is Action.MISMATCH_REVIEW and plan.reason == "CONTRADICTS_CREDITED"
        assert plan.to_status is None
        assert_no_money(plan)


def test_failure_event_claiming_paid_is_a_contradiction():
    plan = plan_fulfillment(record(), ev(CHECKOUT_EXPIRED, status="expired", payment_status="paid"))
    assert plan.action is Action.MISMATCH_REVIEW and plan.reason == "CONTRADICTORY_EVENT"


# ---- archived runs -------------------------------------------------------------------------------
def test_payment_completing_after_reset_credits_the_original_archived_run():
    plan = plan_fulfillment(record(run_state="ARCHIVED"), ev(CHECKOUT_COMPLETED, **PAID))
    assert plan.action is Action.CREDIT and plan.run_id == RUN_ID and plan.credits_archived_run is True


# ---- return visit / server-side reconciliation ---------------------------------------------------
def test_return_visit_without_payment_never_credits():
    plan = plan_reconciliation(record(), facts(**OPEN), requester_user_id=USER_ID)
    assert plan.action is Action.IGNORE and plan.reason == "PAYMENT_PENDING"
    assert_no_money(plan)


@pytest.mark.parametrize("overrides, action, reason", [
    (PAID, Action.CREDIT, "PAID"),
    (EXPIRED, Action.MARK_EXPIRED, "SESSION_EXPIRED"),
    (UNPAID_COMPLETE, Action.IGNORE, "AWAITING_ASYNC_PAYMENT"),
    ({"status": "weird", "payment_status": "unpaid"}, Action.MISMATCH_REVIEW, "UNEXPECTED_SESSION_STATE"),
])
def test_reconciliation_follows_the_retrieved_state(overrides, action, reason):
    plan = plan_reconciliation(record(), facts(**overrides), requester_user_id=USER_ID)
    assert (plan.action, plan.reason) == (action, reason)
    assert plan.record_receipt is False and plan.event_id is None


def test_reconciliation_with_a_mismatched_amount_never_credits():
    plan = plan_reconciliation(record(amount_minor=1_000), facts(**PAID), requester_user_id=USER_ID)
    assert plan.action is Action.MISMATCH_REVIEW and plan.reason == "AMOUNT_MISMATCH"


# ---- exactly-once under every delivery order -----------------------------------------------------
class FakeBackend:
    """Applies plans with the uniqueness rules the real backend must enforce. No DB; test-only."""

    def __init__(self, rec: TopupRecord) -> None:
        self.rec = rec
        self.receipts: dict[str, str] = {}  # provider_receipts PRIMARY KEY (provider, event_id)
        self.ledger: dict[str, int] = {}  # ledger_transactions.source_key UNIQUE
        self.reviews: list[str] = []

    def _lookup(self, s) -> TopupRecord | None:
        if s is None:
            return None
        return self.rec if s.topup_id == self.rec.topup_id or s.session_id == self.rec.stripe_session_id else None

    def deliver(self, item) -> FulfillmentPlan:
        if isinstance(item, StripeEvent):
            plan = plan_fulfillment(self._lookup(item.session), item,
                                    event_already_processed=item.event_id in self.receipts)
        else:
            plan = plan_reconciliation(self._lookup(item), item, requester_user_id=USER_ID)
        if plan.record_receipt:
            assert plan.event_id not in self.receipts
            self.receipts[plan.event_id] = plan.action.value
        if plan.action is Action.CREDIT:
            assert plan.ledger_source_key not in self.ledger, "ledger source_key UNIQUE would abort this"
            assert self.rec.status in plan.from_statuses, "conditional UPDATE would match no row"
            self.ledger[plan.ledger_source_key] = plan.amount_minor
        if plan.to_status is not None:
            assert self.rec.status in plan.from_statuses
            self.rec = replace(self.rec, status=plan.to_status,
                               stripe_session_id=self.rec.stripe_session_id or plan.bind_session_id,
                               stripe_payment_intent_id=self.rec.stripe_payment_intent_id or plan.bind_payment_intent_id)
        if plan.flag_review:
            self.reviews.append(plan.reason)
        return plan

    @property
    def credited_minor(self) -> int:
        return sum(self.ledger.values())


UNKNOWN = verified_event("payment_intent.succeeded", {"id": PI_ID, "object": "payment_intent", "livemode": False},
                         event_id="evt_FIXTUREu0000000000009")
SCENARIOS = {
    "card_paid_with_retries_and_return_visit": (
        [ev(CHECKOUT_COMPLETED, "evt_FIXTUREa0000000000001", **PAID),
         ev(CHECKOUT_COMPLETED, "evt_FIXTUREa0000000000001", **PAID),  # Stripe retry: same event id
         ev(CHECKOUT_ASYNC_SUCCEEDED, "evt_FIXTUREb0000000000002", **PAID),  # same payment, new event id
         facts(**PAID), UNKNOWN],
        500, "CREDITED"),
    "async_success_any_order": (
        [ev(CHECKOUT_COMPLETED, "evt_FIXTUREa0000000000001", **UNPAID_COMPLETE),
         ev(CHECKOUT_ASYNC_SUCCEEDED, "evt_FIXTUREb0000000000002", **PAID),
         ev(CHECKOUT_ASYNC_SUCCEEDED, "evt_FIXTUREb0000000000002", **PAID), UNKNOWN],
        500, "CREDITED"),
    "async_failure_any_order": (
        [ev(CHECKOUT_COMPLETED, "evt_FIXTUREa0000000000001", **UNPAID_COMPLETE),
         ev(CHECKOUT_ASYNC_FAILED, "evt_FIXTUREb0000000000002", **UNPAID_COMPLETE),
         ev(CHECKOUT_ASYNC_FAILED, "evt_FIXTUREb0000000000002", **UNPAID_COMPLETE), UNKNOWN],
        0, "FAILED"),
    "abandoned_checkout_expires": (
        [facts(**OPEN), ev(CHECKOUT_EXPIRED, "evt_FIXTUREe0000000000005", **EXPIRED),
         ev(CHECKOUT_EXPIRED, "evt_FIXTUREe0000000000005", **EXPIRED), UNKNOWN],
        0, "EXPIRED"),
}


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_every_delivery_order_credits_at_most_once(name):
    items, expected_minor, expected_status = SCENARIOS[name]
    orders = 0
    for order in itertools.permutations(items):
        backend = FakeBackend(record())
        plans = [backend.deliver(item) for item in order]
        orders += 1
        assert backend.credited_minor == expected_minor, (name, [p.reason for p in plans])
        assert sum(p.action is Action.CREDIT for p in plans) == (1 if expected_minor else 0)
        if expected_status is not None:
            assert backend.rec.status == expected_status
        assert backend.reviews == []
    assert orders == len(list(itertools.permutations(items)))


def test_abandoned_checkout_ends_expired_or_pending_never_credited():
    backend = FakeBackend(record())
    backend.deliver(facts(**OPEN))
    assert backend.rec.status == "PENDING" and backend.credited_minor == 0
    backend.deliver(ev(CHECKOUT_EXPIRED, "evt_FIXTUREe0000000000005", **EXPIRED))
    assert backend.rec.status == "EXPIRED" and backend.credited_minor == 0
