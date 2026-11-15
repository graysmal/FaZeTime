"""Generic template proposer (D37, CONTRACTS §9.19), ported from ``spikes/p4-generic``.

Trigger (code): an episode in progress for at least 10 s (6 s after a streamer bet cue), no nonterminal market
and no pending candidate of ours, at most 2 markets and 3 proposer calls per episode, at least 30 media seconds
between proposer calls. One ``gemini-3.5-flash-lite`` call picks a kind and fills slots; code then validates
(P(YES) in [0.2, 0.8]; expected lead after lock from this stream's history when there is any, else the model's
estimate; horizon; no repeated kind; cited handles; per-kind slots) and renders every market term.

Posting (§9.17 item 1, §9.19): ``GENERIC_BINARY_V1`` with ``suggested_close_in_s`` = 35 and
``suggested_resolve_in_s`` = 335, citing fresh acknowledged frames (and acknowledged transcript windows when
``FAZETIME_AI_EVIDENCE_REFS=frames+transcripts``). Network/5xx/429 retries resend the same body. A validation
rejection does not consume the episode (§9.17 item 5e): STALE_EVIDENCE is re-posted once at once with fresh
evidence and a new ``candidate_id``; other non-consuming codes pause and leave the episode to the next trigger.

§9.20: ``generic.expected_result_in_s`` is the same "remaining" figure the lead check uses (history first, else the
model's ``seconds_to_outcome``) minus the betting window, clamped to [0, 900]. The labelled, untrusted Twitch
context line (title, category, channel) rides in the prompt's DATA section.
"""
from __future__ import annotations

import logging
import math
import re
import time

from .. import context as cx
from ..gemini import SYSTEM_RULES, CallError, Unavailable
from ..proposer import post_with_retries
from . import templates as tp
from .models import NON_RESOLVER, ModelPool
from .observer import transcript_lines
from .prompts import PROP_SCHEMA, TEMPLATES, proposer_prompt
from .reducer import norm_label

log = logging.getLogger("fazetime.generic.proposer")

CUE_RE = re.compile(r"\b(do you (guys )?think|you think i|bet on|will i|can i|chat,? (do|should|will))\b", re.I)
MAX_MARKETS_PER_EPISODE = 2
MAX_CALLS_PER_EPISODE = 3
MIN_CALL_GAP_MS = 30_000
MIN_ELAPSED_MS, MIN_ELAPSED_CUE_MS = 10_000, 6_000
TRANSCRIPT_WINDOW_MS = 90_000
CANDIDATE_HOLD_S = 65.0  # a PENDING candidate expires 60 s after receipt (§9.17 item 2)
CONSUMED = ("PENDING", "SHADOW", "OPENED", "DRY_RUN")
NON_CONSUMING_PAUSE_S = {"MARKET_BUSY": 30.0, "AI_OFF": 120.0, "SOURCE_NOT_LIVE": 10.0}


def _num(v, cast=float):
    if isinstance(v, bool):
        return None
    try:
        x = cast(v)
    except (TypeError, ValueError):
        return None
    return x if not isinstance(x, float) or math.isfinite(x) else None


def coerce_proposal(p) -> dict | None:
    """Schema check of the proposer answer (types and enums). None when malformed."""
    if not isinstance(p, dict) or p.get("decision") not in ("PROPOSE", "ABSTAIN") or p.get("template") not in TEMPLATES:
        return None
    out = dict(p)
    for k in ("win_verb", "number_label", "phrase", "success_cue", "failure_cue", "reason"):
        out[k] = p.get(k) if isinstance(p.get(k), str) else ""
    out["threshold"] = _num(p.get("threshold"))
    out["p_yes"] = _num(p.get("p_yes"))
    d = _num(p.get("duration_s"), float)
    out["duration_s"] = int(d) if d is not None and float(d).is_integer() else None
    s = _num(p.get("seconds_to_outcome"), float)
    out["seconds_to_outcome"] = int(s) if s is not None else None
    ev = p.get("evidence")
    out["evidence"] = [h for h in ev if isinstance(h, str) and h] if isinstance(ev, list) else []
    return out


def params_for(p: dict) -> tuple[str, dict]:
    kind = p["template"]
    if kind == "EPISODE_OUTCOME":
        return kind, {"win_verb": p["win_verb"]}
    if kind == "END_VALUE_AT_LEAST":
        thr = p["threshold"]
        thr = int(thr) if thr is not None and float(thr).is_integer() else thr
        return kind, {"label": norm_label(p["number_label"])[:40], "threshold": thr}
    if kind == "SAY_PHRASE":
        return kind, {"phrase": tp.clean_phrase(p["phrase"])}
    return kind, {"duration_s": p["duration_s"]}


