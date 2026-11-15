"""Offline tests for the D37 generic profile (CONTRACTS §9.19). FakeTransport only: no model calls, no network
beyond the in-process fake API on 127.0.0.1. Model answers are scripted; all media is synthetic bytes."""
from __future__ import annotations

import json
import re

import pytest

from fazetime_worker import context as cx
from fazetime_worker.api_client import ApiClient, ApiResult
from fazetime_worker.config import Config, from_env
from fazetime_worker.gemini import FakeApiError, FakeTransport, Unavailable
from fazetime_worker.generic import GenericAi, build_generic_ai
from fazetime_worker.generic import templates as tp
from fazetime_worker.generic.models import ModelPool, usage_file
from fazetime_worker.generic.observer import Observer
from fazetime_worker.generic.prompts import OBS_SCHEMA, PROP_SCHEMA, READ_SCHEMA
from fazetime_worker.generic.proposer import check_proposal
from fazetime_worker.generic.reducer import Reducer
from fazetime_worker.generic.resolver import GenericResolver, decide_visual
from fazetime_worker.pipeline import EvidenceTap
from fazetime_worker.proposer import Trace
from fazetime_worker.resolver import MarketTracker, MarketView, StaticMarketSource

from .fake_api import FakeApi

EP = "ep_" + "1" * 32
EP2 = "ep_" + "2" * 32
RUN = "run_" + "3" * 32
STREAM = "str_" + "a" * 32
MKT = "mkt_" + "4" * 32
G31, G35, GEMMA = "gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemma-4-26b-a4b-it"
UTC = "2026-11-15T06:00:00.000Z"


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def evd(seq):
    return f"evd_{seq:032x}"


def jpeg(tag) -> bytes:
    return b"\xff\xd8\xff" + str(tag).encode() + b"\xff\xd9"


def gen_cfg() -> Config:
    c = Config()
    c.ai_enabled, c.ai_profile, c.ai_min_interval_s = True, "generic", 0
    c.ai_evidence_refs = "frames+transcripts"
    return c


def obs(screen="gameplay", boundary="none", text="", outcome="none", numbers=(), unit="level", cue=""):
    return {"activity": "Peggle", "screen": screen, "episode_unit": unit, "boundary": boundary, "outcome_text": text,
            "outcome_for_streamer": outcome, "numbers": [{"label": k, "value": v} for k, v in numbers],
            "popup_text": [], "streamer_cue": cue, "notable": []}


def started(start_ms=0, unit="level") -> Reducer:
    r = Reducer(EP)
    r.apply(obs(unit=unit), start_ms, [start_ms])
    assert r.apply(obs(unit=unit), start_ms + 8000, [start_ms + 8000]) == ["EPISODE_STARTED"]
    return r


# ---- reducer --------------------------------------------------------------------------------------------------
def test_reducer_start_and_result_end():
    r = Reducer(EP)
    assert r.apply(obs("menu"), 0, [0]) == [] and r.cur is None
    assert r.apply(obs(), 8000, [5000, 8000]) == []  # one gameplay observation is not a start
    assert r.apply(obs(), 16000, [13000, 16000]) == ["EPISODE_STARTED"]
    e = r.cur
    assert (e.start_ms, e.phase, r.unit, r.activity) == (8000, "IN_PROGRESS", "level", "Peggle")
    assert r.apply(obs("result_screen", "ended", "LEVEL COMPLETE!", "success"), 60000, [57000, 60000]) == \
        ["EPISODE_ENDED"]
    assert (e.phase, e.end_ms, e.end_kind, e.end_frame_ms) == ("ENDED", 60000, "RESULT_SEEN", [57000, 60000])
    assert e.results == [(60000, "LEVEL COMPLETE!", "success")] and not r.in_progress()
    assert "ended at 60s (RESULT_SEEN)" in r.snapshot(61000)


def test_reducer_away_end_needs_two_consecutive_observations():
    r = started()
    e = r.cur
    assert r.apply(obs("menu"), 40000, [40000]) == []
    assert r.apply(obs("gameplay"), 48000, [48000]) == []  # back in play: the streak resets
    assert r.apply(obs("menu"), 56000, [56000]) == []
    assert r.apply(obs("loading"), 64000, [64000]) == ["EPISODE_ENDED"]
    assert (e.phase, e.end_ms, e.end_kind) == ("ENDED_UNKNOWN", 64000, "LEFT_GAMEPLAY")


def test_reducer_score_reset_ends_episode_and_starts_next():
    r = Reducer(EP)
    r.apply(obs(numbers=[("Score", "0")]), 0, [0])
    r.apply(obs(numbers=[("Score", "0")]), 8000, [8000])
    first = r.cur
    for t, v in ((16000, "1,200"), (24000, "5,000"), (40000, "9,000")):
        assert r.apply(obs(numbers=[("Score", v)]), t, [t]) == []
    assert r.apply(obs(numbers=[("Score", "0")]), 48000, [48000]) == ["EPISODE_ENDED", "EPISODE_STARTED"]
    assert (first.phase, first.end_ms, first.end_kind) == ("ENDED_UNKNOWN", 40000, "NEW_START")
    assert r.cur is not first and r.cur.start_ms == 48000 and r.cur.reads("score")[0][2] == 0.0
    assert r.prior_duration_ms() == 40000  # the median of earlier, ended episodes feeds the lead check


