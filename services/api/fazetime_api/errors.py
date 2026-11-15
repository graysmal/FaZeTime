"""Error envelope and HTTP mapping exactly as CONTRACTS §9.10."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import timeutil
from .ids import new_id

log = logging.getLogger("fazetime.errors")

HTTP_STATUS: dict[str, int] = {
    "UNAUTHENTICATED": 401,
    "FORBIDDEN": 403,
    "NOT_FOUND": 404,
    "INSUFFICIENT_FUNDS": 409,
    "MARKET_CLOSED": 409,
    "STALE_MARKET": 409,
    "WRONG_RUN": 409,
    "IDEMPOTENCY_CONFLICT": 409,
    "SOURCE_STALE": 409,
    "SIDE_CONFLICT": 409,
    "STALE_EPOCH": 409,  # worker-only (§9.16)
    "INVALID_AMOUNT": 422,
    "VALIDATION_FAILED": 422,
    "RATE_LIMITED": 429,
    "INTERNAL_ERROR": 500,
    "CAPABILITY_UNAVAILABLE": 503,
}
RETRYABLE = frozenset({"RATE_LIMITED", "INTERNAL_ERROR"})

SAFE_MESSAGES = {
    "UNAUTHENTICATED": "Authentication required.",
    "FORBIDDEN": "This session is not allowed to do that.",
    "NOT_FOUND": "Not found.",
    "INTERNAL_ERROR": "Internal error; the outcome of a mutation is unknown. Retry with the same operation_id or read /v1/operations/{id}.",
}


class ApiError(Exception):
    def __init__(
        self,
        code: str,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
        retry_after_ms: int | None = None,
        operation_id: str | None = None,
        status: int | None = None,
    ) -> None:
        if code not in HTTP_STATUS:
            raise ValueError(f"unknown error code {code}")
        super().__init__(code)
        self.code = code
        self.message = message or SAFE_MESSAGES.get(code, code.replace("_", " ").capitalize() + ".")
        self.details = details
        self.retry_after_ms = retry_after_ms
        self.operation_id = operation_id
        self.status = status or HTTP_STATUS[code]


def request_id_of(request: Request) -> str:
    rid = getattr(request.state, "request_id", None)
    if not rid:
        rid = new_id("req")
        request.state.request_id = rid
    return rid


def _now_str(request: Request) -> str:
    clock = getattr(request.app.state, "clock", None)
    return timeutil.fmt(clock.now() if clock else timeutil.Clock().now())


def envelope(
    *,
    code: str,
    message: str,
    request_id: str,
    server_time_utc: str,
    operation_id: str | None = None,
    details: dict[str, Any] | None = None,
    retry_after_ms: int | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "error": {
            "code": code,
            "message": message,
            "retryable": code in RETRYABLE,
            "retry_after_ms": retry_after_ms,
            "request_id": request_id,
            "operation_id": operation_id,
            "details": details,
        },
        "server_time_utc": server_time_utc,
    }


def error_response(request: Request, err: ApiError) -> JSONResponse:
    headers = {}
    if err.code == "UNAUTHENTICATED":
        headers["WWW-Authenticate"] = "Bearer"
    if err.code == "RATE_LIMITED" and err.retry_after_ms is not None:
        headers["Retry-After"] = str(max(1, -(-err.retry_after_ms // 1000)))
    body = envelope(
        code=err.code,
        message=err.message,
        request_id=request_id_of(request),
        server_time_utc=_now_str(request),
        operation_id=err.operation_id or getattr(request.state, "operation_id", None),
        details=err.details,
        retry_after_ms=err.retry_after_ms,
    )
    return JSONResponse(body, status_code=err.status, headers=headers)


def validation_fields(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for e in errors:
        out.append({"loc": list(e.get("loc", ())), "msg": str(e.get("msg", "invalid"))})
    return out


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError):
        return error_response(request, exc)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        err = ApiError(
            "VALIDATION_FAILED",
            "Request validation failed.",
            details={"fields": validation_fields(list(exc.errors()))},
        )
        return error_response(request, err)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        mapping = {401: "UNAUTHENTICATED", 403: "FORBIDDEN", 404: "NOT_FOUND", 405: "NOT_FOUND", 429: "RATE_LIMITED"}
        code = mapping.get(exc.status_code)
        if code is not None:
            status = exc.status_code
        elif exc.status_code >= 500:
            code, status = "INTERNAL_ERROR", 500
        else:  # any other 4xx (400, 413, 415, ...) is VALIDATION_FAILED 422 (§9.10)
            code, status = "VALIDATION_FAILED", 422
        return error_response(request, ApiError(code, status=status))
