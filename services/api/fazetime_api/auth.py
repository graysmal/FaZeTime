"""Identity (CONTRACTS §9.8): invite codes, sessions, WebSocket tickets. Secrets are stored hashed only.

Never log invite codes, session tokens or tickets. Phone numbers are not an identity factor (D15/D16).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from . import timeutil, views
from .config import Settings
from .domain import Principal, seed_wallet
from .errors import ApiError
from .ids import new_id, new_invite_code, new_session_token, new_ws_ticket, normalize_invite_code, sha256_hex
from .schemas import EnrollRequest

BAD_INVITE = "Invite code is invalid, already used or expired."


def create_invite(
    conn: sqlite3.Connection,
    *,
    role: str,
    is_bot: bool,
    bind_user_id: str | None,
    created_by_user_id: str | None,
    now: datetime,
    settings: Settings,
) -> tuple[dict, str]:
    """Returns (public invite record, plaintext code). The plaintext is returned once, never stored."""
    if role not in ("VIEWER", "OPERATOR"):
        raise ApiError("VALIDATION_FAILED", "Invite role must be VIEWER or OPERATOR.")
    if role == "OPERATOR" and is_bot:
        raise ApiError("VALIDATION_FAILED", "Operators cannot be bots.",
                       details={"fields": [{"loc": ["is_bot"], "msg": "operators cannot be bots"}]})
    if bind_user_id is not None:
        user = conn.execute("SELECT role, is_bot FROM users WHERE user_id = ?", (bind_user_id,)).fetchone()
        if user is None:
            raise ApiError("NOT_FOUND", "Unknown user for a recovery invite.")
        if user["role"] != role or bool(user["is_bot"]) != is_bot:
            raise ApiError("VALIDATION_FAILED", "A recovery invite must keep the user's role and bot flag.",
                           details={"fields": [{"loc": ["role"], "msg": "must match the bound user"}]})
    code = new_invite_code()
    invite_id = new_id("inv")
    expires = now + timedelta(seconds=settings.invite_ttl_s)
    conn.execute(
        "INSERT INTO invite_codes (invite_id, code_hash, role, is_bot, bind_user_id, created_by_user_id,"
        " created_at_utc, expires_at_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (invite_id, sha256_hex(code), role, 1 if is_bot else 0, bind_user_id, created_by_user_id,
         timeutil.fmt(now), timeutil.fmt(expires)),
    )
    record = {
        "invite_id": invite_id,
        "role": role,
        "is_bot": is_bot,
        "bind_user_id": bind_user_id,
        "expires_at_utc": timeutil.fmt(expires),
    }
    return record, code


def enroll(conn: sqlite3.Connection, *, req: EnrollRequest, now: datetime, settings: Settings) -> dict:
    code = normalize_invite_code(req.invite_code)
    if code is None:
        raise ApiError("UNAUTHENTICATED", BAD_INVITE)
    now_s = timeutil.fmt(now)
    invite = conn.execute(
        "SELECT * FROM invite_codes WHERE code_hash = ? AND used_at_utc IS NULL AND expires_at_utc > ?",
        (sha256_hex(code), now_s),
    ).fetchone()
    if invite is None:
        raise ApiError("UNAUTHENTICATED", BAD_INVITE)
    if invite["bind_user_id"] is not None:
        user_id = invite["bind_user_id"]
        conn.execute(
            "UPDATE users SET display_name = ?, claimed_twitch_login = ? WHERE user_id = ?",
            (req.display_name, req.claimed_twitch_login, user_id),
        )
    else:
        user_id = new_id("usr")
        conn.execute(
            "INSERT INTO users (user_id, display_name, claimed_twitch_login, role, is_bot, created_at_utc)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, req.display_name, req.claimed_twitch_login, invite["role"], invite["is_bot"], now_s),
        )
    claimed = conn.execute(
        "UPDATE invite_codes SET used_at_utc = ?, used_by_user_id = ?"
        " WHERE invite_id = ? AND used_at_utc IS NULL AND expires_at_utc > ?",
        (now_s, user_id, invite["invite_id"], now_s),
    )
    if claimed.rowcount != 1:  # single use by conditional update
        raise ApiError("UNAUTHENTICATED", BAD_INVITE)
    token = new_session_token()
    session_id = new_id("ses")
    expires = now + timedelta(seconds=settings.session_ttl_s)
    conn.execute(
        "INSERT INTO sessions (session_id, token_hash, user_id, invite_id, device_id, created_at_utc, expires_at_utc)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (session_id, sha256_hex(token), user_id, invite["invite_id"], req.device_id, now_s, timeutil.fmt(expires)),
    )
    user = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    stream = views.get_stream(conn)
    if stream is not None:
        run = views.get_active_run(conn, stream["stream_id"])
        if run is not None and user["role"] == "VIEWER":  # D30: operators get no seed grant
            seed_wallet(conn, run, user, now)  # enroll into the active run: SEED_GRANT once
    principal = Principal(user_id, user["role"], bool(user["is_bot"]), session_id, timeutil.fmt(expires))
    return {
        "schema_version": 1,
        "session_token": token,
        "session_id": session_id,
        "expires_at_utc": timeutil.fmt(expires),
        "me": views.me(conn, principal, now),
    }


def authenticate(conn: sqlite3.Connection, token: str, now: datetime) -> Principal | None:
    if not token.startswith("fzs_") or len(token) > 128:
        return None
    row = conn.execute(
        "SELECT s.session_id, s.expires_at_utc, s.revoked_at_utc, u.user_id, u.role, u.is_bot"
        " FROM sessions s JOIN users u ON u.user_id = s.user_id WHERE s.token_hash = ?",
        (sha256_hex(token),),
    ).fetchone()
    if row is None or row["revoked_at_utc"] is not None or timeutil.parse(row["expires_at_utc"]) <= now:
        return None
    return Principal(row["user_id"], row["role"], bool(row["is_bot"]), row["session_id"], row["expires_at_utc"])


def session_valid(conn: sqlite3.Connection, session_id: str, now: datetime) -> bool:
    row = conn.execute("SELECT expires_at_utc, revoked_at_utc FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    return row is not None and row["revoked_at_utc"] is None and timeutil.parse(row["expires_at_utc"]) > now


def revoke_user_sessions(conn: sqlite3.Connection, user_id: str, now: datetime) -> int:
    cur = conn.execute(
        "UPDATE sessions SET revoked_at_utc = ? WHERE user_id = ? AND revoked_at_utc IS NULL",
        (timeutil.fmt(now), user_id),
    )
    return cur.rowcount


def issue_ws_ticket(
    conn: sqlite3.Connection, *, principal: Principal, stream_id: str, now: datetime, settings: Settings
) -> dict:
    if views.get_stream(conn, stream_id) is None:
        raise ApiError("NOT_FOUND", "Unknown stream.")
    ticket = new_ws_ticket()
    expires = now + timedelta(seconds=settings.ws_ticket_ttl_s)
    conn.execute(
        "INSERT INTO ws_tickets (ticket_hash, user_id, session_id, stream_id, created_at_utc, expires_at_utc)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (sha256_hex(ticket), principal.user_id, principal.session_id, stream_id, timeutil.fmt(now), timeutil.fmt(expires)),
    )
    return {"schema_version": 1, "ticket": ticket, "expires_at_utc": timeutil.fmt(expires), "ws_path": "/v1/ws"}


def consume_ws_ticket(conn: sqlite3.Connection, ticket: object, now: datetime) -> tuple[Principal, str] | None:
    """Single use (conditional update), unexpired, and bound to a still-valid session."""
    if not isinstance(ticket, str) or not ticket.startswith("fzw_") or len(ticket) > 128:
        return None
    digest = sha256_hex(ticket)
    now_s = timeutil.fmt(now)
    row = conn.execute(
        "SELECT t.user_id, t.session_id, t.stream_id, t.expires_at_utc, t.used_at_utc,"
        " s.expires_at_utc AS session_expires_at_utc, s.revoked_at_utc, u.role, u.is_bot"
        " FROM ws_tickets t JOIN sessions s ON s.session_id = t.session_id JOIN users u ON u.user_id = t.user_id"
        " WHERE t.ticket_hash = ?",
        (digest,),
    ).fetchone()
    if row is None or row["used_at_utc"] is not None or row["expires_at_utc"] <= now_s:
        return None
    if row["revoked_at_utc"] is not None or row["session_expires_at_utc"] <= now_s:
        return None
    used = conn.execute(
        "UPDATE ws_tickets SET used_at_utc = ? WHERE ticket_hash = ? AND used_at_utc IS NULL AND expires_at_utc > ?",
        (now_s, digest, now_s),
    )
    if used.rowcount != 1:
        return None
    principal = Principal(row["user_id"], row["role"], bool(row["is_bot"]), row["session_id"],
                          row["session_expires_at_utc"])
    return principal, row["stream_id"]
