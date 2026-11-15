"""Domain commands: runs, wallets, markets, wagers, settlement, voids, fixture credits.

Every public function here must run inside a caller-held ``BEGIN IMMEDIATE`` transaction
(``Database.write()``). Transitions are conditional UPDATEs (state + aggregate_version compare-and-set),
written with their ledger rows and outbox events in that single transaction (CONTRACTS §9.3).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from . import events, ledger, source_health, timeutil, views
from .config import Settings
from .errors import ApiError
from .ids import new_id, request_hash
from .schemas import WagerReceipt, WagerRequest
from .settlement import ALGORITHM, StakeLine, compute_payouts

log = logging.getLogger("fazetime.domain")

NONTERMINAL = ("OPEN", "LOCKED", "EVALUATING")
WALLET_ROLES = ("VIEWER",)  # D30: operators have no wallet, seed or raffle weight


class ConcurrentChange(RuntimeError):
    """A conditional UPDATE matched no row. Inside BEGIN IMMEDIATE this indicates a logic error."""


@dataclass(frozen=True)
class Principal:
    user_id: str
    role: str
    is_bot: bool
    session_id: str
    session_expires_at_utc: str


def _fmt(dt: datetime) -> str:
    return timeutil.fmt(dt)


# ------------------------------------------------------------------------------------------------
# Idempotency (§9.7) and audit
# ------------------------------------------------------------------------------------------------
def hash_request(op_type: str, payload: dict) -> str:
    return request_hash({"op_type": op_type, "request": payload})


def check_replay(conn: sqlite3.Connection, actor_user_id: str, operation_id: str, op_type: str, req_hash: str):
    """Return the stored receipt (replayed=true) for an identical retry, or raise IDEMPOTENCY_CONFLICT."""
    row = conn.execute(
        "SELECT op_type, request_hash, response_json FROM operations WHERE actor_user_id = ? AND operation_id = ?",
        (actor_user_id, operation_id),
    ).fetchone()
    if row is None:
        return None
    if row["op_type"] != op_type or row["request_hash"] != req_hash:
        raise ApiError(
            "IDEMPOTENCY_CONFLICT",
            "This operation_id was already used for a different request; nothing was changed.",
            operation_id=operation_id,
        )
    body = json.loads(row["response_json"])
    body["replayed"] = True
    return body


def record_operation(
    conn: sqlite3.Connection,
    *,
    actor_user_id: str,
    operation_id: str,
    op_type: str,
    req_hash: str,
    http_status: int,
    resource_type: str | None,
    resource_id: str | None,
    response: dict,
    now: datetime,
) -> None:
    stored = dict(response)
    stored["replayed"] = False
    conn.execute(
        "INSERT INTO operations (actor_user_id, operation_id, op_type, request_hash, http_status, resource_type,"
        " resource_id, response_json, created_at_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (actor_user_id, operation_id, op_type, req_hash, http_status, resource_type, resource_id,
         json.dumps(stored, separators=(",", ":")), _fmt(now)),
    )


def audit(
    conn: sqlite3.Connection,
    *,
    actor_user_id: str | None,
    actor_kind: str,
    action: str,
    now: datetime,
    operation_id: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    detail: dict | None = None,
) -> None:
    conn.execute(
        "INSERT INTO audit_log (actor_user_id, actor_kind, action, operation_id, target_type, target_id,"
        " detail_json, created_at_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (actor_user_id, actor_kind, action, operation_id, target_type, target_id,
         json.dumps(detail or {}, separators=(",", ":")), _fmt(now)),
    )


# ------------------------------------------------------------------------------------------------
# Runs and wallets (§9.5)
# ------------------------------------------------------------------------------------------------
def seed_wallet(conn: sqlite3.Connection, run: sqlite3.Row, user: sqlite3.Row, now: datetime) -> bool:
    """Create the (user, run) wallet and its labelled SEED_GRANT exactly once. Returns True if seeded."""
    now_s = _fmt(now)
    wallet_id = ledger.ensure_account(
        conn, kind="USER_AVAILABLE", run_id=run["run_id"], user_id=user["user_id"],
        is_simulated=bool(user["is_bot"]), now=now_s,
    )
    seed = int(run["seed_grant_minor"])
    source_key = f"seed:{run['run_id']}:{user['user_id']}"
    if seed <= 0 or ledger.source_exists(conn, source_key) is not None:
        return False
    funding_id = ledger.ensure_account(conn, kind="FUNDING_SOURCE", run_id=run["run_id"], now=now_s)
    ledger.post(
        conn, run_id=run["run_id"], reason="SEED_GRANT", source_key=source_key,
        entries=[(funding_id, -seed), (wallet_id, seed)], now=now_s, is_simulated=bool(user["is_bot"]),
    )
    events.emit_wallet(conn, run["run_id"], user["user_id"], now)
    return True


SETTABLE_AI_MODES = ("OFF", "SHADOW", "APPROVAL", "AUTOMATIC")


def allowed_ai_mode(mode: str | None, settings: Settings) -> str:
    """The mode a new run may start in. AUTOMATIC needs the server flag (D32); anything unknown is OFF."""
    mode = (mode or "OFF").upper()
    if mode not in SETTABLE_AI_MODES:
        return "OFF"
    if mode == "AUTOMATIC" and not settings.allow_automatic:
        return "APPROVAL"
    return mode


def _create_run(
    conn: sqlite3.Connection, stream_id: str, now: datetime, settings: Settings, ai_mode: str | None = None
) -> sqlite3.Row:
    run_id = new_id("run")
    conn.execute(
        "INSERT INTO runs (run_id, stream_id, state, ai_mode, seed_grant_minor, created_at_utc)"
        " VALUES (?, ?, 'ACTIVE', ?, ?, ?)",
        (run_id, stream_id, allowed_ai_mode(ai_mode or settings.ai_mode_default, settings),
         int(settings.seed_grant_minor), _fmt(now)),
    )
    ledger.ensure_account(conn, kind="FUNDING_SOURCE", run_id=run_id, now=_fmt(now))
    run = views.get_run(conn, run_id)
    users = conn.execute(
        "SELECT * FROM users WHERE role = 'VIEWER' ORDER BY user_id"
    ).fetchall()
    for user in users:
        seed_wallet(conn, run, user, now)
    return run


def create_stream_if_absent(
    conn: sqlite3.Connection, *, twitch_channel_login: str, now: datetime, settings: Settings
) -> tuple[sqlite3.Row, bool]:
    login = twitch_channel_login.lower()
    existing = views.get_stream(conn)
    if existing is not None:
        if existing["twitch_channel_login"] != login:
            raise ApiError(
                "VALIDATION_FAILED",
                "v1 supports exactly one stream and it already exists for another channel.",
                details={"fields": [{"loc": ["twitch_channel_login"], "msg": "a stream already exists"}]},
            )
        return existing, False
    stream_id = new_id("str")
    conn.execute(
        "INSERT INTO streams (stream_id, twitch_channel_login, aggregate_version, created_at_utc) VALUES (?, ?, 1, ?)",
        (stream_id, login, _fmt(now)),
    )
    _create_run(conn, stream_id, now, settings)
    events.emit_stream(conn, stream_id, now, settings)
    return views.get_stream(conn, stream_id), True


def reset_run(conn: sqlite3.Connection, *, stream_id: str, now: datetime, settings: Settings) -> dict:
    """§9.5: void the nonterminal market (RUN_RESET, refunds), archive the run, create + seed a new run."""
    stream = views.get_stream(conn, stream_id)
    if stream is None:
        raise ApiError("NOT_FOUND", "Unknown stream.")
    old = views.get_active_run(conn, stream_id)
    voided = None
    market = views.nonterminal_market(conn, old["run_id"])
    if market is not None:
        _void_market(conn, market, "RUN_RESET", now)
        voided = market["market_id"]
    cur = conn.execute(
        "UPDATE runs SET state = 'ARCHIVED', archived_at_utc = ? WHERE run_id = ? AND state = 'ACTIVE'",
        (_fmt(now), old["run_id"]),
    )
    if cur.rowcount != 1:
        raise ConcurrentChange("run was not ACTIVE")
    new = _create_run(conn, stream_id, now, settings, ai_mode=old["ai_mode"])  # the operator's AI mode survives a reset
    version = int(stream["aggregate_version"])
    cur = conn.execute(
        "UPDATE streams SET aggregate_version = ? WHERE stream_id = ? AND aggregate_version = ?",
        (version + 1, stream_id, version),
    )
    if cur.rowcount != 1:
        raise ConcurrentChange("stream version changed")
    events.emit_stream(conn, stream_id, now, settings)
    return {
        "archived_stream_session_id": old["run_id"],
        "stream_session_id": new["run_id"],
        "voided_market_id": voided,
    }


def require_active_run(conn: sqlite3.Connection) -> tuple[sqlite3.Row, sqlite3.Row]:
    stream = views.get_stream(conn)
    run = views.get_active_run(conn, stream["stream_id"]) if stream is not None else None
    if stream is None or run is None:
        raise ApiError("NOT_FOUND", "No stream/run exists yet; an operator must create the stream first.")
    return stream, run


def fixture_credit(
    conn: sqlite3.Connection,
    *,
    actor_user_id: str,
    operation_id: str,
    user_id: str,
    amount_minor: int,
    now: datetime,
    settings: Settings,
) -> dict:
    _, run = require_active_run(conn)
    user = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if user is None or user["role"] not in WALLET_ROLES:
        raise ApiError("NOT_FOUND", "Unknown user.")
    now_s = _fmt(now)
    wallet_id = ledger.ensure_account(
        conn, kind="USER_AVAILABLE", run_id=run["run_id"], user_id=user_id, is_simulated=bool(user["is_bot"]), now=now_s
    )
    available = int(ledger.wallet_account(conn, run["run_id"], user_id)["balance_minor"])
    cap = settings.limits.available_max_minor
    if available + amount_minor > cap:
        raise ApiError(
            "INVALID_AMOUNT",
            "Credit would exceed the maximum available balance.",
            details={"min_minor": 1, "max_minor": max(0, cap - available), "step_minor": 1},
        )
    funding_id = ledger.ensure_account(conn, kind="FUNDING_SOURCE", run_id=run["run_id"], now=now_s)
    txn_id = ledger.post(
        conn, run_id=run["run_id"], reason="FIXTURE_CREDIT", source_key=f"fixture_credit:{actor_user_id}:{operation_id}",
        entries=[(funding_id, -amount_minor), (wallet_id, amount_minor)], now=now_s,
        actor_user_id=actor_user_id, operation_id=operation_id, is_simulated=bool(user["is_bot"]),
    )
    events.emit_wallet(conn, run["run_id"], user_id, now)
    return {
        "txn_id": txn_id,
        "user_id": user_id,
        "amount_minor": amount_minor,
        "reason": "FIXTURE_CREDIT",
        "wallet_after": views.wallet_summary(conn, run["run_id"], user_id),
    }


# ------------------------------------------------------------------------------------------------
# Markets (§9.3)
# ------------------------------------------------------------------------------------------------
def _update_market(conn: sqlite3.Connection, market: sqlite3.Row, *, to_state: str | None = None, **fields) -> sqlite3.Row:
    sets = dict(fields)
    if to_state is not None:
        sets["state"] = to_state
    sets["aggregate_version"] = int(market["aggregate_version"]) + 1
    assignments = ", ".join(f"{column} = ?" for column in sets)
    cur = conn.execute(
        f"UPDATE markets SET {assignments} WHERE market_id = ? AND state = ? AND aggregate_version = ?",
        (*sets.values(), market["market_id"], market["state"], market["aggregate_version"]),
    )
    if cur.rowcount != 1:
        raise ConcurrentChange(f"market {market['market_id']} changed concurrently")
    return views.get_market(conn, market["market_id"])


def _market_closed(market: sqlite3.Row, reason: str, message: str) -> ApiError:
    return ApiError(
        "MARKET_CLOSED",
        message,
        details={"state": market["state"], "close_at_utc": market["close_at_utc"], "reason": reason},
    )


def _wrong_run(conn: sqlite3.Connection, run: sqlite3.Row | None) -> ApiError:
    stream = views.get_stream(conn, run["stream_id"] if run is not None else None)
    current = views.get_active_run(conn, stream["stream_id"]) if stream is not None else None
    return ApiError(
        "WRONG_RUN",
        "That stream session is not the current run; refresh the snapshot.",
        details={"current_stream_session_id": current["run_id"] if current is not None else None},
    )


def _stale_market(conn: sqlite3.Connection, run_id: str, message: str) -> ApiError:
    current = views.nonterminal_market(conn, run_id)
    return ApiError(
        "STALE_MARKET",
        message,
        details={
            "current_market_id": current["market_id"] if current is not None else None,
            "current_rules_version": int(current["rules_version"]) if current is not None else None,
        },
    )


def create_fixture_market(
    conn: sqlite3.Connection,
    *,
    actor_user_id: str,
    question: str,
    yes_label: str,
    no_label: str,
    close_in_s: int,
    resolve_in_s: int,
    now: datetime,
    settings: Settings,
) -> sqlite3.Row:
    _, run = require_active_run(conn)
    problems = []
    if close_in_s * 1000 < settings.min_lead_ms:
        problems.append({"loc": ["close_in_s"], "msg": f"must be at least {settings.min_lead_ms // 1000} s (min_lead_ms)"})
    if close_in_s > settings.max_close_in_s:
        problems.append({"loc": ["close_in_s"], "msg": f"must be at most {settings.max_close_in_s} s"})
    if resolve_in_s > settings.max_resolve_in_s:
        problems.append({"loc": ["resolve_in_s"], "msg": f"must be at most {settings.max_resolve_in_s} s"})
    if problems:
        raise ApiError("VALIDATION_FAILED", "Invalid fixture market timing.", details={"fields": problems})
    market_id = new_id("mkt")
    conn.execute(
        "INSERT INTO markets (market_id, run_id, origin, state, question, yes_label, no_label, rules_version,"
        " aggregate_version, close_in_ms, resolve_in_ms, created_by_user_id, created_at_utc)"
        " VALUES (?, ?, 'OPERATOR_FIXTURE', 'DRAFT', ?, ?, ?, 1, 1, ?, ?, ?, ?)",
        (market_id, run["run_id"], question, yes_label, no_label, close_in_s * 1000, resolve_in_s * 1000,
         actor_user_id, _fmt(now)),
    )
    return views.get_market(conn, market_id)


def open_market(conn: sqlite3.Connection, *, market_id: str, now: datetime, settings: Settings) -> sqlite3.Row:
    market = views.get_market(conn, market_id)
    if market is None:
        raise ApiError("NOT_FOUND", "Unknown market.")
    run = views.get_run(conn, market["run_id"])
    if run["state"] != "ACTIVE":
        raise _wrong_run(conn, run)
    if market["state"] != "DRAFT":
        raise _market_closed(market, "STATE", "Only a DRAFT market can be opened.")
    if views.nonterminal_market(conn, run["run_id"]) is not None:
        raise _stale_market(conn, run["run_id"], "Another market in this run is not terminal yet.")
    if market["origin"] in source_health.TWITCH_ORIGINS:
        health = source_health.current(conn, run["stream_id"], now, settings)
        if health["state"] != "LIVE":
            raise ApiError("SOURCE_STALE", "Twitch source is not LIVE.", details={"source_state": health["state"]})
    close_at = now + timedelta(milliseconds=int(market["close_in_ms"]))
    resolve_by = close_at + timedelta(milliseconds=int(market["resolve_in_ms"]))
    lead_ms = int((close_at - now).total_seconds() * 1000)
    if lead_ms < settings.min_lead_ms:
        raise ApiError(
            "VALIDATION_FAILED",
            "close_at_utc is too soon (min_lead_ms).",
            details={"fields": [{"loc": ["close_in_s"], "msg": f"lead {lead_ms} ms < {settings.min_lead_ms} ms"}]},
        )
    ledger.ensure_account(conn, kind="MARKET_ESCROW", run_id=run["run_id"], market_id=market_id, now=_fmt(now))
    updated = _update_market(
        conn, market, to_state="OPEN",
        opened_at_utc=_fmt(now), close_at_utc=_fmt(close_at), resolve_by_utc=_fmt(resolve_by),
    )
    events.emit_market(conn, market_id, "market.opened", now)
    return updated


def pin_evidence(conn: sqlite3.Connection, market_id: str, evidence_refs: list[dict]) -> None:
    """Frames a market cites survive evidence pruning (§9.16 item 3)."""
    for evidence_id in sorted({r["evidence_id"] for r in evidence_refs if r.get("evidence_id")}):
        conn.execute("UPDATE evidence SET pinned_by_market_id = ? WHERE evidence_id = ? AND pinned_by_market_id IS NULL",
                     (market_id, evidence_id))


def open_ai_market(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    origin: str,
    cnd_id: str,
    question: str,
    yes_label: str,
    no_label: str,
    criteria: dict,
    cancellation: list[str],
    evidence_refs: list[dict],
    close_at: datetime,
    resolve_in_s: int,
    created_by_user_id: str | None,
    now: datetime,
    settings: Settings,
) -> sqlite3.Row:
    """Create and open an AI market in one step. The DRAFT -> OPEN guards of §9.3 are rechecked here, at commit,
    against the real clock: active run, no other nonterminal market, source LIVE, close_at - now >= min_lead_ms."""
    if origin not in source_health.TWITCH_ORIGINS:
        raise ValueError("AI markets have origin AI_APPROVED or AI_AUTOMATIC")
    run = views.get_run(conn, run_id)
    if run is None or run["state"] != "ACTIVE":
        raise _wrong_run(conn, run)
    if views.nonterminal_market(conn, run_id) is not None:
        raise _stale_market(conn, run_id, "Another market in this run is not terminal yet.")
    health = source_health.current(conn, run["stream_id"], now, settings)
    if health["state"] != "LIVE":
        raise ApiError("SOURCE_STALE", "Twitch source is not LIVE.", details={"source_state": health["state"]})
    lead_ms = int((close_at - now).total_seconds() * 1000)
    if lead_ms < max(1, settings.min_lead_ms):
        raise ApiError("VALIDATION_FAILED", "close_at_utc is too soon (min_lead_ms).",
                       details={"fields": [{"loc": ["close_in_s"], "msg": f"lead {lead_ms} ms < {settings.min_lead_ms} ms"}]})
    resolve_by = close_at + timedelta(seconds=int(resolve_in_s))
    market_id = new_id("mkt")
    conn.execute(
        "INSERT INTO markets (market_id, run_id, origin, state, question, yes_label, no_label, rules_version,"
        " aggregate_version, close_in_ms, resolve_in_ms, created_by_user_id, created_at_utc, candidate_cnd_id,"
        " criteria_json, cancellation_json, opening_evidence_json)"
        " VALUES (?, ?, ?, 'DRAFT', ?, ?, ?, 1, 1, ?, ?, ?, ?, ?, ?, ?, ?)",
        (market_id, run_id, origin, question, yes_label, no_label, lead_ms, int(resolve_in_s) * 1000,
         created_by_user_id, _fmt(now), cnd_id, json.dumps(criteria, separators=(",", ":")),
         json.dumps(list(cancellation), separators=(",", ":")), json.dumps(evidence_refs, separators=(",", ":"))),
    )
    market = views.get_market(conn, market_id)
    ledger.ensure_account(conn, kind="MARKET_ESCROW", run_id=run_id, market_id=market_id, now=_fmt(now))
    updated = _update_market(
        conn, market, to_state="OPEN",
        opened_at_utc=_fmt(now), close_at_utc=_fmt(close_at), resolve_by_utc=_fmt(resolve_by),
    )
    pin_evidence(conn, market_id, evidence_refs)
    events.emit_market(conn, market_id, "market.opened", now)
    log.info("AI market %s OPEN origin=%s candidate=%s lead_ms=%d", market_id, origin, cnd_id, lead_ms)
    return updated


def _accepted_wagers(conn: sqlite3.Connection, market_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM wagers WHERE market_id = ? AND status = 'ACCEPTED' ORDER BY wager_id", (market_id,)
    ).fetchall()


def _set_wager_terminal(conn: sqlite3.Connection, wager: sqlite3.Row, **fields) -> None:
    fields["version"] = int(wager["version"]) + 1
    assignments = ", ".join(f"{column} = ?" for column in fields)
    cur = conn.execute(
        f"UPDATE wagers SET {assignments} WHERE wager_id = ? AND status = 'ACCEPTED' AND version = ?",
        (*fields.values(), wager["wager_id"], wager["version"]),
    )
    if cur.rowcount != 1:
        raise ConcurrentChange(f"wager {wager['wager_id']} changed concurrently")


def _assert_escrow_empty(conn: sqlite3.Connection, market_id: str) -> None:
    escrow = ledger.escrow_account(conn, market_id)
    if escrow is not None and int(escrow["balance_minor"]) != 0:
        raise ledger.LedgerError(f"escrow for {market_id} not empty after terminal transition")


def _void_market(
    conn: sqlite3.Connection, market: sqlite3.Row, reason: str, now: datetime, *, at_lock: bool = False,
    resolution: dict | None = None,
) -> sqlite3.Row:
    """Refund every accepted wager exactly once and mark the market VOID, in the caller's transaction."""
    now_s = _fmt(now)
    run_id = market["run_id"]
    wagers = _accepted_wagers(conn, market["market_id"])
    escrow = ledger.escrow_account(conn, market["market_id"])
    users: list[str] = []
    for wager in wagers:
        amount = int(wager["amount_minor"])
        wallet = ledger.wallet_account(conn, run_id, wager["user_id"])
        txn_id = ledger.post(
            conn, run_id=run_id, reason="REFUND", source_key=f"refund:{wager['wager_id']}",
            entries=[(int(escrow["account_id"]), -amount), (int(wallet["account_id"]), amount)], now=now_s,
            market_id=market["market_id"], is_simulated=bool(wager["is_simulated"]),
        )
        _set_wager_terminal(conn, wager, status="REFUNDED", refund_minor=amount, terminal_txn_id=txn_id,
                            terminal_at_utc=now_s)
        if wager["user_id"] not in users:
            users.append(wager["user_id"])
    fields = {"void_reason": reason, "terminal_at_utc": now_s, **(resolution or {})}
    if at_lock:
        fields["locked_at_utc"] = now_s
    updated = _update_market(conn, market, to_state="VOID", **fields)
    _assert_escrow_empty(conn, market["market_id"])
    events.emit_market(conn, market["market_id"], "market.voided", now)
    for wager in wagers:
        events.emit_wager(conn, wager["wager_id"], now)
    for user_id in users:
        events.emit_wallet(conn, run_id, user_id, now)
    log.info("market %s VOID reason=%s refunds=%d", market["market_id"], reason, len(wagers))
    return updated


