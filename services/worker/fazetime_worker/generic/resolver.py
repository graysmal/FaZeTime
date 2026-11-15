"""Generic resolver (D37, CONTRACTS §9.19 item 7): models transcribe, code decides, doubt voids.

Acts only on AI-origin ``GENERIC_BINARY_V1`` markets in LOCKED or EVALUATING (posts only while EVALUATING), at
the market's ``rules_version``, in its lock epoch, for the episode named by ``generic.episode_start_media_ms``.
* Every kind: UNRESOLVABLE when the decisive evidence (the episode end, or the phrase occurrence) is at or before
  ``lock_media_ms + M`` (M = 20 s). No result by ``resolve_by``: the API's sweeper voids (unchanged).
* SAY_PHRASE: a regex over the (unprimed) transcript windows after lock + M until the episode ends. YES cites the
  transcript observation; NO needs the episode end with transcript coverage of the whole window (no hole). A
  hit that might fall inside the margin or across the end boundary, or a hole in the margin, voids.
* DURATION_OVER: code, from the episode's start and end media times. Voids within +/-15 s of the line, or when
  the end was not seen as a result. Still running 15 s past the line is YES.
* EPISODE_OUTCOME / END_VALUE_AT_LEAST: two extraction-only reads in parallel (reader A and reader B: different
  models, different post-end frames); ``decide_visual`` decides. Disagreement voids; a missing result word or an
  unreadable value waits; reads exhausted without agreement voids.
* All cited evidence is at or after ``lock_media_ms``. A reply that arrives after the market, its rules_version
  or the epoch changed is dropped (``LATE_DROPPED``).
"""
from __future__ import annotations

import logging
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from .. import context as cx
from ..gemini import SYSTEM_RULES, CallError, Unavailable
from ..proposer import post_with_retries
from ..resolver import NONTERMINAL, TERMINAL_IGNORED, _parse_utc
from . import templates as tp
from .models import RESOLVER, ModelPool
from .observer import transcript_lines
from .prompts import READ_SCHEMA, read_prompt, valid_read
from .reducer import parse_number

log = logging.getLogger("fazetime.generic.resolver")

AI_ORIGINS = ("AI_APPROVED", "AI_AUTOMATIC")
CODE_MODEL = "worker-code"  # decisions made by deterministic worker code (no model call)
# Generic result lexicon (decide on printed result words, never on a model's say-so alone)
SUCCESS_WORDS = ("complete", "completed", "clear", "cleared", "victory", "win", "wins", "won", "winner", "success",
                 "passed", "champion", "you win", "you won")
FAILURE_WORDS = ("defeat", "defeated", "lose", "lost", "loss", "game over", "failed", "fail", "try again", "retry",
                 "eliminated", "you died", "wasted", "out of balls")
_CUE_STOP = {"screen", "level", "stage", "round", "match", "game", "streamer", "shows", "show", "banner", "text",
             "will", "with", "that", "this", "appears", "appear", "message", "result", "visible", "the", "and"}
NONE_SUPPORT = {"YES": False, "NO": False}
POST_END_WAIT_MS = 4_000  # read only once frames at least this far past the episode end exist
READ_FROM_BEFORE_END_MS = 12_000  # result banners often appear in the last seconds of play
MAX_FRAMES_PER_READ = 6
MAX_READ_ROUNDS = 3
READ_ROUND_GAP_MS = 8_000
COVERAGE_START_SLACK_MS = 4_000
MAX_POSTS_PER_MARKET = 8


def phrase_regex(phrase: str) -> re.Pattern:
    body = r"\W+".join(re.escape(w) for w in phrase.split())
    return re.compile(r"\b" + body + r"(?:s|es|'s)?\b", re.IGNORECASE)


def _has_word(text: str, words) -> bool:
    t = (text or "").lower()
    return any(re.search(r"\b" + re.escape(w) + r"\b", t) for w in words)