def test_epoch_change_resets_state():
    ctx = cx.ContextBuffer(clock=Clock())
    ctx.open_epoch(EP)
    obs_ = Observer(gen_cfg(), pool=None, spawn=lambda fn: fn())
    ai = GenericAi(ctx, obs_, None, None, registry=type("R", (), {"set_run": lambda self, r: None})())
    ai.step()
    ai.reducer.apply(obs(), 0, [0])
    ai.reducer.apply(obs(), 8000, [8000])
    assert ai.reducer.in_progress()
    ctx.open_epoch(EP2)
    ai.step()
    assert ai.reducer.epoch == EP2 and ai.reducer.episodes == [] and ai.observer.epoch == EP2


# ---- templates and validators -----------------------------------------------------------------------------------
def test_templates_render_contract_shapes_and_lengths():
    assert tp.render("EPISODE_OUTCOME", "level", {"win_verb": "clear"})[0] == "Will the streamer clear this level?"
    assert tp.render("END_VALUE_AT_LEAST", "round", {"label": "score", "threshold": 50000})[0] == \
        "Will score be at least 50,000 when this round ends?"
    assert tp.render("SAY_PHRASE", "round", {"phrase": "rush"})[0] == \
        'Will "rush" be heard on stream after betting closes, before this round ends?'  # coordinator ruling
    assert tp.render("DURATION_OVER", "level", {"duration_s": 125})[0] == "Will this level last longer than 2:05?"
    worst = {"EPISODE_OUTCOME": {"win_verb": "complete"}, "END_VALUE_AT_LEAST": {"label": "x" * 40, "threshold": 1.25e9},
             "SAY_PHRASE": {"phrase": "abcdefghij abcdefghij abcdefghij"}, "DURATION_OVER": {"duration_s": 3599}}
    for kind, params in worst.items():
        assert tp.validate_params(kind, params) is None
        for text in tp.render(kind, "match", params):
            assert 0 < len(text) <= 200
        q, y, n = tp.render(kind, "match", params)
        assert y.lower() != n.lower()
        assert all(len(c) <= 200 for c in tp.cancellation(kind, "match", 20, 15))
    assert tp.fingerprint(EP, 12000, "SAY_PHRASE") == f"gen:{EP}:12000:say_phrase"


@pytest.mark.parametrize("kind,params,code", [
    ("EPISODE_OUTCOME", {"win_verb": "dominate"}, "BAD_WIN_VERB"),
    ("EPISODE_OUTCOME", {"win_verb": "win", "extra": 1}, "BAD_PARAMS"),
    ("SAY_PHRASE", {"phrase": "rush b now go"}, "BAD_PHRASE"),
    ("SAY_PHRASE", {"phrase": "the"}, "BAD_PHRASE"),
    ("SAY_PHRASE", {"phrase": "rush1"}, "BAD_PHRASE"),
    ("DURATION_OVER", {"duration_s": 20}, "BAD_DURATION"),
    ("DURATION_OVER", {"duration_s": 3601}, "BAD_DURATION"),
    ("DURATION_OVER", {"duration_s": True}, "BAD_DURATION"),
    ("END_VALUE_AT_LEAST", {"label": "score", "threshold": True}, "BAD_THRESHOLD"),
    ("END_VALUE_AT_LEAST", {"label": "score", "threshold": float("nan")}, "BAD_THRESHOLD"),
    ("END_VALUE_AT_LEAST", {"label": "x" * 41, "threshold": 5}, "BAD_LABEL"),
    ("NOT_A_KIND", {}, "BAD_KIND"),
])
def test_params_validator_rejections(kind, params, code):
    assert tp.validate_params(kind, params) == code


def prop(**kw):
    d = {"decision": "PROPOSE", "template": "EPISODE_OUTCOME", "win_verb": "win", "number_label": "", "threshold": None,
         "phrase": "", "duration_s": None, "success_cue": "", "failure_cue": "", "p_yes": 0.5,
         "seconds_to_outcome": 120, "evidence": ["F1"], "reason": "r"}
    d.update(kw)
    return d


def test_proposal_validator_rejections():
    r = started(0)  # episode from 0; the latest observation at 8 s
    r.apply(obs(numbers=[("score", "100")]), 16000, [16000])
    now, h = 20000, {"F1", "T1"}
    check = lambda p, red=r: check_proposal(p, red, now, 35, h, min_lead_s=30, horizon_s=300)  # noqa: E731
    assert check(prop()) is None
    assert check(prop(decision="ABSTAIN")) == "ABSTAINED"
    assert check(prop(p_yes=0.9)) == "UNBALANCED" and check(prop(p_yes=0.1)) == "UNBALANCED"
    assert check(prop(seconds_to_outcome=40)) == "INSUFFICIENT_LEAD"  # < 35 s window + 30 s lead
    assert check(prop(seconds_to_outcome=400)) == "HORIZON_TOO_LONG"
    assert check(prop(evidence=["F9"])) == "BAD_EVIDENCE" and check(prop(evidence=[])) == "BAD_EVIDENCE"
    r.last_template = "EPISODE_OUTCOME"
    assert check(prop()) == "REPEAT_TEMPLATE"
    r.last_template = None
    assert check(prop(template="END_VALUE_AT_LEAST", number_label="score", threshold=500)) == "UNTRACKED_NUMBER"
    r.apply(obs(numbers=[("score", "300")]), 18000, [18000])
    assert check(prop(template="END_VALUE_AT_LEAST", number_label="score", threshold=500)) is None
    assert check(prop(template="SAY_PHRASE", phrase="")) == "BAD_PHRASE"
    assert check(prop(template="SAY_PHRASE", phrase="Rush!")) is None
    assert check(prop(template="DURATION_OVER", duration_s=60)) == "BAD_DURATION"  # 60 < 20 elapsed + 35 + 20
    assert check(prop(template="DURATION_OVER", duration_s=120)) is None
    # once the stream has history it decides the lead, not the model's estimate
    h2 = Reducer(EP)
    h2.apply(obs(), 0, [0])
    h2.apply(obs(), 8000, [0])
    h2.apply(obs("result_screen", "ended"), 150_000, [150_000])
    h2.apply(obs(), 160_000, [160_000])
    h2.apply(obs(), 168_000, [160_000])
    assert h2.cur.start_ms == 160_000 and h2.prior_duration_ms() == 150_000
    assert check_proposal(prop(seconds_to_outcome=200), h2, 250_000, 35, h, min_lead_s=30, horizon_s=300) == \
        "INSUFFICIENT_LEAD"  # history: 60 s left < 35 + 30, whatever the model estimates
    assert check_proposal(prop(seconds_to_outcome=40), h2, 170_000, 35, h, min_lead_s=30, horizon_s=300) is None


