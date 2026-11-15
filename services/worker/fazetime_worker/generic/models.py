"""One ``Gate`` and one ``GeminiClient`` per model id (D20 free tier; D37/D38).

Each model has its own free-tier quota (500 RPD for each Flash-Lite model, 14.4K for Gemma 4), so each gets its
own persisted Pacific-day counter ``<data_dir>/gemini_usage_<model>.json`` with ``FAZETIME_AI_DAILY_BUDGET``
requests. All gates honour the same stop switch (``FAZETIME_AI_STOP=1`` or ``<data_dir>/AI_STOP``). On a model
that also serves as an evidence reader, ``FAZETIME_AI_RESOLVER_RESERVE`` of the budget is kept for reader calls:
observer and proposer requests stop at budget minus reserve (the existing Gate semantics, per model).

Gemma models take no system instruction (HTTP 500 when one is sent) and no ``media_resolution``. There is no
retry here: one attempt per call; callers fall back along their own model chain.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..gemini import Gate, GeminiClient

RESOLVER = "resolver"  # Gate role that may use the whole budget (evidence reads)
NON_RESOLVER = "proposer"  # Gate role limited to budget - reserve (observer and proposer calls)


def is_gemma(model: str) -> bool:
    return model.lower().startswith("gemma")


def usage_file(data_dir: Path, model: str) -> Path:
    return Path(data_dir) / f"gemini_usage_{re.sub(r'[^A-Za-z0-9_-]', '_', model)}.json"


class ModelPool:
    def __init__(self, cfg, data_dir: Path | None, transport_factory=None, clock=None, wall=None):
        self.models = list(dict.fromkeys(list(cfg.ai_observer_models) + [cfg.ai_proposer_model]
                                         + list(cfg.ai_reader_models)))
        readers = set(cfg.ai_reader_models)
        reserve = cfg.ai_resolver_reserve_requests() if cfg.ai_resolver else 0
        self.clients: dict[str, GeminiClient] = {}
        for m in self.models:
            kw = {}
            if clock is not None:
                kw["clock"] = clock
            if wall is not None:
                kw["wall"] = wall
            gate = Gate(cfg.ai_daily_budget, cfg.ai_min_interval_s,
                        usage_file(data_dir, m) if data_dir else None,
                        Path(data_dir) / "AI_STOP" if data_dir else None,
                        resolver_reserve=reserve if m in readers else 0, **kw)
            transport = transport_factory(m) if transport_factory else None
            self.clients[m] = GeminiClient(gate, transport=transport, model=m, timeout_s=cfg.ai_timeout_s,
                                           max_output_tokens=max(cfg.ai_max_output_tokens, 1500),
                                           media_resolution=None,
                                           thinking_level=None if is_gemma(m) else cfg.ai_thinking_level)

    def client(self, model: str) -> GeminiClient:
        return self.clients[model]

    def gate(self, model: str) -> Gate:
        return self.clients[model].gate

    def stopped(self) -> bool:
        """The shared stop switch (FAZETIME_AI_STOP=1 or <data_dir>/AI_STOP)."""
        return any(c.gate.stopped() for c in self.clients.values())

    def ready(self, model: str, role: str = NON_RESOLVER) -> bool:
        return model in self.clients and self.clients[model].gate.state(role) == "READY"

    def call(self, model: str, *, role: str, text: str, images: list, schema: dict, system: str | None = None,
             media_resolution: str | None = None):
        """One budgeted request. images: [(jpeg, ...)] bytes. Raises Unavailable or CallError (no retry)."""
        if is_gemma(model):
            system, media_resolution = None, None  # Gemma: no system instruction, no media_resolution
        parts = [("text", text)] + [("image", jpeg, "image/jpeg") for jpeg in images]
        return self.clients[model].generate_json(system=system, parts=parts, schema=schema,
                                                 media_resolution=media_resolution, role=role)

    def status(self) -> dict:
        out = {}
        for m, c in self.clients.items():
            g = c.gate
            out[m] = {"gate": g.state(), "non_resolver_gate": g.state(NON_RESOLVER), "used_today": g.used_today,
                      "budget": g.daily_budget, "reader_reserve": g.resolver_reserve, "stats": c.stats.as_dict()}
        return out