def decide_visual(kind: str, params: dict, success_cue: str, failure_cue: str, reads: list):
    """Code decides from two extraction reads. Returns (decision, reason, predicate_support, contradictions)."""
    if len(reads) < 2 or any(r is None for r in reads):
        return "WAIT", "missing read", dict(NONE_SUPPORT), []
    contradictions = [str(c)[:120] for r in reads for c in (r.get("contradictions") or []) if str(c).strip()]
    if contradictions:
        return "UNRESOLVABLE", "contradiction reported by a reader", dict(NONE_SUPPORT), contradictions
    if kind == "EPISODE_OUTCOME":
        outs = [r.get("outcome_for_streamer") for r in reads]
        texts = [str(r.get("result_text") or "").strip()[:80] for r in reads]
        if "success" in outs and "failure" in outs:
            return "UNRESOLVABLE", "reads disagree", {"YES": True, "NO": True}, ["reader A and B disagree"]
        side = "success" if all(o == "success" for o in outs) else "failure" if all(o == "failure" for o in outs) \
            else None
        if side is None or not all(texts):
            return "WAIT", f"no agreed visible result ({outs})", dict(NONE_SUPPORT), []
        lex = SUCCESS_WORDS if side == "success" else FAILURE_WORDS
        cue = success_cue if side == "success" else failure_cue
        cue_words = {w for w in re.findall(r"[a-z]{4,}", (cue or "").lower()) if w not in _CUE_STOP}
        if not any(_has_word(t, lex) or _has_word(t, cue_words) for t in texts):
            return "WAIT", f"result text lacks a result word ({texts})", dict(NONE_SUPPORT), []
        yes = side == "success"
        return ("YES" if yes else "NO"), f"both reads: {side} ({texts[0]!r} / {texts[1]!r})", \
            {"YES": yes, "NO": not yes}, []
    if kind == "END_VALUE_AT_LEAST":
        raw = [str(r.get("value_text") or "")[:24] for r in reads]
        vals = [parse_number(v) for v in raw]
        if any(v is None for v in vals):
            return "WAIT", f"value unreadable ({raw})", dict(NONE_SUPPORT), []
        if abs(vals[0] - vals[1]) > max(1.0, 0.001 * abs(vals[0])):
            return "UNRESOLVABLE", f"reads disagree ({raw})", dict(NONE_SUPPORT), ["reader values disagree"]
        thr = float(params["threshold"])
        if abs(vals[0] - thr) <= max(1.0, 0.001 * abs(thr)):
            return "UNRESOLVABLE", f"value {raw[0]} within one display unit of {thr:g}", dict(NONE_SUPPORT), []
        yes = vals[0] >= thr
        return ("YES" if yes else "NO"), f"value {raw[0]} vs threshold {thr:g}", {"YES": yes, "NO": not yes}, []
    return "WAIT", "not a visual kind", dict(NONE_SUPPORT), []


@dataclass
class Verdict:
    decision: str
    support: dict
    evidence: list  # FrameObs / TranscriptObs, all at or after lock
    reason: str
    contradictions: list = field(default_factory=list)
    model: str = CODE_MODEL


@dataclass
class _GState:
    scanned_seq: int = 0
    hits: list = field(default_factory=list)  # TranscriptObs whose text matches the phrase (after lock)
    cov_end_ms: int | None = None
    first_post_lock_start: int | None = None
    last_window: object = None
    rounds: int = 0
    last_round_frame_ms: int = -10 ** 12
    posts: int = 0
    next_at: float = -1e18
    done: bool = False


@dataclass
class ReadOut:
    model: str
    frames: list
    data: dict | None
    sent: bool
    error: str | None = None
    latency_ms: int | None = None