def lock_if_due(conn: sqlite3.Connection, market_id: str, now: datetime) -> bool:
    """OPEN -> LOCKED at close_at_utc (exclusive deadline); empty/one-sided pools VOID here (D12)."""
    market = views.get_market(conn, market_id)
    if market is None or market["state"] != "OPEN" or now < timeutil.parse(market["close_at_utc"]):
        return False
    yes, no = int(market["yes_minor"]), int(market["no_minor"])
    if yes == 0 or no == 0:
        _void_market(conn, market, "EMPTY_POOL" if yes == 0 and no == 0 else "ONE_SIDED_POOL", now, at_lock=True)
        return True
    run = views.get_run(conn, market["run_id"])
    src = conn.execute("SELECT current_source_epoch, last_media_end_ms FROM source_state WHERE stream_id = ?",
                       (run["stream_id"],)).fetchone()
    _update_market(conn, market, to_state="LOCKED", locked_at_utc=_fmt(now),
                   lock_source_epoch=src["current_source_epoch"] if src else None,
                   lock_media_ms=src["last_media_end_ms"] if src else None)
    events.emit_market(conn, market_id, "market.locked", now)
    return True


def evaluate_if_locked(conn: sqlite3.Connection, market_id: str, now: datetime) -> bool:
    market = views.get_market(conn, market_id)
    if market is None or market["state"] != "LOCKED":
        return False
    _update_market(conn, market, to_state="EVALUATING")
    events.emit_market(conn, market_id, "market.evaluating", now)
    return True


