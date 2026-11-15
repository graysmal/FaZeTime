"""ASR stage: 4 s windows / 3 s hop per epoch, bounded queue, per-window deadline, overlap dedupe.

* Windows never span epochs. On an epoch change the partial window is discarded and queued windows of
  the old epoch are dropped (no temporal context crosses a restart or discontinuity).
* The queue is bounded (drop-oldest). A window that waited longer than `asr_max_wait_s` is dropped
  instead of processed, so a slow model shows up as backlog/STALE, never as a growing silent backlog.
* Decoding is bounded: one temperature (no fallback ladder) and `max_new_tokens`. faster-whisper cannot be
  interrupted mid-call, so the bound on work is what enforces the per-window deadline.
* Transcript text is untrusted data: it is only normalised for overlap comparison and forwarded verbatim.
"""
from __future__ import annotations

import logging
import re
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Protocol

from .util import mono_ns, utc_now

log = logging.getLogger("fazetime.asr")
SR = 16000


@dataclass
class Window:
    epoch: str
    index: int
    media_start_ms: int
    media_end_ms: int
    pcm: bytes  # s16le mono 16 kHz
    available_ns: int
    captured_at_utc: str
    flags: list[str] = field(default_factory=list)


@dataclass
class Segment:
    text: str
    avg_logprob: float | None = None
    no_speech_prob: float | None = None
    compression_ratio: float | None = None


REPETITION_RATIO = 2.4  # Whisper's own compression-ratio threshold; above it the text is a repetition loop


class Engine(Protocol):
    name: str

    def transcribe(self, pcm: bytes) -> list[Segment]: ...


