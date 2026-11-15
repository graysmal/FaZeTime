#!/usr/bin/env python3
"""Capability probe: does a model accept system instruction + image + JSON schema? One request per variant.

Prints only latency, token usage and the parsed answer (never the key). Usage:
  services/worker/.venv/bin/python -I spikes/p4-generic/probe_models.py MODEL FRAME.jpg
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm  # noqa: E402

SCHEMA = {
    "type": "object",
    "properties": {
        "activity": {"type": "string", "description": "What game or activity is on screen"},
        "phase": {"type": "string", "enum": ["menu", "loading", "in_progress", "result_screen", "other"]},
        "visible_numbers": {"type": "array", "items": {"type": "object", "properties": {
            "label": {"type": "string"}, "value": {"type": "string"}}, "required": ["label", "value"]}},
        "notes": {"type": "string"},
    },
    "required": ["activity", "phase", "visible_numbers", "notes"],
}
SYSTEM = "You describe a single frame from a live game stream. Answer only in the JSON schema."
TASK = "Describe the frame: the game, the phase, and every number readable in the game's HUD with its label."


def main() -> None:
    model, frame = sys.argv[1], Path(sys.argv[2])
    llm.load_key()
    import os

    from google import genai
    from google.genai import types

    c = genai.Client(api_key=os.environ["GEMINI_API_KEY"],
                     http_options=types.HttpOptions(timeout=60_000, retry_options=types.HttpRetryOptions(attempts=1)))
    parts = [types.Part.from_text(text=TASK), types.Part.from_bytes(data=frame.read_bytes(), mime_type="image/jpeg")]
    variants = [
        ("system+schema", dict(system_instruction=SYSTEM, response_mime_type="application/json",
                               response_json_schema=SCHEMA)),
        ("schema-only", dict(response_mime_type="application/json", response_json_schema=SCHEMA)),
        ("plain-json-text", dict()),
    ]
    for name, cfg in variants:
        t0 = time.monotonic()
        p = parts if name != "plain-json-text" else [types.Part.from_text(
            text=SYSTEM + "\n" + TASK + "\nReply with only a JSON object with keys activity, phase, visible_numbers "
            "(list of {label, value}), notes.")] + parts[1:]
        try:
            r = c.models.generate_content(model=model, contents=p, config=types.GenerateContentConfig(
                temperature=0, max_output_tokens=800, **cfg))
        except Exception as e:  # report the class and code only
            print(name, "ERROR", type(e).__name__, getattr(e, "code", None), str(getattr(e, "message", ""))[:160])
            continue
        u = r.usage_metadata
        print(name, "OK", f"{(time.monotonic() - t0):.1f}s", "prompt", getattr(u, "prompt_token_count", None),
              "out", getattr(u, "candidates_token_count", None), "thoughts", getattr(u, "thoughts_token_count", None),
              [(str(d.modality), d.token_count) for d in (getattr(u, "prompt_tokens_details", None) or [])])
        print("   ", (r.text or "")[:600].replace("\n", " "))
        break  # the first variant that works is enough


if __name__ == "__main__":
    main()
