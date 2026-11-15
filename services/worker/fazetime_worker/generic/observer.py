"""Stateless observer calls on a non-blocking cadence (D37).

* Single flight: at most one observer request is in the air. ``tick`` never queues: it skips the cycle while a
  call is running, while no new acknowledged frame is due, or while every model in the chain is cooling down,
  out of budget or stopped.
* Cadence in media time: a call is due when the newest acknowledged frame is ``ai_observer_interval_s`` (8 s)
  past the last observed frame while an episode is in progress, ``ai_observer_idle_interval_s`` (16 s) otherwise.
* Input: the latest 1-2 acknowledged frames, the transcript windows since the last call, and the reducer's
  snapshot. Output is only *collected* here; the runtime applies it through ``Reducer.apply`` on the AI thread.
* Model chain (``FAZETIME_AI_OBSERVER_MODELS``): one attempt per model, then the next model in the chain.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass

from ..gemini import CallError, Unavailable
from .models import NON_RESOLVER, ModelPool, is_gemma
from .prompts import OBS_SCHEMA, OBSERVER_PROMPT_VERSION, observer_prompt, valid_observation

log = logging.getLogger("fazetime.generic.observer")

MAX_TRANSCRIPT_WINDOWS = 12  # ~36 s of speech per call
SECOND_FRAME_GAP_MS = 3000  # the older of the two frames is at least this much earlier than the newest


@dataclass
class ObsResult:
    epoch: str
    t_ms: int  # media time of the newest frame sent
    frame_ms: list
    data: dict | None
    model: str | None
    latency_ms: int | None
    error: str | None = None


def default_spawn(fn):
    threading.Thread(target=fn, daemon=True, name="ai-observer").start()


def transcript_lines(transcripts: list) -> str:
    return "\n".join(f"T{i} [{t.media_start_ms / 1000:.0f}s] {t.text.strip()[:400]}"
                     for i, t in enumerate(transcripts, 1))


class Observer:
    def __init__(self, cfg, pool: ModelPool, trace=None, spawn=default_spawn, clock=time.monotonic):
        self.cfg, self.pool, self.trace, self.spawn, self.clock = cfg, pool, trace, spawn, clock
        self.chain = list(cfg.ai_observer_models)
        self.lock = threading.Lock()
        self.inflight = False
        self.pending: deque = deque(maxlen=4)
        self.epoch: str | None = None
        self.last_frame_ms: int | None = None
        self.last_tr_seq = 0
        self.counts: dict = {}
        self.served: dict = {}

    def reset(self, epoch: str | None):
        """New source epoch: cadence and transcript cursor restart; results of the old epoch are dropped."""
        with self.lock:
            self.epoch, self.last_frame_ms, self.last_tr_seq = epoch, None, 0
            self.pending.clear()

    def drain(self) -> list[ObsResult]:
        with self.lock:
            out = list(self.pending)
            self.pending.clear()
        return out

    def busy(self) -> bool:
        with self.lock:
            return self.inflight

    def _count(self, k: str) -> str:
        self.counts[k] = self.counts.get(k, 0) + 1
        return k

    def tick(self, view, red) -> str:
        if view.epoch is None or view.epoch != self.epoch:
            return "NO_EPOCH"
        if self.busy():
            return "BUSY"
        frames = sorted((f for f in view.frames if f.evidence_id), key=lambda f: f.media_ms)
        if not frames:
            return "NO_FRAMES"
        newest = frames[-1]
        interval_s = self.cfg.ai_observer_interval_s if red.in_progress() else self.cfg.ai_observer_idle_interval_s
        if self.last_frame_ms is not None and newest.media_ms < self.last_frame_ms + int(interval_s * 1000):
            return "NOT_DUE"
        chain = [m for m in self.chain if self.pool.ready(m, NON_RESOLVER)]
        if not chain:
            return self._count("COOLDOWN")  # every observer model is cooling down, stopped or out of budget
        older = [f for f in frames if f.media_ms <= newest.media_ms - SECOND_FRAME_GAP_MS]
        sent = ([older[-1]] if older else []) + [newest]
        trs = [t for t in view.transcripts if t.sequence > self.last_tr_seq and t.text.strip()]
        trs = trs[-MAX_TRANSCRIPT_WINDOWS:]
        frame_ms = [f.media_ms for f in sent]
        prompt = observer_prompt(red.snapshot(newest.media_ms), transcript_lines(trs), frame_ms)
        images = [f.jpeg for f in sent]
        self.last_frame_ms = newest.media_ms
        self.last_tr_seq = max([t.sequence for t in view.transcripts] + [self.last_tr_seq])
        epoch = view.epoch
        with self.lock:
            self.inflight = True

        def job():
            res = ObsResult(epoch, newest.media_ms, frame_ms, None, None, None, "ALL_MODELS_FAILED")
            try:
                for model in chain:
                    try:
                        r = self.pool.call(model, role=NON_RESOLVER, text=prompt, images=images, schema=OBS_SCHEMA,
                                           system=None, media_resolution=None if is_gemma(model) else "medium")
                    except Unavailable as u:
                        res.error = "UNAVAILABLE:" + u.reason.split(":")[0]
                        continue
                    except CallError as e:
                        res.error = f"{model}:{e.kind}"
                        continue  # one attempt per model, then the next model in the chain
                    if not valid_observation(r.data):
                        res.error = f"{model}:INVALID_SCHEMA"
                        continue
                    res = ObsResult(epoch, newest.media_ms, frame_ms, r.data, model, r.latency_ms)
                    break
            except Exception:  # never let a worker thread die silently; the cycle is a miss
                log.exception("observer call failed")
            finally:
                with self.lock:
                    if res.epoch == self.epoch:
                        self.pending.append(res)
                    self.inflight = False

        self.spawn(job)
        return self._count("STARTED")

    def note_applied(self, res: ObsResult, events: list):
        k = "OBSERVED" if res.data is not None else "MISS"
        self._count(k)
        if res.model:
            self.served[res.model] = self.served.get(res.model, 0) + 1
        if self.trace is not None:
            o = res.data or {}
            self.trace.write({"role": "observer", "outcome": k, "epoch": res.epoch, "media_ms": res.t_ms,
                              "frames_ms": res.frame_ms, "model": res.model, "latency_ms": res.latency_ms,
                              "error": res.error, "prompt_version": OBSERVER_PROMPT_VERSION,
                              "screen": o.get("screen"), "boundary": o.get("boundary"),
                              "outcome_for_streamer": o.get("outcome_for_streamer"),
                              "n_numbers": len(o.get("numbers") or []), "cue_present": bool(o.get("streamer_cue")),
                              "events": events})
