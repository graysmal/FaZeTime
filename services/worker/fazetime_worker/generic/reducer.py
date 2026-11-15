"""Code-owned game state for the generic profile (D37), ported from ``spikes/p4-generic/generic.py``.

State lives in code, not in model memory. Every observer answer is one observation; ``Reducer.apply`` is the
**only writer** of state. It runs the episode state machine (none -> IN_PROGRESS -> ENDED / ENDED_UNKNOWN),
keeps the activity and unit votes, and per-episode histories of named on-screen numbers. All times are media
milliseconds within one source epoch; a new epoch gets a new Reducer (the AI runtime does that).

Episode ends come from: a result screen or an "ended" boundary (RESULT_SEEN); two consecutive away-from-game
observations (LEFT_GAMEPLAY); a rising number such as a score falling back near zero, or a "started" boundary
more than 30 s into an episode (NEW_START). Model answers are untrusted data: only enumerated fields and parsed
numbers change state, and every list is bounded.
"""
from __future__ import annotations

import re
from collections import Counter, deque
from dataclasses import dataclass, field

SCREENS = ["gameplay", "menu", "loading", "result_screen", "transition", "non_game", "unclear"]
UNITS = ["game", "match", "round", "level", "race", "hand", "run", "fight", "other"]
AWAY_SCREENS = ("menu", "loading", "non_game")

MIN_EPISODE_MS_FOR_RESET = 30_000  # a score reset or "started" hint only splits an episode older than this
MIN_PRIOR_DURATION_MS = 20_000  # earlier episodes shorter than this are ignored by prior_duration_ms()
MAX_EPISODES = 50
MAX_READS_PER_LABEL = 60
MAX_LABELS = 16
MAX_RESULTS = 20
MAX_POPUPS = 20

