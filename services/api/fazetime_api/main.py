"""FastAPI app factory. ONE process, ONE SQLite writer boundary (D13, D22, D28).

Run:  uv run python -m fazetime_api serve          (binds FAZETIME_HOST, default 127.0.0.1:8000)
 or:  uv run uvicorn fazetime_api.main:create_app --factory --host 127.0.0.1 --port 8000
Never run more than one worker process: WebSocket fanout and rate limits are in-process.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.cors import CORSMiddleware

from . import api_operator, api_viewer, errors, timeutil, ws
from .config import Settings, load_settings
from .db import Database
from .deps import Services
from .hub import Hub, cors_origin_regex
from .ids import new_id
from .ratelimit import RateLimiter
from .sweeper import Sweeper

log = logging.getLogger("fazetime.api")


class RequestContextMiddleware:
    """Assigns request_id (req_...), adds X-Request-ID, and turns unhandled errors into the envelope."""

    def __init__(self, app, clock) -> None:
        self.app = app
        self.clock = clock

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        request_id = new_id("req")
        scope.setdefault("state", {})["request_id"] = request_id
        if scope["type"] == "websocket":
            return await self.app(scope, receive, send)
        started = False

        async def send_wrapper(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                MutableHeaders(scope=message).append("X-Request-ID", request_id)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            log.exception("unhandled error request_id=%s path=%s", request_id, scope.get("path"))
            if started:
                raise
            body = errors.envelope(
                code="INTERNAL_ERROR",
                message=errors.SAFE_MESSAGES["INTERNAL_ERROR"],
                request_id=request_id,
                server_time_utc=timeutil.fmt(self.clock.now()),
                operation_id=scope.get("state", {}).get("operation_id"),
            )
            await JSONResponse(body, status_code=500)(scope, receive, send_wrapper)


class EnvelopeCORSMiddleware(CORSMiddleware):
    """Starlette CORS, but a rejected preflight returns the §9.10 envelope (403 FORBIDDEN)."""

    clock = timeutil.Clock()

    def preflight_response(self, request_headers: Headers):
        response = super().preflight_response(request_headers)
        if response.status_code != 400:
            return response
        body = errors.envelope(
            code="FORBIDDEN",
            message="Cross-origin request not allowed for this origin, method or header.",
            request_id=new_id("req"),
            server_time_utc=timeutil.fmt(self.clock.now()),
        )
        return JSONResponse(body, status_code=403)


def create_app(settings: Settings | None = None, clock: timeutil.Clock | None = None) -> FastAPI:
    settings = settings or load_settings()
    clock = clock or timeutil.Clock()
    db = Database(settings.db_path)
    hub = Hub(db)
    svc = Services(
        settings=settings,
        clock=clock,
        db=db,
        hub=hub,
        limiter=RateLimiter(),
        sweeper=Sweeper(db, clock, settings, hub),
        started_at_utc=timeutil.fmt(clock.now()),
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        applied = await asyncio.to_thread(db.migrate)  # numbered migrations at startup (D28)
        if applied:
            log.info("migrations applied: %s", [m.name for m in applied])
        await hub.start()
        await svc.sweeper.run_once()  # startup sweep: lock/void anything that expired while down
        task = asyncio.create_task(svc.sweeper.run_forever(), name="fazetime-sweeper") \
            if settings.sweeper_enabled else None
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            await hub.stop()

    app = FastAPI(
        title="FaZeTime API (demo, test money only)",
        version="0.1.0",
        lifespan=lifespan,
        telemetry={"tracing": False, "metrics": False, "logs": False},
        redoc_url=None,
    )
    app.state.svc = svc
    app.state.clock = clock
    errors.install(app)
    app.include_router(api_viewer.router)
    app.include_router(api_operator.router)
    app.include_router(ws.router)
    app.add_middleware(RequestContextMiddleware, clock=clock)
    app.add_middleware(
        EnvelopeCORSMiddleware,
        allow_origin_regex=cors_origin_regex(settings.allowed_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["authorization", "content-type"],
        expose_headers=["X-Request-ID", "Retry-After"],
        allow_credentials=False,
        allow_private_network=True,
        max_age=600,
    )
    return app
