"""Worker configuration from the environment (CLI flags override). The token is never logged."""
from __future__ import annotations

import os
import re
import socket
from dataclasses import dataclass, field, fields
from pathlib import Path

HOTWORDS_DEFAULT = "FaZeGavin, FaZeNeville, Minecraft, 1v1"


def _env(name: str, default=None):
    v = os.environ.get(name)
    return default if v is None or v == "" else v


@dataclass
class Config:
    # API (CONTRACTS §9.16). api_base None => dry-run (observations go to a local JSONL only).
    api_base: str | None = None
    token: str | None = field(default=None, repr=False)
    stream_id: str | None = None
    # source
    channel: str = "fazegavin1234"
    quality: str = "best"
    test_source_cmd: str | None = None  # => source_kind TEST_FIXTURE, never Twitch evidence
    # frames
    frame_height: int = 480
    frame_interval_s: float = 2.0
    keyframes_only: bool = True  # -skip_frame:v nokey (decode keyframes only)
    jpeg_q: int = 5
    # health thresholds (D29 / §9.4): LIVE <= 12 s, STALE 12-30 s, STOPPED > 30 s (then restart)
    live_max_s: float = 12.0
    stopped_after_s: float = 30.0
    ad_pause_max_s: float = 180.0  # no-media limit while Streamlink reports an ad-filter pause (state GAP)
    connect_timeout_s: float = 60.0
    max_restarts: int = 1000
    heartbeat_s: float = 5.0
    # bounded local ring (debug evidence on the worker host)
    ring_s: float = 120.0
    data_dir: Path = Path.home() / "fazetime-data" / "worker"
    # ASR
    asr_engine: str = "faster-whisper"  # or "fake" (tests / TEST_FIXTURE)
    asr_model: str = "tiny.en"
    asr_threads: int = 3
    asr_beam: int = 5
    asr_temperature: float = 0.0  # single temperature => no fallback ladder
    asr_max_new_tokens: int = 64
    asr_hotwords: str | None = None
    asr_initial_prompt: str | None = None
    asr_window_ms: int = 4000
    asr_hop_ms: int = 3000
    asr_queue_max: int = 4
    asr_max_wait_s: float = 6.0  # per-window deadline: older windows are dropped, not processed
    asr_low_logprob: float = -1.0
    asr_high_no_speech: float = 0.6
    models_dir: Path | None = None
    # uplink
    batch_max_items: int = 50
    batch_max_wait_s: float = 0.5
    uplink_queue_max: int = 2000
    http_timeout_s: float = 10.0
    host_id: str = field(default_factory=lambda: socket.gethostname()[:64] or "worker")
    streamlink_bin: str = "streamlink"
    ffmpeg_bin: str = "ffmpeg"

    @property
    def source_kind(self) -> str:
        return "TEST_FIXTURE" if self.test_source_cmd else "TWITCH_STREAMLINK"

    @property
    def dry_run(self) -> bool:
        return not self.api_base

    def validate(self) -> list[str]:
        problems = []
        if not re.fullmatch(r"[A-Za-z0-9_]{1,25}", self.channel):
            problems.append("channel must be a Twitch login name")
        if self.api_base:
            if not self.token or not self.token.startswith("fzk_"):
                problems.append("FAZETIME_WORKER_TOKEN missing or not an fzk_ token")
            if not self.stream_id or not re.fullmatch(r"str_[0-9a-f]{32}", self.stream_id):
                problems.append("FAZETIME_STREAM_ID missing or not a str_ id")
            if not re.match(r"^https?://", self.api_base):
                problems.append("FAZETIME_API_BASE must be an http(s) URL")
        if self.asr_hop_ms >= self.asr_window_ms:
            problems.append("asr_hop_ms must be smaller than asr_window_ms")
        return problems

    def public_dict(self) -> dict:
        """Loggable view: the token is replaced by its presence only."""
        out = {}
        for f in fields(self):
            v = getattr(self, f.name)
            if f.name == "token":
                out["token_present"] = bool(v)
                continue
            out[f.name] = str(v) if isinstance(v, Path) else v
        out["source_kind"] = self.source_kind
        return out


def from_env() -> Config:
    c = Config()
    c.api_base = _env("FAZETIME_API_BASE")
    c.token = _env("FAZETIME_WORKER_TOKEN")
    c.stream_id = _env("FAZETIME_STREAM_ID")
    c.channel = _env("FAZETIME_TWITCH_CHANNEL", c.channel)
    c.quality = _env("FAZETIME_TWITCH_QUALITY", c.quality)
    c.data_dir = Path(_env("FAZETIME_WORKER_DATA_DIR", str(c.data_dir)))
    c.asr_model = _env("FAZETIME_ASR_MODEL", c.asr_model)
    c.asr_threads = int(_env("FAZETIME_ASR_THREADS", c.asr_threads))
    md = _env("FAZETIME_ASR_MODELS_DIR")
    c.models_dir = Path(md) if md else None
    hw = _env("FAZETIME_ASR_HOTWORDS")
    if hw is not None:
        c.asr_hotwords = None if hw.lower() == "none" else hw
    c.host_id = _env("FAZETIME_WORKER_HOST_ID", c.host_id)[:64]
    c.streamlink_bin = _env("FAZETIME_STREAMLINK_BIN", c.streamlink_bin)
    c.ffmpeg_bin = _env("FAZETIME_FFMPEG_BIN", c.ffmpeg_bin)
    if c.api_base:
        c.api_base = c.api_base.rstrip("/")
    return c