# ---- decide rules -------------------------------------------------------------------------------------------------
def read(text="", outcome="unclear", value="", contradictions=()):
    return {"result_text": text, "result_frames": ["F1"], "outcome_for_streamer": outcome, "value_text": value,
            "value_frame": "F1", "contradictions": list(contradictions)}


def test_decide_visual_rules():
    dv = lambda kind, reads, params=None, cue="": decide_visual(kind, params or {}, cue, "", reads)  # noqa: E731
    d, why, sup, _ = dv("EPISODE_OUTCOME", [read("LEVEL COMPLETE!", "success"), read("Level Complete", "success")])
    assert (d, sup) == ("YES", {"YES": True, "NO": False})
    d, _, sup, _ = dv("EPISODE_OUTCOME", [read("GAME OVER", "failure"), read("game over", "failure")])
    assert (d, sup) == ("NO", {"YES": False, "NO": True})
    d, _, sup, c = dv("EPISODE_OUTCOME", [read("VICTORY", "success"), read("DEFEAT", "failure")])
    assert (d, sup) == ("UNRESOLVABLE", {"YES": True, "NO": True}) and c  # disagreement voids
    assert dv("EPISODE_OUTCOME", [read("AMAZING!", "success"), read("AMAZING!", "success")])[0] == "WAIT"  # lexicon miss
    assert dv("EPISODE_OUTCOME", [read("EXTREME FEVER", "success"), read("FEVER", "success")],
              cue="the Extreme Fever banner")[0] == "YES"  # a word frozen in the market's success cue
    assert dv("EPISODE_OUTCOME", [read("WIN", "success"), None])[0] == "WAIT"
    assert dv("EPISODE_OUTCOME", [read("WIN", "success"), read("WIN", "success", contradictions=["replay"])])[0] == \
        "UNRESOLVABLE"
    p = {"label": "score", "threshold": 50000}
    assert dv("END_VALUE_AT_LEAST", [read(value="61,250"), read(value="61250")], p)[:3:2] == \
        ("YES", {"YES": True, "NO": False})
    assert dv("END_VALUE_AT_LEAST", [read(value="12,000"), read(value="12000")], p)[0] == "NO"
    assert dv("END_VALUE_AT_LEAST", [read(value="50,000"), read(value="50000")], p)[0] == "UNRESOLVABLE"  # one unit
    assert dv("END_VALUE_AT_LEAST", [read(value="49,999"), read(value="49999")], p)[0] == "UNRESOLVABLE"
    assert dv("END_VALUE_AT_LEAST", [read(value="61,250"), read(value="48,000")], p)[0] == "UNRESOLVABLE"
    assert dv("END_VALUE_AT_LEAST", [read(value="?"), read(value="61,250")], p)[0] == "WAIT"


class RecApi:
    def __init__(self):
        self.posts = []

    def get_json(self, path, bearer=None):
        return ApiResult(404, {"error": {"code": "NOT_FOUND"}})

    def post_json(self, path, body):
        self.posts.append((path, body))
        if path.endswith("/resolutions"):
            d = body["resolution"]["decision"]
            return ApiResult(201, {"resolution_id": body["resolution"]["resolution_id"],
                                   "status": "RECORDED" if d == "WAIT" else "PENDING_APPROVAL", "reason": None})
        return ApiResult(201, {"candidate_id": body["candidate"]["candidate_id"], "status": "PENDING",
                               "reject_code": None, "market_id": None})


