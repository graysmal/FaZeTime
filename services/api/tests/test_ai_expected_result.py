"""§9.20 item 2: the optional generic.expected_result_in_s and the public expected_result_at_utc (close_at_utc plus
the estimate), against the real SQLite engine. Viewers get only the derived time, never the generic object."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from fazetime_api import ai, timeutil
from fazetime_api.ids import request_hash
from fazetime_api.schemas import OperatorMarket, PublicMarket

from .test_ai import _err, _status, auto_aw, aw  # noqa: F401  (aw and auto_aw are fixtures)
from .test_ai_generic import GENERIC_MARKERS, _clone, gen_candidate, spec, worker_view

# The viewer market shape, pinned. §9.20 adds exactly expected_result_at_utc; generic stays operator/worker-only.
PUBLIC_MARKET_KEYS = {
    "market_id", "stream_session_id", "rules_version", "aggregate_version", "state", "origin", "question",
    "yes_label", "no_label", "opened_at_utc", "close_at_utc", "resolve_by_utc", "expected_result_at_utc",
    "locked_at_utc", "terminal_at_utc", "pool", "winning_side", "void_reason", "settlement_algorithm", "criteria",
    "opening_evidence_ids", "resolution_evidence_ids", "resolution_mode", "resolution_reason",
}
VIEWER_MARKERS = (*GENERIC_MARKERS, "expected_result_in_s")


def plus(utc: str, seconds: int) -> str:
    return timeutil.fmt(timeutil.parse(utc) + timedelta(seconds=seconds))


def anchored(aw, m: dict, seconds: int) -> str:
    """Review ruling (a): max(close_at, candidate receipt + clamped candidate close_in_s + estimate)."""
    with aw.h.svc.db.read() as conn:
        c = conn.execute("SELECT received_at_utc, close_in_s FROM ai_candidates WHERE market_id = ?",
                         (m["market_id"],)).fetchone()
    worker_anchor = timeutil.parse(c["received_at_utc"]) + timedelta(seconds=int(c["close_in_s"]) + seconds)
    return timeutil.fmt(max(timeutil.parse(m["close_at_utc"]), worker_anchor))


VIEWER_ETA_STATES = ("LOCKED", "EVALUATING")  # review ruling (b): viewers see the time only after betting closes


def market_events(aw, market_id: str) -> list[tuple[str, dict]]:
    with aw.h.svc.db.read() as conn:
        rows = conn.execute("SELECT event_type, audience, payload_json FROM events WHERE aggregate_type = 'MARKET'"
                            " AND aggregate_id = ? ORDER BY event_id", (market_id,)).fetchall()
    assert rows and all(r["audience"] == "PUBLIC" for r in rows)
    return [(r["event_type"], json.loads(r["payload_json"])) for r in rows]


def stored_generic(aw, cnd_id: str) -> str:
    with aw.h.svc.db.read() as conn:
        return conn.execute("SELECT generic_json FROM ai_candidates WHERE cnd_id = ?", (cnd_id,)).fetchone()[0]


def open_generic(aw, generic: dict, **kw) -> dict:
    """APPROVAL mode: propose, then approve with the console's clamped close_in_s (§9.19 item 5)."""
    aw.set_mode("APPROVAL")
    body = _status(aw.propose(body=gen_candidate(aw, generic=generic, **kw)), 201, "PENDING")
    r = aw.approve(body["id"], close_in_s=35)
    assert r.status_code == 200, r.text
    return r.json()["market"]


def lock(aw, m: dict) -> None:
    """Two-sided pool, then the sweeper at close_at_utc (AI markets go on to EVALUATING)."""
    assert aw.h.wager(aw.alice, m, "YES", 500).status_code == 201
    assert aw.h.wager(aw.bob, m, "NO", 500).status_code == 201
    aw.h.clock.set(m["close_at_utc"])
    aw.beat()
    aw.h.sweep()


