"""Fake-API tests of the §9.16 client and the ordered uplink (retries keep the same (epoch, sequence))."""
import logging
import time

import pytest

from fazetime_worker.api_client import ApiClient, FrameOp, ObservationOp, RegisterEpoch, Uplink
from fazetime_worker.util import new_epoch_id, utc_now

from .fake_api import FakeApi

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64 + b"\xff\xd9"


@pytest.fixture
def api():
    a = FakeApi().start()
    yield a
    a.stop()


def mk_uplink(api, **kw):
    client = ApiClient(api.base, api.token, timeout_s=5)
    up = Uplink(client, api.stream_id, batch_wait_s=0.05, sleep=lambda s: time.sleep(min(s, 0.01)), **kw)
    up.start()
    return up


def reg(epoch, reason="PROCESS_START", stream_id="str_" + "a" * 32):
    return RegisterEpoch({"schema_version": 1, "stream_id": stream_id, "source_epoch": epoch,
                          "source_kind": "TEST_FIXTURE", "reason": reason, "variant": None, "host_id": "test",
                          "started_at_utc": utc_now()})


def transcript(seq, text="hello"):
    return {"sequence": seq, "kind": "TRANSCRIPT", "media_start_ms": (seq - 1) * 3000,
            "media_end_ms": (seq - 1) * 3000 + 4000, "captured_at_utc": utc_now(), "source_wall_time_utc": None,
            "quality_flags": [], "transcript": {"text": text, "avg_logprob": -0.3, "no_speech_prob": 0.1,
                                                "model": "fake", "language": "en"},
            "evidence_id": None, "gap": None}


def settle(up, timeout=5):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if up.depth() == 0 and up.idle.is_set():
            return
        time.sleep(0.02)
    raise AssertionError("uplink did not drain")


def test_register_heartbeat_frame_and_observations_in_order(api):
    up = mk_uplink(api)
    ep = new_epoch_id()
    up.put(reg(ep))
    up.put(FrameOp(ep, 1, 2000, 854, 480, JPEG, utc_now(), ["PARTIAL", "NOT_A_CONTRACT_FLAG"]))
    for s in range(2, 7):
        up.put(ObservationOp(ep, transcript(s)))
    settle(up)
    assert api.current == ep and api.epochs[ep]["source_kind"] == "TEST_FIXTURE"
    assert len(api.evidence) == 1 and up.stats["frames_uploaded"] == 1
    frame_obs = api.observations[(ep, 1)]
    assert frame_obs["kind"] == "FRAME" and frame_obs["evidence_id"].startswith("evd_")
    assert frame_obs["quality_flags"] == ["PARTIAL"]  # unknown flags never reach the API
    assert sorted(s for (e, s) in api.observations) == [1, 2, 3, 4, 5, 6]
    assert up.stats["obs_accepted"] == 6 and up.stats["obs_rejected"] == 0
    hb = {"schema_version": 1, "stream_id": api.stream_id, "source_epoch": ep, "worker_state": "LIVE",
          "last_media_end_ms": 9000, "last_input_age_ms": 120, "asr_backlog_ms": 0, "queue_depth": 0,
          "gap_threshold_ms": 12000, "host_id": "test", "host_wall_utc": utc_now()}
    assert up.heartbeat(hb).ok and api.heartbeats[-1]["worker_state"] == "LIVE"
    up.stop()


def test_retries_resend_same_sequence_and_server_dedupes(api):
    up = mk_uplink(api)
    ep = new_epoch_id()
    api.fail_next("/epochs", 503)                       # transient failure before commit
    api.fail_next("/observations", 500, after_commit=True)  # committed, response lost
    api.fail_next("/evidence", 500, after_commit=True)
    up.put(reg(ep))
    up.put(ObservationOp(ep, transcript(1)))
    up.put(FrameOp(ep, 2, 4000, 854, 480, JPEG, utc_now()))
    settle(up)
    assert up.stats["retries"] >= 3
    assert up.stats["obs_duplicates"] >= 1               # resent body hit the (epoch, sequence) dedupe
    assert up.stats["frames_deduped"] == 1               # same (epoch, seq, sha) -> same evidence_id
    assert len(api.evidence) == 1
    assert set(api.observations) == {(ep, 1), (ep, 2)}
    up.stop()


def test_superseded_epoch_items_are_dropped_not_sent(api):
    up = mk_uplink(api)
    a, b = new_epoch_id(), new_epoch_id()
    up.put(reg(a))
    up.put(reg(b, "PTS_DISCONTINUITY"))
    up.put(ObservationOp(a, transcript(1, "late item from the old epoch")))
    up.put(ObservationOp(b, transcript(1)))
    settle(up)
    assert api.epoch_order == [a, b]
    assert (a, 1) not in api.observations and (b, 1) in api.observations
    assert up.stats["dropped_stale_epoch"] == 1
    up.stop()


def test_server_stale_epoch_is_not_retried(api):
    up = mk_uplink(api)
    a = new_epoch_id()
    up.put(reg(a))
    settle(up)
    api.current = "ep_" + "f" * 32  # another registration superseded ours on the server
    up.put(ObservationOp(a, transcript(1)))
    settle(up)
    assert up.stats["dropped_stale_epoch"] == 1 and up.stats["retries"] == 0
    up.stop()


def test_retries_are_bounded(api):
    up = mk_uplink(api, item_max_s=0.3)
    a = new_epoch_id()
    up.put(reg(a))
    settle(up)
    api.fail_next("/observations", 500, times=1000)
    up.put(ObservationOp(a, transcript(1)))
    settle(up, timeout=10)
    assert up.stats["dropped_4xx"] == 1 and 0 < up.stats["retries"] < 1000
    up.stop()


def test_uplink_queue_is_bounded_and_never_drops_registrations():
    class Dead:
        def post_json(self, *a):
            raise AssertionError("not started")
    up = Uplink(Dead(), "str_" + "a" * 32, max_queue=5)
    a = new_epoch_id()
    up.put(reg(a))
    for s in range(1, 20):
        up.put(ObservationOp(a, transcript(s)))
    assert up.depth() == 5 and up.stats["dropped_overflow"] == 15
    assert isinstance(up.q[0], RegisterEpoch)


def test_token_is_never_logged(api, caplog):
    caplog.set_level(logging.DEBUG)
    up = mk_uplink(api)
    a = new_epoch_id()
    api.fail_next("/epochs", 500)
    up.put(reg(a))
    settle(up)
    up.stop()
    assert api.token not in caplog.text
    assert api.token not in repr(up.client)
    assert f"Bearer {api.token}" in api.auth_headers_seen  # but it is sent


def test_wrong_token_is_401_and_not_retried(api):
    client = ApiClient(api.base, "fzk_wrong", timeout_s=5)
    up = Uplink(client, api.stream_id, sleep=lambda s: None)
    up.start()
    up.put(reg(new_epoch_id()))
    settle(up)
    assert up.stats["epochs_registered"] == 0 and up.stats["retries"] == 0
    assert up.last_error.startswith("register 401")
    up.stop()