@pytest.fixture
def renv():
    clock = Clock()
    cfg = gen_cfg()
    ctx = cx.ContextBuffer(clock=clock)
    ctx.open_epoch(EP)
    ctx.set_run(RUN)
    transports = {m: FakeTransport() for m in (G31, G35)}
    pool = ModelPool(cfg, None, transport_factory=lambda m: transports[m], clock=clock)
    api, source = RecApi(), StaticMarketSource()
    tracker = MarketTracker(source, clock=clock)
    res = GenericResolver(cfg, ctx, pool, api, STREAM, tracker, Trace(None), clock=clock, sleep=lambda s: None)

    class E:
        seq = 0
    e = E()
    e.__dict__.update(clock=clock, cfg=cfg, ctx=ctx, transports=transports, api=api, source=source, tracker=tracker,
                      res=res, red=Reducer(EP))

    def frame(ms):
        e.seq += 1
        ctx.add_frame(EP, e.seq, ms, jpeg(e.seq), 854, 480, UTC)
        ctx.on_evidence_ack(EP, e.seq, evd(e.seq))
        return e.seq

    def say(start, text="", end=None, ack=True):
        e.seq += 1
        ctx.add_transcript(EP, e.seq, start, end if end is not None else start + 4000, text, [], UTC)
        if ack:
            ctx.on_observations_ack(EP, [e.seq])
        return e.seq

    def market(kind, params, start_ms, lock_ms, state="EVALUATING"):
        g = {"spec_version": "gen-1", "kind": kind, "unit": "level", "params": params,
             "episode_start_media_ms": start_ms, "success_cue": "", "failure_cue": ""}
        m = MarketView(MKT, 1, state, "q", "Yes", "No", lock_source_epoch=EP, lock_media_ms=lock_ms,
                       resolve_by_utc="2099-01-01T00:00:00.000Z", origin="AI_APPROVED",
                       template_id="GENERIC_BINARY_V1", generic=g)
        source.set(m)
        tracker.poke()
        return m

    def episode(start_ms, end_ms=None, end_kind="RESULT_SEEN", last_t=None):
        ep = e.red._new_episode(start_ms, {}, start_ms)
        if end_ms is not None:
            ep.phase, ep.end_ms, ep.end_kind = ("ENDED" if end_kind == "RESULT_SEEN" else "ENDED_UNKNOWN"), end_ms, end_kind
        e.red.last_t_ms = last_t if last_t is not None else (end_ms or start_ms)
        return ep

    def tick():
        e.tracker.poke()
        return e.res.tick(ctx.view(), e.red)
    e.frame, e.say, e.market, e.episode, e.tick = frame, say, market, episode, tick
    return e


def posted(env):
    return [b["resolution"] for p, b in env.api.posts if p.endswith("/resolutions")]


@pytest.mark.parametrize("end_s,kind,want", [(130, "RESULT_SEEN", "UNRESOLVABLE"), (150, "RESULT_SEEN", "YES"),
                                             (95, "RESULT_SEEN", "NO"), (150, "LEFT_GAMEPLAY", "UNRESOLVABLE")])
def test_duration_band_and_end_kind(renv, end_s, kind, want):
    for ms in range(40_000, end_s * 1000 + 4001, 2000):
        renv.frame(ms)
    renv.episode(0, end_s * 1000, kind)
    renv.market("DURATION_OVER", {"duration_s": 120}, 0, 40_000)
    assert renv.tick().startswith(f"POSTED:{want}:")
    r = posted(renv)[0]
    assert r["decision"] == want and r["model"] == "worker-code" and r["prompt_version"] == "generic-resolver-1.0"
    assert r["predicate_support"] == {"YES": want == "YES", "NO": want == "NO"}
    assert r["media_interval"]["start_ms"] >= 40_000 and renv.transports[G31].calls == []  # code, no model call


def test_duration_still_running_past_line_is_yes(renv):
    for ms in range(40_000, 140_001, 2000):
        renv.frame(ms)
    renv.episode(0, None, last_t=130_000)
    renv.market("DURATION_OVER", {"duration_s": 120}, 0, 40_000)
    assert renv.tick() == "WAIT_LOCAL"  # 130 s is inside the 120 s + 15 s band
    renv.red.last_t_ms = 136_000
    assert renv.tick() == "POSTED:YES:PENDING_APPROVAL"


def speech_setup(env, lock=50_000, upto=100_000, phrase_at=None, text="we go rush now"):
    seqs = {}
    for start in range(30_000, upto, 3000):
        seqs[start] = env.say(start, text if start == phrase_at else "nice shot there")
    for ms in range(30_000, upto + 1, 2000):
        env.frame(ms)
    return seqs


def test_speech_phrase_inside_margin_is_unresolvable(renv):
    speech_setup(renv, phrase_at=60_000)  # lock 50 s + M 20 s: the hit window starts at 60 s
    renv.episode(0, None, last_t=100_000)
    renv.market("SAY_PHRASE", {"phrase": "rush"}, 0, 50_000)
    assert renv.tick() == "POSTED:UNRESOLVABLE:PENDING_APPROVAL"
    r = posted(renv)[0]
    assert "PHRASE_IN_MARGIN" in r["reason"] and r["media_interval"]["start_ms"] >= 50_000
    assert f"{EP}:" in " ".join(r["evidence_ids"])  # the transcript observation itself is cited


def test_speech_window_straddling_lock_voids_and_cites_only_post_lock(renv):
    speech_setup(renv, phrase_at=48_000)  # window 48-52 s straddles the lock at 50 s
    renv.episode(0, None, last_t=100_000)
    renv.market("SAY_PHRASE", {"phrase": "rush"}, 0, 50_000)
    assert renv.tick() == "POSTED:UNRESOLVABLE:PENDING_APPROVAL"
    r = posted(renv)[0]
    assert all(e.startswith("evd_") for e in r["evidence_ids"]) and r["media_interval"]["start_ms"] >= 50_000


def test_speech_yes_after_margin_and_no_with_full_coverage(renv):
    seqs = speech_setup(renv, phrase_at=81_000)
    renv.episode(0, None, last_t=84_000)
    renv.market("SAY_PHRASE", {"phrase": "rush"}, 0, 50_000)
    assert renv.tick() == "WAIT_LOCAL"  # no observation yet confirms the episode was running at 85 s
    renv.red.last_t_ms = 88_000
    assert renv.tick() == "POSTED:YES:PENDING_APPROVAL"
    r = posted(renv)[0]
    assert r["predicate_support"] == {"YES": True, "NO": False}
    assert r["evidence_ids"][0] == f"{EP}:{seqs[81_000]}" and r["media_interval"]["start_ms"] == 81_000


