"""Causal slicing of a prepared fixture (see prep_fixture.py) for replay. LOCAL FIXTURE ONLY.

A replay advances a media clock in fixed steps (Twitch delivers about every 6 s). At each step the consumer sees
only what has already been "received": transcript words whose end time is at least ``asr_delay_s`` in the past,
and frames whose media second has passed. Nothing from the future is ever exposed.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Word:
    start: float
    end: float
    text: str
    p: float


@dataclass
class Frame:
    t: float  # media second
    path: Path

    def jpeg(self) -> bytes:
        return self.path.read_bytes()


@dataclass
class Slice:
    t0: float  # exclusive
    t1: float  # inclusive: the media clock at this step
    words: list[Word] = field(default_factory=list)
    frames: list[Frame] = field(default_factory=list)

    def text(self) -> str:
        return " ".join(w.text for w in self.words).strip()


class Fixture:
    def __init__(self, root: Path):
        self.root = Path(root)
        tr = json.loads((self.root / "transcript.json").read_text())
        self.asr_model = tr.get("model")
        self.words: list[Word] = []
        for s in tr["segments"]:
            ws = s.get("words") or []
            if ws:
                self.words.extend(Word(w["start"], w["end"], w["word"], w.get("p", 1.0)) for w in ws)
            else:
                self.words.append(Word(s["start"], s["end"], s["text"], 1.0))
        self.words.sort(key=lambda w: w.end)
        self.frames = sorted((Frame(float(p.stem.split("_")[1]), p) for p in (self.root / "frames").glob("f_*.jpg")),
                             key=lambda f: f.t)
        probe = json.loads((self.root / "probe.json").read_text())
        self.duration_s = float(probe["duration_s"])

    def frame_at(self, t: float) -> Frame | None:
        """The latest frame at or before media second t."""
        best = None
        for f in self.frames:
            if f.t <= t:
                best = f
            else:
                break
        return best

    def slices(self, step_s: float = 6.0, asr_delay_s: float = 1.5, start_s: float = 0.0):
        t0 = start_s
        while t0 < self.duration_s + asr_delay_s:
            t1 = t0 + step_s
            words = [w for w in self.words if t0 < w.end + asr_delay_s <= t1]
            frames = [f for f in self.frames if t0 < f.t <= t1]
            yield Slice(t0, t1, words, frames)
            t0 = t1

    def words_between(self, a: float, b: float) -> list[Word]:
        return [w for w in self.words if a < w.end <= b]


def fmt_words(words: list[Word], base: float = 0.0) -> str:
    """Transcript lines with media timestamps, e.g. '[61.2s] do you guys think'. Groups words into ~4 s lines."""
    lines, cur, cur_t = [], [], None
    for w in words:
        if cur_t is None:
            cur_t = w.start
        cur.append(w.text)
        if w.end - cur_t >= 4.0:
            lines.append(f"[{cur_t - base:.1f}s] {' '.join(cur)}")
            cur, cur_t = [], None
    if cur:
        lines.append(f"[{cur_t - base:.1f}s] {' '.join(cur)}")
    return "\n".join(lines)
