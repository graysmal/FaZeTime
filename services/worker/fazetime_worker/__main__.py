"""CLI: `python -m fazetime_worker run|check`.

Environment (see README): FAZETIME_API_BASE, FAZETIME_WORKER_TOKEN, FAZETIME_STREAM_ID,
FAZETIME_TWITCH_CHANNEL, FAZETIME_ASR_MODEL, FAZETIME_ASR_THREADS, FAZETIME_ASR_MODELS_DIR, ...
Without FAZETIME_API_BASE the worker runs in dry-run mode (uplink_dryrun.jsonl in the data dir).
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from pathlib import Path

from .config import HOTWORDS_DEFAULT, from_env


def _args(argv):
    p = argparse.ArgumentParser(prog="fazetime_worker")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("run", "check"):
        s = sub.add_parser(name)
        s.add_argument("--channel")
        s.add_argument("--quality")
        s.add_argument("--duration-s", type=float, default=None)
        s.add_argument("--data-dir")
        s.add_argument("--dry-run", action="store_true", help="ignore FAZETIME_API_BASE; record uplink locally")
        s.add_argument("--test-source-cmd", default=None,
                       help="OFFLINE TEST ONLY: command whose stdout replaces Streamlink (source_kind TEST_FIXTURE)")
        s.add_argument("--asr-engine", choices=["faster-whisper", "fake"])
        s.add_argument("--asr-model")
        s.add_argument("--asr-threads", type=int)
        s.add_argument("--asr-beam", type=int)
        s.add_argument("--max-new-tokens", type=int)
        s.add_argument("--hotwords", default=None, help=f"default: none; e.g. {HOTWORDS_DEFAULT!r}")
        s.add_argument("--initial-prompt", default=None)
        s.add_argument("--no-keyframes-only", action="store_true", help="decode every video frame (costly at 1080p60)")
        s.add_argument("--frame-height", type=int)
        s.add_argument("--models-dir")
        s.add_argument("--log-level", default="INFO")
    return p.parse_args(argv)


def build_config(a):
    cfg = from_env()
    if a.channel:
        cfg.channel = a.channel
    if a.quality:
        cfg.quality = a.quality
    if a.data_dir:
        cfg.data_dir = Path(a.data_dir)
    if a.dry_run:
        cfg.api_base = None
    if a.test_source_cmd:
        cfg.test_source_cmd = a.test_source_cmd
    if a.asr_engine:
        cfg.asr_engine = a.asr_engine
    if a.asr_model:
        cfg.asr_model = a.asr_model
    if a.asr_threads:
        cfg.asr_threads = a.asr_threads
    if a.asr_beam:
        cfg.asr_beam = a.asr_beam
    if a.max_new_tokens:
        cfg.asr_max_new_tokens = a.max_new_tokens
    if a.hotwords is not None:
        cfg.asr_hotwords = None if a.hotwords.lower() == "none" else a.hotwords
    if a.initial_prompt is not None:
        cfg.asr_initial_prompt = a.initial_prompt or None
    if a.no_keyframes_only:
        cfg.keyframes_only = False
    if a.frame_height:
        cfg.frame_height = a.frame_height
    if a.models_dir:
        cfg.models_dir = Path(a.models_dir)
    return cfg


def main(argv=None) -> int:
    a = _args(argv if argv is not None else sys.argv[1:])
    logging.basicConfig(level=getattr(logging, a.log_level.upper(), logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("faster_whisper").setLevel(logging.WARNING)
    cfg = build_config(a)
    problems = cfg.validate()
    for tool in ([cfg.ffmpeg_bin] + ([] if cfg.test_source_cmd else [cfg.streamlink_bin])):
        if shutil.which(tool) is None and not Path(tool).exists():
            problems.append(f"binary not found: {tool}")
    if a.cmd == "check" or problems:
        print(json.dumps({"config": cfg.public_dict(), "problems": problems}, indent=1, default=str))
        return 1 if problems else 0
    from .pipeline import Pipeline, install_signal_handlers
    p = Pipeline(cfg)
    install_signal_handlers(p)
    final = p.run(a.duration_s)
    print(json.dumps(final, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
