"""§9.19 generic AI markets (GENERIC_BINARY_V1, D37) and the D39 35 s close floor, against the real SQLite engine."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from starlette.testclient import TestClient

from fazetime_api import db as dbmod
from fazetime_api import timeutil
from fazetime_api.ids import new_id
from fazetime_api.main import create_app
from fazetime_api.schemas import PublicMarket

from .conftest import Harness, make_settings, op
from .test_ai import _err, _status, auto_aw, aw  # noqa: F401  (aw and auto_aw are fixtures)

YES_P = "YES if the level in progress when betting opened ends with a visible result showing the streamer clears it."
NO_P = "NO if it ends with a visible result showing the streamer does not."
SUCCESS_CUE = "Gold LEVEL COMPLETE banner with a points tally"
FAILURE_CUE = "Red TRY AGAIN banner over the board"
QUESTIONS = {"EPISODE_OUTCOME": "Will the streamer clear this level?",
             "END_VALUE_AT_LEAST": "Will score be at least 25,000 when this level ends?",
             "SAY_PHRASE": "Will \"let's go\" be heard on stream before this level ends?",
             "DURATION_OVER": "Will this level last longer than 1:35?"}
PARAMS = {"EPISODE_OUTCOME": {"win_verb": "clear"}, "END_VALUE_AT_LEAST": {"label": "score", "threshold": 25000},
          "SAY_PHRASE": {"phrase": "let's go"}, "DURATION_OVER": {"duration_s": 95}}
# Strings that only a generic object carries; none may reach a viewer payload (§9.19 item 6).
GENERIC_MARKERS = ('"generic"', "gen-1", "spec_version", "episode_start_media_ms", "success_cue", "failure_cue",
                   "win_verb", SUCCESS_CUE, FAILURE_CUE, "GENERIC_BINARY_V1", "gen:")


def spec(kind: str = "EPISODE_OUTCOME", start_ms: int = 1000, **kw) -> dict:
    return {"spec_version": "gen-1", "kind": kind, "unit": "level", "params": PARAMS[kind],
            "episode_start_media_ms": start_ms, "success_cue": SUCCESS_CUE, "failure_cue": FAILURE_CUE, **kw}


def gen_candidate(aw, refs: list[str] | None = None, kind: str = "EPISODE_OUTCOME", start_ms: int = 1000,
                  **kw) -> dict:
    """A worker-rendered GENERIC_BINARY_V1 candidate (§9.19 item 1): Yes/No labels, 35 s window, 300 s horizon."""
    base = aw.candidate(refs if refs is not None else [aw.transcript("okay level five, here we go")],
                        template_id="GENERIC_BINARY_V1", episode_fingerprint=f"gen:{aw.ep}:{start_ms}:{kind.lower()}",
                        question=QUESTIONS[kind], yes={"label": "Yes", "predicate": YES_P},
                        no={"label": "No", "predicate": NO_P}, subjects=[], announced_at_media_ms=start_ms,
                        suggested_close_in_s=35, suggested_resolve_in_s=335,
                        cancellation_conditions=["The level is abandoned or restarted"],
                        rationale="A new level just started.", generic=spec(kind, start_ms))
    return {**base, **kw}


def worker_view(aw) -> dict | None:
    r = aw.h.client.get(f"/v1/worker/market?stream_id={aw.sid}", headers=aw.wh)
    assert r.status_code == 200, r.text
    return r.json()["market"]


def generic_evaluating_market(aw) -> dict:
    aw.set_mode("APPROVAL")
    body = _status(aw.propose(body=gen_candidate(aw)), 201, "PENDING")
    a = aw.approve(body["id"], close_in_s=35)
    assert a.status_code == 200, a.text
    m = a.json()["market"]
    assert aw.h.wager(aw.alice, m, "YES", 500).status_code == 201
    assert aw.h.wager(aw.bob, m, "NO", 500).status_code == 201
    aw.h.clock.set(m["close_at_utc"])
    aw.beat()
    aw.h.sweep()
    row = aw.market(m["market_id"])
    assert row["state"] == "EVALUATING", row
    return row


# ---- acceptance and approval --------------------------------------------------------------------------------
def test_generic_candidate_pending_then_approval_opens_yes_no_market(aw):
    aw.set_mode("APPROVAL")
    frame = aw.frame(aw.media)
    cand = gen_candidate(aw, [aw.transcript("okay level five, here we go"), frame])
    body = _status(aw.propose(body=cand), 201, "PENDING")
    assert (body["close_in_s"], body["resolve_in_s"]) == (35, 335)
    listed = aw.candidates()[0]  # §9.19 item 6: operator list carries template_id and the parsed generic object
    assert listed["id"] == body["id"] and listed["template_id"] == "GENERIC_BINARY_V1"
    assert listed["generic"] == cand["generic"] and listed["subjects"] == []
    assert listed["episode_fingerprint"] == cand["episode_fingerprint"]
    with aw.h.svc.db.read() as conn:
        stored = conn.execute("SELECT template_id, generic_json FROM ai_candidates WHERE cnd_id = ?",
                              (body["id"],)).fetchone()
    assert stored["template_id"] == "GENERIC_BINARY_V1" and json.loads(stored["generic_json"]) == cand["generic"]
    aw.tick(10)
    r = aw.approve(body["id"], close_in_s=35)  # §9.19 item 5: the console sends the clamped close_in_s
    assert r.status_code == 200, r.text
    market = r.json()["market"]
    assert market["origin"] == "AI_APPROVED" and market["state"] == "OPEN"
    assert (market["question"], market["yes_label"], market["no_label"]) == (QUESTIONS["EPISODE_OUTCOME"], "Yes", "No")
    assert timeutil.parse(market["close_at_utc"]) == aw.h.clock.now() + timedelta(seconds=35)
    assert timeutil.parse(market["resolve_by_utc"]) == aw.h.clock.now() + timedelta(seconds=35 + 335)
    assert r.json()["candidate"]["generic"] == cand["generic"]
    public = PublicMarket.model_validate(aw.h.snapshot(aw.alice)["market"]).model_dump()
    assert public["criteria"] == {"YES": YES_P, "NO": NO_P}  # criteria come from the rendered predicates
    assert public["opening_evidence_ids"] == [frame]
    view = worker_view(aw)
    assert view["market_id"] == market["market_id"]
    assert view["template_id"] == "GENERIC_BINARY_V1" and view["generic"] == cand["generic"]


@pytest.mark.parametrize("kind", list(PARAMS))
def test_each_generic_kind_reaches_pending(aw, kind):
    aw.set_mode("APPROVAL")
    cand = gen_candidate(aw, kind=kind, subjects=["the streamer"])  # 0 or 1 subjects
    _status(aw.propose(body=cand), 201, "PENDING")
    assert aw.candidates()[0]["generic"] == cand["generic"]


def test_float_threshold_and_empty_cues_round_trip(aw):
    aw.set_mode("APPROVAL")
    generic = spec("END_VALUE_AT_LEAST", params={"label": "time left", "threshold": 12.5}, success_cue="",
                   failure_cue="")
    _status(aw.propose(body=gen_candidate(aw, kind="END_VALUE_AT_LEAST", generic=generic)), 201, "PENDING")
    assert aw.candidates()[0]["generic"] == generic


def test_generic_automatic_opens_immediately(auto_aw):
    aw = auto_aw
    assert aw.set_mode("AUTOMATIC").status_code == 200
    cand = gen_candidate(aw)
    body = _status(aw.propose(body=cand), 201, "OPENED")
    market = aw.h.snapshot(aw.alice)["market"]
    assert market["market_id"] == body["market_id"] and market["origin"] == "AI_AUTOMATIC"
    assert (market["yes_label"], market["no_label"]) == ("Yes", "No")
    assert timeutil.parse(market["close_at_utc"]) - aw.h.clock.now() == timedelta(seconds=35)
    view = worker_view(aw)
    assert view["template_id"] == "GENERIC_BINARY_V1" and view["generic"] == cand["generic"]


def test_worker_view_template_fields_are_null_for_fixture_markets(aw):
    aw.h.open_market(aw.operator)
    view = worker_view(aw)
    assert view["origin"] == "OPERATOR_FIXTURE" and view["template_id"] is None and view["generic"] is None


# ---- schema (422, not recorded) -----------------------------------------------------------------------------
def _without(d: dict, key: str) -> dict:
    return {k: v for k, v in d.items() if k != key}


BAD_GENERIC = [
    {**spec(), "spec_version": "gen-2"},
    {**spec(), "kind": "FREEFORM"},
    {**spec(), "unit": ""},
    {**spec(), "unit": "x" * 21},
    {**spec(), "episode_start_media_ms": -1},
    {**spec(), "episode_start_media_ms": 1.5},
    {**spec(), "success_cue": "x" * 161},
    {**spec(), "failure_cue": "x" * 161},
    {**spec(), "extra": 1},
    _without(spec(), "failure_cue"),
    _without(spec(), "params"),
    {**spec(), "params": {}},
    {**spec(), "params": {"win_verb": "lose"}},
    {**spec(), "params": {"win_verb": "win", "phrase": "rush"}},  # extra key
    {**spec(), "params": {"phrase": "rush"}},  # another kind's params
    {**spec(), "params": ["win"]},
    spec("END_VALUE_AT_LEAST", params={"label": "score"}),
    spec("END_VALUE_AT_LEAST", params={"label": "", "threshold": 5}),
    spec("END_VALUE_AT_LEAST", params={"label": "x" * 41, "threshold": 5}),
    spec("END_VALUE_AT_LEAST", params={"label": "score", "threshold": "5"}),
    spec("END_VALUE_AT_LEAST", params={"label": "score", "threshold": True}),
    spec("SAY_PHRASE", params={"phrase": "one two three four"}),
    spec("SAY_PHRASE", params={"phrase": "rush!"}),
    spec("SAY_PHRASE", params={"phrase": ""}),
    spec("SAY_PHRASE", params={"phrase": "rush  b"}),
    spec("SAY_PHRASE", params={"phrase": "'"}),
    spec("DURATION_OVER", params={"duration_s": 29}),
    spec("DURATION_OVER", params={"duration_s": 3601}),
    spec("DURATION_OVER", params={"duration_s": 95.0}),
    "EPISODE_OUTCOME",
]


def test_generic_schema_violations_are_422_and_not_recorded(aw):
    aw.set_mode("APPROVAL")
    before = aw.counts()
    bodies = [_without(gen_candidate(aw), "generic"),  # missing for GENERIC
              gen_candidate(aw, generic=None),  # null for GENERIC
              gen_candidate(aw, subjects=["A", "B", "C"]),  # schema allows at most 2 subjects
              aw.candidate([aw.transcript()], generic=spec())]  # forbidden for H2H
    bodies += [gen_candidate(aw, generic=bad) for bad in BAD_GENERIC]
    for body in bodies:
        r = aw.propose(body=body)
        assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_FAILED", (body.get("generic"), r.text)
    after = aw.counts()
    assert (after["ai_candidates"], after["inference_traces"]) == (before["ai_candidates"], before["inference_traces"])
    _status(aw.propose(body=gen_candidate(aw)), 201, "PENDING")  # nothing above was recorded or burned


# ---- validation (recorded, 201 REJECTED) --------------------------------------------------------------------
@pytest.mark.parametrize("change", [
    {"no": {"label": "No", "predicate": YES_P}},  # equal predicates
    {"no": {"label": "No", "predicate": YES_P.upper()}},  # equal, case-insensitively
    {"no": {"label": "Yes", "predicate": NO_P}},  # equal labels
    {"no": {"label": "YES", "predicate": NO_P}},  # equal labels, case-insensitively
    {"yes": {"label": "!!", "predicate": YES_P}},  # a label with no content
    {"episode_fingerprint": "h2h:streamer|board:level-5"},  # does not start with gen:
    {"episode_fingerprint": "level:{ep}:1000:episode_outcome"},  # does not start with gen:
    {"episode_fingerprint": "gen:{ep}:1000:say_phrase"},  # does not end with the kind
    {"episode_fingerprint": "gen:{ep}:1000"},  # no kind at all
    {"subjects": ["FaZeGavin", "FaZeNeville"]},  # GENERIC allows at most 1 subject
])
def test_generic_bad_terms_are_unpaired_sides(aw, change):
    aw.set_mode("APPROVAL")
    change = {k: v.format(ep=aw.ep) if isinstance(v, str) else v for k, v in change.items()}
    before = aw.counts()["ai_candidates"]
    _status(aw.propose(body=gen_candidate(aw, **change)), 201, "REJECTED", "UNPAIRED_SIDES")
    assert aw.counts()["ai_candidates"] == before + 1  # recorded (§9.17 item 5e)
    _status(aw.propose(body=gen_candidate(aw)), 201, "PENDING")  # a validation rejection does not burn the episode


def test_generic_check_keeps_contract_order(aw):
    """UNPAIRED_SIDES comes after DUPLICATE_EPISODE and before SOURCE_NOT_LIVE (§9.17 order, §9.19 item 2)."""
    aw.set_mode("APPROVAL")
    _status(aw.propose(body=gen_candidate(aw)), 201, "PENDING")
    _status(aw.propose(body=gen_candidate(aw, subjects=["A", "B"])), 201, "REJECTED", "DUPLICATE_EPISODE")
    ref = aw.transcript()
    aw.h.clock.advance(13)  # heartbeat older than 12 s -> STALE
    bad = gen_candidate(aw, [ref], kind="SAY_PHRASE", subjects=["A", "B"])
    _status(aw.propose(body=bad), 201, "REJECTED", "UNPAIRED_SIDES")
    _status(aw.propose(body=gen_candidate(aw, [ref], kind="SAY_PHRASE")), 201, "REJECTED", "SOURCE_NOT_LIVE")


def test_generic_duplicate_episode(aw):
    aw.set_mode("APPROVAL")
    first = _status(aw.propose(body=gen_candidate(aw)), 201, "PENDING")
    _status(aw.propose(body=gen_candidate(aw)), 201, "REJECTED", "DUPLICATE_EPISODE")  # new candidate_id, same episode
    upper = gen_candidate(aw, episode_fingerprint=f"GEN:{aw.ep}:1000:EPISODE_OUTCOME")
    _status(aw.propose(body=upper), 201, "REJECTED", "DUPLICATE_EPISODE")  # canonical (lowercased) fingerprint
    assert aw.reject(first["id"]).status_code == 200
    _status(aw.propose(body=gen_candidate(aw)), 201, "REJECTED", "DUPLICATE_EPISODE")  # operator rejection burns it
    _status(aw.propose(body=gen_candidate(aw, kind="SAY_PHRASE")), 201, "PENDING")  # another kind, another fingerprint


def test_generic_replay_and_conflict(aw):
    aw.set_mode("APPROVAL")
    cand = gen_candidate(aw)
    first = _status(aw.propose(body=cand), 201, "PENDING")
    again = aw.propose(body=cand)
    assert again.status_code == 200 and again.json()["replayed"] is True and again.json()["id"] == first["id"]
    changed = {**cand, "generic": {**cand["generic"], "success_cue": "something else"}}
    _err(aw.propose(body=changed), 409, "IDEMPOTENCY_CONFLICT")
    assert aw.counts()["ai_candidates"] == 1


# ---- D39 timing (§9.19 items 4 and 5) -----------------------------------------------------------------------
def test_close_floor_is_35_s(aw):
    aw.set_mode("SHADOW")
    _status(aw.propose(body=gen_candidate(aw, suggested_close_in_s=34)), 201, "REJECTED", "INSUFFICIENT_LEAD")
    r = _status(aw.propose(body=gen_candidate(aw, suggested_close_in_s=35)), 201, "SHADOW")
    assert (r["close_in_s"], r["resolve_in_s"]) == (35, 335)


def test_generic_approval_anchoring_with_35_s_window(aw):
    aw.set_mode("APPROVAL")
    received = aw.h.clock.now()
    body = _status(aw.propose(body=gen_candidate(aw)), 201, "PENDING")
    aw.tick(5.001)  # without an override, 29.999 s would remain < min_lead 30 s
    _err(aw.approve(body["id"]), 409, "MARKET_CLOSED", "INSUFFICIENT_LEAD")
    _err(aw.approve(body["id"], close_in_s=34), 409, "MARKET_CLOSED", "INSUFFICIENT_LEAD")
    r = aw.approve(body["id"], close_in_s=35)  # the console's GENERIC override: the full window from approval
    assert r.status_code == 200, r.text
    close_at = timeutil.parse(r.json()["market"]["close_at_utc"])
    assert close_at == aw.h.clock.now() + timedelta(seconds=35) and close_at > received + timedelta(seconds=35)


def test_generic_approval_without_override_stays_anchored_to_receipt(aw):
    aw.set_mode("APPROVAL")
    received = aw.h.clock.now()
    body = _status(aw.propose(body=gen_candidate(aw)), 201, "PENDING")
    aw.tick(5)  # exactly min_lead (30 s) remains
    r = aw.approve(body["id"])
    assert r.status_code == 200, r.text
    assert timeutil.parse(r.json()["market"]["close_at_utc"]) == received + timedelta(seconds=35)


# ---- lifecycle and viewer isolation -------------------------------------------------------------------------
def test_generic_market_settles_once_and_never_reaches_viewer_payloads(aw):
    m = generic_evaluating_market(aw)
    view = worker_view(aw)
    assert view["state"] == "EVALUATING" and view["generic"]["kind"] == "EPISODE_OUTCOME"
    alice_before = aw.h.available(aw.alice)
    s = _status(aw.resolve(aw.resolution(m, "YES", reason="LEVEL COMPLETE banner seen.")), 201, "PENDING_APPROVAL")
    r = aw.approve_resolution(s["id"])
    assert r.status_code == 200 and r.json()["market"]["winning_side"] == "YES", r.text
    assert aw.h.available(aw.alice) == alice_before + 1000
    assert aw.h.reconcile()["ok"] is True
    assert worker_view(aw) is None  # terminal
    payloads = []
    for actor in (aw.alice, aw.bob):
        snap = aw.h.snapshot(actor)
        PublicMarket.model_validate(snap["market"])  # strict model: no unplanned fields
        payloads.append(json.dumps(snap))
        payloads.append(aw.h.client.get("/v1/me", headers=actor.h).text)
    with aw.h.svc.db.read() as conn:
        events = [r[0] for r in conn.execute("SELECT payload_json FROM events WHERE audience IN ('PUBLIC', 'USER')")]
        traces = json.dumps([dict(r) for r in conn.execute("SELECT * FROM inference_traces")])
    assert events and any("market.settled" in e or '"SETTLED"' in e for e in events)
    payloads += events
    for text in payloads:
        leaked = [marker for marker in GENERIC_MARKERS if marker in text]
        assert not leaked, (leaked, text[:300])
    assert SUCCESS_CUE not in traces and FAILURE_CUE not in traces  # cues live on the candidate row only
    operator_text = aw.h.client.get("/v1/operator/candidates", headers=aw.operator.h).text  # positive control
    assert all(marker in operator_text for marker in GENERIC_MARKERS), "markers must be detectable where allowed"


# ---- storage backstops (migration 0006) ---------------------------------------------------------------------
def _clone(conn, cnd_id: str, **changes) -> None:
    row = dict(conn.execute("SELECT * FROM ai_candidates WHERE cnd_id = ?", (cnd_id,)).fetchone())
    row.update(cnd_id=new_id("cnd"), candidate_id=op(), status="REJECTED", reject_code="UNPAIRED_SIDES")
    row.update(changes)
    conn.execute(f"INSERT INTO ai_candidates ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})",
                 tuple(row.values()))


def test_generic_terms_are_immutable_and_tied_to_the_template(aw):
    aw.set_mode("APPROVAL")
    body = _status(aw.propose(body=gen_candidate(aw)), 201, "PENDING")
    h2h = _status(aw.propose(), 201, "PENDING")
    for sql in ("UPDATE ai_candidates SET status = 'EXPIRED', generic_json = NULL WHERE cnd_id = ?",
                "UPDATE ai_candidates SET status = 'EXPIRED', template_id = 'H2H_WINNER_V1' WHERE cnd_id = ?"):
        with aw.h.svc.db.write() as conn, pytest.raises(Exception, match="template terms are immutable"):
            conn.execute(sql, (body["id"],))
    for source, changes, match in ((body["id"], {"generic_json": None}, "required for GENERIC_BINARY_V1"),
                                   (body["id"], {"template_id": "H2H_WINNER_V1"}, "forbidden for other templates"),
                                   (h2h["id"], {"generic_json": json.dumps(spec())}, "forbidden for other templates"),
                                   (body["id"], {"generic_json": "{not json"}, "CHECK constraint")):
        with aw.h.svc.db.write() as conn, pytest.raises(Exception, match=match):
            _clone(conn, source, **changes)
    with aw.h.svc.db.write() as conn:
        _clone(conn, body["id"])  # the unchanged clone is valid, so each failure above came from its change


def test_migration_0006_upgrades_a_database_with_existing_h2h_candidates(tmp_path, clock, monkeypatch):
    """The Pi database already has 0001-0005 and H2H rows. 0006 must apply on restart and keep them readable."""
    path = str(tmp_path / "upgrade.db")
    real = dbmod._migration_files
    monkeypatch.setattr(dbmod, "_migration_files", lambda: [m for m in real() if m[0] <= 5])
    with TestClient(create_app(make_settings(path), clock)) as client:
        h = Harness(client, clock)
        operator = h.bootstrap_operator()
        h.create_stream(operator)
        ids = h.stream()
        now = timeutil.fmt(clock.now())
        with h.svc.db.write() as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(ai_candidates)")}
            assert "generic_json" not in cols
            conn.execute(
                "INSERT INTO ai_candidates (cnd_id, candidate_id, request_hash, stream_id, run_id, source_epoch,"
                " template_id, episode_fingerprint, raw_fingerprint, question, yes_label, yes_predicate, no_label,"
                " no_predicate, subjects_json, evidence_ids_json, announced_at_media_ms, suggested_close_in_s,"
                " suggested_resolve_in_s, cancellation_json, rationale, model, prompt_version, ai_mode, status,"
                " received_at_utc, expires_at_utc) VALUES (?, ?, ?, ?, ?, ?, 'H2H_WINNER_V1', 'h2h:a|b:x', 'h2h:a|b:x',"
                " 'Will A win?', 'A', 'A wins.', 'B', 'B wins.', '[\"A\",\"B\"]', '[]', 0, 90, 300, '[]', '', 'm',"
                " 'p', 'SHADOW', 'SHADOW', ?, ?)",
                (new_id("cnd"), op(), "0" * 64, ids["stream_id"], ids["run_id"], new_id("ep"), now, now))
    monkeypatch.setattr(dbmod, "_migration_files", real)
    with TestClient(create_app(make_settings(path), clock)) as client:  # restart applies 0006
        h = Harness(client, clock)
        versions = [v["version"] for v in h.svc.db.schema_versions()]
        assert versions == [m[0] for m in real()] and versions[:6] == [1, 2, 3, 4, 5, 6]  # 0006 and later apply
        r = client.get("/v1/operator/candidates", headers=operator.h)
        assert r.status_code == 200, r.text
        (legacy,) = r.json()["candidates"]
        assert legacy["template_id"] == "H2H_WINNER_V1" and legacy["generic"] is None and legacy["status"] == "SHADOW"
