"""Offline end-to-end: TEST_FIXTURE source -> real FFmpeg -> capture -> fake ASR -> fake API (~40 s).

Deterministic replay only: source_kind TEST_FIXTURE, synthetic tones, no Twitch, no model. It proves the
epoch/sequence/gap/frame/transcript wiring, not ASR quality or Twitch behaviour.
"""
import shutil
import threading
import time
from collections import defaultdict
from pathlib import Path

import pytest

from fazetime_worker.api_client import ApiClient
from fazetime_worker.asr import FakeEngine
from fazetime_worker.config import Config
from fazetime_worker.pipeline import Pipeline

from .fake_api import FakeApi

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def test_offline_end_to_end(tmp_path):
    api = FakeApi().start()
    cfg = Config(api_base=api.base, token=api.token, stream_id=api.stream_id, channel="offline_test",
                 test_source_cmd=f"env PART1_S=12 STALL_S=3 PART2_S=8 JUMP_S=5 bash {ROOT}/scripts/test_source_lavfi.sh",
                 data_dir=tmp_path, asr_engine="fake", max_restarts=1, heartbeat_s=1.0, ring_s=30,
                 batch_max_wait_s=0.2)
    p = Pipeline(cfg, engine=FakeEngine(), client=ApiClient(api.base, api.token))
    final = p.run(duration_s=38)
    api.stop()

    reasons = [api.epochs[e]["reason"] for e in api.epoch_order]
    kinds = {api.epochs[e]["source_kind"] for e in api.epoch_order}
    assert kinds == {"TEST_FIXTURE"}
    assert reasons[:3] == ["PROCESS_START", "PTS_DISCONTINUITY", "PROCESS_RESTART"], reasons
    first, second = api.epoch_order[0], api.epoch_order[1]

    by_epoch = defaultdict(list)
    for (ep, seq), it in api.observations.items():
        by_epoch[ep].append((seq, it))
    for ep, items in by_epoch.items():
        seqs = sorted(s for s, _ in items)
        assert seqs[0] >= 1 and len(seqs) == len(set(seqs))

    gaps = [it for _, it in by_epoch[first] if it["kind"] == "GAP"]
    assert len(gaps) == 1 and gaps[0]["gap"]["reason"] == "PTS_DISCONTINUITY"
    assert not [it for _, it in by_epoch[second] if it["kind"] == "GAP"]

    frames = sorted((it["media_start_ms"], it["evidence_id"]) for _, it in by_epoch[first] if it["kind"] == "FRAME")
    assert len(frames) >= 4
    assert all(e.startswith("evd_") for _, e in frames)
    spacing = [b[0] - a[0] for a, b in zip(frames, frames[1:])]
    assert all(1900 <= d <= 2100 for d in spacing), spacing
    f2 = [it["media_start_ms"] for _, it in by_epoch[second] if it["kind"] == "FRAME"]
    assert f2 and min(f2) < 2100  # second epoch restarts its media timeline near 0

    tr = sorted((it["media_start_ms"], it["media_end_ms"]) for _, it in by_epoch[first] if it["kind"] == "TRANSCRIPT")
    assert tr[:3] == [(0, 4000), (3000, 7000), (6000, 10000)]
    t2 = sorted(it["media_start_ms"] for _, it in by_epoch[second] if it["kind"] == "TRANSCRIPT")
    assert t2 and t2[0] == 0

    live = [h for h in api.heartbeats if h["worker_state"] == "LIVE" and h["source_epoch"] == first]
    assert live, "no LIVE heartbeat for the first epoch"
    ends = [h["last_media_end_ms"] for h in live]
    assert ends == sorted(ends)
    assert final["uplink"]["obs_rejected"] == 0 and final["uplink"]["dropped_4xx"] == 0
