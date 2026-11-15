"""Summarise the full-length streaming runs (all P0-B epochs). Prints counts and variants only."""
import json
import re
import sys
from collections import Counter
from pathlib import Path

root = Path(sys.argv[1])
PREFIX = r"(?:faze|face|phase|fase|fays|faiz|phrase)"
ALIAS = {"FaZeGavin": re.compile(rf"\b(?:{PREFIX}[\s,.\-]*)?gav[iey]n\b", re.I),
         "FaZeNeville": re.compile(rf"\b(?:{PREFIX}[\s,.\-]*)?nev(?:i|e)l(?:l|le|e)?\b", re.I)}
VAR = {"FaZeGavin": re.compile(r"\b(\w+[\s,.\-]+)?gav[iey]n\b", re.I),
       "FaZeNeville": re.compile(r"\b(\w+[\s,.\-]+)?nev(?:i|e)l(?:l|le|e)?\b", re.I)}
agg = {}
for ep_dir in sorted(p for p in root.iterdir() if p.is_dir()):
    summ = json.loads((ep_dir / "summary.json").read_text())
    for run in summ["runs"]:
        name = run["config"]["name"]
        s = run["stream"]
        tr = json.loads((ep_dir / f"transcript_{name}.json").read_text())["stream"]
        a = agg.setdefault(name, {"windows": 0, "speech": 0, "proc": [], "missed": 0, "media_s": 0.0,
                                  "alias": Counter(), "exact": Counter(), "variants": {k: Counter() for k in ALIAS}})
        a["windows"] += s["chunks"]
        a["speech"] += s["speech_chunks"]
        a["missed"] += s["deadline_missed_over_hop"]
        a["media_s"] += s["chunks"] * 3.0
        a["proc"].append((s["proc_p50_s"], s["proc_p95_s"], s["proc_max_s"], s["duty"], s["chunks"]))
        for c in tr:
            t = c["text"]
            for k, rx in ALIAS.items():
                if rx.search(t):
                    a["alias"][k] += 1
                if k.lower() in t.lower():
                    a["exact"][k] += 1
                for m in VAR[k].finditer(t):
                    a["variants"][k][m.group(0).lower().strip()] += 1
for name, a in agg.items():
    duty = sum(p[3] * p[4] for p in a["proc"]) / a["windows"]
    print(f"{name}: windows {a['windows']} speech {a['speech']} media {a['media_s']:.0f}s duty(weighted) {duty:.3f} "
          f"per-epoch p95 {[p[1] for p in a['proc']]} max {[p[2] for p in a['proc']]} over-hop {a['missed']}")
    for k in ALIAS:
        print(f"   {k}: windows with alias match {a['alias'][k]}, exact spelling {a['exact'][k]}, "
              f"variants {a['variants'][k].most_common(8)}")