def remaining_s(red, now_ms: int, sto) -> float | None:
    """Seconds from ``now_ms`` until the outcome is expected. Once the stream has history it decides (this stream's
    median earlier episode duration minus the current episode's age); otherwise the model's ``seconds_to_outcome``."""
    e = red.cur
    prior = red.prior_duration_ms()
    if prior and e is not None:
        return (prior - (now_ms - e.start_ms)) / 1000
    return None if sto is None else float(sto)


def expected_result_in_s(remaining: float | None, close_s: int) -> int | None:
    """§9.20 item 2: seconds from betting close (lock) until the result is expected, clamped to [0, 900]."""
    return None if remaining is None else tp.clamp_eta(remaining - close_s)


def check_proposal(p: dict, red, now_ms: int, close_s: int, handles: set, *, min_lead_s: int,
                   horizon_s: int) -> str | None:
    """Deterministic gate (spike ``check_proposal`` plus the §9.19 slot rules). Returns a reject code or None."""
    if p.get("decision") != "PROPOSE" or p.get("template") in (None, "NONE"):
        return "ABSTAINED"
    e = red.cur
    if e is None or e.phase != "IN_PROGRESS":
        return "NO_EPISODE"
    pv = p.get("p_yes")
    if pv is None or not 0.2 <= pv <= 0.8:
        return "UNBALANCED"
    sto = p.get("seconds_to_outcome")
    if sto is None:
        return "MALFORMED"
    # Lead: the model's own time estimate is unreliable, so once the stream has history it decides (report:
    # lines come from history, not from the model). A result that still lands near lock voids at resolution.
    remaining = remaining_s(red, now_ms, sto)
    if remaining < close_s + min_lead_s:
        return "INSUFFICIENT_LEAD"
    if red.last_template and p["template"] == red.last_template:
        return "REPEAT_TEMPLATE"
    if min(sto, remaining) > close_s + horizon_s:
        return "HORIZON_TOO_LONG"
    cited = p.get("evidence") or []
    if not cited or any(h not in handles for h in cited):
        return "BAD_EVIDENCE"
    kind = p["template"]
    if kind == "END_VALUE_AT_LEAST":
        if len(e.reads(p.get("number_label", ""))) < 2:
            return "UNTRACKED_NUMBER"
        if not p.get("threshold"):
            return "BAD_THRESHOLD"
    elif kind == "SAY_PHRASE":
        if not 1 <= len(tp.clean_phrase(p.get("phrase")).split()) <= 3:
            return "BAD_PHRASE"
    elif kind == "DURATION_OVER":
        d = p.get("duration_s")
        if d is None or d * 1000 < (now_ms - e.start_ms) + (close_s + 20) * 1000:
            return "BAD_DURATION"
    _, params = params_for(p)
    return tp.validate_params(kind, params)