_NUM = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def parse_number(value) -> float | None:
    """'1:05' -> 65 seconds; '10,835,540' -> 10835540; '3 balls' -> 3. None if no single clear number."""
    v = str(value or "").strip()
    m = re.fullmatch(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", v)
    if m:
        a, b, c = m.groups()
        return float(int(a) * 3600 + int(b) * 60 + int(c)) if c else float(int(a) * 60 + int(b))
    found = _NUM.findall(v)
    if len(found) != 1:
        return None
    try:
        return float(found[0].replace(",", ""))
    except ValueError:
        return None


def norm_label(label) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", "", str(label or "").lower())).strip()


@dataclass
class Episode:
    idx: int
    unit: str
    start_ms: int
    phase: str = "IN_PROGRESS"  # IN_PROGRESS | ENDED | ENDED_UNKNOWN
    end_ms: int | None = None
    end_kind: str = ""  # RESULT_SEEN | LEFT_GAMEPLAY | NEW_START
    end_frame_ms: list = field(default_factory=list)  # frames of the observation that ended it
    numbers: dict = field(default_factory=dict)  # label -> [(t_ms, raw, parsed)]
    results: list = field(default_factory=list)  # (t_ms, outcome_text, outcome_for_streamer)
    popups: list = field(default_factory=list)  # (t_ms, text)
    markets: int = 0  # markets proposed for this episode (proposer cap 2)
    proposer_calls: int = 0  # proposer model calls for this episode (cap 3)
    last_proposer_ms: int = -10 ** 12

    @property
    def ended(self) -> bool:
        return self.phase != "IN_PROGRESS"

    def add_number(self, t_ms: int, label: str, raw: str, val: float | None):
        if label not in self.numbers and len(self.numbers) >= MAX_LABELS:
            return
        reads = self.numbers.setdefault(label, [])
        reads.append((t_ms, str(raw)[:24], val))
        del reads[:-MAX_READS_PER_LABEL]

    def reads(self, label: str) -> list:
        return [r for r in self.numbers.get(norm_label(label), []) if r[2] is not None]

    def number_summary(self, max_items: int = 8) -> list[dict]:
        out = []
        for label, reads in self.numbers.items():
            vals = [r for r in reads if r[2] is not None]
            if not vals:
                continue
            t, raw, _ = vals[-1]
            out.append({"label": label, "last": raw, "last_at_s": round(t / 1000), "reads": len(vals)})
        out.sort(key=lambda d: -d["reads"])
        return out[:max_items]


def _s(ms: int | float) -> str:
    return f"{ms / 1000:.0f}s"


class Reducer:
    """One per source epoch. ``apply`` is the only state writer; everything else reads."""

    def __init__(self, epoch: str | None = None):
        self.epoch = epoch
        self.episodes: list[Episode] = []
        self.cur: Episode | None = None
        self.activity_votes: Counter = Counter()
        self.unit_votes: Counter = Counter()
        self.gameplay_run: list[int] = []
        self.away_streak = 0
        self.last_template: str | None = None  # the previous market's kind (no repeats in a row)
        self.last_t_ms: int | None = None  # media time of the newest applied observation
        self.n_obs = 0
        self.recent: deque = deque(maxlen=20)  # (t_ms, screen, boundary): status/debug only, no free text
        self._next_idx = 1

    # ---- reads ----------------------------------------------------------------------------------------
    def prior_duration_ms(self) -> int | None:
        """Median duration of earlier episodes in this epoch whose end was seen."""
        ds = sorted(e.end_ms - e.start_ms for e in self.episodes
                    if e.end_ms is not None and e is not self.cur and e.end_ms - e.start_ms > MIN_PRIOR_DURATION_MS)
        return ds[len(ds) // 2] if ds else None

    def find(self, start_ms: int) -> Episode | None:
        return next((e for e in reversed(self.episodes) if e.start_ms == start_ms), None)

    @property
    def activity(self) -> str:
        return self.activity_votes.most_common(1)[0][0] if self.activity_votes else "unknown"

    @property
    def unit(self) -> str:
        if not self.unit_votes:
            return "game"
        u = self.unit_votes.most_common(1)[0][0]
        return "game" if u == "other" else u

    def in_progress(self) -> bool:
        return self.cur is not None and self.cur.phase == "IN_PROGRESS"

    def snapshot(self, now_ms: int) -> str:
        e = self.cur
        lines = [f"activity: {self.activity}; unit of play: {self.unit}"]
        if e is None:
            lines.append("episode: none seen yet")
        else:
            lines.append(f"episode #{e.idx}: {e.phase}, started at {_s(e.start_ms)}"
                         + (f", ended at {_s(e.end_ms)} ({e.end_kind})" if e.end_ms is not None else
                            f", running for {_s(now_ms - e.start_ms)}"))
            prior = self.prior_duration_ms()
            if prior:
                lines.append(f"earlier units of play in this stream lasted about {_s(prior)}")
            ns = e.number_summary(6)
            if ns:
                lines.append("numbers last read: " + "; ".join(f"{d['label']}={d['last']} @{d['last_at_s']}s"
                                                                for d in ns))
        return "\n".join(lines)

    # ---- the only writer --------------------------------------------------------------------------------
    def _new_episode(self, start_ms: int, o: dict, t_ms: int) -> Episode:
        ep = Episode(idx=self._next_idx, unit=self.unit, start_ms=int(start_ms))
        self._next_idx += 1
        self.episodes.append(ep)
        del self.episodes[:-MAX_EPISODES]
        self.cur = ep
        for n in _numbers(o):
            ep.add_number(t_ms, n[0], n[1], parse_number(n[1]))
        self.gameplay_run, self.away_streak = [], 0
        return ep

    @staticmethod
    def _reset(reads: list, new_val: float | None) -> bool:
        """A number that kept rising (a score) suddenly falls back near zero: a new unit of play began."""
        vals = [r[2] for r in reads if r[2] is not None]
        if new_val is None or len(vals) < 3:
            return False
        rising = all(b >= a for a, b in zip(vals[-3:], vals[-2:]))
        top = max(vals)
        return rising and top >= 100 and new_val <= 0.1 * top

    def apply(self, o: dict, t_ms: int, frame_ms: list) -> list[str]:
        """Apply one observer answer at media time ``t_ms`` (its newest frame). Returns state events."""
        ev: list[str] = []
        t_ms = int(t_ms)
        prev_t = self.last_t_ms if self.last_t_ms is not None else t_ms
        self.last_t_ms = t_ms if self.last_t_ms is None else max(t_ms, self.last_t_ms)
        self.n_obs += 1
        screen = o.get("screen") if o.get("screen") in SCREENS else "unclear"
        boundary = o.get("boundary") if o.get("boundary") in ("none", "started", "ended") else "none"
        self.recent.append((t_ms, screen, boundary))
        act = str(o.get("activity") or "").strip()[:60]
        if act and act.lower() not in ("unknown", "unclear", "none"):
            self.activity_votes[act] += 1
            if len(self.activity_votes) > 20:
                self.activity_votes = Counter(dict(self.activity_votes.most_common(10)))
        if o.get("episode_unit") in UNITS:
            self.unit_votes[o["episode_unit"]] += 1
        out_text = str(o.get("outcome_text") or "").strip()[:120]
        out_kind = o.get("outcome_for_streamer")
        has_result = bool(out_text) or out_kind in ("success", "failure")
        ended_signal = screen == "result_screen" or boundary == "ended"
        frames = sorted(int(x) for x in (frame_ms or []))
        e = self.cur

        if e is not None and e.phase == "IN_PROGRESS":
            reset = False
            for label, raw in _numbers(o):
                val = parse_number(raw)
                if t_ms - e.start_ms > MIN_EPISODE_MS_FOR_RESET and self._reset(e.numbers.get(label, []), val):
                    reset = True
                    break
                e.add_number(t_ms, label, raw, val)
            if reset:
                e.phase, e.end_ms, e.end_kind = "ENDED_UNKNOWN", prev_t, "NEW_START"
                ev.append("EPISODE_ENDED")
                self._new_episode(t_ms, o, t_ms)
                ev.append("EPISODE_STARTED")
                return ev
            for p in o.get("popup_text") or []:
                if isinstance(p, str) and p.strip() and len(e.popups) < MAX_POPUPS:
                    e.popups.append((t_ms, p.strip()[:60]))
            if has_result and len(e.results) < MAX_RESULTS:
                e.results.append((t_ms, out_text, out_kind))
            if ended_signal:
                e.phase, e.end_ms, e.end_kind = "ENDED", t_ms, "RESULT_SEEN"
                ev.append("EPISODE_ENDED")
            elif screen in AWAY_SCREENS:
                self.away_streak += 1
                if self.away_streak >= 2:
                    e.phase, e.end_ms, e.end_kind = "ENDED_UNKNOWN", t_ms, "LEFT_GAMEPLAY"
                    ev.append("EPISODE_ENDED")
            else:
                self.away_streak = 0
            if boundary == "started" and e.phase == "IN_PROGRESS" and t_ms - e.start_ms > MIN_EPISODE_MS_FOR_RESET:
                e.phase, e.end_ms, e.end_kind = "ENDED_UNKNOWN", t_ms, "NEW_START"
                ev.append("EPISODE_ENDED")
            if e.phase != "IN_PROGRESS":
                e.end_frame_ms = frames
                self.gameplay_run = []
            return ev

        # no episode in progress: keep collecting result evidence for an ended one, and look for a new start
        if e is not None and has_result and len(e.results) < MAX_RESULTS:
            e.results.append((t_ms, out_text, out_kind))
        if screen == "gameplay" and not ended_signal:
            self.gameplay_run.append(t_ms)
            if len(self.gameplay_run) >= 2 or boundary == "started":
                # the first gameplay frame of the run is the earliest the new unit was seen
                start = min(self.gameplay_run[0], frames[0] if frames else t_ms)
                self._new_episode(start, o, t_ms)
                ev.append("EPISODE_STARTED")
        else:
            self.gameplay_run = []
        return ev


def _numbers(o: dict) -> list[tuple[str, str]]:
    out = []
    for n in (o.get("numbers") or [])[:12]:
        if not isinstance(n, dict):
            continue
        label = norm_label(n.get("label", ""))[:40]
        if label:
            out.append((label, str(n.get("value", ""))[:24]))
    return out
