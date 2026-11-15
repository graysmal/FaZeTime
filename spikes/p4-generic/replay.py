#!/usr/bin/env python3
"""Causal replay of a prepared fixture through the game-agnostic observer -> proposer -> resolver loop (D37).

LOCAL FIXTURE ONLY: this is a quality test, never the Twitch ingestion gate. Nothing is posted to the API.
Writes <run_dir>/calls.jsonl (every model request), events.jsonl and summary.json.

  services/worker/.venv/bin/python -I spikes/p4-generic/replay.py FIXTURE_DIR RUN_DIR [--step 6]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I mode does not add the script dir

import generic as g  # noqa: E402
from fixture import Fixture
from llm import SYSTEM_RULES, Llm

ASR_DELAY_S = 1.5
CLOSE_S = g.BET_WINDOW_S  # D39: 35 s (the API still enforces its old 45 s floor until integration)
CUE_RE = re.compile(r"\b(do you (guys )?think|you think i|bet on|will i|can i|chat,? (do|should|will))\b", re.I)


def handles_for(words, base_label="T") -> tuple[str, set[str]]:
    lines, cur, cur_t, hs = [], [], None, set()
    for w in words:
        if cur_t is None:
            cur_t = w.start
        cur.append(w.text)
        if w.end - cur_t >= 4.0:
            h = f"{base_label}{len(lines) + 1}"
            lines.append(f"{h} [{cur_t:.0f}s] {' '.join(cur)}")
            hs.add(h)
            cur, cur_t = [], None
    if cur:
        h = f"{base_label}{len(lines) + 1}"
        lines.append(f"{h} [{cur_t:.0f}s] {' '.join(cur)}")
        hs.add(h)
    return "\n".join(lines), hs


def frames_at(fx: Fixture, times: list[float]) -> list:
    out, seen = [], set()
    for t in times:
        f = fx.frame_at(t)
        if f is not None and f.t not in seen:
            seen.add(f.t)
            out.append(f)
    return sorted(out, key=lambda f: f.t)


class Replay:
    def __init__(self, fx: Fixture, run_dir: Path, step: float, flash_cap: int, observer: str = "flash"):
        self.fx, self.step, self.flash_cap = fx, step, flash_cap
        self.L = Llm(run_dir, budget=400, min_interval_s=4.2)
        self.red = g.Reducer()
        self.markets: list[g.Market] = []
        self.flash_calls = 0
        self.ev = (run_dir / "events.jsonl").open("w")
        self.run_dir = run_dir
        self.last_obs = None
        # Default observer: gemini-3.1-flash-lite (about 1.7 s). Gemma 4 first is opt-in: a large quota, but HTTP 500
        # on about half its calls on 2026-11-15, which adds a failed attempt to many slices.
        self.observer_chain = ([g.OBSERVER_MODEL, "gemini-3.1-flash-lite"] if observer == "gemma-first"
                               else ["gemini-3.1-flash-lite"])
        self.served: dict[str, int] = {}
        self.last_obs_latency_s = 0.0

    def emit(self, kind: str, t: float, **kw):
        rec = {"kind": kind, "t": round(t, 1), **kw}
        self.ev.write(json.dumps(rec) + "\n")
        self.ev.flush()
        short = {k: v for k, v in kw.items() if k in ("question", "decision", "reason", "code", "episode", "end_kind",
                                                      "template", "screen", "activity", "outcome", "cue", "p_yes")}
        print(f"[{t:6.1f}s] {kind} {json.dumps(short)[:300]}", flush=True)

    @property
    def active(self) -> g.Market | None:
        return next((m for m in self.markets if m.state in ("OPEN", "LOCKED")), None)

    # -------------------------------------------------------------------------------------------- observer
    def observe(self, sl):
        frames = frames_at(self.fx, [sl.t1 - 3, sl.t1])
        transcript, _ = handles_for(sl.words)
        prompt = g.observer_prompt(self.red.snapshot(sl.t1), transcript, [f.t for f in frames])
        parts = [("image", f.jpeg(), "image/jpeg") for f in frames]
        served = None
        o = None
        self.last_obs_latency_s = 0.0
        if self.observer_chain[0].startswith("gemma"):
            # one attempt only: the Gemma 4 API returns frequent HTTP 500s; skip it while its gate cools down
            o = self.L.call(role="observer", model=self.observer_chain[0], media_t=sl.t1, task=prompt, parts=parts,
                            schema=g.OBS_SCHEMA, media_resolution=None, system=None, tpm_cap=14000,
                            wait_cooldown_s=0)
            served = self.observer_chain[0] if o is not None else None
        if o is None:
            fb = self.observer_chain[-1]
            o = self.L.call(role="observer", model=fb, media_t=sl.t1, task=prompt, parts=parts, schema=g.OBS_SCHEMA,
                            media_resolution="medium", system=None, wait_cooldown_s=35)
            served = fb if o is not None else None
        if o is None:
            self.emit("OBSERVER_MISS", sl.t1)
            return
        self.served[served] = self.served.get(served, 0) + 1
        self.last_obs = o
        self.last_obs_latency_s = (o.get("_latency_ms") or 0) / 1000
        evs = self.red.apply(o, sl.t1, [f.t for f in frames])
        self.emit("OBS", sl.t1, screen=o.get("screen"), activity=o.get("activity"), boundary=o.get("boundary"),
                  outcome=o.get("outcome_for_streamer"), outcome_text=o.get("outcome_text"),
                  numbers=o.get("numbers"), popups=o.get("popup_text"), cue=o.get("streamer_cue"),
                  latency_ms=o.get("_latency_ms"))
        for e in evs:
            ep = self.red.cur
            self.emit(e, sl.t1, episode=ep.idx if ep else None, start_t=ep.start_t if ep else None,
                      end_kind=ep.end_kind if ep else None, unit=self.red.unit, activity=self.red.activity)

    # -------------------------------------------------------------------------------------------- proposer
    def maybe_propose(self, now: float):
        e = self.red.cur
        if self.active is not None or e is None or e.phase != "IN_PROGRESS":
            return
        if e.markets >= 2 or e.proposer_calls >= 3 or now - e.last_proposer_t < 30:
            return
        recent = self.fx.words_between(now - 90 - ASR_DELAY_S, now - ASR_DELAY_S)
        recent_text = " ".join(w.text for w in recent)
        cue = (self.last_obs or {}).get("streamer_cue") or ""
        spoken_cue = bool(CUE_RE.search(" ".join(w.text for w in self.fx.words_between(now - 20, now - ASR_DELAY_S))))
        if now - e.start_t < (6 if (cue or spoken_cue) else 10):
            return
        if self.flash_calls >= self.flash_cap:
            return
        transcript, handles = handles_for(recent)
        frames = frames_at(self.fx, [now - 16, now - 8, now])
        handles |= {f"F{i + 1}" for i in range(len(frames))}
        prompt = g.proposer_prompt(self.red, now, transcript, [f.t for f in frames], CLOSE_S, cue)
        e.proposer_calls += 1
        e.last_proposer_t = now
        self.flash_calls += 1
        p = self.L.call(role="proposer", model=g.PROPOSER_MODEL, media_t=now, task=prompt,
                        parts=[("image", f.jpeg(), "image/jpeg") for f in frames], schema=g.PROP_SCHEMA,
                        media_resolution="low", system=SYSTEM_RULES)
        if p is None:
            self.emit("PROPOSER_ERROR", now)
            return
        # pipeline delay before viewers see the market: this slice's observer call plus the proposer call
        latency_s = self.last_obs_latency_s + (p.get("_latency_ms") or 0) / 1000
        code = g.check_proposal(p, self.red, now, CLOSE_S, handles, recent_text)
        if code:
            self.emit("PROPOSAL_REJECTED", now, code=code, template=p.get("template"), p_yes=p.get("p_yes"),
                      reason=p.get("reason"), raw={k: p.get(k) for k in ("win_verb", "number_label", "threshold",
                                                                          "phrase", "duration_s",
                                                                          "seconds_to_outcome")})
            return
        m = g.render_market(p, self.red, f"m{len(self.markets) + 1}", now, latency_s, CLOSE_S)
        e.markets += 1
        self.markets.append(m)
        self.red.last_template = m.template
        self.emit("PROPOSED", now, mid=m.mid, template=m.template, question=m.question, yes=m.yes_rule, no=m.no_rule,
                  params=m.params, p_yes=m.p_yes, pipeline_latency_s=round(latency_s, 2),
                  published_at=round(m.published_at, 1),
                  close_at=round(m.close_at, 1), resolve_by=round(m.resolve_by, 1), success_cue=m.success_cue,
                  failure_cue=m.failure_cue, reason=m.reason, cue=cue)

    # -------------------------------------------------------------------------------------------- resolver
    def settle(self, m: g.Market, now: float, decision: str, reason: str):
        m.decision, m.decided_at, m.decision_reason = decision, now, reason
        m.state = "VOID" if decision == "UNRESOLVABLE" else "RESOLVED"
        self.emit("RESOLVED", now, mid=m.mid, question=m.question, decision=decision, reason=reason)

    def resolve_step(self, now: float):
        m = self.active
        if m is None:
            return
        if m.state == "OPEN":
            if now < m.close_at:
                return
            m.state = "LOCKED"
            self.emit("LOCKED", now, mid=m.mid)
        ep = self.red.episodes[m.episode_idx - 1]
        margin = g.OUTCOME_MARGIN_S
        if ep.end_t is not None and ep.end_t <= m.close_at + margin:
            return self.settle(m, now, "UNRESOLVABLE",
                               f"RESULT_BEFORE_LOCK: unit ended at {ep.end_t:.0f}s, lock {m.close_at:.0f}s + {margin}s")
        if now >= m.resolve_by:
            return self.settle(m, now, "UNRESOLVABLE", "RESOLUTION_TIMEOUT")
        ended = ep.phase != "IN_PROGRESS"
        if m.template == "SAY_PHRASE":
            upto = min(now - ASR_DELAY_S, ep.end_t if ended else 1e9)
            early = g.speech_hit(self.fx, m.params["phrase"], m.close_at, min(upto, m.close_at + margin))
            if early:
                return self.settle(m, now, "UNRESOLVABLE", f"RESULT_BEFORE_LOCK: phrase at {early[0]:.0f}s")
            hit = g.speech_hit(self.fx, m.params["phrase"], m.close_at + margin, upto)
            if hit:
                return self.settle(m, now, "YES", f"transcript at {hit[0]:.0f}s: ...{hit[1]}...")
            if ended and now - ASR_DELAY_S >= ep.end_t:
                return self.settle(m, now, "NO", f"{m.unit} ended at {ep.end_t:.0f}s without the phrase")
            return
        if m.template == "DURATION_OVER":
            d, unc = m.params["duration_s"], g.DURATION_BAND_S
            if not ended and now - ep.start_t > d + unc:
                return self.settle(m, now, "YES", f"still running {now - ep.start_t:.0f}s after start")
            if ended:
                dur = ep.end_t - ep.start_t
                if ep.end_kind != "RESULT_SEEN":
                    return self.settle(m, now, "UNRESOLVABLE", f"end not clearly seen ({ep.end_kind})")
                if abs(dur - d) <= unc:
                    return self.settle(m, now, "UNRESOLVABLE", f"duration {dur:.0f}s within +/-{unc:.0f}s of line")
                return self.settle(m, now, "YES" if dur > d else "NO", f"duration {dur:.0f}s vs {d}s")
            return
        # visual templates: two independent extraction reads after the end, code decides
        if not ended or now < ep.end_t + self.step or len(m.reads) >= 4:
            return
        if m.reads and now < m.reads[-1]["t"] + 2 * self.step:
            return
        label = m.params.get("label")
        tr_words = self.fx.words_between(ep.end_t - 20, now - ASR_DELAY_S)
        transcript, _ = handles_for(tr_words)
        # result banners often appear in the last seconds of play, before any result screen
        sets = ([ep.end_t - 12, ep.end_t - 8, ep.end_t - 4, ep.end_t, ep.end_t + 3, now],
                [ep.end_t - 10, ep.end_t - 6, ep.end_t - 2, ep.end_t + 1, now - 1])
        jobs = []
        for model, times in zip(g.RESOLVER_MODELS, sets):
            if self.flash_calls >= self.flash_cap:
                break
            frames = frames_at(self.fx, [t for t in times if t <= now])
            prompt = g.read_prompt(m.unit, label, transcript, [f.t for f in frames])
            self.flash_calls += 1
            jobs.append((model, frames, prompt))
        # the two independent reads run in parallel (different models, separate quotas)
        with ThreadPoolExecutor(max_workers=2) as ex:
            futs = [ex.submit(self.L.call, role="resolver", model=model, media_t=now, task=prompt,
                              parts=[("image", f.jpeg(), "image/jpeg") for f in frames], schema=g.READ_SCHEMA,
                              media_resolution=None, system=SYSTEM_RULES) for model, frames, prompt in jobs]
            reads = [f.result() for f in futs]
        read_latency_s = max([((r or {}).get("_latency_ms") or 0) / 1000 for r in reads] or [0])
        for (model, frames, _), r in zip(jobs, reads):
            self.emit("READ", now, mid=m.mid, model=model, frames=[f.t for f in frames],
                      latency_ms=(r or {}).get("_latency_ms"),
                      read={k: (r or {}).get(k) for k in ("result_text", "outcome_for_streamer", "value_text",
                                                          "contradictions")})
        m.reads.append({"t": now, "reads": reads})
        decision, reason = g.decide_visual(m, reads)
        if decision != "WAIT":
            return self.settle(m, now + read_latency_s, decision, reason)
        self.emit("WAIT", now, mid=m.mid, reason=reason)

    # -------------------------------------------------------------------------------------------- loop
    def run(self):
        t0 = time.time()
        for sl in self.fx.slices(step_s=self.step, asr_delay_s=ASR_DELAY_S):
            now = sl.t1
            if now > self.fx.duration_s + self.step:
                break
            self.observe(sl)
            self.resolve_step(now)
            self.maybe_propose(now)
        end_t = self.fx.duration_s + ASR_DELAY_S
        for m in self.markets:
            if m.state in ("OPEN", "LOCKED"):
                self.settle(m, end_t, "UNRESOLVABLE", "STREAM_ENDED (fixture ended before resolution)")
        summary = {
            "fixture": str(self.fx.root), "asr": self.fx.asr_model, "step_s": self.step,
            "wall_s": round(time.time() - t0, 1),
            "episodes": [{"idx": e.idx, "unit": e.unit, "start_t": e.start_t, "end_t": e.end_t, "phase": e.phase,
                          "end_kind": e.end_kind, "results": e.results[:6], "numbers": e.number_summary(6),
                          "popups": e.popups[:12]} for e in self.red.episodes],
            "activity_votes": self.red.activity_votes.most_common(5),
            "unit_votes": self.red.unit_votes.most_common(5),
            "markets": [{k: getattr(m, k) for k in ("mid", "template", "question", "yes_rule", "no_rule", "params",
                                                     "p_yes", "proposed_at", "published_at", "close_at",
                                                     "resolve_by", "state", "decision", "decided_at",
                                                     "decision_reason", "success_cue", "failure_cue", "reason")}
                        for m in self.markets],
            "flash_calls": self.flash_calls,
            "observer_served_by": self.served,
            "llm": self.L.summary(),
        }
        (self.run_dir / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
        print(json.dumps({k: summary[k] for k in ("episodes", "markets", "flash_calls", "observer_served_by",
                                                  "wall_s")}, indent=1, default=str)[:6000])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("fixture", type=Path)
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--step", type=float, default=6.0)
    ap.add_argument("--flash-cap", type=int, default=24, help="max proposer+resolver requests this replay may use")
    ap.add_argument("--observer", choices=["flash", "gemma-first"], default="flash")
    a = ap.parse_args()
    a.run_dir.mkdir(parents=True, exist_ok=True)
    Replay(Fixture(a.fixture), a.run_dir, a.step, a.flash_cap, a.observer).run()


if __name__ == "__main__":
    main()
