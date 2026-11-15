"""faster-whisper int8 CPU engine with the Pi worker's bounded decoding policy (D22, spikes/p0b-team).

The decoding keyword arguments are identical to `services/worker/fazetime_worker/asr.py`
`FasterWhisperEngine` with the worker defaults:

* `temperature=0.0` as a single value: no temperature-fallback ladder (the default ladder caused 7.9 s stalls);
* `max_new_tokens=64`: bounded work per window;
* `vad_filter=True`, `beam_size=5`, `language="en"`, `condition_on_previous_text=False`;
* NO `initial_prompt` and NO `hotwords`. On the team audio they fabricated "FaZeGavin" and "1v1" loops on
  noise and silence, so names are canonicalised downstream (`fazetime_worker/names.py`) instead.

The compression-ratio filter (Whisper's own 2.4 threshold) is applied to `text`. Every decoded segment is
still returned with its `compression_ratio`, so the Pi worker's own filter and LOW_CONFIDENCE flagging see
exactly what they would see from a local engine.

Transcript text is untrusted data. It is never interpreted here, only bounded and returned.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import asdict, dataclass

SR = 16000
REPETITION_RATIO = 2.4
MAX_SEGMENTS = 32
MAX_SEGMENT_CHARS = 500
MAX_TEXT_CHARS = 1000

DECODE_KW = dict(language="en", beam_size=5, vad_filter=True, temperature=0.0, max_new_tokens=64,
                 condition_on_previous_text=False)
FORBIDDEN_KW = ("initial_prompt", "hotwords", "prefix")


@dataclass
class Seg:
    start_ms: int
    end_ms: int
    text: str
    avg_logprob: float
    no_speech_prob: float
    compression_ratio: float


@dataclass
class Result:
    text: str
    segments: list[Seg]
    filtered_repetitive: int
    compute_ms: int

    def segments_json(self) -> list[dict]:
        return [asdict(s) for s in self.segments]


def pcm_to_float(pcm: bytes):
    import numpy as np
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0


def build_result(raw_segments, compute_ms: int) -> Result:
    """Bound and filter decoded segments (pure function, unit-tested without a model)."""
    segs: list[Seg] = []
    for s in raw_segments:
        if len(segs) >= MAX_SEGMENTS:
            break
        segs.append(Seg(start_ms=max(0, int(round(float(s.start) * 1000))),
                        end_ms=max(0, int(round(float(s.end) * 1000))),
                        text=str(s.text).strip()[:MAX_SEGMENT_CHARS],
                        avg_logprob=round(float(s.avg_logprob), 4),
                        no_speech_prob=round(float(s.no_speech_prob), 4),
                        compression_ratio=round(float(s.compression_ratio), 4)))
    voiced = [s for s in segs if s.text]
    kept = [s for s in voiced if s.compression_ratio <= REPETITION_RATIO]
    text = " ".join(s.text for s in kept).strip()[:MAX_TEXT_CHARS]
    return Result(text=text, segments=segs, filtered_repetitive=len(voiced) - len(kept), compute_ms=compute_ms)


class WhisperEngine:
    """One loaded model. `concurrency` parallel transcribe() calls are supported (CTranslate2 workers)."""

    def __init__(self, model: str, threads: int, concurrency: int = 1, models_dir: str | None = None,
                 local_files_only: bool = True):
        from faster_whisper import WhisperModel
        assert not any(k in DECODE_KW for k in FORBIDDEN_KW), "decoder prompts are forbidden (spikes/p0b-team)"
        t0 = time.perf_counter()
        self.model = WhisperModel(model, device="cpu", compute_type="int8", cpu_threads=threads,
                                  num_workers=max(1, concurrency), download_root=models_dir,
                                  local_files_only=local_files_only)
        self.load_s = round(time.perf_counter() - t0, 2)
        self.model_name = model
        self.name = f"faster-whisper-{model}-int8"
        self.threads, self.concurrency = threads, concurrency
        self._lock = threading.Lock()  # only guards the counters below; decoding itself runs in parallel
        self.calls = 0

    def transcribe(self, pcm: bytes) -> Result:
        audio = pcm_to_float(pcm)
        t0 = time.perf_counter()
        segs, _info = self.model.transcribe(audio, **DECODE_KW)
        raw = []
        for s in segs:  # the generator decodes lazily; bound the number of segments consumed
            raw.append(s)
            if len(raw) >= MAX_SEGMENTS:
                break
        compute_ms = int((time.perf_counter() - t0) * 1000)
        with self._lock:
            self.calls += 1
        return build_result(raw, compute_ms)


def env_int(name: str, default: int) -> int:
    v = os.environ.get(name)
    return int(v) if v not in (None, "") else default
