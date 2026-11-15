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


def _fraction(v) -> float:
    """'0.4' or '40%' -> 0.4 (range is checked by Config.validate)."""
    s = str(v).strip()
    return float(s[:-1]) / 100 if s.endswith("%") else float(s)


def challenge_slug(name: str) -> str:
    """Episode-fingerprint slug for a challenge name: 'Minecraft 1v1' -> 'minecraft-1v1'."""
    return re.sub(r"[^a-z0-9]+", "-", str(name or "").lower()).strip("-")[:48]


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
    # ---- P4/P5 AI (Gemini, D20 free tier). Off unless FAZETIME_AI_ENABLED=1. Key: GEMINI_API_KEY (env only).
    ai_enabled: bool = False
    ai_proposer: bool = True
    ai_resolver: bool = True
    ai_model: str = "gemini-3.5-flash-lite"
    ai_daily_budget: int = 300  # requests per Pacific day, persisted in <data_dir>/gemini_usage.json
    # share of ai_daily_budget kept for the resolver: a proposer request is refused once the day's total usage
    # (both roles) reaches budget - reserve, so every proposal leaves the reserve for settling it
    ai_resolver_reserve: float = 0.4
    ai_min_interval_s: float = 6.0  # global: at most 10 requests/min
    ai_timeout_s: float = 20.0
    ai_max_output_tokens: int = 600
    # measured: image tokens depend on media_resolution, not pixel size (384x216 and 854x480 both ~1,100 at the
    # default; "low" = 264, and a 14 px synthetic chat line stayed legible). Proposer frames are supporting only.
    ai_media_resolution: str | None = "low"  # proposer calls; None = model default
    ai_resolver_media_resolution: str | None = None  # resolver calls: model default (~1,100 tokens per crop)
    ai_thinking_level: str | None = None
    ai_participants: tuple = ("FaZeGavin", "FaZeNeville")
    ai_challenge_name: str = "Minecraft 1v1"  # FAZETIME_AI_CHALLENGE: named in the market question/predicates
    ai_transcript_window_ms: int = 60_000
    ai_max_frames: int = 1  # proposer frames per call
    ai_frame_height: int = 480  # proposer frame height; downscaling does not reduce tokens on this model
    ai_evidence_max_age_s: float = 75.0  # API rejects evidence received > 90 s ago
    # frames = only server evd_ ids; frames+transcripts also cites API-acknowledged transcript observations as
    # <source_epoch>:<sequence> (the format the in-progress API accepts; not yet written into CONTRACTS §9.17)
    ai_evidence_refs: str = "frames+transcripts"
    ai_close_in_s: int = 60
    ai_resolve_in_s: int = 480
    ai_expected_setup_s: float = 90.0  # announced setup before the fight (D19 recording: >= 90 s)
    ai_lead_margin_s: float = 15.0
    ai_proposer_min_gap_s: float = 15.0
    ai_proposer_max_calls_per_epoch: int = 8
    ai_resolver_poll_s: float = 10.0
    ai_resolver_max_calls_per_market: int = 24
    ai_resolver_frames: int = 2
    ai_chat_crop: tuple = (0.0, 0.42, 0.62, 0.5)  # x, y, w, h fractions: Minecraft chat (bottom-left)
    ai_resolve_rule: str = "DEATH_MESSAGE_REQUIRED"  # or DEATH_OR_SPOKEN
    ai_post_wait: bool = True
    ai_market_source: str = "auto"  # auto | worker | snapshot | none
    resolver_session_token: str | None = field(default=None, repr=False)
    streamlink_bin: str = "streamlink"
    ffmpeg_bin: str = "ffmpeg"

    @property
    def ai_challenge(self) -> str:
        """Fingerprint slug, derived from the challenge name (default 'minecraft-1v1', unchanged)."""
        return challenge_slug(self.ai_challenge_name)

    def ai_resolver_reserve_requests(self) -> int:
        """Daily requests only the resolver may use (rounded up, integer math)."""
        bp = round(self.ai_resolver_reserve * 10_000)
        return min(self.ai_daily_budget, max(0, (self.ai_daily_budget * bp + 9_999) // 10_000))

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
        if self.ai_enabled:  # a missing GEMINI_API_KEY is not a problem: AI is then disabled and logged once
            if self.ai_evidence_refs not in ("frames", "frames+transcripts"):
                problems.append("FAZETIME_AI_EVIDENCE_REFS must be frames or frames+transcripts")
            if self.ai_resolve_rule not in ("DEATH_MESSAGE_REQUIRED", "DEATH_OR_SPOKEN"):
                problems.append("FAZETIME_AI_RESOLVE_RULE must be DEATH_MESSAGE_REQUIRED or DEATH_OR_SPOKEN")
            if len(self.ai_participants) != 2:
                problems.append("FAZETIME_AI_PARTICIPANTS must name exactly two participants")
            name = self.ai_challenge_name or ""
            if not (0 < len(name) <= 40) or re.search(r"[\x00-\x1f\x7f]", name) or not self.ai_challenge:
                problems.append("FAZETIME_AI_CHALLENGE must be 1-40 printable characters with a letter or digit")
            if not 0.0 <= self.ai_resolver_reserve < 1.0:
                problems.append("FAZETIME_AI_RESOLVER_RESERVE must be a fraction in [0, 1) or a percentage like 40%")
            elif self.ai_proposer and self.ai_daily_budget - self.ai_resolver_reserve_requests() <= 0:
                problems.append("FAZETIME_AI_RESOLVER_RESERVE leaves the proposer no daily requests")
        return problems

    def public_dict(self) -> dict:
        """Loggable view: the token is replaced by its presence only."""
        out = {}
        for f in fields(self):
            v = getattr(self, f.name)
            if f.name in ("token", "resolver_session_token"):
                out[f.name + "_present"] = bool(v)
                continue
            out[f.name] = str(v) if isinstance(v, Path) else v
        out["ai_challenge"] = self.ai_challenge
        out["ai_resolver_reserve_requests"] = self.ai_resolver_reserve_requests()
        out["source_kind"] = self.source_kind
        out["gemini_key_present"] = bool(os.environ.get("GEMINI_API_KEY"))
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
    b = lambda v: str(v).lower() in ("1", "true", "yes", "on")  # noqa: E731
    # auto (default): on when GEMINI_API_KEY is present and an API is configured (not in dry-run); 1 = on; 0 = off
    ai = str(_env("FAZETIME_AI_ENABLED", "auto")).lower()
    c.ai_enabled = (bool(os.environ.get("GEMINI_API_KEY")) and bool(c.api_base)) if ai == "auto" else b(ai)
    c.ai_proposer = b(_env("FAZETIME_AI_PROPOSER", "1"))
    c.ai_resolver = b(_env("FAZETIME_AI_RESOLVER", "1"))
    c.ai_model = _env("FAZETIME_AI_MODEL", c.ai_model)
    c.ai_daily_budget = int(_env("FAZETIME_AI_DAILY_BUDGET", c.ai_daily_budget))
    c.ai_resolver_reserve = _fraction(_env("FAZETIME_AI_RESOLVER_RESERVE", c.ai_resolver_reserve))
    c.ai_challenge_name = " ".join(str(_env("FAZETIME_AI_CHALLENGE", c.ai_challenge_name)).split())
    c.ai_min_interval_s = float(_env("FAZETIME_AI_MIN_INTERVAL_S", c.ai_min_interval_s))
    c.ai_timeout_s = float(_env("FAZETIME_AI_TIMEOUT_S", c.ai_timeout_s))
    mr = lambda v: None if str(v).lower() in ("", "default", "none") else v  # noqa: E731
    c.ai_media_resolution = mr(_env("FAZETIME_AI_MEDIA_RESOLUTION", c.ai_media_resolution))
    c.ai_resolver_media_resolution = mr(_env("FAZETIME_AI_RESOLVER_MEDIA_RESOLUTION", c.ai_resolver_media_resolution))
    c.ai_thinking_level = _env("FAZETIME_AI_THINKING_LEVEL", c.ai_thinking_level)
    parts = _env("FAZETIME_AI_PARTICIPANTS")
    if parts:
        c.ai_participants = tuple(p.strip() for p in parts.split(",") if p.strip())
    c.ai_frame_height = int(_env("FAZETIME_AI_FRAME_HEIGHT", c.ai_frame_height))
    c.ai_max_frames = int(_env("FAZETIME_AI_MAX_FRAMES", c.ai_max_frames))
    c.ai_resolver_frames = int(_env("FAZETIME_AI_RESOLVER_FRAMES", c.ai_resolver_frames))
    c.ai_evidence_refs = _env("FAZETIME_AI_EVIDENCE_REFS", c.ai_evidence_refs)
    c.ai_close_in_s = int(_env("FAZETIME_AI_CLOSE_IN_S", c.ai_close_in_s))
    c.ai_resolve_in_s = int(_env("FAZETIME_AI_RESOLVE_IN_S", c.ai_resolve_in_s))
    c.ai_expected_setup_s = float(_env("FAZETIME_AI_EXPECTED_SETUP_S", c.ai_expected_setup_s))
    c.ai_lead_margin_s = float(_env("FAZETIME_AI_LEAD_MARGIN_S", c.ai_lead_margin_s))
    c.ai_resolve_rule = _env("FAZETIME_AI_RESOLVE_RULE", c.ai_resolve_rule)
    crop = _env("FAZETIME_AI_CHAT_CROP")
    if crop:
        c.ai_chat_crop = tuple(float(x) for x in crop.split(","))
    c.ai_market_source = _env("FAZETIME_AI_MARKET_SOURCE", c.ai_market_source)
    c.resolver_session_token = _env("FAZETIME_RESOLVER_SESSION_TOKEN")
    return c