# ---- the derived time ---------------------------------------------------------------------------------------
def test_expected_result_at_in_every_market_view(aw):
    m = open_generic(aw, spec(expected_result_in_s=120))
    expected = anchored(aw, m, 120)
    assert OperatorMarket.model_validate(m).expected_result_at_utc == expected  # approve response (operator view)
    assert aw.candidates()[0]["generic"]["expected_result_in_s"] == 120  # stored inside generic (operator view)
    assert worker_view(aw)["generic"]["expected_result_in_s"] == 120  # §9.19 item 6 worker read-back
    assert PublicMarket.model_validate(aw.h.snapshot(aw.alice)["market"]).expected_result_at_utc is None  # OPEN
    lock(aw, m)
    row = aw.market(m["market_id"])
    assert row["state"] == "EVALUATING" and row["close_at_utc"] == m["close_at_utc"]
    assert aw.h.snapshot(aw.bob)["market"]["expected_result_at_utc"] == expected  # after lock: viewers see it
    health = aw.h.client.get("/v1/operator/health", headers=aw.operator.h)
    assert health.status_code == 200 and health.json()["markets"][0]["expected_result_at_utc"] == expected
    s = _status(aw.resolve(aw.resolution(row, "YES")), 201, "PENDING_APPROVAL")
    settled = aw.approve_resolution(s["id"])
    assert settled.status_code == 200 and settled.json()["market"]["expected_result_at_utc"] == expected  # operator
    final = aw.h.snapshot(aw.alice)["market"]
    assert final["state"] == "SETTLED" and final["expected_result_at_utc"] is None  # terminal: viewers no longer
    events = market_events(aw, m["market_id"])
    assert {"market.opened", "pool.updated", "market.locked", "market.evaluating",
            "market.settled"} <= {t for t, _ in events}
    for event_type, payload in events:
        want = expected if payload["state"] in VIEWER_ETA_STATES else None
        assert PublicMarket.model_validate(payload).expected_result_at_utc == want, event_type
    assert aw.h.reconcile()["ok"] is True


@pytest.mark.parametrize("delay,est", [(20, 60), (50, 10)])
def test_expected_result_at_ignores_approval_delay_and_never_precedes_close(aw, delay, est):
    """Review ruling (a): the worker estimates from its proposal, so an approval delay must not push the time later;
    when the delay exceeds the estimate the time is the close itself, never before it."""
    aw.set_mode("APPROVAL")
    body = _status(aw.propose(body=gen_candidate(aw, generic=spec(expected_result_in_s=est))), 201, "PENDING")
    with aw.h.svc.db.read() as conn:
        c = conn.execute("SELECT received_at_utc, close_in_s FROM ai_candidates WHERE cnd_id = ?",
                         (body["id"],)).fetchone()
    aw.h.clock.set(plus(c["received_at_utc"], delay))
    aw.beat()
    r = aw.approve(body["id"], close_in_s=35)
    assert r.status_code == 200, r.text
    m = r.json()["market"]
    assert m["close_at_utc"] == plus(c["received_at_utc"], delay + 35)  # 35 s counted from approval
    worker_anchor = plus(c["received_at_utc"], int(c["close_in_s"]) + est)
    assert m["expected_result_at_utc"] == max(m["close_at_utc"], worker_anchor)
    assert m["expected_result_at_utc"] < plus(m["close_at_utc"], est)  # the approval delay is not added on top


@pytest.mark.parametrize("seconds", [0, 1, 335, 900])
def test_expected_result_at_bounds(aw, seconds):
    m = open_generic(aw, spec(expected_result_in_s=seconds))
    assert m["expected_result_at_utc"] == anchored(aw, m, seconds)  # operator view
    assert aw.h.snapshot(aw.alice)["market"]["expected_result_at_utc"] is None  # OPEN: hidden from viewers
    lock(aw, m)
    assert aw.h.snapshot(aw.alice)["market"]["expected_result_at_utc"] == anchored(aw, m, seconds)


