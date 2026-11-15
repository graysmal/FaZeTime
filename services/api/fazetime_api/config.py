"""Runtime settings, read from FAZETIME_* environment variables. No secrets live here."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace

DEFAULT_ALLOWED_ORIGINS = ("https://www.twitch.tv",)  # add the pinned chrome-extension://<id> exactly


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return default if value is None or value == "" else value


def _env_int(name: str, default: int) -> int:
    return int(_env(name, str(default)))


def _env_float(name: str, default: float) -> float:
    return float(_env(name, str(default)))


def _env_bool(name: str, default: bool) -> bool:
    return _env(name, "1" if default else "0").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Limits:
    """CONTRACTS §9.2. Published in snapshot.limits; clients never hardcode them."""

    stake_min_minor: int = 100
    stake_max_minor: int = 50_000
    stake_step_minor: int = 100
    stake_default_minor: int = 500
    topup_presets_minor: tuple[int, ...] = (500, 1_000, 5_000)
    topup_min_minor: int = 500
    topup_max_minor: int = 10_000
    topup_step_minor: int = 100
    available_max_minor: int = 1_000_000


@dataclass(frozen=True)
class Settings:
    db_path: str = "var/fazetime.db"
    evidence_dir: str = "var/evidence"
    evidence_keep_frames: int = 600
    evidence_keep_s: int = 30 * 60
    evidence_max_bytes: int = 300 * 1024
    worker_json_max_bytes: int = 256 * 1024
    host: str = "127.0.0.1"
    port: int = 8000
    allowed_origins: tuple[str, ...] = DEFAULT_ALLOWED_ORIGINS  # WebSocket Origin allowlist (exact)
    cors_origins: tuple[str, ...] | None = None  # None -> the chrome-extension:// entries of allowed_origins
    seed_grant_minor: int = 2_000
    fixture_credit_max_minor: int = 100_000
    min_lead_ms: int = 30_000
    max_close_in_s: int = 6 * 3600
    max_resolve_in_s: int = 6 * 3600
    session_ttl_s: int = 72 * 3600
    invite_ttl_s: int = 24 * 3600
    ws_ticket_ttl_s: int = 30
    ws_auth_timeout_s: float = 5.0
    ws_ping_interval_s: float = 25.0
    ws_session_recheck_s: float = 30.0  # fixed timer, independent of traffic (<= 60 s)
    sweeper_enabled: bool = True
    sweeper_interval_s: float = 1.0
    # Source health thresholds (§9.4, D29). Health is STOPPED until P3 supplies observations.
    health_live_max_s: float = 12.0
    health_stale_max_s: float = 30.0
    health_backlog_max_ms: int = 12_000
    # Presence (PROJECT_PLAN P2, §9.13 I).
    presence_heartbeat_interval_ms: int = 15_000
    presence_ttl_ms: int = 45_000
    # Rate limits: (max events, window seconds). In-memory, single process.
    rl_enroll: tuple[int, float] = (10, 600.0)
    rl_wager: tuple[int, float] = (20, 10.0)
    rl_ws_ticket: tuple[int, float] = (20, 60.0)
    rl_presence: tuple[int, float] = (30, 60.0)
    log_level: str = "INFO"
    operator_dist: str | None = None  # optional apps/operator build served same-origin at /operator/
    limits: Limits = field(default_factory=Limits)

    def with_overrides(self, **kwargs) -> "Settings":
        return replace(self, **kwargs)


def _origins(raw: str) -> tuple[str, ...]:
    origins = tuple(o.strip().rstrip("/") for o in raw.split(",") if o.strip())
    bad = [o for o in origins if "*" in o or "://" not in o]
    if bad:
        raise ValueError(f"origins must be exact scheme://host entries, no wildcards: {bad}")
    return origins


def cors_origins(settings: "Settings") -> tuple[str, ...]:
    if settings.cors_origins is not None:
        return settings.cors_origins
    return tuple(o for o in settings.allowed_origins if o.startswith("chrome-extension://"))


def load_settings() -> Settings:
    origins = _origins(_env("FAZETIME_ALLOWED_ORIGINS", ",".join(DEFAULT_ALLOWED_ORIGINS)))
    cors_raw = os.environ.get("FAZETIME_CORS_ORIGINS")
    data_dir = _env("FAZETIME_DATA_DIR", "var")
    return Settings(
        db_path=_env("FAZETIME_DB_PATH", os.path.join(data_dir, "fazetime.db")),
        evidence_dir=_env("FAZETIME_EVIDENCE_DIR", os.path.join(data_dir, "evidence")),
        evidence_keep_frames=_env_int("FAZETIME_EVIDENCE_KEEP_FRAMES", 600),
        evidence_keep_s=_env_int("FAZETIME_EVIDENCE_KEEP_S", 30 * 60),
        health_live_max_s=_env_float("FAZETIME_HEALTH_LIVE_MAX_S", 12.0),
        health_stale_max_s=_env_float("FAZETIME_HEALTH_STALE_MAX_S", 30.0),
        health_backlog_max_ms=_env_int("FAZETIME_HEALTH_BACKLOG_MAX_MS", 12_000),
        host=_env("FAZETIME_HOST", "127.0.0.1"),
        port=_env_int("FAZETIME_PORT", 8000),
        allowed_origins=origins,
        cors_origins=_origins(cors_raw) if cors_raw else None,
        seed_grant_minor=_env_int("FAZETIME_SEED_GRANT_MINOR", 2_000),
        min_lead_ms=_env_int("FAZETIME_MIN_LEAD_MS", 30_000),
        sweeper_enabled=_env_bool("FAZETIME_SWEEPER_ENABLED", True),
        sweeper_interval_s=_env_float("FAZETIME_SWEEPER_INTERVAL_S", 1.0),
        log_level=_env("FAZETIME_LOG_LEVEL", "INFO"),
        operator_dist=os.environ.get("FAZETIME_OPERATOR_DIST") or None,
    )
