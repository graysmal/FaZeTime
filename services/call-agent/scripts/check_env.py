"""Private credential check for the call agent. Prints names and results, never values.

Usage: .venv/bin/python scripts/check_env.py [--inference] [path/to/.env.local]

- Always (read-only, free): LIVEKIT_URL, LIVEKIT_API_KEY and LIVEKIT_API_SECRET are
  filled in, and the key and secret are accepted by that URL's project
  (RoomService.ListRooms).
- With --inference: one tiny LiveKit Inference text request (about 20 tokens on
  openai/gpt-oss-120b, a tiny fraction of a cent from the project's Inference credit). It proves the
  same keys can use Inference, which the realtime voice model needs, and prints the
  gateway's credit headers (limit and used) when it sends them.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from dotenv import dotenv_values
from livekit import api

PLACEHOLDER_MARKERS = ("YOUR_", "your_", "<", "changeme")


def filled(value: str | None) -> bool:
    return bool(value) and not any(m in value for m in PLACEHOLDER_MARKERS)


def masked_host(url: str) -> str:
    host = url.split("://", 1)[-1].split("/", 1)[0]
    parts = host.split(".")
    return "***." + ".".join(parts[1:]) if len(parts) > 2 else "***"


async def check_livekit(env: dict[str, str | None]) -> bool:
    keys = ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")
    missing = [k for k in keys if not filled(env.get(k))]
    if missing:
        print(f"LiveKit: MISSING {', '.join(missing)}")
        return False
    url = env["LIVEKIT_URL"] or ""
    if not url.startswith(("wss://", "https://")):
        print("LiveKit: LIVEKIT_URL must start with wss://")
        return False
    http_url = "https://" + url.split("://", 1)[1]
    lk = api.LiveKitAPI(http_url, env["LIVEKIT_API_KEY"], env["LIVEKIT_API_SECRET"])
    try:
        rooms = await lk.room.list_rooms(api.ListRoomsRequest())
        print(f"LiveKit: OK, key and secret accepted by {masked_host(url)} ({len(rooms.rooms)} active rooms)")
        return True
    except api.TwirpError as exc:
        print(f"LiveKit: REJECTED by {masked_host(url)}: {exc.code} (key, secret and URL must be one project)")
        return False
    except Exception as exc:  # network errors
        print(f"LiveKit: could not reach {masked_host(url)}: {type(exc).__name__}")
        return False
    finally:
        await lk.aclose()


async def check_inference(env: dict[str, str | None]) -> bool:
    import openai
    from livekit.agents.inference._utils import (
        QUOTA_HEADER_FIELDS,
        create_access_token,
        get_default_inference_url,
    )

    token = create_access_token(env["LIVEKIT_API_KEY"], env["LIVEKIT_API_SECRET"], ttl=60)
    client = openai.AsyncClient(api_key=token, base_url=get_default_inference_url(), max_retries=0)
    try:
        raw = await client.chat.completions.with_raw_response.create(
            model="openai/gpt-oss-120b",
            messages=[{"role": "user", "content": "Reply with the single word: ok"}],
            max_completion_tokens=16,
        )
        quota = {f: raw.headers.get(h) for h, f in QUOTA_HEADER_FIELDS.items() if raw.headers.get(h)}
        print(f"Inference: OK, gateway accepted the keys (HTTP {raw.http_response.status_code})")
        print(f"Inference: quota headers: {quota or 'none sent'}")
        return True
    except openai.APIStatusError as exc:
        quota = {f: exc.response.headers.get(h) for h, f in QUOTA_HEADER_FIELDS.items() if exc.response.headers.get(h)}
        print(f"Inference: REJECTED (HTTP {exc.status_code}); quota headers: {quota or 'none sent'}")
        return False
    except Exception as exc:
        print(f"Inference: could not reach the gateway: {type(exc).__name__}")
        return False
    finally:
        await client.close()


async def run(env: dict[str, str | None], inference: bool) -> int:
    ok = await check_livekit(env)
    if ok and inference:
        ok = await check_inference(env)
    return 0 if ok else 1


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--inference"]
    path = Path(args[0] if args else Path(__file__).resolve().parents[1] / ".env.local")
    if not path.is_file():
        print(f"env file not found: {path}")
        return 2
    mode = path.stat().st_mode & 0o777
    print(f"env file: {path} (mode {mode:o}{', should be 600' if mode & 0o077 else ''})")
    env = dotenv_values(path)
    print(f"AGENT_NAME: {env.get('AGENT_NAME') or 'MISSING'}")
    return asyncio.run(run(env, "--inference" in sys.argv[1:]))


if __name__ == "__main__":
    sys.exit(main())
