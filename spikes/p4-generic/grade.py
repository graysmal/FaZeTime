#!/usr/bin/env python3
"""Grade a replay run against the coordinator's ground-truth labels. LOCAL FIXTURE ONLY.

  python3 -I spikes/p4-generic/grade.py RUN_DIR [GROUND_TRUTH_JSON]

RUN_DIR holds one sub-directory per fixture (verbose/, normal/), each with summary.json from replay.py.
Prints episodes (detected vs labelled), every market with the expected answer, and timing and latency checks.
Speech bets are graded against the full-file transcript of the fixture.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

MARGIN_S = 20  # void margin after lock (report's M; D39 sets the 35 s window)


def truth_episode(gt_eps: list[dict], start: float, end: float | None) -> dict | None:
    best, best_ov = None, 0.0
    for e in gt_eps:
        a, b = e["start_s"], e["end_s"] if e["end_s"] is not None else 1e9
        ov = min(b, end if end is not None else 1e9) - max(a, start)
        if ov > best_ov:
            best, best_ov = e, ov
    return best


def words(fixture_dir: Path) -> list[tuple[float, str]]:
    tr = json.loads((fixture_dir / "transcript.json").read_text())
    return [(w["end"], w["word"]) for s in tr["segments"] for w in (s.get("words") or [])]


def expected(m: dict, te: dict | None, fixture_dir: Path) -> tuple[str, str]:
    if te is None:
        return "?", "no labelled episode"
    end = te["end_s"]
    if m["template"] == "EPISODE_OUTCOME":
        if te["outcome"] == "UNFINISHED":
            return "VOID", "episode unfinished in the fixture"
        return ("YES" if te["outcome"] == "WON" else "NO"), f"labelled {te['outcome']} at {end}s"
    if m["template"] == "DURATION_OVER":
        if end is None:
            return "VOID", "episode unfinished"
        dur, d = end - te["start_s"], m["params"]["duration_s"]
        if abs(dur - d) <= 15:  # inside the duration void band: the system should void
            return "VOID", f"labelled duration {dur:.0f}s vs {d}s is inside the 15 s void band"
        return ("YES" if dur > d else "NO"), f"labelled duration {dur:.0f}s vs {d}s"
    if m["template"] == "SAY_PHRASE":
        ph = m["params"]["phrase"]
        pat = re.compile(r"\b" + r"\W+".join(map(re.escape, ph.split())) + r"(?:s|es|'s)?\b", re.I)
        lo, hi = m["close_at"] + MARGIN_S, end if end is not None else 1e9
        text = " ".join(w for t, w in words(fixture_dir) if lo < t <= hi)
        return ("YES" if pat.search(text) else "NO"), f"phrase in transcript ({lo:.0f}s, {hi:.0f}s]"
    return "?", "grade by hand (needs the labelled value)"


def main() -> None:
    run = Path(sys.argv[1])
    gt = json.loads(Path(sys.argv[2] if len(sys.argv) > 2 else
                         Path.home() / "fazetime-data/fixtures/peggle/ground_truth.json").read_text())
    totals = {"markets": 0, "correct": 0, "wrong": 0, "void_ok": 0, "void_missed_answer": 0, "ungraded": 0}
    for sub in sorted(p for p in run.iterdir() if (p / "summary.json").exists()):
        s = json.loads((sub / "summary.json").read_text())
        name = sub.name
        g = gt.get(name, {})
        fixture_dir = Path(s["fixture"])
        print(f"\n=== {name}  (observer served by {s.get('observer_served_by')}, flash calls {s.get('flash_calls')}, "
              f"wall {s.get('wall_s')} s)")
        print("episodes (detected -> labelled):")
        for e in s["episodes"]:
            te = truth_episode(g.get("episodes", []), e["start_t"], e["end_t"])
            lab = f"{te['id']} {te['start_s']}-{te['end_s']} {te['outcome']}" if te else "none"
            print(f"  #{e['idx']} {e['start_t']:.0f}-{e['end_t'] if e['end_t'] is None else round(e['end_t'])} "
                  f"{e['end_kind'] or 'open'}  ->  {lab}")
        print("markets:")
        for m in s["markets"]:
            totals["markets"] += 1
            ep_idx = None
            # the market's episode is the detected one that contains its proposal time
            for e in s["episodes"]:
                if e["start_t"] <= m["proposed_at"] and (e["end_t"] is None or m["proposed_at"] <= e["end_t"]):
                    ep_idx = e
            te = truth_episode(g.get("episodes", []), ep_idx["start_t"], ep_idx["end_t"]) if ep_idx else None
            exp, why = expected(m, te, fixture_dir)
            if (te and te.get("end_s") is not None and m["template"] != "SAY_PHRASE"
                    and te["end_s"] <= m["close_at"] + MARGIN_S):
                exp, why = "VOID", f"labelled end {te['end_s']}s is inside lock + {MARGIN_S}s (fairness void)"
            got = m["decision"]
            got_n = "VOID" if got == "UNRESOLVABLE" else got
            if exp == "?":
                verdict = "UNGRADED"
                totals["ungraded"] += 1
            elif got_n == exp:
                verdict = "CORRECT" if exp != "VOID" else "VOID_OK"
                totals["correct" if exp != "VOID" else "void_ok"] += 1
            elif got_n == "VOID":
                verdict = "VOID_BUT_ANSWERABLE"
                totals["void_missed_answer"] += 1
            else:
                verdict = "WRONG"
                totals["wrong"] += 1
            fair = ""
            if te and te.get("end_s") is not None:
                lead = te["end_s"] - m["close_at"]
                fair = f" outcome {lead:+.0f}s after lock" + (" (TOO EARLY: inside margin)" if lead < MARGIN_S else "")
            lat = ""
            if m.get("decided_at") and te and te.get("end_s") is not None and got_n in ("YES", "NO"):
                lat = f" settled {m['decided_at'] - te['end_s']:+.0f}s after the labelled end"
            print(f"  {m['mid']} [{m['template']}] {m['question']!r} p_yes={m['p_yes']}\n"
                  f"      proposed {m['proposed_at']:.0f}s, published {m['published_at']:.1f}s, "
                  f"closed {m['close_at']:.1f}s; got {got} at {m['decided_at'] or 0:.1f}s; expected {exp} ({why})\n"
                  f"      => {verdict};{fair};{lat}\n      reason: {m['decision_reason'][:150]}")
    print("\nTOTALS", json.dumps(totals))


if __name__ == "__main__":
    main()
