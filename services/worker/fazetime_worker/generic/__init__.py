"""Game-agnostic AI profile (D37, CONTRACTS §9.19): ``FAZETIME_AI_PROFILE=generic``. The h2h default is unchanged.

Observer -> Reducer (the only state writer) -> template proposer -> extract-then-decide resolver, ported from
``spikes/p4-generic``. One AI thread ticks every second: it applies finished observer answers through the reducer,
then runs the resolver, the proposer and (non-blocking) the next observer call. The API stays the only writer of
markets and money; model output is untrusted data validated by code.

§9.20 item 3: a ``StreamMeta`` thread (started with this one; never in TEST_FIXTURE mode) keeps the Twitch title,
category and channel from ``streamlink --json``. Each tick passes them to the observer and proposer prompts as one
labelled untrusted line, and the category names the activity until an observer answer does.
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from ..proposer import Registry, Trace
from ..resolver import HttpMarketSource, MarketTracker
from .models import ModelPool
from .observer import Observer, default_spawn
from .proposer import GenericProposer
from .reducer import Reducer
from .resolver import GenericResolver
from .stream_meta import StreamMeta

log = logging.getLogger("fazetime.generic")


class GenericAi(threading.Thread):
    def __init__(self, ctx, observer: Observer, proposer, resolver, registry: Registry, tick_s: float = 1.0,
                 stream: StreamMeta | None = None):
        super().__init__(daemon=True, name="ai-generic")
        self.ctx, self.observer, self.proposer, self.resolver, self.registry = ctx, observer, proposer, resolver, registry
        self.tick_s = tick_s
        self.stream = stream  # None in TEST_FIXTURE mode or with FAZETIME_AI_STREAM_CONTEXT=0
        self.reducer = Reducer(None)
        self.last_obs: dict | None = None
        self.run_id: str | None = None
        self.stop_flag = threading.Event()
        self.last: dict = {}

    def _sync(self, view):
        if view.epoch != self.reducer.epoch:  # an epoch change resets all game state
            self.reducer, self.last_obs = Reducer(view.epoch), None
            self.observer.reset(view.epoch)
        if view.run_id and view.run_id != self.run_id:
            previous, self.run_id = self.run_id, view.run_id
            self.registry.set_run(view.run_id)  # run-scoped fingerprints (the API forgets them on reset)
            if previous is not None:
                if self.proposer is not None:
                    self.proposer.on_new_run()
                self.reducer.last_template = None
                if self.reducer.cur is not None:
                    self.reducer.cur.markets = self.reducer.cur.proposer_calls = 0

    def step(self) -> dict:
        view = self.ctx.view()
        self._sync(view)
        pool = self.observer.pool
        if pool is not None and pool.stopped():  # AI_STOP: no model calls and no proposals or resolutions at all
            self.last = {"observer": "STOPPED", "proposer": "STOPPED", "resolver": "STOPPED"}
            return dict(self.last)
        line = ""
        if self.stream is not None:  # untrusted Twitch context; the category only seeds the activity name
            self.reducer.category = (self.stream.category() or "")[:60] or None
            line = self.stream.line()
        for res in self.observer.drain():
            if res.epoch != self.reducer.epoch:
                continue  # late answer for an old epoch
            events = self.reducer.apply(res.data, res.t_ms, res.frame_ms) if res.data is not None else []
            if res.data is not None:
                self.last_obs = res.data
            self.observer.note_applied(res, events)
        if self.resolver is not None:
            self.last["resolver"] = self.resolver.tick(view, self.reducer)
        if self.proposer is not None:
            self.last["proposer"] = self.proposer.tick(self.ctx.view(), self.reducer, self.last_obs, line)
        self.last["observer"] = self.observer.tick(self.ctx.view(), self.reducer, line)
        return dict(self.last)

    def run(self):
        if self.stream is not None and self.stream.ident is None:
            self.stream.start()  # its own thread: the Streamlink call never runs on this loop
        try:
            while not self.stop_flag.is_set():
                try:
                    self.step()
                except Exception:
                    log.exception("generic AI tick failed")
                self.stop_flag.wait(self.tick_s)
        finally:
            if self.stream is not None:
                self.stream.stop()

    def status(self) -> dict:
        r, e = self.reducer, self.reducer.cur
        return {"profile": "generic", "models": self.pool_status(), "last": dict(self.last),
                "observer": dict(self.observer.counts), "observer_served_by": dict(self.observer.served),
                "proposer": getattr(self.proposer, "counts", None), "resolver": getattr(self.resolver, "counts", None),
                "stream_context": None if self.stream is None else self.stream.status(),
                "state": {"epoch": r.epoch, "activity": r.activity, "unit": r.unit, "observations": r.n_obs,
                          "last_t_ms": r.last_t_ms, "episodes": len(r.episodes),
                          "current": None if e is None else {"idx": e.idx, "phase": e.phase, "start_ms": e.start_ms,
                                                             "end_ms": e.end_ms, "end_kind": e.end_kind,
                                                             "markets": e.markets, "proposer_calls": e.proposer_calls}}}

    def pool_status(self) -> dict:
        return self.observer.pool.status()


def build_generic_ai(cfg, ctx, api, stream_id: str, data_dir: Path | None, transport_factory=None,
                     clock=time.monotonic, wall=time.time, sleep=time.sleep, spawn=default_spawn,
                     market_source=None, stream_fetch=None):
    """Returns (GenericAi thread, ModelPool, MarketTracker). Nothing is started here. ``stream_fetch`` replaces the
    Streamlink metadata call (tests); TEST_FIXTURE mode (``test_source_cmd``) builds no fetcher at all."""
    pool = ModelPool(cfg, data_dir, transport_factory=transport_factory, clock=clock, wall=wall)
    if market_source is None and cfg.ai_market_source != "none":
        market_source = HttpMarketSource(api, stream_id, cfg.resolver_session_token, cfg.ai_market_source)
    tracker, registry = MarketTracker(market_source, clock=clock), Registry()
    trace = Trace(Path(data_dir) / "ai_trace.jsonl" if data_dir else None)
    observer = Observer(cfg, pool, trace, spawn=spawn, clock=clock)
    prop = GenericProposer(cfg, ctx, pool, api, stream_id, tracker, registry, trace, clock=clock, sleep=sleep) \
        if cfg.ai_proposer else None
    res = GenericResolver(cfg, ctx, pool, api, stream_id, tracker, trace, clock=clock, wall=wall, sleep=sleep) \
        if cfg.ai_resolver else None
    stream = StreamMeta(cfg, trace, fetch=stream_fetch) \
        if getattr(cfg, "ai_stream_context", True) and not cfg.test_source_cmd else None
    return GenericAi(ctx, observer, prop, res, registry, stream=stream), pool, tracker


__all__ = ["GenericAi", "StreamMeta", "build_generic_ai"]