def test_automatic_market_opened_event_carries_expected_result_at(auto_aw):
    """AUTOMATIC records the candidate PENDING and opens it in the same transaction, so market.opened (built while
    the market opens) already sees the stored estimate. The final candidate row is what the one-step insert wrote."""
    aw = auto_aw
    assert aw.set_mode("AUTOMATIC").status_code == 200
    cand = gen_candidate(aw, generic=spec(expected_result_in_s=60))
    body = _status(aw.propose(body=cand), 201, "OPENED")
    (first_type, opened), *_ = market_events(aw, body["market_id"])
    assert first_type == "market.opened" and opened["state"] == "OPEN" and opened["expected_result_at_utc"] is None
    assert aw.h.snapshot(aw.alice)["market"]["expected_result_at_utc"] is None  # OPEN: hidden from viewers
    health = aw.h.client.get("/v1/operator/health", headers=aw.operator.h).json()
    assert health["markets"][0]["expected_result_at_utc"] == plus(opened["close_at_utc"], 60)  # AUTOMATIC: close+est
    with aw.h.svc.db.read() as conn:
        row = conn.execute("SELECT * FROM ai_candidates WHERE cnd_id = ?", (body["id"],)).fetchone()
        trace = conn.execute("SELECT result, code, market_id FROM inference_traces WHERE subject_id = ?",
                             (body["id"],)).fetchone()
    assert (row["status"], row["market_id"], row["reject_code"], row["ai_mode"]) == (
        "OPENED", body["market_id"], None, "AUTOMATIC")
    assert row["decided_at_utc"] == row["received_at_utc"] and row["decided_by_user_id"] is None
    assert (trace["result"], trace["code"], trace["market_id"]) == ("OPENED", None, body["market_id"])
    again = aw.propose(body=cand)
    assert again.status_code == 200 and again.json()["replayed"] is True
    assert (again.json()["status"], again.json()["market_id"]) == ("OPENED", body["market_id"])
    assert aw.counts()["markets"] == 1


@pytest.mark.parametrize("case", ["absent", "null", "h2h", "fixture"])
def test_expected_result_at_is_null_without_an_estimate(aw, case):
    if case == "fixture":
        m = aw.h.open_market(aw.operator)
    elif case == "h2h":
        m = aw.open_ai_market()
    else:  # a generic candidate with no estimate: key left out, or sent as null
        m = open_generic(aw, spec() if case == "absent" else spec(expected_result_in_s=None))
    assert "expected_result_at_utc" in m and m["expected_result_at_utc"] is None
    assert aw.h.snapshot(aw.alice)["market"]["expected_result_at_utc"] is None
    lock(aw, m)
    assert aw.h.snapshot(aw.alice)["market"]["expected_result_at_utc"] is None
    events = market_events(aw, m["market_id"])
    assert len(events) >= 4  # opened, two pool updates, locked
    assert all(payload["expected_result_at_utc"] is None for _, payload in events)


# ---- schema, idempotency and storage ------------------------------------------------------------------------
@pytest.mark.parametrize("bad", [-1, 901, 1.5, 60.0, "60", True, [60], {"s": 60}])
def test_bad_expected_result_in_s_is_422_and_not_recorded(aw, bad):
    aw.set_mode("APPROVAL")
    body = gen_candidate(aw, generic=spec(expected_result_in_s=bad))
    before = aw.counts()
    _err(aw.propose(body=body), 422, "VALIDATION_FAILED")
    assert aw.counts() == before
    _status(aw.propose(body=gen_candidate(aw)), 201, "PENDING")  # nothing above was recorded or burned


def test_request_hash_is_unchanged_for_bodies_without_the_estimate(aw):
    """Rows stored before §9.20 hashed generic without expected_result_in_s (the base GenericSpec had exactly the
    other seven fields). Absent and null must hash as before so a worker retry replays instead of conflicting."""
    body = {"schema_version": 1, "stream_id": aw.sid, "source_epoch": aw.ep, "candidate": gen_candidate(aw)}
    req = ai.ProposalRequest.model_validate(body)
    legacy = req.model_dump(mode="json")
    del legacy["candidate"]["generic"]["expected_result_in_s"]  # the pre-§9.20 dump
    assert ai._proposal_hash(req) == request_hash(legacy)
    explicit_null = json.loads(json.dumps(body))
    explicit_null["candidate"]["generic"]["expected_result_in_s"] = None
    assert ai._proposal_hash(ai.ProposalRequest.model_validate(explicit_null)) == request_hash(legacy)
    with_value = json.loads(json.dumps(body))
    with_value["candidate"]["generic"]["expected_result_in_s"] = 120
    assert ai._proposal_hash(ai.ProposalRequest.model_validate(with_value)) != request_hash(legacy)
    h2h = {**body, "candidate": aw.candidate([aw.transcript()])}  # H2H: generic still left out entirely
    h2h_req = ai.ProposalRequest.model_validate(h2h)
    h2h_legacy = h2h_req.model_dump(mode="json")
    del h2h_legacy["candidate"]["generic"]
    assert ai._proposal_hash(h2h_req) == request_hash(h2h_legacy)