def timeout_if_due(conn: sqlite3.Connection, market_id: str, now: datetime) -> bool:
    """LOCKED/EVALUATING -> VOID(RESOLUTION_TIMEOUT) at resolve_by_utc, in every mode."""
    market = views.get_market(conn, market_id)
    if market is None or market["state"] not in ("LOCKED", "EVALUATING"):
        return False
    if now < timeutil.parse(market["resolve_by_utc"]):
        return False
    _void_market(conn, market, "RESOLUTION_TIMEOUT", now)
    return True


def source_gap_if_needed(conn: sqlite3.Connection, market_id: str, now: datetime, settings: Settings) -> bool:
    """Twitch-origin markets VOID with SOURCE_GAP when health is GAP/STOPPED (§9.4). Fixtures are exempt."""
    market = views.get_market(conn, market_id)
    if market is None or market["state"] not in NONTERMINAL or market["origin"] not in source_health.TWITCH_ORIGINS:
        return False
    run = views.get_run(conn, market["run_id"])
    health = source_health.current(conn, run["stream_id"], now, settings)
    if health["state"] not in ("GAP", "STOPPED"):
        return False
    _void_market(conn, market, "SOURCE_GAP", now)
    return True


def settle_fixture_market(
    conn: sqlite3.Connection, *, market_id: str, winning_side: str, now: datetime
) -> sqlite3.Row:
    """EVALUATING -> SETTLED before resolve_by_utc. Fixture origins only (§9.17 item 5)."""
    market = views.get_market(conn, market_id)
    if market is None:
        raise ApiError("NOT_FOUND", "Unknown market.")
    if market["origin"] not in source_health.FIXTURE_ORIGINS:
        raise ApiError("VALIDATION_FAILED", "Only fixture-origin markets settle through this operator route.",
                       details={"fields": [{"loc": ["market_id"], "msg": "not a fixture market"}]})
    return _settle_market(conn, market, winning_side, now)


