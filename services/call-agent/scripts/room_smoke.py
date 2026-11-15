"""Smoke test the call agent without FaceTime: imitate one Chert call in a LiveKit room.

Usage: .venv/bin/python scripts/room_smoke.py [path/to/.env.local]

It creates a throwaway room in the LiveKit project from .env.local, dispatches the
running agent (AGENT_NAME) into it, joins as a fake "chert-bridge-smoke" caller that
publishes silence, then sets the room metadata to Chert's bridge_ready signal and
measures how long the agent takes to make audible sound (Chert ends a call that stays
silent for 10 s after bridge_ready), and checks that the agent publishes one camera
track delivering frames. The room is deleted at the end.

Cost: LiveKit connection minutes for a few seconds, plus the greeting's realtime model
audio through LiveKit Inference (a small fraction of a cent). No FaceTime minutes.
Prints no credential values.
"""

from __future__ import annotations

import array
import asyncio
import json
import math
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values
from livekit import api, rtc

LOUD_RMS = 300  # int16 RMS above which a frame counts as audible speech
LISTEN_S = 12.0
MAX_GREET_S = 9.0


def median_pitch_hz(samples: array.array, rate: int = 24000) -> float | None:
    """Rough median fundamental (60-400 Hz) over 40 ms windows, by autocorrelation."""
    import numpy as np

    x = np.asarray(samples, dtype=np.float32)
    win, lo, hi = int(rate * 0.04), rate // 400, rate // 60
    f0s = []
    for start in range(0, len(x) - win, win):
        w = x[start : start + win] - x[start : start + win].mean()
        ac = np.correlate(w, w, mode="full")[win - 1 :]
        if ac[0] <= 0:
            continue
        lag = lo + int(np.argmax(ac[lo:hi]))
        if ac[lag] / ac[0] > 0.5:
            f0s.append(rate / lag)
    return float(np.median(f0s)) if f0s else None