def test_speech_no_needs_coverage_and_gap_voids(renv):
    speech_setup(renv, upto=100_000)
    renv.episode(0, 95_000)
    renv.market("SAY_PHRASE", {"phrase": "rush"}, 0, 50_000)
    assert renv.tick() == "POSTED:NO:PENDING_APPROVAL"
    assert posted(renv)[0]["predicate_support"] == {"YES": False, "NO": True}


def test_speech_transcript_hole_blocks_no(renv):
    for start in list(range(30_000, 60_000, 3000)) + list(range(66_000, 100_000, 3000)):  # 6 s hole after 61 s
        renv.say(start, "nice shot")
    for ms in range(30_000, 100_001, 2000):
        renv.frame(ms)
    renv.episode(0, 95_000)
    renv.market("SAY_PHRASE", {"phrase": "rush"}, 0, 50_000)
    assert renv.tick() == "POSTED:UNRESOLVABLE:PENDING_APPROVAL"
    assert "COVERAGE_GAP" in posted(renv)[0]["reason"]


def test_episode_end_inside_margin_voids_every_kind(renv):
    for ms in range(40_000, 80_001, 2000):
        renv.frame(ms)
    renv.episode(0, 65_000)  # ended at 65 s; lock 50 s + 20 s margin
    renv.market("EPISODE_OUTCOME", {"win_verb": "win"}, 0, 50_000)
    assert renv.tick() == "POSTED:UNRESOLVABLE:PENDING_APPROVAL"
    assert "RESULT_BEFORE_LOCK_MARGIN" in posted(renv)[0]["reason"] and renv.transports[G35].calls == []


def test_visual_late_reply_is_dropped(renv):
    for ms in range(40_000, 130_001, 2000):
        renv.frame(ms)
    renv.episode(0, 120_000)
    m = renv.market("EPISODE_OUTCOME", {"win_verb": "win"}, 0, 50_000)

    def late(kw):
        m.state = "VOID"  # the operator voided it while the reads were in flight
        return read("YOU WIN", "success")
    renv.transports[G35].push(late)
    renv.transports[G31].push(read("YOU WIN", "success"))
    assert renv.tick() == "LATE_DROPPED" and posted(renv) == []


def test_reader_falls_back_to_other_model_on_transient_error(renv):
    """D37 end-to-end regression: reader B's model (3.1) answered 504; the other reader model reads B's frames."""
    for ms in range(40_000, 130_001, 2000):
        renv.frame(ms)
    renv.episode(0, 120_000)
    renv.market("EPISODE_OUTCOME", {"win_verb": "clear"}, 0, 50_000)
    renv.transports[G35].push(read("LEVEL COMPLETE!", "success"), read("LEVEL COMPLETE!", "success"))
    renv.transports[G31].push(FakeApiError(504, "DEADLINE_EXCEEDED"))
    renv.tick()
    out = posted(renv)
    assert len(out) == 1 and out[0]["decision"] == "YES"
    assert out[0]["predicate_support"] == {"YES": True, "NO": False}
    assert len(renv.transports[G35].calls) == 2 and len(renv.transports[G31].calls) == 1


def test_non_generic_or_fixture_market_is_ignored(renv):
    renv.episode(0, 120_000)
    m = renv.market("EPISODE_OUTCOME", {"win_verb": "win"}, 0, 50_000)
    m.origin = "OPERATOR_FIXTURE"
    assert renv.tick() == "NOT_GENERIC_AI"
    m.origin, m.template_id = "AI_APPROVED", "H2H_WINNER_V1"
    assert renv.tick() == "NOT_GENERIC_AI"


# ---- per-model gates, Gemma quirks, observer cadence ---------------------------------------------------------------
def test_per_model_gates_are_independent_and_persisted(tmp_path):
    cfg = gen_cfg()
    cfg.ai_daily_budget, cfg.ai_resolver_reserve = 2, 0.0
    cfg.ai_observer_models = (GEMMA, G31)
    t = {m: FakeTransport([{"ok": 1}] * 5) for m in (GEMMA, G31, G35)}
    pool = ModelPool(cfg, tmp_path, transport_factory=lambda m: t[m])
    for _ in range(2):
        pool.call(G31, role="proposer", text="x", images=[], schema={})
    with pytest.raises(Unavailable) as e:
        pool.call(G31, role="resolver", text="x", images=[], schema={})
    assert e.value.reason == "BUDGET_EXHAUSTED"
    assert pool.ready(G35) and pool.ready(GEMMA)  # other models keep their own quota
    pool.call(G35, role="proposer", text="x", images=[], schema={})
    assert json.loads(usage_file(tmp_path, G31).read_text())["requests"] == 2
    assert json.loads(usage_file(tmp_path, G35).read_text())["requests"] == 1
    assert not usage_file(tmp_path, GEMMA).exists()
    again = ModelPool(cfg, tmp_path, transport_factory=lambda m: t[m])  # a restart keeps the counters
    assert not again.ready(G31) and again.gate(G35).used_today == 1
    (tmp_path / "AI_STOP").write_text("")
    assert all(again.gate(m).state() == "STOPPED" for m in (GEMMA, G31, G35)) and again.stopped()