def settle_ai_market(
    conn: sqlite3.Connection, *, market_id: str, winning_side: str, now: datetime, resolution: dict
) -> sqlite3.Row:
    """An accepted AI resolution (operator-approved or AUTOMATIC) settles through the same path as fixtures."""
    market = views.get_market(conn, market_id)
    if market is None:
        raise ApiError("NOT_FOUND", "Unknown market.")
    if market["origin"] not in source_health.TWITCH_ORIGINS:
        raise ApiError("VALIDATION_FAILED", "Only AI-origin markets settle from an AI resolution.",
                       details={"fields": [{"loc": ["market_id"], "msg": "not an AI market"}]})
    return _settle_market(conn, market, winning_side, now, resolution=resolution)


def void_ai_unresolvable(conn: sqlite3.Connection, *, market_id: str, now: datetime, resolution: dict) -> sqlite3.Row:
    """An accepted UNRESOLVABLE resolution: VOID with UNRESOLVABLE, every stake refunded once (§9.3)."""
    market = views.get_market(conn, market_id)
    if market is None:
        raise ApiError("NOT_FOUND", "Unknown market.")
    if market["state"] not in NONTERMINAL:
        raise _market_closed(market, "STATE", "The market is already terminal.")
    if now >= timeutil.parse(market["resolve_by_utc"]):
        raise _market_closed(market, "DEADLINE", "The resolution deadline has passed; the market will VOID.")
    return _void_market(conn, market, "UNRESOLVABLE", now, resolution=resolution)


