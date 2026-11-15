"""Identifier, token and canonical-hash helpers (CONTRACTS §9.1, §9.7, §9.8)."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import uuid

ID_PREFIXES = ("usr", "ses", "str", "run", "mkt", "wgr", "txn", "evd", "ep", "req", "inv")
CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_CROCKFORD_ALIASES = str.maketrans({"O": "0", "I": "1", "L": "1"})
UUID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"


def new_id(prefix: str) -> str:
    if prefix not in ID_PREFIXES:
        raise ValueError(f"unknown id prefix {prefix!r}")
    return f"{prefix}_{uuid.uuid4().hex}"


def id_pattern(prefix: str) -> str:
    return rf"^{prefix}_[0-9a-f]{{32}}$"


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_session_token() -> str:
    raw = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii").rstrip("=")
    return f"fzs_{raw}"


def new_ws_ticket() -> str:
    raw = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii").rstrip("=")
    return f"fzw_{raw}"


def new_invite_code() -> str:
    """12 Crockford base32 characters from a CSPRNG (60 bits)."""
    return "".join(secrets.choice(CROCKFORD) for _ in range(12))


def format_invite_code(code: str) -> str:
    return f"{code[0:4]}-{code[4:8]}-{code[8:12]}"


def normalize_invite_code(raw: str) -> str | None:
    """Case- and hyphen-insensitive Crockford normalization. Returns None for malformed input."""
    if not isinstance(raw, str) or len(raw) > 64:
        return None
    code = raw.replace("-", "").replace(" ", "").upper().translate(_CROCKFORD_ALIASES)
    if len(code) != 12 or any(ch not in CROCKFORD for ch in code):
        return None
    return code


def canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def request_hash(payload: object) -> str:
    """SHA-256 of the canonical (sorted-key) JSON request (§9.7)."""
    return sha256_hex(canonical_json(payload))