def test_stop_switch_idles_the_whole_generic_runtime(tmp_path, monkeypatch):
    clock = Clock()
    ctx = cx.ContextBuffer(clock=clock)
    ctx.open_epoch(EP)
    ai, pool, _ = build_generic_ai(gen_cfg(), ctx, RecApi(), STREAM, tmp_path, clock=clock, sleep=lambda s: None,
                                   transport_factory=lambda m: FakeTransport(), spawn=lambda fn: fn(),
                                   market_source=StaticMarketSource())
    ctx.add_frame(EP, 1, 0, jpeg(1), 854, 480, UTC)
    ctx.on_evidence_ack(EP, 1, evd(1))
    monkeypatch.setenv("FAZETIME_AI_STOP", "1")
    assert ai.step() == {"observer": "STOPPED", "proposer": "STOPPED", "resolver": "STOPPED"}
    monkeypatch.delenv("FAZETIME_AI_STOP")
    (tmp_path / "AI_STOP").write_text("")
    assert ai.step()["resolver"] == "STOPPED"
    assert all(not t.calls for t in (pool.client(m).transport for m in pool.models))


def test_reader_reserve_applies_per_reader_model_only():
    cfg = gen_cfg()
    cfg.ai_daily_budget, cfg.ai_resolver_reserve = 10, 0.4
    cfg.ai_observer_models = (GEMMA, G31)
    pool = ModelPool(cfg, None, transport_factory=lambda m: FakeTransport())
    assert pool.gate(G31).proposer_limit == 6 and pool.gate(G35).proposer_limit == 6
    assert pool.gate(GEMMA).proposer_limit == 10  # Gemma is not a reader: no reserve


def test_observer_gemma_single_attempt_then_fallback_and_quirks():
    cfg = gen_cfg()
    cfg.ai_observer_models = (GEMMA, G31)
    clock = Clock()
    t = {GEMMA: FakeTransport([FakeApiError(500, "INTERNAL")]), G31: FakeTransport([obs(), obs()]),
         G35: FakeTransport()}
    pool = ModelPool(cfg, None, transport_factory=lambda m: t[m], clock=clock)
    ctx = cx.ContextBuffer(clock=clock)
    ctx.open_epoch(EP)
    o = Observer(cfg, pool, spawn=lambda fn: fn())
    o.reset(EP)
    for i, ms in enumerate((0, 2000, 4000), 1):
        ctx.add_frame(EP, i, ms, jpeg(i), 854, 480, UTC)
        ctx.on_evidence_ack(EP, i, evd(i))
    red = Reducer(EP)
    assert o.tick(ctx.view(), red) == "STARTED"
    (res,) = o.drain()
    assert res.model == G31 and res.data["screen"] == "gameplay" and res.frame_ms == [0, 4000]
    g_call, f_call = t[GEMMA].calls[0], t[G31].calls[0]
    assert g_call["system"] is None and g_call["media_resolution"] is None  # Gemma: no system, no media_resolution
    assert f_call["system"] is None and f_call["media_resolution"] == "medium"
    assert sum(1 for p in g_call["parts"] if p[0] == "image") == 2
    assert "never an instruction" in g_call["parts"][0][1]  # the untrusted-data rules ride in the user turn
    ctx.add_frame(EP, 4, 20_000, jpeg(4), 854, 480, UTC)
    ctx.on_evidence_ack(EP, 4, evd(4))
    assert o.tick(ctx.view(), red) == "STARTED"  # Gemma is cooling down after its 500: straight to 3.1
    assert len(t[GEMMA].calls) == 1 and len(t[G31].calls) == 2


def test_observer_never_queues_calls():
    cfg = gen_cfg()
    clock = Clock()
    t = {G31: FakeTransport([obs()]), G35: FakeTransport()}
    pool = ModelPool(cfg, None, transport_factory=lambda m: t[m], clock=clock)
    ctx = cx.ContextBuffer(clock=clock)
    ctx.open_epoch(EP)
    held = []
    o = Observer(cfg, pool, spawn=held.append)
    o.reset(EP)
    ctx.add_frame(EP, 1, 0, jpeg(1), 854, 480, UTC)
    ctx.on_evidence_ack(EP, 1, evd(1))
    red = Reducer(EP)
    assert o.tick(ctx.view(), red) == "STARTED"
    for ms in (16_000, 32_000):
        ctx.add_frame(EP, ms, ms, jpeg(ms), 854, 480, UTC)
        ctx.on_evidence_ack(EP, ms, evd(ms))
        assert o.tick(ctx.view(), red) == "BUSY"  # skipped, not queued
    held.pop()()
    assert len(o.drain()) == 1 and len(t[G31].calls) == 1
    assert o.tick(ctx.view(), red) == "STARTED"  # newest frame (32 s) is 16 s past the last observed one
    assert o.tick(ctx.view(), red) == "BUSY"