class Windower:
    """Cuts each epoch's contiguous PCM into fixed windows with overlap. Thread-confined to the caller."""

    def __init__(self, window_ms: int, hop_ms: int, emit: Callable[[Window], None]):
        assert 0 < hop_ms < window_ms
        self.win = window_ms * SR // 1000 * 2
        self.hop = hop_ms * SR // 1000 * 2
        self.window_ms, self.hop_ms = window_ms, hop_ms
        self.emit = emit
        self.epoch: str | None = None
        self.buf = bytearray()
        self.buf_start = 0  # epoch sample index of buf[0]
        self.index = 0
        self.discarded_partial = 0

    def feed(self, epoch: str, pcm: bytes, media_start_ms: int, t_ns: int, captured_at_utc: str):
        if epoch != self.epoch:
            if self.buf:
                self.discarded_partial += 1
            self.epoch, self.buf, self.buf_start, self.index = epoch, bytearray(), 0, 0
        expected_ms = (self.buf_start + len(self.buf) // 2) * 1000 // SR
        if media_start_ms != expected_ms:  # capture guarantees contiguity; never stitch silently
            log.warning("non-contiguous pcm in %s: expected %d got %d ms; restarting window", epoch, expected_ms,
                        media_start_ms)
            self.buf = bytearray()
            self.buf_start = media_start_ms * SR // 1000
        self.buf += pcm
        while len(self.buf) >= self.win:
            start_s = self.buf_start
            self.emit(Window(epoch, self.index, start_s * 1000 // SR, (start_s + self.win // 2) * 1000 // SR,
                             bytes(self.buf[:self.win]), t_ns, captured_at_utc))
            self.index += 1
            del self.buf[:self.hop]
            self.buf_start += self.hop // 2


class BoundedQueue:
    """Drop-oldest queue of windows with backlog accounting (CONTRACTS §9.16 asr_backlog_ms)."""

    def __init__(self, maxlen: int):
        self.maxlen = maxlen
        self.items: deque[Window] = deque()
        self.cv = threading.Condition()
        self.dropped_full = 0
        self.dropped_stale = 0
        self.dropped_superseded = 0
        self.in_flight: Window | None = None
        self.last_drop_ns = 0  # any window skipped for overflow or staleness (=> transcript coverage hole)

    def put(self, w: Window):
        with self.cv:
            self.items.append(w)
            while len(self.items) > self.maxlen:
                self.items.popleft()
                self.dropped_full += 1
                self.last_drop_ns = mono_ns()
            self.cv.notify()

    def note_stale_drop(self):
        with self.cv:
            self.dropped_stale += 1
            self.last_drop_ns = mono_ns()

    def get(self, timeout: float = 0.5) -> Window | None:
        with self.cv:
            if not self.items:
                self.cv.wait(timeout)
            if not self.items:
                return None
            w = self.items.popleft()
            self.in_flight = w
            return w

    def done(self):
        with self.cv:
            self.in_flight = None

    def drop_epochs_except(self, epoch: str):
        with self.cv:
            keep = [w for w in self.items if w.epoch == epoch]
            self.dropped_superseded += len(self.items) - len(keep)
            self.items = deque(keep)

    def depth(self) -> int:
        with self.cv:
            return len(self.items) + (1 if self.in_flight else 0)

    def backlog_ms(self, now_ns: int | None = None) -> int:
        """Age of the oldest window not yet transcribed (queued or in flight), 0 when idle."""
        now_ns = now_ns or mono_ns()
        with self.cv:
            oldest = self.in_flight or (self.items[0] if self.items else None)
            if oldest is None:
                return 0
            return max(0, int((now_ns - oldest.available_ns) / 1e6))


_WORD = re.compile(r"[a-z0-9']+")


def norm_words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


class OverlapDeduper:
    """Removes words repeated across the window overlap: the longest suffix of the previous window's
    words that equals a prefix of the current window's words (normalised, up to `max_words`)."""

    def __init__(self, max_words: int = 8):
        self.max_words = max_words
        self.epoch: str | None = None
        self.prev: list[str] = []

    def dedupe(self, epoch: str, text: str) -> tuple[str, bool]:
        if epoch != self.epoch:
            self.epoch, self.prev = epoch, []
        raw_tokens = text.split()
        norm = [norm_words(t) for t in raw_tokens]
        flat_idx = [i for i, ws in enumerate(norm) for _ in ws]  # word -> raw token index
        words = [w for ws in norm for w in ws]
        trimmed = False
        best = 0
        for k in range(min(len(self.prev), len(words), self.max_words), 0, -1):
            if self.prev[-k:] == words[:k]:
                best = k
                break
        out = text.strip()
        if best:
            cut_token = flat_idx[best - 1] + 1  # drop whole raw tokens covering the repeated words
            out = " ".join(raw_tokens[cut_token:])
            trimmed = True
        self.prev = (self.prev + words)[-self.max_words * 4:] if words else []
        return out, trimmed


class FakeEngine:
    """Deterministic test engine (TEST_FIXTURE / unit tests): reports energy, never real speech."""

    name = "fake-energy"

    def transcribe(self, pcm: bytes) -> list[Segment]:
        import numpy as np
        x = np.frombuffer(pcm, dtype="<i2").astype("float32")
        rms = float(np.sqrt(np.mean(x * x))) if len(x) else 0.0
        return [Segment(f"tone rms {int(rms)}", -0.2, 0.01)] if rms > 300 else []


class FasterWhisperEngine:
    def __init__(self, model: str, threads: int, beam: int, temperature: float, max_new_tokens: int,
                 hotwords: str | None, initial_prompt: str | None, models_dir: str | None):
        from pathlib import Path

        from faster_whisper import WhisperModel
        local = Path(models_dir) / model if models_dir else None
        source = str(local) if local is not None and (local / "model.bin").exists() else model  # plain CT2 dir first
        self.model = WhisperModel(source, device="cpu", compute_type="int8", cpu_threads=threads, num_workers=1,
                                  download_root=models_dir)
        self.name = f"faster-whisper-{model}-int8"
        self.kw = dict(language="en", beam_size=beam, vad_filter=True, temperature=temperature,
                       max_new_tokens=max_new_tokens, condition_on_previous_text=False)
        if hotwords:
            self.kw["hotwords"] = hotwords
        if initial_prompt:
            self.kw["initial_prompt"] = initial_prompt

    def transcribe(self, pcm: bytes) -> list[Segment]:
        import numpy as np
        audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        segs, _ = self.model.transcribe(audio, **self.kw)
        return [Segment(s.text.strip(), float(s.avg_logprob), float(s.no_speech_prob), float(s.compression_ratio))
                for s in segs]


class AsrWorker(threading.Thread):
    """Single consumer thread. Calls `publish(window, text, segments_meta, flags, latency_ms)`."""

    def __init__(self, engine: Engine, queue: BoundedQueue, is_current: Callable[[str], bool],
                 publish: Callable[..., None], max_wait_s: float, low_logprob: float, high_no_speech: float):
        super().__init__(daemon=True, name="asr")
        self.engine, self.q, self.is_current, self.publish = engine, queue, is_current, publish
        self.max_wait_ns = int(max_wait_s * 1e9)
        self.low_logprob, self.high_no_speech = low_logprob, high_no_speech
        self.dedupe = OverlapDeduper()
        self.stop_flag = threading.Event()
        self.processed = 0
        self.proc_ms: deque = deque(maxlen=200)
        self.latency_ms: deque = deque(maxlen=200)
        self.errors = 0
        self.filtered_repetitive = 0

    def run(self):
        while not self.stop_flag.is_set():
            w = self.q.get(timeout=0.5)
            if w is None:
                continue
            try:
                if not self.is_current(w.epoch):
                    self.q.dropped_superseded += 1
                    continue
                if mono_ns() - w.available_ns > self.max_wait_ns:
                    self.q.note_stale_drop()
                    continue
                t0 = mono_ns()
                try:
                    segs = self.engine.transcribe(w.pcm)
                except Exception:  # model failure is a health problem, not a crash loop
                    self.errors += 1
                    log.exception("ASR failure on %s window %d", w.epoch, w.index)
                    continue
                t1 = mono_ns()
                self.proc_ms.append((t1 - t0) / 1e6)
                self.latency_ms.append((t1 - w.available_ns) / 1e6)
                # With a single temperature there is no fallback re-decode, so repetition loops
                # ("Okay. Okay. Okay.", "1v1, 1v1, ...") must be filtered here instead.
                kept = [s for s in segs if s.text and (s.compression_ratio is None or s.compression_ratio <= REPETITION_RATIO)]
                filtered = len(kept) < len([s for s in segs if s.text])
                self.filtered_repetitive += int(filtered)
                segs = kept
                text = " ".join(s.text for s in segs).strip()
                text, trimmed = self.dedupe.dedupe(w.epoch, text)
                flags = list(w.flags)
                if filtered:
                    flags.append("LOW_CONFIDENCE")
                if trimmed:
                    flags.append("DEDUPED_OVERLAP")
                lp = min((s.avg_logprob for s in segs if s.avg_logprob is not None), default=None)
                ns = max((s.no_speech_prob for s in segs if s.no_speech_prob is not None), default=None)
                if text and ((lp is not None and lp < self.low_logprob) or (ns is not None and ns > self.high_no_speech)):
                    flags.append("LOW_CONFIDENCE")
                self.processed += 1
                if self.is_current(w.epoch):
                    self.publish(w, text[:1000], lp, ns, self.engine.name, flags, int((t1 - w.available_ns) / 1e6))
                else:
                    self.q.dropped_superseded += 1
            finally:
                self.q.done()

    def stats(self) -> dict:
        def p(xs, q):
            xs = sorted(xs)
            return round(xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))], 1) if xs else None
        return {"processed": self.processed, "errors": self.errors, "filtered_repetitive": self.filtered_repetitive,
                "dropped_full": self.q.dropped_full,
                "dropped_stale": self.q.dropped_stale, "dropped_superseded": self.q.dropped_superseded,
                "proc_ms_p50": p(self.proc_ms, .5), "proc_ms_p95": p(self.proc_ms, .95),
                "latency_ms_p95": p(self.latency_ms, .95), "engine": self.engine.name, "at": utc_now()}
