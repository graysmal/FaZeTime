"""P5 resolver: YES / NO / WAIT / UNRESOLVABLE for the market this stream locked (CONTRACTS §9.17 part 4).

* The worker learns the market from a ``MarketSource`` (``HttpMarketSource`` tries the worker route
  ``GET /v1/worker/market`` and then, if a read-only session token is configured, the stream snapshot;
  tests use ``StaticMarketSource``). It never changes market state itself.
* Only evidence from the market's lock epoch and **after** ``lock_media_ms`` is used. Frames are cropped to the
  in-game chat region (death message) at native resolution; transcripts are post-lock spans.
* Calls are triggered by a deterministic spoken cue ("<name> wins", "slain", cancel words) or a bounded
  periodic visual check; WAIT backs off. Each market has a call cap and stops before ``resolve_by_utc``.
* The model reads the frames; the decision is then recomputed deterministically under the evidence rule:
  DEATH_MESSAGE_REQUIRED (default) needs a cited death message naming one subject killed by the other; spoken
  "<name> wins" (checked on the transcript text itself) can only corroborate or contradict. Any contradiction,
  a coverage gap before the decisive cue, or a cited cancellation cue -> UNRESOLVABLE. Anything else -> WAIT.
  Elapsed time is never a loss; the API's sweeper voids at the deadline.
* A reply that arrives after the market or epoch changed is dropped (``LATE_DROPPED``); the API also ignores it.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import context as cx
from .gemini import SYSTEM_RULES, CallError, Unavailable
from .proposer import Trace, model_schema, post_with_retries, sanitize

log = logging.getLogger("fazetime.resolver")

PROMPT_VERSION = "h2h-resolver-1.0"
# API IGNORED reasons after which this market can never accept a resolution from this worker
TERMINAL_IGNORED = {"UNKNOWN_MARKET", "MARKET_TERMINAL", "NOT_AI_MARKET", "STALE_MARKET", "EPOCH_MISMATCH",
                    "DEADLINE", "DUPLICATE", "SUPERSEDED", "NO_LOCK_POSITION"}
NONTERMINAL = ("OPEN", "LOCKED", "EVALUATING")

TASK = (
    "TASK (resolver for a locked market): the question concerns a Minecraft 1v1 between subject_a and subject_b. "
    "Look ONLY at the images and transcript spans in DATA, all of which come after betting closed. Report whether "
    "an in-game chat death message is legible (for example '<killed> was slain by <killer>'); copy the text you "
    "read into death_message.text_read and give the killed and killer names exactly as shown. Report whether a "
    "transcript span says who won. decision: YES if subject_a clearly won, NO if subject_b clearly won, WAIT if "
    "the fight is not decided yet or the result is not legible, UNRESOLVABLE only for a draw, an abandoned or "
    "restarted fight, or evidence that contradicts itself. Names may be mis-heard ('face Gavin' = FaZeGavin). "
    "Never guess; celebration, shouting or elapsed time are not results."
)


class DeathMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seen: bool
    frame_handle: str = Field(description="F# where it is legible, or empty string")
    text_read: str = Field(description="The chat line as read, or empty string")
    killed: str = Field(description="Name of the player who died, or empty string")
    killer: str = Field(description="Name of the killer, or empty string")


class SpokenWinner(BaseModel):
    model_config = ConfigDict(extra="forbid")
    heard: bool
    transcript_handle: str = Field(description="T# that states the winner, or empty string")
    winner: str = Field(description="Winner name, or empty string")


class ResolutionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["YES", "NO", "WAIT", "UNRESOLVABLE"]
    death_message: DeathMessage
    spoken_winner: SpokenWinner
    cancellation_cue: Literal["NONE", "DRAW", "NO_CONTEST", "ABANDONED", "RESTARTED"]
    cancellation_handles: list[str] = Field(max_length=4)
    contradictions: list[str] = Field(max_length=5)
    evidence_handles: list[str] = Field(max_length=8)
    reason: str = Field(description="Under 300 characters")


# ---- market view + sources --------------------------------------------------------------------------------
@dataclass
class MarketView:
    market_id: str
    rules_version: int
    state: str
    question: str = ""
    yes_label: str = ""
    no_label: str = ""
    lock_source_epoch: str | None = None
    lock_media_ms: int | None = None
    locked_at_utc: str | None = None
    resolve_by_utc: str | None = None
    origin: str | None = None
    criteria: dict | None = None

    @classmethod
    def from_json(cls, m: dict | None):
        if not m or not m.get("market_id"):
            return None
        return cls(m["market_id"], int(m.get("rules_version") or 1), str(m.get("state")), m.get("question") or "",
                   m.get("yes_label") or "", m.get("no_label") or "", m.get("lock_source_epoch"),
                   m.get("lock_media_ms"), m.get("locked_at_utc"), m.get("resolve_by_utc"), m.get("origin"),
                   m.get("criteria"))


class StaticMarketSource:
    """Config/test source: whatever was ``set`` is the current market."""

    def __init__(self, market: MarketView | None = None):
        self.market = market

    def set(self, market: MarketView | None):
        self.market = market

    def fetch(self):
        return self.market


class HttpMarketSource:
    """GET /v1/worker/market?stream_id= (proposed worker route), else the snapshot with a read-only session
    bearer (FAZETIME_RESOLVER_SESSION_TOKEN). Neither available -> None (resolver idle; operator resolves)."""

    def __init__(self, api, stream_id: str, session_token: str | None = None, mode: str = "auto"):
        self.api, self.stream_id, self._session = api, stream_id, session_token
        self.worker_route = mode in ("auto", "worker")
        self.snapshot = mode in ("auto", "snapshot") and bool(session_token)
        self.last_error: str | None = None

    def __repr__(self):
        return "HttpMarketSource(<redacted>)"

    def fetch(self):
        if self.worker_route:
            res = self.api.get_json(f"/v1/worker/market?stream_id={self.stream_id}")
            if res.ok:
                body = res.body or {}
                return MarketView.from_json(body.get("market") if "market" in body else body)
            if res.status in (404, 405, 501) or res.code in ("CAPABILITY_UNAVAILABLE", "NOT_FOUND"):
                self.worker_route = False
                log.warning("worker market route unavailable (%s); %s", res.status,
                            "using snapshot" if self.snapshot else "resolver needs a market source")
            else:
                self.last_error = f"{res.status or res.error} {res.code or ''}".strip()
                raise RuntimeError(self.last_error)
        if self.snapshot:
            res = self.api.get_json(f"/v1/streams/{self.stream_id}/snapshot", bearer=self._session)
            if not res.ok:
                self.last_error = f"snapshot {res.status or res.error} {res.code or ''}".strip()
                raise RuntimeError(self.last_error)
            return MarketView.from_json((res.body or {}).get("market"))
        return None


class MarketTracker:
    """Caches the current market; polls every 2 s while one is nonterminal (or was just proposed), else 5 s."""

    def __init__(self, source, clock=time.monotonic):
        self.source, self.clock = source, clock
        self.current: MarketView | None = None
        self.next_poll = -1e18
        self.errors = 0
        self.ok = 0

    def poke(self):
        self.next_poll = -1e18

    def poll(self, force: bool = False) -> MarketView | None:
        now = self.clock()
        if self.source is None or (not force and now < self.next_poll):
            return self.current
        try:
            self.current = self.source.fetch()
            self.ok += 1
        except Exception as exc:  # keep the last view; a failed poll never invents a state
            self.errors += 1
            log.debug("market poll failed: %s", type(exc).__name__)
        self.next_poll = now + (2.0 if self.nonterminal() else 5.0)
        return self.current

    def nonterminal(self) -> bool:
        return self.current is not None and self.current.state in NONTERMINAL


def _parse_utc(s: str | None) -> float | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


def derive_lock_ms(view: cx.EpochView, locked_at_utc: str | None, margin_ms: int = 2000) -> int | None:
    """Fallback when the API view has no lock_media_ms: last media this worker had captured by the lock time."""
    if not locked_at_utc:
        return None
    ends = [t.media_end_ms for t in view.transcripts if t.captured_at_utc <= locked_at_utc]
    ends += [f.media_ms for f in view.frames if f.captured_at_utc <= locked_at_utc]
    return max(ends) + margin_ms if ends else None


@dataclass
class _MState:
    calls: int = 0
    next_at: float = -1e18
    backoff_s: float = 0.0
    last_seq: int = 0
    last_cue_seq: int = 0
    done: bool = False


class Resolver:
    def __init__(self, cfg, ctx: cx.ContextBuffer, gemini, api, stream_id: str, tracker: MarketTracker, registry,
                 transform=cx.identity_transform, trace: Trace | None = None, clock=time.monotonic,
                 wall=time.time, sleep=time.sleep):
        self.cfg, self.ctx, self.gemini, self.api, self.stream_id = cfg, ctx, gemini, api, stream_id
        self.tracker, self.registry, self.transform = tracker, registry, transform
        self.trace = trace or Trace(None)
        self.clock, self.wall, self.sleep = clock, wall, sleep
        self.participants = list(cfg.ai_participants)
        self.markets: dict = {}
        self.counts: dict = {}

    def _count(self, outcome: str) -> str:
        key = outcome.split(":")[0]
        self.counts[key] = self.counts.get(key, 0) + 1
        return outcome

    def subjects(self, m: MarketView) -> tuple | None:
        s = self.registry.subjects_for(m) if self.registry is not None else None
        if s:
            return s
        a, b = cx.canon_name(m.yes_label, self.participants), cx.canon_name(m.no_label, self.participants)
        return (a, b) if a and b and a != b else None

    def tick(self) -> str:
        m = self.tracker.poll()
        if m is None or m.state not in ("LOCKED", "EVALUATING"):
            return "IDLE"
        st = self.markets.setdefault((m.market_id, m.rules_version), _MState())
        if st.done:
            return "DONE"
        view = self.ctx.view()
        if m.lock_source_epoch and m.lock_source_epoch != view.epoch:
            st.done = True  # an epoch change voids the market (§9.4); never resolve across epochs
            return self._count("EPOCH_MISMATCH")
        if m.state != "EVALUATING":
            return "WAIT_EVALUATING"
        lock_ms = m.lock_media_ms if m.lock_media_ms is not None else derive_lock_ms(view, m.locked_at_utc)
        if lock_ms is None:
            return "NO_LOCK_POSITION"
        subj = self.subjects(m)
        if subj is None:
            return "NO_SUBJECTS"
        deadline = _parse_utc(m.resolve_by_utc)
        if deadline is not None and self.wall() >= deadline - 5.0:
            return "PAST_DEADLINE"
        post_tr = [t for t in view.transcripts if t.media_start_ms >= lock_ms]
        post_fr = [f for f in view.frames if f.media_ms > lock_ms and f.evidence_id]
        if not post_fr and not post_tr:
            return "NO_POST_LOCK_DATA"
        cue = [t for t in post_tr if t.sequence > st.last_cue_seq and
               (cx.spoken_winners(t.text) or cx.has_slain(t.text) or cx.has_cancel_cue(t.text))]
        now = self.clock()
        newest = max([o.sequence for o in post_tr + post_fr] or [0])
        if not cue and now < st.next_at:
            return "NOT_DUE"
        if newest <= st.last_seq:
            return "NO_NEW_DATA"
        if st.calls >= self.cfg.ai_resolver_max_calls_per_market:
            return "CALL_CAP"
        frames = self._pick_frames(post_fr, cue, st)
        if not frames:
            return "NO_FRAME_EVIDENCE"
        return self._count(self._resolve(m, st, subj, lock_ms, view, post_tr, frames, cue, newest))

    def _pick_frames(self, post_fr, cue, st) -> list:
        n = max(1, self.cfg.ai_resolver_frames)
        if cue:
            c = cue[-1].media_start_ms
            near = [f for f in post_fr if c - 12_000 <= f.media_ms <= c + 4_000]
            pool = near or post_fr[-n:]
        else:
            pool = [f for f in post_fr if f.sequence > st.last_seq] or post_fr[-1:]
        if len(pool) <= n:
            return pool
        step = (len(pool) - 1) / (n - 1) if n > 1 else 0
        return [pool[round(i * step)] for i in range(n)] if n > 1 else pool[-1:]

    def _resolve(self, m, st, subj, lock_ms, view, post_tr, frames, cue, newest) -> str:
        a, b = subj
        trs = [t for t in post_tr if t.media_end_ms >= (view.media_now_ms or 0) - self.cfg.ai_transcript_window_ms]
        specs = [(None, tuple(self.cfg.ai_chat_crop), "chat_crop")] * len(frames)
        built = cx.build(view, role="resolver", transcripts=trs, frames=frames, frame_specs=specs,
                         state={"known_participants": self.participants, "subject_a": a, "subject_b": b,
                                "question": m.question[:200], "lock_media_ms": lock_ms,
                                "predicates": {"YES": f"{a} wins (death message shows {b} killed by {a})",
                                               "NO": f"{b} wins (death message shows {a} killed by {b})"}},
                         transform=self.transform)
        now = self.clock()
        try:
            res = self.gemini.generate_json(system=SYSTEM_RULES + "\n\n" + TASK, parts=built.parts,
                                            schema=model_schema(ResolutionOut),
                                            media_resolution=self.cfg.ai_resolver_media_resolution,
                                            role="resolver")
        except Unavailable as u:
            return "GEMINI_UNAVAILABLE:" + u.reason
        except CallError as e:
            st.calls += 1
            st.next_at = now + (60.0 if e.kind == "QUOTA" else 15.0)
            return self._log("QUOTA_PAUSED" if e.kind == "QUOTA" else "MODEL_ERROR:" + e.kind, m)
        st.calls += 1
        st.last_seq = newest
        if cue:
            st.last_cue_seq = max(t.sequence for t in cue)
        meta = {"model": self.gemini.model, "model_version": res.model_version, "latency_ms": res.latency_ms,
                "media_resolution": self.cfg.ai_resolver_media_resolution or "default",
                "usage": res.usage, "context": built.meta, "lock_media_ms": lock_ms,
                "handles": {h: [o.sequence, getattr(o, "media_ms", getattr(o, "media_start_ms", None))]
                            for h, o in built.handles.items()}}
        try:
            out = ResolutionOut.model_validate(res.data)
        except ValidationError:
            self._backoff(st)
            return self._log("MALFORMED", m, **meta)
        meta["model_decision"] = out.decision
        meta["death_message"] = out.death_message.model_dump() | {"text_read": sanitize(out.death_message.text_read, 120)}
        decision, support, contradictions, handles, why = self.decide(out, built, a, b, trs, view.gaps, lock_ms)
        meta |= {"decision": decision, "why": why, "support": support}
        # late-reply guard: the market and epoch must still be the ones this context was built for
        cur = self.tracker.poll(force=True)
        if (cur is None or cur.market_id != m.market_id or cur.rules_version != m.rules_version
                or cur.state != "EVALUATING" or self.ctx.view().epoch != built.epoch):
            st.done = cur is None or cur.market_id != m.market_id or cur.state not in NONTERMINAL
            return self._log("LATE_DROPPED", m, **meta)
        if decision == "WAIT":
            self._backoff(st)
            if not self.cfg.ai_post_wait:
                return self._log("WAIT_LOCAL", m, **meta)
        evidence_objs = built.frames(handles) or frames[-1:]
        evidence = [f.evidence_id for f in evidence_objs]
        if self.cfg.ai_evidence_refs == "frames+transcripts":
            evidence += [cx.obs_ref(t.epoch, t.sequence) for t in built.transcripts(handles) if t.ack_mono is not None]
        times = [f.media_ms for f in evidence_objs] + [x for t in built.transcripts(handles)
                                                       for x in (t.media_start_ms, t.media_end_ms)]
        reason = sanitize(f"{why}. {out.reason}", 300)
        body = {"schema_version": 1, "stream_id": self.stream_id, "source_epoch": built.epoch, "resolution": {
            "resolution_id": str(uuid.uuid4()), "market_id": m.market_id, "rules_version": m.rules_version,
            "decision": decision, "evidence_ids": evidence[:20],
            "media_interval": {"start_ms": min(times), "end_ms": max(times)},
            "predicate_support": support, "contradictions": [sanitize(c, 120) for c in contradictions][:5],
            "reason": reason, "model": self.gemini.model[:64], "prompt_version": PROMPT_VERSION}}
        r = post_with_retries(self.api, "/v1/worker/resolutions", body, sleep=self.sleep)
        status = (r.body or {}).get("status") if r.ok else None
        meta |= {"resolution_id": body["resolution"]["resolution_id"], "evidence_ids": evidence,
                 "http_status": r.status, "status": status, "api_code": r.code}
        if not r.ok:
            self._backoff(st)
            return self._log("POST_FAILED:" + str(r.code or r.status or r.error), m, **meta)
        api_reason = (r.body or {}).get("reason")
        meta["api_reason"] = api_reason
        if status in ("SETTLED", "VOIDED", "PENDING_APPROVAL") or (
                status == "IGNORED" and api_reason in TERMINAL_IGNORED) or (
                decision != "WAIT" and status in (None, "DRY_RUN")):
            st.done = True
        elif status == "IGNORED":
            self._backoff(st)  # e.g. EVIDENCE_BEFORE_LOCK: retry later with newer evidence, within the call cap
        return self._log(f"POSTED:{decision}:{status or 'DRY_RUN'}", m, **meta)

    def _backoff(self, st):
        st.backoff_s = min(30.0, max(self.cfg.ai_resolver_poll_s, st.backoff_s * 1.5 or self.cfg.ai_resolver_poll_s))
        st.next_at = self.clock() + st.backoff_s

    def decide(self, out: ResolutionOut, built: cx.BuiltContext, a: str, b: str, trs: list, gaps: list,
               lock_ms: int):
        """Deterministic decision under the evidence rule. Returns (decision, support, contradictions,
        evidence_handles, why)."""
        contradictions = [c for c in out.contradictions if c.strip()]
        cited = [h for h in out.evidence_handles if h in built.handles]
        # visual: the model's reading of a cited frame, mapped to the two subjects
        dm = out.death_message
        vis_yes = vis_no = False
        dm_frame = None
        if dm.seen and dm.frame_handle in built.handles and built.frames([dm.frame_handle]):
            dm_frame = built.handles[dm.frame_handle]
            killer, killed = cx.canon_name(dm.killer, [a, b]), cx.canon_name(dm.killed, [a, b])
            if killer == a and killed == b:
                vis_yes = True
            elif killer == b and killed == a:
                vis_no = True
            else:
                contradictions.append("death message does not name one subject killed by the other")
        # spoken: recomputed on the transcript text itself (the model's claim alone is not used)
        spoken = {}
        for h, o in built.handles.items():
            if isinstance(o, cx.TranscriptObs):
                for w in cx.spoken_winners(o.text) & {a, b}:
                    spoken.setdefault(w, []).append(h)
        sp_yes, sp_no = a in spoken, b in spoken
        yes = vis_yes or (sp_yes and self.cfg.ai_resolve_rule == "DEATH_OR_SPOKEN")
        no = vis_no or (sp_no and self.cfg.ai_resolve_rule == "DEATH_OR_SPOKEN")
        handles = ([dm.frame_handle] if dm_frame else []) + spoken.get(a, []) + spoken.get(b, []) + cited
        handles = list(dict.fromkeys(handles))
        cue_ms = None
        if dm_frame is not None:
            cue_ms = dm_frame.media_ms
        elif spoken:
            cue_ms = min(built.handles[h].media_start_ms for hs in spoken.values() for h in hs)
        # cancellation: only when a cited transcript really contains a cancellation word
        cancel_h = [h for h in out.cancellation_handles if h in built.handles
                    and isinstance(built.handles[h], cx.TranscriptObs) and cx.has_cancel_cue(built.handles[h].text)]
        if out.cancellation_cue != "NONE" and cancel_h:
            return "UNRESOLVABLE", {"YES": False, "NO": False}, contradictions + [
                f"cancellation cue {out.cancellation_cue}"], list(dict.fromkeys(cancel_h + handles)), \
                "cancellation cue in speech"
        if (vis_yes or sp_yes) and (vis_no or sp_no):
            return "UNRESOLVABLE", {"YES": True, "NO": True}, contradictions + [
                "evidence supports both sides"], handles, "contradictory evidence"
        if (yes or no) and cue_ms is not None and any(s < cue_ms and e > lock_ms for s, e in gaps):
            return "UNRESOLVABLE", {"YES": yes, "NO": no}, contradictions + [
                "coverage gap between lock and the decisive cue"], handles, "coverage gap before decisive cue"
        if yes and out.decision == "YES":
            return "YES", {"YES": True, "NO": False}, contradictions, handles, f"{a} wins per cited evidence"
        if no and out.decision == "NO":
            return "NO", {"YES": False, "NO": True}, contradictions, handles, f"{b} wins per cited evidence"
        if out.decision in ("YES", "NO"):
            why = "model answer not supported by the evidence rule"
        elif out.decision == "UNRESOLVABLE":
            why = "model UNRESOLVABLE without a verified contradiction or cancellation cue"
        else:
            why = "no decisive cue yet"
        return "WAIT", {"YES": False, "NO": False}, contradictions, handles, why

    def _log(self, outcome, m: MarketView, **kw):
        self.trace.write({"role": "resolver", "outcome": outcome, "market_id": m.market_id,
                          "rules_version": m.rules_version, "prompt_version": PROMPT_VERSION} | kw)
        log.info("resolver %s market=%s %s", outcome, m.market_id,
                 {k: kw.get(k) for k in ("why", "latency_ms", "status") if k in kw})
        return outcome


class AiThread(threading.Thread):
    """Runs proposer + resolver ticks serially (one model call at a time) off the media threads."""

    def __init__(self, proposer, resolver, tick_s: float = 1.0):
        super().__init__(daemon=True, name="ai")
        self.proposer, self.resolver, self.tick_s = proposer, resolver, tick_s
        self.stop_flag = threading.Event()
        self.last: dict = {}

    def run(self):
        while not self.stop_flag.is_set():
            for name, part in (("resolver", self.resolver), ("proposer", self.proposer)):
                if part is None:
                    continue
                try:
                    self.last[name] = part.tick()
                except Exception:
                    log.exception("%s tick failed", name)
            self.stop_flag.wait(self.tick_s)