def _settle_market(
    conn: sqlite3.Connection, market: sqlite3.Row, winning_side: str, now: datetime, *, resolution: dict | None = None
) -> sqlite3.Row:
    """EVALUATING -> SETTLED before resolve_by_utc. Payouts per ECONOMICS §4, all in this transaction."""
    market_id = market["market_id"]
    run = views.get_run(conn, market["run_id"])
    if run["state"] != "ACTIVE":
        raise _wrong_run(conn, run)
    if market["state"] != "EVALUATING":
        raise _market_closed(market, "STATE", "Only an EVALUATING market can be settled.")
    if now >= timeutil.parse(market["resolve_by_utc"]):
        raise _market_closed(market, "DEADLINE", "The resolution deadline has passed; the market will VOID.")
    now_s = _fmt(now)
    run_id = market["run_id"]
    wagers = _accepted_wagers(conn, market_id)
    payouts = compute_payouts(
        [StakeLine(w["wager_id"], w["side"], int(w["amount_minor"])) for w in wagers], winning_side
    )  # raises SettlementInvariantError unless 0 < W < T; nothing is written in that case
    escrow = ledger.escrow_account(conn, market_id)
    bumped: set[str] = set()
    users: list[str] = []
    for wager in wagers:
        if wager["user_id"] not in users:
            users.append(wager["user_id"])
        wallet = ledger.wallet_account(conn, run_id, wager["user_id"])
        if wager["wager_id"] in payouts:
            payout = payouts[wager["wager_id"]]
            txn_id = ledger.post(
                conn, run_id=run_id, reason="PAYOUT", source_key=f"payout:{wager['wager_id']}",
                entries=[(int(escrow["account_id"]), -payout), (int(wallet["account_id"]), payout)], now=now_s,
                market_id=market_id, is_simulated=bool(wager["is_simulated"]),
            )
            _set_wager_terminal(conn, wager, status="WON", payout_minor=payout, terminal_txn_id=txn_id,
                                terminal_at_utc=now_s)
            bumped.add(wager["user_id"])
        else:
            _set_wager_terminal(conn, wager, status="LOST", payout_minor=0, terminal_at_utc=now_s)
    for user_id in users:
        if user_id not in bumped:  # in_play fell without a movement: advance balance_version
            ledger.bump_version(conn, int(ledger.wallet_account(conn, run_id, user_id)["account_id"]))
    updated = _update_market(conn, market, to_state="SETTLED", winning_side=winning_side,
                             settlement_algorithm=ALGORITHM, terminal_at_utc=now_s, **(resolution or {}))
    _assert_escrow_empty(conn, market_id)
    events.emit_market(conn, market_id, "market.settled", now)
    for wager in wagers:
        events.emit_wager(conn, wager["wager_id"], now)
    for user_id in users:
        events.emit_wallet(conn, run_id, user_id, now)
    log.info("market %s SETTLED side=%s winners=%d", market_id, winning_side, len(payouts))
    return updated


