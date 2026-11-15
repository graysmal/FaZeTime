"""Unit tests: sequences/epochs, windows + overlap dedupe, queue bounds, ASR worker drop rules, JPEG size."""
import struct
import threading

import numpy as np
import pytest

from fazetime_worker.asr import AsrWorker, BoundedQueue, OverlapDeduper, Segment, Window, Windower
from fazetime_worker.capture import jpeg_size
from fazetime_worker.config import Config
from fazetime_worker.util import EPOCH_RE, UTC_RE, EpochSequencer, StaleEpochError, new_epoch_id, redact_urls, utc_now

SR = 16000


def pcm_ms(ms, value=0):
    return np.full(ms * SR // 1000, value, dtype="<i2").tobytes()


# ---- sequences and epochs ------------------------------------------------------------------------
def test_sequence_starts_at_one_and_is_monotonic_per_epoch():
    s = EpochSequencer()
    a = new_epoch_id()
    s.open(a)
    assert [s.next(a) for _ in range(3)] == [1, 2, 3]
    b = new_epoch_id()
    s.open(b)
    assert s.next(b) == 1  # fresh sequence for the new epoch


def test_old_epoch_can_never_emit_again_or_reopen():
    s = EpochSequencer()
    a, b = new_epoch_id(), new_epoch_id()
    s.open(a)
    s.next(a)
    s.open(b)
    with pytest.raises(StaleEpochError):
        s.next(a)
    with pytest.raises(ValueError):
        s.open(a)
    with pytest.raises(ValueError):
        s.open(b)


def test_concurrent_sequences_are_unique():
    s = EpochSequencer()
    a = new_epoch_id()
    s.open(a)
    got = []
    lock = threading.Lock()

    def take():
        for _ in range(500):
            v = s.next(a)
            with lock:
                got.append(v)

    ts = [threading.Thread(target=take) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(got) == list(range(1, 2001))


def test_formats():
    assert EPOCH_RE.match(new_epoch_id())
    assert UTC_RE.match(utc_now())
    assert redact_urls("GET https://x.ttvnw.net/v1/a.m3u8?sig=abc&token=def ok") == \
        "GET https://x.ttvnw.net/v1/a.m3u8?<redacted> ok"


def test_config_never_exposes_token():
    c = Config(api_base="http://fazetime:8000", token="fzk_secret_value", stream_id="str_" + "a" * 32)
    assert "fzk_secret_value" not in repr(c)
    assert "fzk_secret_value" not in str(c.public_dict())
    assert c.public_dict()["token_present"] is True
    assert c.validate() == []
    assert Config(api_base="http://x", token="bad", stream_id="nope").validate()


# ---- windows -----------------------------------------------------------------------------------------
def test_windower_cuts_4s_windows_with_1s_overlap_from_irregular_pieces():
    out = []
    w = Windower(4000, 3000, out.append)
    ep = new_epoch_id()
    pos = 0
    for piece in (700, 1300, 2500, 1500, 4000):  # 10 s total, irregular arrival
        w.feed(ep, pcm_ms(piece), pos, 1, "t")
        pos += piece
    assert [(x.media_start_ms, x.media_end_ms) for x in out] == [(0, 4000), (3000, 7000), (6000, 10000)]
    assert [x.index for x in out] == [0, 1, 2]
    assert all(len(x.pcm) == 4 * SR * 2 for x in out)


def test_windower_never_spans_epochs():
    out = []
    w = Windower(4000, 3000, out.append)
    a, b = new_epoch_id(), new_epoch_id()
    w.feed(a, pcm_ms(3500), 0, 1, "t")  # partial window in a
    w.feed(b, pcm_ms(4000), 0, 2, "t")  # b restarts at media 0
    assert [(x.epoch, x.media_start_ms) for x in out] == [(b, 0)]
    assert w.discarded_partial == 1


def test_windower_resets_on_noncontiguous_input():
    out = []
    w = Windower(4000, 3000, out.append)
    ep = new_epoch_id()
    w.feed(ep, pcm_ms(2000), 0, 1, "t")
    w.feed(ep, pcm_ms(4000), 5000, 2, "t")  # hole: never stitched
    assert [(x.media_start_ms, x.media_end_ms) for x in out] == [(5000, 9000)]


# ---- queue -----------------------------------------------------------------------------------------
def mkwin(epoch, i, t_ns=0):
    return Window(epoch, i, i * 3000, i * 3000 + 4000, b"", t_ns, "t")


def test_queue_is_bounded_drop_oldest_and_reports_backlog():
    q = BoundedQueue(3)
    ep = new_epoch_id()
    for i in range(5):
        q.put(mkwin(ep, i, t_ns=i * 1_000_000_000))
    assert q.depth() == 3 and q.dropped_full == 2
    assert [w.index for w in q.items] == [2, 3, 4]
    assert q.backlog_ms(now_ns=10_000_000_000) == 8000  # oldest queued became available at t=2 s
    w = q.get(0)
    assert w.index == 2 and q.depth() == 3  # in flight still counts
    q.done()
    assert q.depth() == 2
    q.drop_epochs_except(new_epoch_id())
    assert q.depth() == 0 and q.dropped_superseded == 2
    assert q.backlog_ms() == 0


# ---- overlap dedupe ------------------------------------------------------------------------------------
@pytest.mark.parametrize("prev,cur,expected,trimmed", [
    ("we are going to fight now", "fight now. FaZeGavin wins", "FaZeGavin wins", True),
    ("Hello there", "General Kenobi", "General Kenobi", False),
    ("it's FaZeNeville", "FaZeNeville, and the 1v1 starts", "and the 1v1 starts", True),
    ("one two three", "One, two three four", "four", True),
])
def test_overlap_dedupe(prev, cur, expected, trimmed):
    d = OverlapDeduper()
    ep = new_epoch_id()
    d.dedupe(ep, prev)
    assert d.dedupe(ep, cur) == (expected, trimmed)


def test_overlap_dedupe_resets_on_epoch_and_silence():
    d = OverlapDeduper()
    a, b = new_epoch_id(), new_epoch_id()
    d.dedupe(a, "three two one")
    assert d.dedupe(b, "one fight") == ("one fight", False)  # new epoch: no context reuse
    d.dedupe(b, "lets go")
    d.dedupe(b, "")  # silence window
    assert d.dedupe(b, "go again") == ("go again", False)


# ---- ASR worker rules -------------------------------------------------------------------------------------
class ListEngine:
    name = "list-engine"

    def __init__(self, segs):
        self.segs = segs

    def transcribe(self, pcm):
        return self.segs


def run_worker(engine, windows, current, max_wait_s=6.0, now_offset_ns=0):
    q = BoundedQueue(10)
    out = []
    w = AsrWorker(engine, q, lambda e: e == current, lambda *a: out.append(a), max_wait_s, -1.0, 0.6)
    for win in windows:
        q.put(win)
    w.start()
    import time
    t0 = time.time()
    while q.depth() and time.time() - t0 < 5:
        time.sleep(0.01)
    w.stop_flag.set()
    w.join(2)
    return out, q, w


def test_asr_worker_drops_stale_and_superseded_and_flags_low_confidence():
    from fazetime_worker.util import mono_ns
    cur, old = new_epoch_id(), new_epoch_id()
    now = mono_ns()
    wins = [mkwin(old, 0, now), mkwin(cur, 0, now - 20_000_000_000), mkwin(cur, 1, now)]
    out, q, w = run_worker(ListEngine([Segment("hello FaZeGavin", -1.5, 0.1)]), wins, cur)
    assert q.dropped_superseded == 1 and q.dropped_stale == 1
    assert len(out) == 1
    win, text, lp, ns, model, flags, latency = out[0]
    assert (win.epoch, win.index, text, model) == (cur, 1, "hello FaZeGavin", "list-engine")
    assert "LOW_CONFIDENCE" in flags


def test_jpeg_size_parses_sof():
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 17, 8, 480, 854, 3) + b"\x00" * 9
    data = b"\xff\xd8" + b"\xff\xe0" + struct.pack(">H", 4) + b"ab" + sof + b"\xff\xd9"
    assert jpeg_size(data) == (854, 480)


# ---- repetition filter and name aliases ---------------------------------------------------------------
def test_repetition_loops_are_filtered_and_flagged():
    from fazetime_worker.util import mono_ns
    cur = new_epoch_id()
    segs = [Segment("1v1, 1v1, 1v1, 1v1, 1v1, 1v1, 1v1, 1v1", -0.2, 0.1, 3.9), Segment("FaZeGavin wins", -0.3, 0.1, 1.1)]
    out, q, w = run_worker(ListEngine(segs), [mkwin(cur, 0, mono_ns())], cur)
    win, text, lp, ns, model, flags, latency = out[0]
    assert text == "FaZeGavin wins" and "LOW_CONFIDENCE" in flags and w.filtered_repetitive == 1


@pytest.mark.parametrize("text,gavin,neville", [
    ("I'm FaZe Gavin. How long", 1, 0),
    ("What a phase Gavin on Twitch", 1, 0),
    ("put it in a face, Gavin.", 1, 0),
    ("1v1ing my friend face neville", 0, 1),
    ("FaZeGavin vs FaZeNeville", 1, 1),
    ("nothing relevant, gave in", 0, 0),
])
def test_name_aliases(text, gavin, neville):
    from fazetime_worker.names import find_names
    assert find_names(text) == {"FaZeGavin": gavin, "FaZeNeville": neville}


def test_asr_drops_turn_heartbeat_stale(tmp_path):
    from fazetime_worker.asr import FakeEngine
    from fazetime_worker.pipeline import Pipeline
    from fazetime_worker.util import mono_ns
    cfg = Config(data_dir=tmp_path, asr_engine="fake", asr_queue_max=2)
    p = Pipeline(cfg, engine=FakeEngine())
    ep = new_epoch_id()
    p.on_epoch(ep, "PROCESS_START", None, "best", utc_now())
    p.uplink.registered.add(ep)
    p.capture.state = "LIVE"

    class Att:  # minimal attempt stand-in for status()
        epoch = ep
        first_audio_ns = last_audio_ns = last_byte_ns = mono_ns()
        index, frames, frames_skipped = 0, 0, 0
        burst_starts, seg_delays_ms = [], []

        def media_pos_ms(self):
            return 4000
    p.capture.attempt = Att()
    assert p.heartbeat_body()["worker_state"] == "LIVE"
    for i in range(3):  # overflow a 2-window queue -> one window skipped
        p.queue.put(mkwin(ep, i, mono_ns()))
    body = p.heartbeat_body()
    assert body["worker_state"] == "STALE" and body["queue_depth"] == 2
