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
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware
from starlette.staticfiles import StaticFiles

import os

from . import api_operator, api_viewer, errors, timeutil, worker, ws
from .config import Settings, cors_origins, load_settings
from .db import Database
from .deps import Services
from .hub import Hub
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


class OperatorStatic(StaticFiles):
    """apps/operator build at /operator/ (same origin: no CORS entry). Unknown extension-less paths are client
    routes and get index.html; a missing asset (has a '.') stays 404. Responses refuse framing."""

    async def get_response(self, path: str, scope):
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404 or "." in path.rsplit("/", 1)[-1]:
                raise
            response = await super().get_response("index.html", scope)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response


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
        os.makedirs(settings.evidence_dir, exist_ok=True)
        applied = await asyncio.to_thread(db.migrate)  # numbered migrations at startup (D28)
        log.info("ws origins=%s cors origins=%s", ",".join(settings.allowed_origins),
                 ",".join(cors_origins(settings)) or "(none)")
        if not any(o.startswith("chrome-extension://") for o in settings.allowed_origins):
            log.warning("no pinned chrome-extension://<id> in FAZETIME_ALLOWED_ORIGINS; extension-page sockets get 4403")
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
    app.include_router(worker.router)
    app.include_router(worker.operator_router)
    if settings.operator_dist and os.path.isfile(os.path.join(settings.operator_dist, "index.html")):
        app.mount("/operator", OperatorStatic(directory=settings.operator_dist, html=True), name="operator-ui")
        log.info("operator UI mounted at /operator/ from %s", settings.operator_dist)
    app.add_middleware(RequestContextMiddleware, clock=clock)
    app.add_middleware(
        EnvelopeCORSMiddleware,
        allow_origins=list(cors_origins(settings)),
        allow_methods=["GET", "POST"],
        allow_headers=["authorization", "content-type"],
        expose_headers=["X-Request-ID", "Retry-After"],
        allow_credentials=False,
        allow_private_network=True,
        max_age=600,
    )
    return app