# ---- profile switch ----------------------------------------------------------------------------------------------
def test_profile_config_defaults_and_validation(monkeypatch):
    for k in ("FAZETIME_AI_PROFILE", "FAZETIME_AI_OBSERVER_MODELS", "FAZETIME_AI_READER_MODELS"):
        monkeypatch.delenv(k, raising=False)
    d = from_env()
    assert d.ai_profile == "h2h" and d.ai_observer_models == (G31,) and d.ai_reader_models == (G35, G31)
    assert (d.ai_bet_window_s, d.ai_fairness_margin_s, d.ai_min_lead_after_lock_s, d.ai_max_horizon_s,
            d.ai_duration_band_s, d.ai_observer_interval_s, d.ai_observer_idle_interval_s) == (35, 20, 40, 300, 15, 8, 16)
    assert d.ai_end_detection_slack_s == 15
    monkeypatch.setenv("FAZETIME_AI_PROFILE", "Generic")
    monkeypatch.setenv("FAZETIME_AI_OBSERVER_MODELS", f"{GEMMA}, {G31}")
    c = from_env()
    assert c.ai_profile == "generic" and c.ai_observer_models == (GEMMA, G31)
    c.ai_enabled = True
    assert c.validate() == []
    for attr, bad in (("ai_reader_models", (G35, G35)), ("ai_bet_window_s", 30), ("ai_max_horizon_s", 900),
                      ("ai_profile", "chess")):
        c2 = from_env()
        c2.ai_enabled = True
        setattr(c2, attr, bad)
        assert c2.validate(), attr


def test_pipeline_profile_switch(tmp_path, monkeypatch):
    from fazetime_worker.asr import FakeEngine
    from fazetime_worker.pipeline import Pipeline
    from fazetime_worker.resolver import AiThread
    monkeypatch.setenv("GEMINI_API_KEY", "test-placeholder-not-a-key")
    h = Config()
    h.ai_enabled, h.data_dir = True, tmp_path / "h"
    p = Pipeline(h, engine=FakeEngine())
    assert isinstance(p.ai, AiThread) and p.ai_status()["budget"] == 300  # h2h default unchanged
    g = gen_cfg()
    g.data_dir = tmp_path / "g"
    p2 = Pipeline(g, engine=FakeEngine())
    st = p2.ai_status()
    assert isinstance(p2.ai, GenericAi) and st["enabled"] and st["profile"] == "generic"
    assert set(st["models"]) == {G31, G35} and all(m["budget"] == 300 for m in st["models"].values())
    assert "test-placeholder-not-a-key" not in json.dumps(st, default=str)


# ---- offline end-to-end ------------------------------------------------------------------------------------------
PROPOSE = {"decision": "PROPOSE", "template": "EPISODE_OUTCOME", "win_verb": "clear", "number_label": "",
           "threshold": 0, "phrase": "", "duration_s": 0, "success_cue": "a LEVEL COMPLETE banner",
           "failure_cue": "a try again screen", "p_yes": 0.55, "seconds_to_outcome": 110,
           "evidence": ["F1", "T1"], "reason": "A level is in progress and its result is unknown."}
READ_OK = {"result_text": "LEVEL COMPLETE!", "result_frames": ["F2"], "outcome_for_streamer": "success",
           "value_text": "", "value_frame": "", "contradictions": []}