def operator_void(conn: sqlite3.Connection, *, market_id: str, now: datetime) -> sqlite3.Row:
    market = views.get_market(conn, market_id)
    if market is None:
        raise ApiError("NOT_FOUND", "Unknown market.")
    if market["state"] not in NONTERMINAL:
        raise _market_closed(market, "STATE", "Only an OPEN, LOCKED or EVALUATING market can be voided.")
    return _void_market(conn, market, "OPERATOR_CANCELLED", now)


# ------------------------------------------------------------------------------------------------
# Wagers (§9.6) — check order inside BEGIN IMMEDIATE is exactly the contract's
# ------------------------------------------------------------------------------------------------
def place_wager(conn: sqlite3.Connection, *, principal: Principal, req: WagerRequest, clock, settings: Settings):
    """Returns (receipt, replayed). Raises ApiError for every business rejection (never cached)."""
    if principal.role != "VIEWER":  # D30, also enforced by the route dependency
        raise ApiError("FORBIDDEN", "Only viewer accounts can place wagers (D30).")
    now = clock.now()  # read after BEGIN IMMEDIATE acquired the write lock
    req_hash = hash_request("WAGER", req.model_dump(mode="json"))
    # 1. idempotency replay or conflict
    replay = check_replay(conn, principal.user_id, req.operation_id, "WAGER", req_hash)
    if replay is not None:
        return replay, True
    # 2. WRONG_RUN
    run = views.get_run(conn, req.stream_session_id)
    if run is None or run["state"] != "ACTIVE":
        raise _wrong_run(conn, run)
    # 3. STALE_MARKET (unknown market, not in this run, DRAFT, or rules_version mismatch)
    market = views.get_market(conn, req.market_id)
    if (
        market is None
        or market["run_id"] != run["run_id"]
        or market["state"] == "DRAFT"
        or int(market["rules_version"]) != req.rules_version
    ):
        raise _stale_market(conn, run["run_id"], "That market or rules_version is not current; refresh the snapshot.")
    # 4. MARKET_CLOSED (state, deadline, pause)
    if market["state"] != "OPEN":
        raise _market_closed(market, "STATE", "Betting is closed for this market.")
    close_at = timeutil.parse(market["close_at_utc"])
    if now >= close_at:
        raise _market_closed(market, "DEADLINE", "Betting closed at close_at_utc.")
    # (No operator pause exists in P2; DRAW_BOUNDARY blocks new markets only, D27.)
    # 5. SOURCE_STALE (Twitch-origin markets only; fixture origins are exempt and labelled)
    if market["origin"] in source_health.TWITCH_ORIGINS:
        health = source_health.current(conn, run["stream_id"], now, settings)
        if health["state"] != "LIVE":
            raise ApiError("SOURCE_STALE", "The Twitch source is not live; betting is paused.",
                           details={"source_state": health["state"]})
    # 6. SIDE_CONFLICT
    existing = conn.execute(
        "SELECT side FROM wagers WHERE market_id = ? AND user_id = ? LIMIT 1", (market["market_id"], principal.user_id)
    ).fetchone()
    if existing is not None and existing["side"] != req.side:
        raise ApiError("SIDE_CONFLICT", "You already bet the other side of this market.",
                       details={"existing_side": existing["side"]})
    # 7. INSUFFICIENT_FUNDS
    wallet = ledger.wallet_account(conn, run["run_id"], principal.user_id)
    available = int(wallet["balance_minor"]) if wallet is not None else 0
    if wallet is None or available < req.amount_minor:
        raise ApiError("INSUFFICIENT_FUNDS", "Not enough demo credits.",
                       details={"available_minor": available, "requested_minor": req.amount_minor})
    # 8. accept: debit available, credit escrow, insert wager, insert outbox events
    now_s = _fmt(now)
    amount = req.amount_minor
    escrow = ledger.escrow_account(conn, market["market_id"])
    in_play_before = views.in_play_minor(conn, run["run_id"], principal.user_id)
    wager_id = new_id("wgr")
    stake_txn = ledger.post(
        conn, run_id=run["run_id"], reason="WAGER_STAKE",
        source_key=f"stake:{principal.user_id}:{req.operation_id}",
        entries=[(int(wallet["account_id"]), -amount), (int(escrow["account_id"]), amount)], now=now_s,
        market_id=market["market_id"], actor_user_id=principal.user_id, operation_id=req.operation_id,
        is_simulated=principal.is_bot,
    )
    yes, no = int(market["yes_minor"]), int(market["no_minor"])
    updated = _update_market(
        conn, market,
        yes_minor=yes + amount if req.side == "YES" else yes,
        no_minor=no + amount if req.side == "NO" else no,
        simulated_minor=int(market["simulated_minor"]) + (amount if principal.is_bot else 0),
        wager_count=int(market["wager_count"]) + 1,
    )
    wallet_after = ledger.wallet_account(conn, run["run_id"], principal.user_id)
    conn.execute(
        "INSERT INTO wagers (wager_id, market_id, run_id, user_id, operation_id, side, amount_minor, is_simulated,"
        " rules_version, status, version, accepted_at_utc, stake_txn_id, market_aggregate_version,"
        " wallet_after_available_minor, wallet_after_in_play_minor, wallet_after_balance_version)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACCEPTED', 1, ?, ?, ?, ?, ?, ?)",
        (wager_id, market["market_id"], run["run_id"], principal.user_id, req.operation_id, req.side, amount,
         1 if principal.is_bot else 0, int(market["rules_version"]), now_s, stake_txn,
         int(updated["aggregate_version"]), int(wallet_after["balance_minor"]), in_play_before + amount,
         int(wallet_after["version"])),
    )
    row = conn.execute("SELECT * FROM wagers WHERE wager_id = ?", (wager_id,)).fetchone()
    receipt = views.wager_receipt(row, replayed=False)
    WagerReceipt.model_validate(receipt)  # a malformed receipt aborts the transaction
    record_operation(conn, actor_user_id=principal.user_id, operation_id=req.operation_id, op_type="WAGER",
                     req_hash=req_hash, http_status=201, resource_type="WAGER", resource_id=wager_id,
                     response=receipt, now=now)
    events.emit_market(conn, market["market_id"], "pool.updated", now)
    events.emit_wager(conn, wager_id, now)
    events.emit_wallet(conn, run["run_id"], principal.user_id, now)
    # Last statement before COMMIT: the server commit time must still be < close_at_utc (§9.3).
    if clock.now() >= close_at:
        raise _market_closed(market, "DEADLINE", "Betting closed at close_at_utc.")
    return receipt, False
