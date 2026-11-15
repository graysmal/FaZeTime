"""Budgeted Gemini access for the fixture replay, reusing the worker's client (gate, redaction, no retries).

The key is read from the repo's ``.env.local`` (mode 600) into this process only and is never printed.
Every request is logged (role, media time, latency, tokens, the parsed answer) to ``<run_dir>/calls.jsonl``.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "services" / "worker"))

from fazetime_worker.gemini import SYSTEM_RULES, CallError, Gate, GeminiClient, Unavailable  # noqa: E402

__all__ = ["Llm", "SYSTEM_RULES", "CallError", "Unavailable"]


def load_key() -> None:
    if os.environ.get("GEMINI_API_KEY"):
        return
    for line in (REPO / ".env.local").read_text().splitlines():
        if line.startswith("GEMINI_API_KEY="):
            os.environ["GEMINI_API_KEY"] = line.split("=", 1)[1].strip().strip('"').strip("'")
            return
    raise SystemExit("GEMINI_API_KEY not found in .env.local")


class Llm:
    """One client per model id. ``budget`` caps this replay's requests (persisted per Pacific day)."""

    def __init__(self, run_dir: Path, budget: int, min_interval_s: float = 4.5, timeout_s: float = 30.0,
                 max_output_tokens: int = 1500):
        load_key()
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.budget = budget
        self.min_interval_s = min_interval_s
        self.fixtures = Path.home() / "fazetime-data" / "fixtures"
        self.timeout_s = timeout_s
        self.max_output_tokens = max_output_tokens
        self.clients: dict[str, GeminiClient] = {}
        self.tok_window: dict[str, list[tuple[float, int]]] = {}  # per model: (wall, tokens) for a TPM governor
        self.log = (self.run_dir / "calls.jsonl").open("a")
        self._log_lock = threading.Lock()
        self._client_lock = threading.Lock()

    def client(self, model: str) -> GeminiClient:
        """Each model has its own free-tier quota, so each gets its own gate and persisted daily counter."""
        with self._client_lock:
            return self._client(model)

    def _client(self, model: str) -> GeminiClient:
        if model not in self.clients:
            gate = Gate(daily_budget=self.budget, min_interval_s=self.min_interval_s,
                        state_path=self.fixtures / f"usage_{model}.json", stop_file=self.fixtures / "AI_STOP")
            self.clients[model] = GeminiClient(gate, model=model, timeout_s=self.timeout_s,
                                               max_output_tokens=self.max_output_tokens)
        return self.clients[model]

    def _tpm_wait(self, model: str, tpm_cap: int | None) -> None:
        if not tpm_cap:
            return
        win = self.tok_window.setdefault(model, [])
        while True:
            now = time.time()
            win[:] = [(t, n) for t, n in win if now - t < 60.0]
            if sum(n for _, n in win) < tpm_cap or not win:
                return
            time.sleep(max(0.2, 60.0 - (now - win[0][0]) + 0.1))

    def call(self, *, role: str, model: str, media_t: float, task: str, parts: list, schema: dict,
             media_resolution: str | None = "low", system: str | None = SYSTEM_RULES,
             tpm_cap: int | None = None, wait_cooldown_s: float = 20.0) -> dict | None:
        """One request (waits out the local min-interval and short cooldowns). Returns the parsed object or None.
        Gemma models: pass system=None (a system instruction returned HTTP 500) and media_resolution=None."""
        cl = self.client(model)
        self._tpm_wait(model, tpm_cap)
        res = None
        for _ in range(30):
            try:
                res = cl.generate_json(system=system, parts=[("text", task)] + parts, schema=schema,
                                       media_resolution=media_resolution, role=None)
                break
            except Unavailable as u:
                if u.retry_in_s and (u.reason == "RATE_LIMITED_LOCAL" or u.retry_in_s <= wait_cooldown_s):
                    time.sleep(u.retry_in_s + 0.05)
                    continue
                self._log(role, model, media_t, error=f"UNAVAILABLE {u.reason}")
                return None
            except CallError as e:
                self._log(role, model, media_t, error=f"{e.kind} {e.http_status or ''}".strip())
                return None
        if res is None:
            return None
        self.tok_window.setdefault(model, []).append((time.time(), int(res.usage.get("total", 0) or 0)))
        self._log(role, model, media_t, latency_ms=res.latency_ms, usage=res.usage, data=res.data,
                  n_images=sum(1 for p in parts if p[0] == "image"))
        res.data["_latency_ms"] = res.latency_ms
        return res.data

    def _log(self, role, model, media_t, **kw):
        rec = {"wall": round(time.time(), 2), "role": role, "model": model, "media_t": round(media_t, 1), **kw}
        with self._log_lock:  # resolver reads run in parallel threads
            self.log.write(json.dumps(rec) + "\n")
            self.log.flush()

    def summary(self) -> dict:
        out = {}
        for m, c in self.clients.items():
            out[m] = c.stats.as_dict()
            out[m]["used_today_this_counter"] = c.gate.used_today
        return out