class GenericProposer:
    def __init__(self, cfg, ctx: cx.ContextBuffer, pool: ModelPool, api, stream_id: str, tracker, registry, trace,
                 clock=time.monotonic, sleep=time.sleep):
        self.cfg, self.ctx, self.pool, self.api, self.stream_id = cfg, ctx, pool, api, stream_id
        self.tracker, self.registry, self.trace = tracker, registry, trace
        self.clock, self.sleep = clock, sleep
        self.model = cfg.ai_proposer_model
        self.close_s = int(cfg.ai_bet_window_s)
        self.resolve_s = int(cfg.ai_bet_window_s + cfg.ai_max_horizon_s)
        self.paused_until = -1e18
        self.pause_kind: str | None = None
        self.hold_until = -1e18  # our last candidate may still be PENDING at the API
        self.counts: dict = {}

    def _count(self, outcome: str) -> str:
        k = outcome.split(":")[0]
        self.counts[k] = self.counts.get(k, 0) + 1
        return outcome

    def on_new_run(self):
        """Operator reset: API pauses and the pending-candidate hold belong to the old run (quota pauses stay)."""
        if self.pause_kind != "QUOTA":
            self.paused_until, self.pause_kind = -1e18, None
        self.hold_until = -1e18

    def _pause(self, seconds: float, kind: str):
        self.paused_until, self.pause_kind = self.clock() + seconds, kind

    def tick(self, view, red, last_obs: dict | None, stream_line: str = "") -> str:
        e = red.cur
        if view.epoch is None or red.epoch != view.epoch or e is None or e.phase != "IN_PROGRESS":
            return "NO_EPISODE"
        now = self.clock()
        if now < self.paused_until:
            return "PAUSED"
        if now < self.hold_until:
            return "CANDIDATE_PENDING"
        if self.tracker is not None and self.tracker.poll() is not None and self.tracker.nonterminal():
            return "MARKET_BUSY"
        if e.markets >= MAX_MARKETS_PER_EPISODE:
            return "EPISODE_MARKET_CAP"
        if e.proposer_calls >= MAX_CALLS_PER_EPISODE:
            return "EPISODE_CALL_CAP"
        now_ms = red.last_t_ms if red.last_t_ms is not None else 0
        if now_ms - e.last_proposer_ms < MIN_CALL_GAP_MS:
            return "DEBOUNCE"
        recent = [t for t in view.transcripts if t.media_end_ms > now_ms - TRANSCRIPT_WINDOW_MS and t.text.strip()]
        cue = str((last_obs or {}).get("streamer_cue") or "").strip()[:120]
        spoken_cue = bool(CUE_RE.search(" ".join(t.text for t in recent if t.media_end_ms > now_ms - 20_000)))
        if now_ms - e.start_ms < (MIN_ELAPSED_CUE_MS if (cue or spoken_cue) else MIN_ELAPSED_MS):
            return "TOO_EARLY"
        if not self.pool.ready(self.model, NON_RESOLVER):
            return "GEMINI_UNAVAILABLE"
        frames = self._frames(view, now_ms, now)
        if not frames:
            return "NO_FRAME_EVIDENCE"
        return self._count(self._propose(view, red, e, now_ms, recent[-24:], frames, cue, stream_line))

    def _fresh_frames(self, view, now) -> list:
        return [f for f in view.frames if f.evidence_id and f.ack_mono is not None
                and now - f.ack_mono <= self.cfg.ai_evidence_max_age_s]

    def _frames(self, view, now_ms: int, now: float) -> list:
        """The fresh acknowledged frames nearest to now - 16 s, now - 8 s and now (spike: 3 frames)."""
        fresh = self._fresh_frames(view, now)
        out = []
        for target in (now_ms - 16_000, now_ms - 8_000, now_ms):
            before = [f for f in fresh if f.media_ms <= target]
            f = before[-1] if before else None
            if f is not None and f not in out:
                out.append(f)
        return sorted(out, key=lambda f: f.media_ms)

    def _log(self, outcome: str, view, **kw) -> str:
        self.trace.write({"role": "proposer", "profile": "generic", "outcome": outcome, "epoch": view.epoch,
                          "run": view.run_id, "media_now_ms": view.media_now_ms,
                          "prompt_version": tp.PROPOSER_PROMPT_VERSION} | kw)
        if outcome.startswith(("POSTED", "REJECT", "ABSTAIN", "MALFORMED", "QUOTA", "MODEL_ERROR")):
            log.info("generic proposer %s %s", outcome, {k: kw.get(k) for k in ("kind", "reject_code", "status",
                                                                                "fingerprint", "latency_ms") if k in kw})
        return outcome

    def _evidence(self, view, frames: list, cited_transcripts: list) -> list:
        """Fresh acknowledged frames first (sorted by media time), then cited acknowledged transcript windows."""
        now = self.clock()
        max_age = self.cfg.ai_evidence_max_age_s
        ev = [f.evidence_id for f in sorted(frames, key=lambda f: f.media_ms)
              if f.evidence_id and f.ack_mono is not None and now - f.ack_mono <= max_age]
        if self.cfg.ai_evidence_refs == "frames+transcripts":
            ev += [cx.obs_ref(t.epoch, t.sequence) for t in cited_transcripts
                   if t.ack_mono is not None and now - t.ack_mono <= self.cfg.ai_evidence_max_age_s]
        return list(dict.fromkeys(ev))[:20]

    def _propose(self, view, red, e, now_ms, recent, frames, cue, stream_line: str = "") -> str:
        handles = {f"T{i}": t for i, t in enumerate(recent, 1)} | {f"F{i}": f for i, f in enumerate(frames, 1)}
        prompt = proposer_prompt(red, now_ms, transcript_lines(recent), [f.media_ms for f in frames], self.close_s,
                                 cue, self.cfg.ai_min_lead_after_lock_s, self.cfg.ai_max_horizon_s, stream_line)
        before = (e.proposer_calls, e.last_proposer_ms)
        e.proposer_calls += 1
        e.last_proposer_ms = now_ms
        try:
            res = self.pool.call(self.model, role=NON_RESOLVER, text=prompt, images=[f.jpeg for f in frames],
                                 schema=PROP_SCHEMA, system=SYSTEM_RULES, media_resolution="low")
        except Unavailable as u:
            e.proposer_calls, e.last_proposer_ms = before  # refused before sending: not a call
            return "GEMINI_UNAVAILABLE:" + u.reason
        except CallError as err:
            if err.kind == "QUOTA":
                self._pause(60.0, "QUOTA")
                return self._log("QUOTA_PAUSED", view, episode=e.idx)
            return self._log("MODEL_ERROR:" + err.kind, view, episode=e.idx)
        meta = {"model": self.model, "model_version": res.model_version, "latency_ms": res.latency_ms,
                "usage": res.usage, "episode": e.idx, "episode_start_ms": e.start_ms,
                "handles": {h: getattr(o, "media_ms", getattr(o, "media_start_ms", None)) for h, o in handles.items()}}
        p = coerce_proposal(res.data)
        if p is None:
            return self._log("MALFORMED", view, **meta)
        meta |= {"decision": p["decision"], "kind": p["template"], "p_yes": p["p_yes"],
                 "seconds_to_outcome": p["seconds_to_outcome"], "cited": p["evidence"][:8]}
        if self.ctx.view().epoch != view.epoch or red.cur is not e or e.phase != "IN_PROGRESS":
            return self._log("REJECT:STALE_EPOCH_LOCAL", view, **meta)
        code = check_proposal(p, red, now_ms, self.close_s, set(handles), min_lead_s=self.cfg.ai_min_lead_after_lock_s,
                              horizon_s=self.cfg.ai_max_horizon_s)
        if code == "ABSTAINED":
            return self._log("ABSTAIN", view, **meta)
        if code:
            return self._log("REJECT:" + code, view, **meta)
        kind, params = params_for(p)
        fp = tp.fingerprint(view.epoch, e.start_ms, kind)
        if fp in self.registry.used:
            return self._log("REJECT:DUPLICATE_EPISODE_LOCAL", view, **meta)
        cited_tr = [handles[h] for h in p["evidence"] if isinstance(handles.get(h), cx.TranscriptObs)]
        return self._post_new(view, red, e, kind, params, p, frames, cited_tr, now_ms, meta, retry_stale=True)

    def _post_new(self, view, red, e, kind, params, p, frames, cited_tr, now_ms, meta, retry_stale: bool) -> str:
        evidence = self._evidence(view, frames, cited_tr)
        eta = expected_result_in_s(remaining_s(red, now_ms, p["seconds_to_outcome"]), self.close_s)
        send_eta = bool(getattr(self.cfg, "ai_result_eta", True))
        meta = meta | ({"expected_result_in_s": eta} if send_eta else {})
        code, cand = tp.make_candidate(
            source_epoch=view.epoch, kind=kind, unit=red.unit, params=params, episode_start_media_ms=e.start_ms,
            success_cue=p["success_cue"], failure_cue=p["failure_cue"], evidence_ids=evidence,
            announced_at_media_ms=now_ms, close_in_s=self.close_s, resolve_in_s=self.resolve_s,
            margin_s=self.cfg.ai_fairness_margin_s, band_s=self.cfg.ai_duration_band_s, rationale=p["reason"],
            model=self.model, expected_result_in_s=eta, send_eta=send_eta)
        if code:
            return self._log("REJECT:" + code, view, **meta)
        body = {"schema_version": 1, "stream_id": self.stream_id, "source_epoch": view.epoch, "candidate": cand}
        res = post_with_retries(self.api, "/v1/worker/proposals", body, sleep=self.sleep)
        fp, rb = cand["episode_fingerprint"], res.body or {}
        meta = meta | {"candidate_id": cand["candidate_id"], "fingerprint": fp, "evidence_ids": cand["evidence_ids"],
                       "http_status": res.status, "question": cand["question"]}
        if not res.ok:
            code = res.code or (str(res.status) if res.status else res.error)
            if code == "STALE_EPOCH":
                return self._log("REJECT:STALE_EPOCH", view, **meta)
            self._pause(20.0, "API")
            return self._log("POST_FAILED:" + str(code), view, **meta)
        status, reject = rb.get("status") or "DRY_RUN", rb.get("reject_code")
        meta |= {"status": status, "reject_code": reject, "market_id": rb.get("market_id")}
        if status in CONSUMED:
            self.registry.used.add(fp)
            self.registry.add(cand, status, rb.get("market_id"))
            e.markets += 1
            red.last_template = kind
            if status != "OPENED":
                self.hold_until = self.clock() + CANDIDATE_HOLD_S
            if self.tracker is not None:
                self.tracker.poke()
            return self._log("POSTED:" + status, view, **meta)
        if reject == "DUPLICATE_EPISODE":
            self.registry.used.add(fp)  # consumed earlier in this run
        elif reject == "STALE_EVIDENCE" and retry_stale:
            # a validation rejection does not consume the episode: one immediate retry, new candidate_id
            self._log("REJECTED:STALE_EVIDENCE", view, **meta)
            fresh = self._frames(self.ctx.view(), now_ms, self.clock())
            return self._post_new(view, red, e, kind, params, p, fresh or frames, cited_tr, now_ms, meta,
                                  retry_stale=False)
        self._pause(NON_CONSUMING_PAUSE_S.get(reject, 20.0), "API")
        return self._log("REJECTED:" + str(reject), view, **meta)