async def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / ".env.local")
    env = dotenv_values(path)
    url, key, secret = env.get("LIVEKIT_URL"), env.get("LIVEKIT_API_KEY"), env.get("LIVEKIT_API_SECRET")
    # A shell AGENT_NAME wins, so a second copy under a test name can be checked
    # without touching the copy that holds the Chert line.
    agent_name = os.environ.get("AGENT_NAME") or env.get("AGENT_NAME") or "fazetime-bookie"
    if not (url and key and secret):
        print("missing LiveKit values in", path)
        return 2
    http_url = "https://" + url.split("://", 1)[1]
    room_name = f"fazetime-smoke-{uuid.uuid4().hex[:8]}"
    lk = api.LiveKitAPI(http_url, key, secret)
    room = rtc.Room()
    stats = {"first_audible": None, "audible_frames": 0, "frames": 0, "agent_joined": None, "agent_tracks": 0,
             "video_tracks": 0, "video_frames": 0, "video_size": None, "video_after_ready": 0, "early_audible": 0}
    t_ready: float | None = None
    readers: list[asyncio.Task] = []
    voiced: array.array = array.array("h")  # audible agent audio at 24 kHz, for a pitch estimate

    async def read_audio(track: rtc.Track) -> None:
        async for ev in rtc.AudioStream(track, sample_rate=24000, num_channels=1):
            samples = array.array("h", bytes(ev.frame.data))
            if not samples:
                continue
            rms = math.sqrt(sum(s * s for s in samples) / len(samples))
            stats["frames"] += 1
            if rms > LOUD_RMS:
                if t_ready is None:
                    # Speech before bridge_ready means the agent greeted on join: Chert's Mac
                    # would not hear it, and the call would end at remote_audio_timeout.
                    stats["early_audible"] += 1
                    continue
                stats["audible_frames"] += 1
                if len(voiced) < 24000 * 10:
                    voiced.extend(samples)
                if stats["first_audible"] is None:
                    stats["first_audible"] = time.monotonic()

    async def read_video(track: rtc.Track) -> None:
        async for ev in rtc.VideoStream(track):
            stats["video_frames"] += 1
            stats["video_size"] = (ev.frame.width, ev.frame.height)
            if t_ready is not None:
                stats["video_after_ready"] += 1

    @room.on("track_subscribed")
    def _on_track(track: rtc.Track, pub: rtc.RemoteTrackPublication, participant: rtc.RemoteParticipant) -> None:
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            stats["agent_tracks"] += 1
            readers.append(asyncio.ensure_future(read_audio(track)))
        elif track.kind == rtc.TrackKind.KIND_VIDEO:
            stats["video_tracks"] += 1
            readers.append(asyncio.ensure_future(read_video(track)))

    @room.on("participant_connected")
    def _on_participant(p: rtc.RemoteParticipant) -> None:
        if stats["agent_joined"] is None:
            stats["agent_joined"] = time.monotonic()

    pusher: asyncio.Task | None = None
    try:
        await lk.room.create_room(api.CreateRoomRequest(name=room_name, empty_timeout=30))
        await lk.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(agent_name=agent_name, room=room_name, metadata='{"chert_smoke":true}')
        )
        token = (
            api.AccessToken(key, secret)
            .with_identity("chert-bridge-smoke")
            .with_grants(api.VideoGrants(room_join=True, room=room_name))
            .to_jwt()
        )
        t_start = time.monotonic()
        await room.connect(url, token)
        source = rtc.AudioSource(48000, 1)
        mic = rtc.LocalAudioTrack.create_audio_track("mic", source)
        await room.local_participant.publish_track(
            mic, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        )

        async def push_silence() -> None:
            frame = rtc.AudioFrame.create(48000, 1, 480)  # 10 ms of zeros
            while True:
                await source.capture_frame(frame)

        pusher = asyncio.ensure_future(push_silence())

        for _ in range(150):  # up to 15 s for the agent to join
            if room.remote_participants:
                break
            await asyncio.sleep(0.1)
        if not room.remote_participants:
            print("FAIL: the agent never joined the room (is scripts/start_agent.sh running?)")
            return 1
        joined = (stats["agent_joined"] or time.monotonic()) - t_start
        print(f"agent joined after {joined:.1f} s")

        await asyncio.sleep(4.5)  # Chert's bridge joined ~4.6 s before bridge_ready on the real call
        meta = {"chert_call": "smoke", "chert_bridge_ready": True, "at": datetime.now(timezone.utc).isoformat()}
        t_ready = time.monotonic()  # taken before the update, so the measured delay is never flattering
        await lk.room.update_room_metadata(api.UpdateRoomMetadataRequest(room=room_name, metadata=json.dumps(meta)))
        print("bridge_ready set; listening", LISTEN_S, "s")
        await asyncio.sleep(LISTEN_S)
    finally:
        if pusher:
            pusher.cancel()
        for r in readers:
            r.cancel()
        await room.disconnect()
        try:
            await lk.room.delete_room(api.DeleteRoomRequest(room=room_name))
        except Exception:
            pass
        await lk.aclose()

    print(f"agent audio tracks: {stats['agent_tracks']}, frames: {stats['frames']}, audible frames: {stats['audible_frames']}")
    fps = stats["video_after_ready"] / LISTEN_S
    print(f"agent video tracks: {stats['video_tracks']}, frames: {stats['video_frames']}, size: {stats['video_size']}, "
          f"~{fps:.1f} fps after bridge_ready")
    f0 = median_pitch_hz(voiced)
    print(f"median voice pitch: {f'{f0:.0f} Hz' if f0 else 'n/a'} (rough autocorrelation estimate)")
    if stats["video_tracks"] != 1 or fps < 5:
        print("FAIL: expected one agent camera track delivering frames")
        return 1
    if stats["early_audible"]:
        print(f"FAIL: the agent spoke before bridge_ready ({stats['early_audible']} audible frames); it must greet only on the signal")
        return 1
    if stats["first_audible"] and t_ready:
        delay = stats["first_audible"] - t_ready
        # chert dev polls for bridge_ready every 500 ms, so the agent's real budget is under 10 s.
        verdict = "OK" if delay < MAX_GREET_S else f"TOO SLOW (limit {MAX_GREET_S:.0f} s; Chert ends the call at 10 s)"
        print(f"first audible audio {delay:.2f} s after bridge_ready: {verdict}")
        return 0 if delay < MAX_GREET_S else 1
    print("FAIL: no audible audio from the agent after bridge_ready")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
