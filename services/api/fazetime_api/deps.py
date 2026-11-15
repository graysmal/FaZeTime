"""Request-level helpers: service container, authentication, body parsing with §9.10 error mapping."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TypeVar

from fastapi import Depends, Request
from pydantic import BaseModel, ValidationError

from . import auth
from .config import Settings
from .db import Database
from .domain import Principal
from .errors import ApiError, validation_fields
from .hub import Hub
from .ids import UUID_PATTERN
from .ratelimit import RateLimiter

_UUID_RE = re.compile(UUID_PATTERN)
MAX_BODY_BYTES = 16 * 1024
M = TypeVar("M", bound=BaseModel)


@dataclass
class Services:
    settings: Settings
    clock: object
    db: Database
    hub: Hub
    limiter: RateLimiter
    sweeper: object
    started_at_utc: str


def svc_of(request: Request) -> Services:
    return request.app.state.svc


def session_principal(request: Request) -> Principal:
    """Bearer-only session auth (§9.8). Tokens in URLs or cookies are ignored."""
    svc = svc_of(request)
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token:
        raise ApiError("UNAUTHENTICATED", "Missing bearer session token.")
    with svc.db.read() as conn:
        principal = auth.authenticate(conn, token, svc.clock.now())
    if principal is None:
        raise ApiError("UNAUTHENTICATED", "Session is invalid, expired or revoked.")
    request.state.principal = principal
    return principal


def viewer_principal(principal: Principal = Depends(session_principal)) -> Principal:
    if principal.role not in ("VIEWER", "OPERATOR"):
        raise ApiError("FORBIDDEN")
    return principal


def operator_principal(principal: Principal = Depends(session_principal)) -> Principal:
    if principal.role != "OPERATOR":
        raise ApiError("FORBIDDEN", "Operator session required.")
    return principal


def client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def read_capped(request: Request, max_bytes: int) -> bytes:
    """Reject oversize bodies from Content-Length, or while streaming (chunked), before buffering them."""
    too_large = ApiError("VALIDATION_FAILED", "Request body too large.",
                         details={"fields": [{"loc": ["body"], "msg": f"at most {max_bytes} bytes"}]})
    length = request.headers.get("content-length")
    if length is not None and (not length.isdigit() or int(length) > max_bytes):
        raise too_large
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > max_bytes:
            raise too_large
        chunks.append(chunk)
    return b"".join(chunks)


def bettor_principal(principal: Principal = Depends(session_principal)) -> Principal:
    """D30: only VIEWER-role users wager; operators are FORBIDDEN."""
    if principal.role != "VIEWER":
        raise ApiError("FORBIDDEN", "Only viewer accounts can place wagers (D30).")
    return principal


async def parse_body(
    request: Request, model: type[M], *, amount_field: str | None = None, amount_details: dict | None = None,
    max_bytes: int = MAX_BODY_BYTES,
) -> M:
    """Validate a JSON body after auth and rate limiting. extra='forbid' makes user_id a VALIDATION_FAILED."""
    raw = await read_capped(request, max_bytes)
    try:
        data = json.loads(raw) if raw else None
    except ValueError:
        data = None
    if isinstance(data, dict):
        op = data.get("operation_id")
        if isinstance(op, str) and _UUID_RE.fullmatch(op):
            request.state.operation_id = op
    try:
        return model.model_validate_json(raw if raw else b"null")
    except ValidationError as exc:
        errors = [{**e, "loc": ("body", *e.get("loc", ()))} for e in exc.errors(include_url=False, include_input=False)]
        if amount_field and errors and all(tuple(e["loc"])[:2] == ("body", amount_field) for e in errors):
            raise ApiError("INVALID_AMOUNT", "Amount must be a whole number of minor units within limits.",
                           details=amount_details)
        raise ApiError("VALIDATION_FAILED", "Request validation failed.",
                       details={"fields": validation_fields(errors)})


def body_schema(model: type[BaseModel]) -> dict:
    """OpenAPI requestBody for routes that parse their body manually (to keep the §9.6 check order)."""
    return {
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": model.model_json_schema()}},
        }
    }