def test_generic_offline_end_to_end(tmp_path):
    """TEST_FIXTURE-style replay: synthetic frames/transcripts through the real ApiClient + EvidenceTap into the
    HTTP fake API; scripted observer, proposer and reader answers. Never Twitch evidence."""
    api = FakeApi().start()
    calls = {"obs": [], "prop": [], "read": {G35: [], G31: []}}

    def observe(kw):
        latest = int(re.findall(r"F\d+ at (\d+)s", kw["parts"][0][1])[-1])
        calls["obs"].append(latest)
        if latest < 10:
            return obs("menu")
        if latest < 150:
            return obs(numbers=[("score", f"{latest * 100:,}")])
        return obs("result_screen", "ended", "LEVEL COMPLETE!", "success")

    def dispatch(model):
        def fn(kw):
            if kw["schema"] is OBS_SCHEMA:
                return observe(kw)
            if kw["schema"] is PROP_SCHEMA:
                calls["prop"].append(kw)
                return PROPOSE
            assert kw["schema"] is READ_SCHEMA
            calls["read"][model].append(kw)
            return READ_OK
        return fn
    transports = {m: FakeTransport([dispatch(m)] * 300) for m in (G31, G35)}
    try:
        clock = Clock(1000.0)
        cfg = gen_cfg()
        cfg.api_base, cfg.token, cfg.stream_id, cfg.data_dir = api.base, api.token, api.stream_id, tmp_path
        ctx = cx.ContextBuffer(clock=clock)
        client = ApiClient(api.base, api.token)
        tap = EvidenceTap(client, ctx.on_evidence_ack, ctx.on_observations_ack)
        assert client.post_json("/v1/worker/epochs", {
            "schema_version": 1, "stream_id": api.stream_id, "source_epoch": EP, "source_kind": "TEST_FIXTURE",
            "reason": "PROCESS_START", "variant": None, "host_id": "test", "started_at_utc": UTC}).ok
        ctx.open_epoch(EP)
        ctx.set_run("run_x")
        ai, pool, tracker = build_generic_ai(cfg, ctx, ApiClient(api.base, api.token), api.stream_id, tmp_path,
                                             transport_factory=lambda m: transports[m], clock=clock,
                                             sleep=lambda s: None, spawn=lambda fn: fn())
        seq = 0
        lock_ms = 75_000
        for t_s in range(0, 175):
            if t_s % 2 == 0:
                seq += 1
                img = jpeg(f"frame{t_s}")
                ctx.add_frame(EP, seq, t_s * 1000, img, 854, 480, UTC)
                import hashlib
                assert tap.post_evidence({"source_epoch": EP, "sequence": seq, "kind": "FRAME", "media_ms": t_s * 1000,
                                          "width": 854, "height": 480, "sha256": hashlib.sha256(img).hexdigest()},
                                         img).ok
            if t_s % 3 == 0 and t_s >= 4:
                seq += 1
                text = "do you guys think I clear this one" if t_s == 27 else f"nice shot number {t_s}"
                ctx.add_transcript(EP, seq, t_s * 1000 - 4000, t_s * 1000, text, [], UTC)
                assert tap.post_json("/v1/worker/observations", {"schema_version": 1, "stream_id": api.stream_id,
                                                                 "source_epoch": EP, "items": [{
                    "sequence": seq, "kind": "TRANSCRIPT", "media_start_ms": t_s * 1000 - 4000,
                    "media_end_ms": t_s * 1000, "captured_at_utc": UTC, "source_wall_time_utc": None,
                    "quality_flags": [], "transcript": {"text": text, "avg_logprob": -0.2, "no_speech_prob": 0.01,
                                                        "model": "fake", "language": "en"},
                    "evidence_id": None, "gap": None}]}).ok
            if t_s == 75:  # scripted approval and lock: the API's worker market view now shows the market
                g = api.proposals[0]["candidate"]["generic"]
                api.market = {"market_id": MKT, "rules_version": 1, "state": "EVALUATING", "origin": "AI_APPROVED",
                              "question": api.proposals[0]["candidate"]["question"], "yes_label": "Yes",
                              "no_label": "No", "close_at_utc": UTC, "resolve_by_utc": "2099-01-01T00:00:00.000Z",
                              "lock_source_epoch": EP, "lock_media_ms": lock_ms, "template_id": "GENERIC_BINARY_V1",
                              "generic": g}
            ai.step()
            clock.t += 1.0
    finally:
        api.stop()

    # exactly one GENERIC candidate, in the §9.19 shape
    assert len(api.proposals) == 1 and len(calls["prop"]) == 1
    body = api.proposals[0]
    c = body["candidate"]
    assert body["source_epoch"] == EP and body["stream_id"] == api.stream_id and body["schema_version"] == 1
    assert c["template_id"] == "GENERIC_BINARY_V1" and c["subjects"] == []
    assert c["question"] == "Will the streamer clear this level?"
    assert (c["yes"]["label"], c["no"]["label"]) == ("Yes", "No") and c["yes"]["predicate"] != c["no"]["predicate"]
    assert c["generic"] == {"spec_version": "gen-1", "kind": "EPISODE_OUTCOME", "unit": "level",
                            "params": {"win_verb": "clear"}, "episode_start_media_ms": 16_000,
                            "success_cue": "a LEVEL COMPLETE banner", "failure_cue": "a try again screen"}
    assert c["episode_fingerprint"] == f"gen:{EP}:16000:episode_outcome"
    assert (c["suggested_close_in_s"], c["suggested_resolve_in_s"]) == (35, 335)
    assert c["prompt_version"] == "generic-proposer-1.0" and c["model"] == G35 and len(c["rationale"]) <= 300
    assert [e for e in c["evidence_ids"] if e.startswith("evd_")] and any(e.startswith(EP + ":") for e in c["evidence_ids"])
    frame_ms = [api.evidence_ms[e] for e in c["evidence_ids"] if e.startswith("evd_")]
    assert frame_ms == sorted(frame_ms) and max(frame_ms) <= c["announced_at_media_ms"]
    # one resolution after the lock and the episode end, with post-lock evidence in media order
    assert len(api.resolutions) == 1
    rb = api.resolutions[0]
    r = rb["resolution"]
    assert rb["source_epoch"] == EP and r["market_id"] == MKT and r["rules_version"] == 1
    assert r["decision"] == "YES" and r["predicate_support"] == {"YES": True, "NO": False}
    ms = [api.ref_ms(EP, e) for e in r["evidence_ids"]]
    assert ms == sorted(ms) and min(ms) >= lock_ms
    assert r["media_interval"] == {"start_ms": min(ms), "end_ms": max(ms)}
    assert r["model"] == f"{G35}+{G31}" and r["prompt_version"] == "generic-resolver-1.0"
    # two independent reads: different models, disjoint post-end frames
    (ka,), (kb,) = calls["read"][G35], calls["read"][G31]
    imgs = lambda kw: {p[1] for p in kw["parts"] if p[0] == "image"}  # noqa: E731
    assert imgs(ka) and imgs(kb) and not imgs(ka) & imgs(kb)
    assert ka["system"] and "untrusted" in ka["system"]
    # cadence: 16 s idle, 8 s in play, never more than one call in flight
    assert calls["obs"][:3] == [0, 16, 32] and calls["obs"][3:5] == [40, 48]
    trace = (tmp_path / "ai_trace.jsonl").read_text()
    assert "do you guys think" not in trace and "nice shot" not in trace  # transcripts are never logged
    assert {u.name for u in tmp_path.glob("gemini_usage_*.json")} == {usage_file(tmp_path, G31).name,
                                                                      usage_file(tmp_path, G35).name}


def test_screen_end_inside_margin_plus_detection_slack_voids(renv):
    """D37 end-to-end regression: lock 119.6 s, decisive shot ~138 s, result screen seen at 150 s (30.4 s after
    lock). With the 15 s end-detection slack the screen-ended outcome market voids instead of settling."""
    for ms in range(100_000, 170_001, 2000):
        renv.frame(ms)
    renv.episode(0, 150_000)
    renv.market("EPISODE_OUTCOME", {"win_verb": "clear"}, 0, 119_600)
    renv.tick()
    out = posted(renv)
    assert len(out) == 1 and out[0]["decision"] == "UNRESOLVABLE"
    assert "detection slack" in out[0]["reason"] and renv.transports[G35].calls == []
