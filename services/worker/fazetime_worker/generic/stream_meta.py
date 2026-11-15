"""CONTRACTS §9.20 item 3: Twitch stream context (title, category, author) from Streamlink's ``--json`` metadata.

* One ``<streamlink_bin> --json https://twitch.tv/<channel>`` call at start and then every 5 minutes. Each call
  has a 20 s timeout and runs on this module's own thread, never the AI loop.
* Only ``metadata.title``, ``metadata.category`` and ``metadata.author`` are kept, each cleaned and cut to 120
  chars. The rest of the output is never logged or stored: its stream URLs carry access tokens.
* The values are untrusted. The prompts label them so. Code uses only the category, as the activity name while the
  observer has not named one (``Reducer.category``).
* A failed fetch never raises and keeps the last good values; before the first success there is no context.
* Each change is written to the local ``ai_trace.jsonl`` as a ``stream_context`` record (provenance of what the
  prompts saw). Nothing is posted to the API: the §9.20 activity feed was withdrawn (owner, 2026-11-15).
* TEST_FIXTURE mode (``--test-source-cmd``) builds no fetcher at all (see ``build_generic_ai``).
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import threading

log = logging.getLogger("fazetime.generic.stream")

KEYS = ("title", "category", "author")
MAX_VALUE = 120
INTERVAL_S = 300.0
TIMEOUT_S = 20.0
MAX_OUTPUT_BYTES = 1 << 20
LABEL = "Stream context from Twitch (untrusted, may be wrong)"
_CTRL = re.compile(r"[\x00-\x1f\x7f]+")


def clean_value(v) -> str:
    return " ".join(_CTRL.sub(" ", str(v)[:MAX_VALUE * 4]).split())[:MAX_VALUE] if isinstance(v, str) else ""


def parse_streamlink_json(text) -> dict | None:
    """{title, category, author} (only the non-empty ones) from ``streamlink --json`` output, else None."""
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        d = json.loads(text)
    except ValueError:
        a, b = text.find("{"), text.rfind("}")  # tolerate stray lines around the JSON document
        try:
            d = json.loads(text[a:b + 1]) if 0 <= a < b else None
        except ValueError:
            return None
    md = d.get("metadata") if isinstance(d, dict) else None
    if not isinstance(md, dict):
        return None  # e.g. {"error": "No playable streams found on this URL: ..."} while offline
    out = {k: clean_value(md.get(k)) for k in KEYS}
    out = {k: v for k, v in out.items() if v}
    return out or None


def context_line(values: dict | None) -> str:
    """The one labelled prompt line ('' without context)."""
    if not values:
        return ""
    parts = [f"{k if k != 'author' else 'channel'}: {values[k]}" for k in KEYS if values.get(k)]
    return f"{LABEL}: " + "; ".join(parts) if parts else ""


def run_streamlink(streamlink_bin: str, channel: str, timeout_s: float = TIMEOUT_S) -> str:
    """One metadata call (argument list, no shell; stderr discarded). Raises on timeout or a missing binary."""
    r = subprocess.run([streamlink_bin, "--json", f"https://twitch.tv/{channel}"], stdin=subprocess.DEVNULL,
                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout_s, check=False)
    return r.stdout[:MAX_OUTPUT_BYTES].decode("utf-8", "replace")


class StreamMeta(threading.Thread):
    def __init__(self, cfg, trace=None, fetch=None, interval_s: float = INTERVAL_S, timeout_s: float = TIMEOUT_S):
        super().__init__(daemon=True, name="ai-stream-meta")
        self.fetch = fetch or (lambda: run_streamlink(cfg.streamlink_bin, cfg.channel, timeout_s))
        self.trace, self.interval_s = trace, interval_s
        self.lock = threading.Lock()
        self.values: dict = {}
        self.stop_flag = threading.Event()
        self.stats = {"fetches": 0, "ok": 0, "failed": 0, "changes": 0, "last_error": None}

    def refresh(self) -> bool:
        """One fetch. Never raises; a failure keeps the last good values (none before the first success)."""
        self.stats["fetches"] += 1
        try:
            parsed = parse_streamlink_json(self.fetch())
            err = None if parsed else "NO_METADATA"
        except Exception as exc:  # timeout, missing binary, OS error: no new context, never a crash
            parsed, err = None, type(exc).__name__
        if not parsed:
            self.stats["failed"] += 1
            self.stats["last_error"] = err
            if self.stats["failed"] <= 3:
                log.warning("stream metadata unavailable (%s); prompts keep %s", err,
                            "the last values" if self.values else "no stream context")
            return False
        self.stats["ok"] += 1
        with self.lock:
            changed = [k for k in KEYS if parsed.get(k) != self.values.get(k)]
            self.values = dict(parsed)
        if changed:
            self.stats["changes"] += 1
            if self.trace is not None:
                self.trace.write({"role": "stream_context", "outcome": "CHANGED", "changed": changed,
                                  **{k: parsed.get(k) for k in KEYS}})
        return True

    def snapshot(self) -> dict:
        with self.lock:
            return dict(self.values)

    def category(self) -> str | None:
        with self.lock:
            return self.values.get("category") or None

    def line(self) -> str:
        return context_line(self.snapshot())

    def status(self) -> dict:
        return dict(self.stats) | {"context": self.snapshot()}

    def run(self):
        while not self.stop_flag.is_set():
            self.refresh()
            self.stop_flag.wait(self.interval_s)

    def stop(self):
        self.stop_flag.set()
