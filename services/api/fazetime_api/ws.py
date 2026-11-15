"""WebSocket protocol (CONTRACTS §9.9, §9.13 H).

URL carries no secret. Origin is checked against the allowlist (close 4403). The first client frame
must be {"type":"auth","ticket":"fzw_..."} within 5 s, else close 4401. Then the server sends
{"type":"ready","event_hwm":N} followed by {"type":"event","event":DomainEvent} frames. App-level
{"type":"ping"}/{"type":"pong"} either way. The session is re-checked on every server ping.
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect, WebSocketState

from . import auth, timeutil
from .hub import Subscriber, origin_allowed

log = logging.getLogger("fazetime.ws")
router = APIRouter()

CLOSE_AUTH = 4401
CLOSE_FORBIDDEN = 4403


async def _close(ws: WebSocket, code: int) -> None:
    """Close once; a peer that already went away (1006) is normal, not an application error."""
    if ws.application_state == WebSocketState.DISCONNECTED or ws.client_state == WebSocketState.DISCONNECTED:
        return
    try:
        await ws.close(code=code)
    except (RuntimeError, WebSocketDisconnect, OSError):
        pass


@router.websocket("/v1/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    svc = ws.app.state.svc
    settings = svc.settings
    await ws.accept()
    if not origin_allowed(ws.headers.get("origin"), settings.allowed_origins):
        await _close(ws, CLOSE_FORBIDDEN)
        return
    try:
        first = await asyncio.wait_for(ws.receive(), timeout=settings.ws_auth_timeout_s)
    except (TimeoutError, WebSocketDisconnect):
        await _close(ws, CLOSE_AUTH)
        return
    if first.get("type") == "websocket.disconnect":
        return
    try:
        data = json.loads(first.get("text") or "")
    except ValueError:
        data = None
    if not isinstance(data, dict) or data.get("type") != "auth":
        await _close(ws, CLOSE_AUTH)
        return

    def consume():
        with svc.db.write() as conn:
            return auth.consume_ws_ticket(conn, data.get("ticket"), svc.clock.now())

    result = await asyncio.to_thread(consume)
    if result is None:
        await _close(ws, CLOSE_AUTH)
        return
    principal, stream_id = result
    if principal.role not in ("VIEWER", "OPERATOR"):
        await _close(ws, CLOSE_FORBIDDEN)
        return

    sub = Subscriber(user_id=principal.user_id, role=principal.role, stream_id=stream_id)
    hwm = svc.hub.register(sub)
    try:
        await ws.send_json({"type": "ready", "schema_version": 1, "event_hwm": hwm, "stream_id": stream_id,
                            "server_time_utc": timeutil.fmt(svc.clock.now())})

        async def sender() -> None:
            while True:
                try:
                    item = await asyncio.wait_for(sub.queue.get(), timeout=settings.ws_ping_interval_s)
                except TimeoutError:
                    def still_valid():
                        with svc.db.read() as conn:
                            return auth.session_valid(conn, principal.session_id, svc.clock.now())
                    if not await asyncio.to_thread(still_valid):
                        await _close(ws, CLOSE_AUTH)
                        return
                    await ws.send_json({"type": "ping"})
                    continue
                if sub.overflowed:
                    while not sub.queue.empty():
                        sub.queue.get_nowait()
                    sub.overflowed = False
                    await ws.send_json({"type": "resync", "reason": "overflow"})
                    continue
                await ws.send_json(item)

        async def receiver() -> None:
            while True:
                message = await ws.receive()
                if message.get("type") == "websocket.disconnect":
                    return
                try:
                    frame = json.loads(message.get("text") or "")
                except ValueError:
                    continue
                if isinstance(frame, dict) and frame.get("type") == "ping":
                    sub.control({"type": "pong"})

        async def session_watch() -> None:
            def still_valid():
                with svc.db.read() as conn:
                    return auth.session_valid(conn, principal.session_id, svc.clock.now())
            while True:
                await asyncio.sleep(settings.ws_session_recheck_s)
                if not await asyncio.to_thread(still_valid):
                    await _close(ws, CLOSE_AUTH)
                    return

        tasks = {asyncio.create_task(sender()), asyncio.create_task(receiver()), asyncio.create_task(session_watch())}
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in done:
            exc = task.exception()
            if exc is not None and not isinstance(exc, (WebSocketDisconnect, RuntimeError)):
                log.warning("websocket task ended with %s", type(exc).__name__)
    except (WebSocketDisconnect, OSError):
        pass
    finally:
        svc.hub.unregister(sub)
        await _close(ws, 1000)
