"""SYNTHETIC live smoke of the P4 proposer / P5 resolver against real Gemini (not Twitch, not the P4 gate).

Frames are drawn with ffmpeg and carry a visible "SYNTHETIC" label. The API is an in-memory recorder; nothing is
posted anywhere. A private Gate caps this script at --max-requests (default 6) model requests.
Reads GEMINI_API_KEY from the environment, or from --env-file (KEY=VALUE lines); the value is never printed.

  uv run python scripts/ai_smoke.py --env-file ../../.env.local --out <dir> [--cases a,b,c]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fazetime_worker import context as cx  # noqa: E402
from fazetime_worker.api_client import ApiResult  # noqa: E402
from fazetime_worker.config import Config  # noqa: E402
from fazetime_worker.gemini import Gate, GeminiClient  # noqa: E402
from fazetime_worker.proposer import Proposer, Registry, Trace  # noqa: E402
from fazetime_worker.resolver import MarketTracker, MarketView, Resolver, StaticMarketSource  # noqa: E402

EP = "ep_" + "5" * 32
RUN = "run_" + "6" * 32
STREAM = "str_" + "7" * 32
MKT = "mkt_" + "8" * 32
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"


def load_key(env_file: str | None):
    if os.environ.get("GOOGLE_API_KEY"):
        sys.exit("GOOGLE_API_KEY is set; unset it first")
    if env_file and not os.environ.get("GEMINI_API_KEY"):
        for line in Path(env_file).read_text().splitlines():
            k, _, v = line.partition("=")
            if k.strip() == "GEMINI_API_KEY" and v.strip():
                os.environ["GEMINI_API_KEY"] = v.strip().strip('"').strip("'")
    if not os.environ.get("GEMINI_API_KEY"):
        sys.exit("GEMINI_API_KEY not available")


def draw(path: Path, chat: str | None):
    """854x480 Minecraft-like synthetic frame; chat text ~14 px (GUI scale 4 at 1080p, downscaled to 480p)."""
    vf = ["drawbox=x=0:y=0:w=iw:h=200:color=0x87ceeb:t=fill",
          "drawbox=x=0:y=200:w=iw:h=280:color=0x5d9b3a:t=fill",
          "drawbox=x=380:y=150:w=40:h=110:color=0x3b2a1a:t=fill",
          f"drawtext=fontfile={FONT}:text='SYNTHETIC TEST FRAME':x=w-tw-10:y=10:fontsize=14:fontcolor=red",
          "drawbox=x=300:y=440:w=254:h=28:color=0x444444:t=fill"]
    if chat:
        vf += ["drawbox=x=4:y=372:w=330:h=20:color=black@0.5:t=fill",
               f"drawtext=fontfile={FONT}:text='{chat}':x=8:y=375:fontsize=14:fontcolor=white"]
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=black:s=854x480", "-vf", ",".join(vf), "-frames:v", "1", "-q:v", "4", str(path)],
                   check=True)
    return path.read_bytes()


class RecordingApi:
    def __init__(self, mode="APPROVAL"):
        self.mode, self.posts = mode, []

    def get_json(self, path, bearer=None):
        return ApiResult(404, {"error": {"code": "NOT_FOUND"}})

    def post_json(self, path, body):
        self.posts.append((path, body))
        if path.endswith("/proposals"):
            return ApiResult(200, {"candidate_id": body["candidate"]["candidate_id"], "status": "PENDING",
                                   "reject_code": None, "market_id": None})
        d = body["resolution"]["decision"]
        return ApiResult(200, {"resolution_id": body["resolution"]["resolution_id"],
                               "status": "RECORDED" if d == "WAIT" else "PENDING_APPROVAL", "reason": ""})


def last_trace(path: Path) -> dict:
    lines = path.read_text().splitlines() if path.exists() else []
    return json.loads(lines[-1]) if lines else {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file")
    ap.add_argument("--out", required=True)
    ap.add_argument("--cases", default="a,b,c")
    ap.add_argument("--max-requests", type=int, default=6)
    ap.add_argument("--media-resolution", default=None)
    a = ap.parse_args()
    load_key(a.env_file)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    cfg = Config()
    cfg.ai_min_interval_s = 4.0
    cfg.ai_proposer_min_gap_s = 0
    gate = Gate(daily_budget=a.max_requests, min_interval_s=4.0, state_path=out / "smoke_usage.json")
    gem = GeminiClient(gate, model=cfg.ai_model, timeout_s=30, media_resolution=a.media_resolution)
    tx = cx.FrameTransformer()
    results = []

    def setup():
        ctx = cx.ContextBuffer()
        ctx.open_epoch(EP)
        ctx.set_run(RUN)
        return ctx

    def frame(ctx, seq, ms, jpeg):
        ctx.add_frame(EP, seq, ms, jpeg, 854, 480, "2026-11-15T06:00:00.000Z")
        ctx.on_evidence_ack(EP, seq, f"evd_{seq:032x}")

    scene = draw(out / "synthetic_scene.jpg", None)
    for case in a.cases.split(","):
        while gate.state() == "COOLDOWN" or time.monotonic() < gate.last_start + gate.min_interval_s:
            time.sleep(0.5)
        ctx, api = setup(), RecordingApi()
        trace = Trace(out / f"trace_{case}.jsonl")
        tracker = MarketTracker(StaticMarketSource())
        if case in ("a", "b", "b1", "b2"):
            prop = Proposer(cfg, ctx, gem, api, STREAM, tracker, Registry(), tx, trace)
            if case == "a":
                ctx.add_transcript(EP, 1, 0, 4000, "Hi, it's face Gavin and we'll be 1v1ing my friend", [], "t")
                ctx.add_transcript(EP, 2, 3000, 7000, "my friend phase Neville!", [], "t")
            elif case in ("b", "b1"):
                ctx.add_transcript(EP, 1, 0, 4000, "okay chat, let me grab some wood and build a little house", [], "t")
                ctx.add_transcript(EP, 2, 3000, 7000, "thanks for the follow, appreciate it", [], "t")
            else:
                ctx.add_transcript(EP, 1, 0, 4000, "Last week face Gavin and phase Neville did a 1v1,", [], "t")
                ctx.add_transcript(EP, 2, 3000, 7000, "that was such a close fight, chat remembers", [], "t")
            frame(ctx, 3, 6000, scene)
            outcome = prop.tick()
            rec = {"case": case, "role": "proposer", "outcome": outcome, "model_calls": prop.gemini.stats.requests}
            if case in ("b", "b1"):
                rec["note"] = "pre-filter: no model request"
            t = last_trace(out / f"trace_{case}.jsonl")
            rec |= {k: t.get(k) for k in ("latency_ms", "usage", "model_version", "image_bytes", "decision")
                    if k in t}
            if api.posts:
                c = api.posts[0][1]["candidate"]
                rec["candidate"] = {k: c[k] for k in ("episode_fingerprint", "question", "subjects", "evidence_ids",
                                                      "announced_at_media_ms", "suggested_close_in_s",
                                                      "suggested_resolve_in_s", "prompt_version", "model")}
            results.append(rec)
        elif case in ("c", "c_no", "c_wait"):
            chat = {"c": "FaZeNeville was slain by FaZeGavin", "c_no": "FaZeGavin was slain by FaZeNeville",
                    "c_wait": None}[case]
            lock = 100_000
            src = StaticMarketSource(MarketView(MKT, 1, "EVALUATING",
                                                "Will FaZeGavin win the Minecraft 1v1 against FaZeNeville?",
                                                "FaZeGavin", "FaZeNeville", lock_source_epoch=EP, lock_media_ms=lock,
                                                resolve_by_utc="2099-01-01T00:00:00.000Z"))
            res = Resolver(cfg, ctx, gem, api, STREAM, MarketTracker(src), Registry(), tx, trace)
            img = draw(out / f"synthetic_{case}.jpg", chat)
            frame(ctx, 10, lock + 4000, img)
            ctx.add_transcript(EP, 11, lock + 3000, lock + 7000,
                               {"c": "face Gavin wins!", "c_no": "phase Neville wins!", "c_wait": "come on, come on"}[case],
                               [], "t")
            outcome = res.tick()
            t = last_trace(out / f"trace_{case}.jsonl")
            rec = {"case": case, "role": "resolver", "outcome": outcome}
            rec |= {k: t.get(k) for k in ("latency_ms", "usage", "model_version", "model_decision", "decision", "why",
                                          "support", "death_message", "evidence_ids") if k in t}
            if api.posts:
                r = api.posts[0][1]["resolution"]
                rec["posted"] = {k: r[k] for k in ("decision", "evidence_ids", "media_interval", "predicate_support",
                                                   "contradictions", "prompt_version", "model")}
            results.append(rec)
    summary = {"label": "SYNTHETIC frames + scripted transcripts; real Gemini; in-memory API (no posts)",
               "gemini": gem.stats.as_dict(), "gate_used": gate.used_today, "results": results}
    (out / "smoke_results.json").write_text(json.dumps(summary, indent=1, default=str))
    print(json.dumps(summary, indent=1, default=str))


if __name__ == "__main__":
    main()
