"""Contract test (CONTRACTS §9.14): every JSON fixture in packages/contracts/fixtures/v1/ must validate
against the backend's Pydantic models, chosen by folder/name. Fixtures are read-only here; a failure is a
contract finding to report to the coordinator, never a reason to edit the fixture."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fazetime_api.domain import hash_request
from fazetime_api.ids import normalize_invite_code
from fazetime_api.schemas import (
    DomainEvent,
    EnrollRequest,
    EnrollResponse,
    ErrorEnvelope,
    Me,
    OperatorMarket,
    PresenceAck,
    PresenceHeartbeat,
    StreamSnapshot,
    WagerReceipt,
    WagerRequest,
    WsTicketResponse,
)
from fazetime_api.settlement import StakeLine, compute_payouts

FIXTURES = Path(__file__).resolve().parents[3] / "packages" / "contracts" / "fixtures" / "v1"
ALL = sorted(p.relative_to(FIXTURES).as_posix() for p in FIXTURES.rglob("*.json")) if FIXTURES.is_dir() else []

BY_NAME = {
    "enroll/request": EnrollRequest,
    "enroll/response": EnrollResponse,
    "ws/ticket_response": WsTicketResponse,
    "presence/heartbeat": PresenceHeartbeat,
    "presence/ack": PresenceAck,
    "wager/request": WagerRequest,
    "wager/request_conflict": WagerRequest,
    "wager/receipt_accepted": WagerReceipt,
    "wager/receipt_replayed": WagerReceipt,
    "operator/market_draft": OperatorMarket,
}
BY_FOLDER = {"snapshot": StreamSnapshot, "me": Me, "error": ErrorEnvelope, "event": DomainEvent}
SPECIAL = {"event/sequence_reorder_duplicate", "domain/settlement_worked_example"}
REQUIRED = {
    "snapshot": ["no_market", "open_no_position", "open_with_position", "open_empty_pool", "open_one_sided",
                 "open_low_balance", "open_source_stale", "locked", "evaluating", "settled_win", "settled_loss",
                 "settled_no_position", "void_one_sided", "void_empty", "void_source_gap",
                 "void_resolution_timeout", "void_unresolvable", "run_reset"],
    "operator": ["market_draft"], "me": ["viewer_funded", "viewer_low_balance"], "enroll": ["request", "response"],
    "ws": ["ticket_response"], "presence": ["heartbeat", "ack"],
    "wager": ["request", "receipt_accepted", "receipt_replayed", "request_conflict"],
    "domain": ["settlement_worked_example"],
}
ERROR_CODES = ["UNAUTHENTICATED", "FORBIDDEN", "INVALID_AMOUNT", "INSUFFICIENT_FUNDS", "MARKET_CLOSED",
               "STALE_MARKET", "WRONG_RUN", "IDEMPOTENCY_CONFLICT", "CAPABILITY_UNAVAILABLE", "SOURCE_STALE",
               "RATE_LIMITED", "VALIDATION_FAILED", "SIDE_CONFLICT", "NOT_FOUND", "INTERNAL_ERROR"]
EVENT_TYPES = ["stream.updated", "source.health", "market.opened", "pool.updated", "market.locked",
               "market.evaluating", "market.settled", "market.voided", "wager.updated", "wallet.changed"]
BANNER_EXPECTATION = {
    "settled_win": "WON", "settled_loss": "LOST", "settled_no_position": "NONE", "void_one_sided": "VOID_REFUNDED",
    "void_empty": "NONE", "void_source_gap": "VOID_REFUNDED", "void_resolution_timeout": "UNRESOLVED_REFUNDED",
    "void_unresolvable": "UNRESOLVED_REFUNDED",
}

pytestmark = pytest.mark.skipif(not ALL, reason="packages/contracts/fixtures/v1 not present")


def _load(rel: str):
    return json.loads((FIXTURES / rel).read_text(encoding="utf-8"))


def test_required_fixture_files_exist():
    names = {p[:-5] for p in ALL}
    missing = [f"{folder}/{n}" for folder, items in REQUIRED.items() for n in items if f"{folder}/{n}" not in names]
    missing += [f"error/{c.lower()}" for c in ERROR_CODES if f"error/{c.lower()}" not in names]
    missing += [f"event/{t.replace('.', '_')}" for t in EVENT_TYPES if f"event/{t.replace('.', '_')}" not in names]
    if "event/sequence_reorder_duplicate" not in names:
        missing.append("event/sequence_reorder_duplicate")
    assert missing == [], f"contract finding: missing fixtures {missing}"


@pytest.mark.parametrize("rel", ALL)
def test_fixture_validates_against_backend_model(rel):
    name = rel[:-5]
    folder, base = name.split("/", 1)
    data = _load(rel)
    if name in SPECIAL:
        pytest.skip("checked by a dedicated test below")
    model = BY_NAME.get(name) or BY_FOLDER.get(folder)
    assert model is not None, f"contract finding: no backend model mapped for {rel}"
    obj = model.model_validate(data)  # raises with a precise field path on any mismatch
    if folder == "error":
        assert obj.error.code == base.upper(), f"{rel}: file name and error code disagree"
    if folder == "event":
        assert obj.event_type == base.replace("_", ".", 1), f"{rel}: file name and event_type disagree"
        assert obj.payload.get("stream_session_id", obj.stream_session_id) == obj.stream_session_id
    if folder == "snapshot":
        assert (obj.market is None) == (obj.my_position is None), f"{rel}: my_position must accompany market"
        if obj.market is not None:
            assert obj.my_position.market_id == obj.market.market_id
            assert obj.market.stream_session_id == obj.stream.stream_session_id == obj.wallet.stream_session_id
        if base in BANNER_EXPECTATION:
            assert obj.my_position.result == BANNER_EXPECTATION[base], f"{rel}: banner/result mismatch"


def test_wager_request_conflict_hashes_differently_under_same_key():
    a, b = _load("wager/request.json"), _load("wager/request_conflict.json")
    assert a["operation_id"] == b["operation_id"]
    ra, rb = WagerRequest.model_validate(a), WagerRequest.model_validate(b)
    assert hash_request("WAGER", ra.model_dump(mode="json")) != hash_request("WAGER", rb.model_dump(mode="json"))


def test_replayed_receipt_matches_accepted_except_flag():
    accepted, replayed = _load("wager/receipt_accepted.json"), _load("wager/receipt_replayed.json")
    assert accepted["replayed"] is False and replayed["replayed"] is True
    assert {**replayed, "replayed": False} == accepted


def test_enroll_request_invite_code_format_is_normalizable():
    assert normalize_invite_code(_load("enroll/request.json")["invite_code"]) is not None


def test_settlement_worked_example_matches_backend_algorithm():
    data = _load("domain/settlement_worked_example.json")
    assert data["fee_minor"] == 0 and data["settlement_algorithm"] == "PARIMUTUEL_FLOOR_REMAINDER_V1"
    stakes = [StakeLine(w["wager_id"], w["side"], w["amount_minor"]) for w in data["wagers"]]
    payouts = compute_payouts(stakes, data["winning_side"])
    expected = {p["wager_id"]: p["final_payout_minor"] for p in data["expected"]["payouts"]}
    assert payouts == expected
    total = sum(s.amount_minor for s in stakes)
    winning = sum(s.amount_minor for s in stakes if s.side == data["winning_side"])
    for p in data["expected"]["payouts"]:
        stake = next(s.amount_minor for s in stakes if s.wager_id == p["wager_id"])
        assert p["initial_payout_minor"] == stake * total // winning
        assert p["remainder_numerator"] == (stake * total) % winning
        assert p["net_profit_minor"] == p["final_payout_minor"] - stake
    assert data["expected"]["final_payout_sum_minor"] == sum(payouts.values()) == total
    assert all(lp["wager_id"] not in payouts for lp in data["expected"]["losing_payouts"])


def test_sequence_reorder_duplicate_is_consistent_with_version_rule():
    data = _load("event/sequence_reorder_duplicate.json")
    applied, highest, final = [], data["initial_market_aggregate_version"], None
    for raw in data["delivered"]:
        event = DomainEvent.model_validate(raw)
        if event.aggregate_version > highest:
            highest = event.aggregate_version
            applied.append(event.event_id)
            final = event.payload
    flags = data["expected_applied"]  # one boolean per delivered event
    assert len(flags) == len(data["delivered"])
    assert applied == [e["event_id"] for e, flag in zip(data["delivered"], flags) if flag]
    assert final == data["expected_final_market"]
