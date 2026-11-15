#!/usr/bin/env python3
"""P0-F tailnet transport spike: tiny HTTP health + WebSocket echo server (websockets >= 13 asyncio API).

  GET /healthz -> 200 "ok"
  /ws          -> echoes every text/binary message back unchanged
  anything else -> 404

Spike code only. Binds to ONE explicit address, which must be a Tailscale CGNAT IPv4 (100.64.0.0/10);
0.0.0.0 / :: / non-tailnet addresses are refused because the Pi sits on venue Wi-Fi.
SIGTERM/SIGINT close the server gracefully (clients receive close code 1001 "going away").
Keepalive pings are OFF by default (--ping-interval 0) so an idle test measures true idle survival.
"""
from __future__ import annotations

import argparse
import asyncio
import http
import ipaddress
import signal
import sys
import time
from datetime import datetime, timezone

from websockets.asyncio.server import serve

TAILNET = ipaddress.ip_network("100.64.0.0/10")


def log(msg):
    print(f"{datetime.now(timezone.utc).isoformat(timespec='milliseconds')} {msg}", flush=True)


def process_request(connection, request):
    if request.path == "/healthz":
        return connection.respond(http.HTTPStatus.OK, "ok\n")
    if request.path != "/ws":
        return connection.respond(http.HTTPStatus.NOT_FOUND, "not found\n")
    return None  # continue the WebSocket handshake


async def echo(ws):
    peer = ws.remote_address[0] if ws.remote_address else "?"
    t0 = time.monotonic()
    n = 0
    log(f"open peer={peer}")
    try:
        async for msg in ws:
            n += 1
            await ws.send(msg)
    finally:
        log(f"close peer={peer} msgs={n} code={ws.close_code} held_s={time.monotonic() - t0:.1f}")


async def main(args):
    ip = ipaddress.ip_address(args.host)
    if ip.version != 4 or ip not in TAILNET:
        sys.exit(f"refusing to bind {args.host}: only a Tailscale 100.64.0.0/10 IPv4 is allowed")
    ping = args.ping_interval or None
    async with serve(echo, args.host, args.port, process_request=process_request,
                     ping_interval=ping, ping_timeout=ping, max_size=2**16, max_queue=16) as server:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, server.close)
        log(f"ready http://{args.host}:{args.port}/healthz ws://{args.host}:{args.port}/ws ping_interval={ping}")
        await server.wait_closed()
    log("stopped")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--host", required=True, help="Tailscale IPv4 from `tailscale ip -4`")
    p.add_argument("--port", type=int, default=8787)
    p.add_argument("--ping-interval", type=float, default=0.0, help="seconds; 0 disables keepalive pings")
    asyncio.run(main(p.parse_args()))