def test_estimate_storage_replay_and_conflict(aw):
    aw.set_mode("APPROVAL")
    cand = gen_candidate(aw)  # no estimate
    first = _status(aw.propose(body=cand), 201, "PENDING")
    stored = stored_generic(aw, first["id"])
    assert "expected_result_in_s" not in stored and json.loads(stored) == cand["generic"]  # pre-§9.20 bytes
    explicit_null = {**cand, "generic": {**cand["generic"], "expected_result_in_s": None}}
    again = aw.propose(body=explicit_null)
    assert again.status_code == 200 and again.json()["replayed"] is True and again.json()["id"] == first["id"]
    _err(aw.propose(body={**cand, "generic": {**cand["generic"], "expected_result_in_s": 120}}), 409,
         "IDEMPOTENCY_CONFLICT")
    second_cand = gen_candidate(aw, start_ms=5000, generic=spec(start_ms=5000, expected_result_in_s=120))
    second = _status(aw.propose(body=second_cand), 201, "PENDING")
    assert json.loads(stored_generic(aw, second["id"])) == second_cand["generic"]
    without = {**second_cand, "generic": spec(start_ms=5000)}
    _err(aw.propose(body=without), 409, "IDEMPOTENCY_CONFLICT")
    assert aw.counts()["ai_candidates"] == 2


def test_worst_case_generic_object_with_estimate_fits_the_0006_json_check(aw):
    """Every string at its maximum length in characters that JSON-escape to six, plus the largest estimate, still
    fits migration 0006's 4096-character check, and that check still applies to generic_json."""
    aw.set_mode("APPROVAL")
    worst, start_ms = "\u0001", 9_007_199_254_740_991
    generic = spec("END_VALUE_AT_LEAST", start_ms=start_ms, unit=worst * 20,
                   params={"label": worst * 40, "threshold": -1.2345678901234567e-300},
                   success_cue=worst * 160, failure_cue=worst * 160, expected_result_in_s=900)
    body = _status(aw.propose(body=gen_candidate(aw, kind="END_VALUE_AT_LEAST", start_ms=start_ms, generic=generic)),
                   201, "PENDING")
    stored = stored_generic(aw, body["id"])
    assert len(stored) <= 4096 and json.loads(stored) == generic
    with aw.h.svc.db.write() as conn, pytest.raises(Exception, match="CHECK constraint"):
        _clone(conn, body["id"], generic_json=json.dumps({**generic, "success_cue": "x" * 4096}))


# ---- viewer isolation ---------------------------------------------------------------------------------------
def test_viewers_get_only_the_derived_time_never_the_estimate_or_generic(aw):
    assert set(PublicMarket.model_fields) == PUBLIC_MARKET_KEYS
    m = open_generic(aw, spec(expected_result_in_s=120))
    expected = anchored(aw, m, 120)
    lock(aw, m)
    payloads = []
    for actor in (aw.alice, aw.bob):
        snap = aw.h.snapshot(actor)
        assert set(snap["market"]) == PUBLIC_MARKET_KEYS and snap["market"]["expected_result_at_utc"] == expected
        payloads += [json.dumps(snap), aw.h.client.get("/v1/me", headers=actor.h).text]
    for _, payload in market_events(aw, m["market_id"]):
        want = expected if payload["state"] in VIEWER_ETA_STATES else None
        assert set(payload) == PUBLIC_MARKET_KEYS and payload["expected_result_at_utc"] == want
    with aw.h.svc.db.read() as conn:
        payloads += [r[0] for r in conn.execute("SELECT payload_json FROM events WHERE audience IN ('PUBLIC', 'USER')")]
    for text in payloads:
        leaked = [marker for marker in VIEWER_MARKERS if marker in text]
        assert not leaked, (leaked, text[:300])
    operator_text = aw.h.client.get("/v1/operator/candidates", headers=aw.operator.h).text  # positive control
    assert all(marker in operator_text for marker in VIEWER_MARKERS), "markers must be detectable where allowed"
