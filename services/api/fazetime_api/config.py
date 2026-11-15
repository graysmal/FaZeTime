"""Runtime settings, read from FAZETIME_* environment variables. No secrets live here."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace

DEFAULT_ALLOWED_ORIGINS = ("https://www.twitch.tv", "chrome-extension://*")


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
    host: str = "127.0.0.1"
    port: int = 8000
    allowed_origins: tuple[str, ...] = DEFAULT_ALLOWED_ORIGINS
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
    sweeper_enabled: bool = True
    sweeper_interval_s: float = 1.0
    # Source health thresholds (§9.4, D29). Health is STOPPED until P3 supplies observations.
    health_live_max_s: float = 12.0
    health_stale_max_s: float = 30.0
    # Presence (PROJECT_PLAN P2, §9.13 I).
    presence_heartbeat_interval_ms: int = 15_000
    presence_ttl_ms: int = 45_000
    # Rate limits: (max events, window seconds). In-memory, single process.
    rl_enroll: tuple[int, float] = (10, 600.0)
    rl_wager: tuple[int, float] = (20, 10.0)
    rl_ws_ticket: tuple[int, float] = (20, 60.0)
    rl_presence: tuple[int, float] = (30, 60.0)
    log_level: str = "INFO"
    limits: Limits = field(default_factory=Limits)

    def with_overrides(self, **kwargs) -> "Settings":
        return replace(self, **kwargs)


def load_settings() -> Settings:
    origins = tuple(
        o.strip() for o in _env("FAZETIME_ALLOWED_ORIGINS", ",".join(DEFAULT_ALLOWED_ORIGINS)).split(",") if o.strip()
    )
    return Settings(
        db_path=_env("FAZETIME_DB_PATH", "var/fazetime.db"),
        host=_env("FAZETIME_HOST", "127.0.0.1"),
        port=_env_int("FAZETIME_PORT", 8000),
        allowed_origins=origins,
        seed_grant_minor=_env_int("FAZETIME_SEED_GRANT_MINOR", 2_000),
        min_lead_ms=_env_int("FAZETIME_MIN_LEAD_MS", 30_000),
        sweeper_enabled=_env_bool("FAZETIME_SWEEPER_ENABLED", True),
        sweeper_interval_s=_env_float("FAZETIME_SWEEPER_INTERVAL_S", 1.0),
        log_level=_env("FAZETIME_LOG_LEVEL", "INFO"),
    )