class GenericResolver:
    def __init__(self, cfg, ctx: cx.ContextBuffer, pool: ModelPool, api, stream_id: str, tracker, trace,
                 clock=time.monotonic, wall=time.time, sleep=time.sleep):
        self.cfg, self.ctx, self.pool, self.api, self.stream_id = cfg, ctx, pool, api, stream_id
        self.tracker, self.trace, self.clock, self.wall, self.sleep = tracker, trace, clock, wall, sleep
        self.readers = list(cfg.ai_reader_models)
        self.markets: dict = {}
        self.counts: dict = {}

    def _count(self, outcome: str) -> str:
        k = outcome.split(":")[0]
        self.counts[k] = self.counts.get(k, 0) + 1
        return outcome

    def tick(self, view, red) -> str:
        m = self.tracker.poll()
        if m is None or m.state not in ("LOCKED", "EVALUATING"):
            return "IDLE"
        if m.template_id != tp.TEMPLATE_ID or m.generic is None or m.origin not in AI_ORIGINS:
            return "NOT_GENERIC_AI"
        st = self.markets.setdefault((m.market_id, m.rules_version), _GState())
        while len(self.markets) > 20:
            self.markets.pop(next(iter(self.markets)))
        if st.done:
            return "DONE"
        if m.lock_source_epoch and m.lock_source_epoch != view.epoch:
            st.done = True  # an epoch change voids the market (§9.4); never resolve across epochs
            return self._count("EPOCH_MISMATCH")
        if m.lock_media_ms is None:
            return "NO_LOCK_POSITION"
        if red.epoch != view.epoch:
            return "NO_STATE"
        code, spec = tp.parse_generic(m.generic)
        if code:
            st.done = True
            return self._count("BAD_SPEC:" + code)
        deadline = _parse_utc(m.resolve_by_utc)
        if deadline is not None and self.wall() >= deadline - 5.0:
            return "PAST_DEADLINE"
        lock = int(m.lock_media_ms)
        if spec["kind"] == "SAY_PHRASE":
            self._scan(st, view, spec, lock)
        if self.clock() < st.next_at:
            return "BACKOFF"
        ep = red.find(spec["episode_start_media_ms"])
        if ep is None:
            return "NO_EPISODE"  # not this worker's episode (or forgotten): the sweeper voids at the deadline
        evaluating = m.state == "EVALUATING"  # as polled; _post re-polls after any model call (late replies)
        v = self._decide(m, st, spec, ep, red, view, lock)
        if v is None:
            return "WAIT_LOCAL"
        if not evaluating:
            return "WAIT_EVALUATING"
        return self._count(self._post(m, st, v, lock))

    # ---- evidence helpers -----------------------------------------------------------------------------
    @staticmethod
    def _post_lock_frames(view, lock: int, near_ms: int, n: int = 2) -> list:
        fr = [f for f in view.frames if f.evidence_id and f.media_ms >= lock]
        fr.sort(key=lambda f: (abs(f.media_ms - near_ms), f.media_ms))
        return sorted(fr[:n], key=lambda f: f.media_ms)

    def _void(self, reason: str, evidence: list, support=None, contradictions=None) -> Verdict:
        return Verdict("UNRESOLVABLE", dict(support or NONE_SUPPORT), evidence, reason, list(contradictions or []))

    # ---- decisions --------------------------------------------------------------------------------------
    def _decide(self, m, st, spec, ep, red, view, lock: int) -> Verdict | None:
        margin = int(self.cfg.ai_fairness_margin_s * 1000)
        kind = spec["kind"]
        # The screen-detected end trails the decisive moment, so screen-ended kinds get the detection slack too
        # (D37 end-to-end: lock 119.6 s, winning shot ~138 s, result screen detected at 150 s).
        slack = 0 if kind == "SAY_PHRASE" else int(self.cfg.ai_end_detection_slack_s * 1000)
        end = ep.end_ms
        if end is not None and end <= lock + margin + slack:
            return self._void(f"RESULT_BEFORE_LOCK_MARGIN: episode ended at {end} ms, lock {lock} ms + {margin} ms"
                              f" + {slack} ms detection slack", self._post_lock_frames(view, lock, end))
        if kind == "SAY_PHRASE":
            return self._decide_speech(st, spec, ep, red, view, lock, margin)
        if kind == "DURATION_OVER":
            return self._decide_duration(spec, ep, red, view, lock, margin)
        return self._decide_visual(m, st, spec, ep, view, lock)

    def _scan(self, st: _GState, view, spec, lock: int):
        rx = phrase_regex(spec["params"]["phrase"])
        for t in sorted(view.transcripts, key=lambda t: t.sequence):
            if t.sequence <= st.scanned_seq:
                continue
            st.scanned_seq = t.sequence
            if t.media_end_ms <= lock:
                continue
            if st.first_post_lock_start is None:
                st.first_post_lock_start = t.media_start_ms
            st.cov_end_ms = max(st.cov_end_ms or 0, t.media_end_ms)
            st.last_window = t
            if rx.search(t.text or "") and len(st.hits) < 10:
                st.hits.append(t)

    def _decide_speech(self, st, spec, ep, red, view, lock: int, margin: int) -> Verdict | None:
        end = ep.end_ms
        refs_tr = self.cfg.ai_evidence_refs == "frames+transcripts"

        def gap_in(a, b):
            return any(s < b and e > a for s, e in view.gaps)

        margin_covered = (st.first_post_lock_start is not None
                          and st.first_post_lock_start <= lock + COVERAGE_START_SLACK_MS
                          and not gap_in(lock, lock + margin + 4_000))
        for h in sorted(st.hits, key=lambda t: t.media_start_ms):
            if end is not None and h.media_start_ms >= end:
                continue  # after the episode: not part of this market
            cite = ([h] if h.media_start_ms >= lock else []) + self._post_lock_frames(view, lock, h.media_end_ms, 1)
            if h.media_start_ms <= lock + margin:
                return self._void(f"PHRASE_IN_MARGIN: transcript seq {h.sequence} "
                                  f"[{h.media_start_ms}-{h.media_end_ms}] ms vs lock {lock} + {margin}", cite)
            if end is not None and h.media_end_ms > end:
                return self._void(f"PHRASE_AT_END_BOUNDARY: transcript seq {h.sequence} spans the end at {end} ms",
                                  cite)
            if end is None and (red.last_t_ms is None or h.media_end_ms > red.last_t_ms):
                return None  # wait until an observation confirms the episode was still running then
            if not margin_covered:
                return self._void("COVERAGE_GAP_IN_MARGIN: transcript hole between lock and lock + M", cite)
            if refs_tr and h.ack_mono is None:
                return None  # cite the transcript observation once the API has accepted it
            frame = self._post_lock_frames(view, lock, h.media_end_ms, 1)
            return Verdict("YES", {"YES": True, "NO": False}, ([h] if refs_tr else []) + frame,
                           f"phrase heard in transcript seq {h.sequence} at {h.media_start_ms}-{h.media_end_ms} ms")
        if end is None:
            return None
        if st.cov_end_ms is None or st.cov_end_ms < end:
            return None  # the transcript has not reached the episode end yet
        if gap_in(lock, end) or st.first_post_lock_start is None or \
                st.first_post_lock_start > lock + COVERAGE_START_SLACK_MS:
            return self._void("COVERAGE_GAP: transcript hole between lock and the episode end",
                              self._post_lock_frames(view, lock, end))
        last = st.last_window if refs_tr and getattr(st.last_window, "ack_mono", None) is not None else None
        return Verdict("NO", {"YES": False, "NO": True},
                       self._post_lock_frames(view, lock, end) + ([last] if last else []),
                       f"episode ended at {end} ms ({ep.end_kind}) without the phrase; transcript covered "
                       f"{lock}-{st.cov_end_ms} ms")

    def _decide_duration(self, spec, ep, red, view, lock: int, margin: int) -> Verdict | None:
        d_ms = int(spec["params"]["duration_s"]) * 1000
        band = int(self.cfg.ai_duration_band_s * 1000)
        if ep.end_ms is None:
            if red.last_t_ms is not None and red.last_t_ms - ep.start_ms > d_ms + band:
                decisive = ep.start_ms + d_ms + band
                if decisive <= lock + margin:
                    return self._void("RESULT_BEFORE_LOCK_MARGIN: duration passed the line too early",
                                      self._post_lock_frames(view, lock, red.last_t_ms))
                return Verdict("YES", {"YES": True, "NO": False},
                               self._post_lock_frames(view, lock, red.last_t_ms, 1),
                               f"still in progress {(red.last_t_ms - ep.start_ms) // 1000} s after start "
                               f"(line {d_ms // 1000} s + {band // 1000} s band)")
            return None
        near = self._post_lock_frames(view, lock, ep.end_ms)
        if ep.end_kind != "RESULT_SEEN":
            return self._void(f"END_NOT_SEEN_AS_RESULT ({ep.end_kind})", near)
        dur = ep.end_ms - ep.start_ms
        if abs(dur - d_ms) <= band:
            return self._void(f"WITHIN_BAND: duration {dur // 1000} s within {band // 1000} s of {d_ms // 1000} s",
                              near)
        yes = dur > d_ms
        return Verdict("YES" if yes else "NO", {"YES": yes, "NO": not yes}, near,
                       f"duration {dur // 1000} s vs line {d_ms // 1000} s")

    def _decide_visual(self, m, st, spec, ep, view, lock: int) -> Verdict | None:
        end = ep.end_ms
        if end is None or m.state != "EVALUATING":
            return None
        frames = sorted((f for f in view.frames if f.evidence_id and f.media_ms >= max(lock, end - READ_FROM_BEFORE_END_MS)),
                        key=lambda f: f.media_ms)
        if len(frames) < 2 or frames[-1].media_ms < end + POST_END_WAIT_MS:
            return None
        if st.rounds >= MAX_READ_ROUNDS:
            return self._void(f"NO_AGREED_RESULT after {st.rounds} read rounds", self._post_lock_frames(view, lock, end))
        if frames[-1].media_ms < st.last_round_frame_ms + READ_ROUND_GAP_MS:
            return None
        sets = [_spread(frames[0::2]), _spread(frames[1::2])]  # different frames for reader A and reader B
        trs = [t for t in view.transcripts if t.media_start_ms >= max(lock, end - 20_000) and t.text.strip()][-12:]
        label = spec["params"].get("label") if spec["kind"] == "END_VALUE_AT_LEAST" else None
        prompts = [read_prompt(spec["unit"], label, transcript_lines(trs), [f.media_ms for f in fs]) for fs in sets]
        # Each reader keeps its own frames; if its model errors or is cooling down, the other reader model reads
        # those same frames (degraded model independence, never shared frames). Seen in the D37 end-to-end run:
        # gemini-3.1-flash-lite answered 504 on reader B and the market timed out on WAIT.
        chains = [[m] + [x for x in self.readers if x != m] for m in self.readers]
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="ai-reader") as ex:
            futs = [ex.submit(self._read_chain, chain, fs, pr) for chain, fs, pr in zip(chains, sets, prompts)]
            outs = [f.result() for f in futs]
        if not any(o.sent for o in outs):
            return None  # both gates refused (cooldown, budget or stop): no round used
        st.rounds += 1
        st.last_round_frame_ms = frames[-1].media_ms
        decision, reason, support, contradictions = decide_visual(
            spec["kind"], spec["params"], spec["success_cue"], spec["failure_cue"], [o.data for o in outs])
        self.trace.write({"role": "resolver", "profile": "generic", "outcome": "READS", "market_id": m.market_id,
                          "round": st.rounds, "decision": decision, "why": reason,
                          "reads": [{"model": o.model, "frames_ms": [f.media_ms for f in o.frames], "error": o.error,
                                     "latency_ms": o.latency_ms,
                                     "result_text": tp.sanitize((o.data or {}).get("result_text"), 80),
                                     "outcome_for_streamer": (o.data or {}).get("outcome_for_streamer"),
                                     "value_text": tp.sanitize((o.data or {}).get("value_text"), 24)} for o in outs],
                          "prompt_version": tp.RESOLVER_PROMPT_VERSION})
        cited = []
        for o in outs:
            d = o.data or {}
            hs = [h for h in (d.get("result_frames") or []) if isinstance(h, str)] + [str(d.get("value_frame") or "")]
            cited += [o.frames[int(h[1:]) - 1] for h in hs if re.fullmatch(r"F\d{1,2}", h) and 1 <= int(h[1:]) <= len(o.frames)]
        evidence = cited or [f for o in outs for f in o.frames]
        model = "+".join(o.model for o in outs)
        if decision == "WAIT":
            return Verdict("WAIT", dict(NONE_SUPPORT), evidence, reason, [], model) if self.cfg.ai_post_wait else None
        return Verdict(decision, support, evidence, reason, contradictions, model)

    def _read_chain(self, models: list, frames: list, prompt: str) -> ReadOut:
        """The first model that returns a valid read wins; a malformed answer is not retried on another model."""
        out = None
        for model in models:
            out = self._read(model, frames, prompt)
            if out.data is not None or out.error == "INVALID_SCHEMA":
                return out
        return out

    def _read(self, model: str, frames: list, prompt: str) -> ReadOut:
        for attempt in range(2):
            try:
                r = self.pool.call(model, role=RESOLVER, text=prompt, images=[f.jpeg for f in frames],
                                   schema=READ_SCHEMA, system=SYSTEM_RULES, media_resolution=None)
            except Unavailable as u:
                if u.reason == "RATE_LIMITED_LOCAL" and u.retry_in_s is not None and u.retry_in_s <= 8 and attempt == 0:
                    self.sleep(u.retry_in_s + 0.05)  # this model just served an observer call: wait, then read
                    continue
                return ReadOut(model, frames, None, False, "UNAVAILABLE:" + u.reason.split(":")[0])
            except CallError as e:
                return ReadOut(model, frames, None, True, e.kind)
            if not valid_read(r.data):
                return ReadOut(model, frames, None, True, "INVALID_SCHEMA", r.latency_ms)
            return ReadOut(model, frames, r.data, True, None, r.latency_ms)
        return ReadOut(model, frames, None, False, "UNAVAILABLE:RATE_LIMITED_LOCAL")

    # ---- posting ----------------------------------------------------------------------------------------
    def _post(self, m, st: _GState, v: Verdict, lock: int) -> str:
        cur = self.tracker.poll(force=True)
        if (cur is None or cur.market_id != m.market_id or cur.rules_version != m.rules_version
                or cur.state != "EVALUATING" or self.ctx.view().epoch != (m.lock_source_epoch or self.ctx.view().epoch)):
            st.done = cur is None or cur.market_id != m.market_id or cur.state not in NONTERMINAL
            return self._log("LATE_DROPPED", m, decision=v.decision, why=v.reason)
        refs, times = [], []
        for o in sorted(v.evidence, key=lambda o: getattr(o, "media_ms", getattr(o, "media_start_ms", 0))):
            if isinstance(o, cx.FrameObs) and o.evidence_id and o.media_ms >= lock:
                refs.append(o.evidence_id)
                times.append(o.media_ms)
            elif (isinstance(o, cx.TranscriptObs) and self.cfg.ai_evidence_refs == "frames+transcripts"
                  and o.ack_mono is not None and o.media_start_ms >= lock):
                refs.append(cx.obs_ref(o.epoch, o.sequence))
                times += [o.media_start_ms, o.media_end_ms]
        refs = list(dict.fromkeys(refs))[:20]
        if not refs:
            return "NO_POST_LOCK_EVIDENCE"
        body = {"schema_version": 1, "stream_id": self.stream_id, "source_epoch": m.lock_source_epoch or self.ctx.view().epoch,
                "resolution": {
                    "resolution_id": str(uuid.uuid4()), "market_id": m.market_id, "rules_version": m.rules_version,
                    "decision": v.decision, "evidence_ids": refs,
                    "media_interval": {"start_ms": min(times), "end_ms": max(times)},
                    "predicate_support": {"YES": bool(v.support["YES"]), "NO": bool(v.support["NO"])},
                    "contradictions": [tp.sanitize(c, 120) for c in v.contradictions][:5],
                    "reason": tp.sanitize(v.reason, 300), "model": v.model[:64],
                    "prompt_version": tp.RESOLVER_PROMPT_VERSION}}
        r = post_with_retries(self.api, "/v1/worker/resolutions", body, sleep=self.sleep)
        st.posts += 1
        status = (r.body or {}).get("status") if r.ok else None
        api_reason = (r.body or {}).get("reason") if r.ok else None
        meta = {"decision": v.decision, "why": v.reason, "model": v.model, "evidence_ids": refs,
                "resolution_id": body["resolution"]["resolution_id"], "http_status": r.status, "status": status,
                "api_reason": api_reason, "api_code": r.code, "lock_media_ms": lock}
        if not r.ok:
            st.next_at = self.clock() + 10.0
            return self._log("POST_FAILED:" + str(r.code or r.status or r.error), m, **meta)
        if status in ("SETTLED", "VOIDED", "PENDING_APPROVAL") or (
                status == "IGNORED" and api_reason in TERMINAL_IGNORED) or (
                v.decision != "WAIT" and status in (None, "DRY_RUN")):
            st.done = True
        elif status == "IGNORED":
            st.next_at = self.clock() + 10.0  # e.g. EVIDENCE_BEFORE_LOCK: retry later, bounded below
        if st.posts >= MAX_POSTS_PER_MARKET:
            st.done = True
        return self._log(f"POSTED:{v.decision}:{status or 'DRY_RUN'}", m, **meta)

    def _log(self, outcome: str, m, **kw) -> str:
        self.trace.write({"role": "resolver", "profile": "generic", "outcome": outcome, "market_id": m.market_id,
                          "rules_version": m.rules_version, "prompt_version": tp.RESOLVER_PROMPT_VERSION} | kw)
        log.info("generic resolver %s market=%s %s", outcome, m.market_id,
                 {k: kw.get(k) for k in ("decision", "status", "api_reason") if k in kw})
        return outcome


def _spread(frames: list, n: int = MAX_FRAMES_PER_READ) -> list:
    if len(frames) <= n:
        return list(frames)
    step = (len(frames) - 1) / (n - 1)
    return [frames[round(i * step)] for i in range(n)]
