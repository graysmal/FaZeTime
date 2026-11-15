#!/usr/bin/env python3
"""Full-stream soak through the DEPLOYED service (D34): every epoch of the team P0-B capture, 4 s windows with a
3 s hop, sent back-to-back over HTTP with the same headers the worker client sends. Run on the VM as root:

  grep '^ASR_REMOTE_TOKEN=' /etc/fazetime-asr.env | python -I service_stream.py URL AUDIO_DIR NAMES_PY

Prints timings and name counts only (never transcript text). Uses the same 2.4 compression-ratio filter as the
worker by reading the server's `text` (which already excludes repetitive segments).
"""
from __future__ import annotations

import http.client
import importlib.util
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vm_bench import HOP_S, SR, WIN_S, load_epochs, pctl  # noqa: E402


def main():
    url, audio_dir, names_py = urlsplit(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    token = sys.stdin.readline().strip().split("=", 1)[-1]
    spec = importlib.util.spec_from_file_location("names", names_py)
    names = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(names)
    conn = http.client.HTTPConnection(url.hostname, url.port, timeout=10)
    win, hop = WIN_S * SR * 2, HOP_S * SR * 2
    rtt, comp, statuses = [], [], {}
    alias_windows = {"FaZeGavin": 0, "FaZeNeville": 0}
    exact = {"FaZeGavin": 0, "FaZeNeville": 0}
    filtered, windows, per_epoch = 0, 0, {}
    for ep, pcm in sorted(load_epochs(audio_dir).items()):
        ep_comp = []
        for i, s in enumerate(range(0, len(pcm) - win + 1, hop)):
            t = time.perf_counter()
            conn.request("POST", "/v1/transcribe", body=pcm[s:s + win],
                         headers={"Authorization": f"Bearer {token}", "Content-Type": "application/octet-stream",
                                  "X-Source-Epoch": ep, "X-Sequence": str(i),
                                  "X-Media-Start-Ms": str(s // 2 * 1000 // SR)})
            r = conn.getresponse()
            body = r.read()
            el = time.perf_counter() - t
            statuses[r.status] = statuses.get(r.status, 0) + 1
            windows += 1
            if r.status != 200:
                conn.close()
                conn = http.client.HTTPConnection(url.hostname, url.port, timeout=10)
                continue
            o = json.loads(body)
            rtt.append(el)
            comp.append(o["compute_ms"] / 1000)
            ep_comp.append(o["compute_ms"] / 1000)
            filtered += int(o["filtered_repetitive"] > 0)
            for k, v in names.find_names(o["text"]).items():
                alias_windows[k] += int(v > 0)
            low = o["text"].lower()
            exact["FaZeGavin"] += len(re.findall(r"\bfazegavin\b", low))
            exact["FaZeNeville"] += len(re.findall(r"\bfazeneville\b", low))
        per_epoch[ep] = {"windows": len(ep_comp), "p95_s": pctl(ep_comp, .95), "max_s": round(max(ep_comp), 3)}
    print(json.dumps({"windows": windows, "statuses": statuses, "rtt_p50_s": pctl(rtt, .5), "rtt_p95_s": pctl(rtt, .95),
                      "compute_p50_s": pctl(comp, .5), "compute_p95_s": pctl(comp, .95),
                      "compute_max_s": round(max(comp), 3), "duty": round(sum(comp) / (len(comp) * HOP_S), 3),
                      "windows_over_hop": sum(c > HOP_S for c in comp), "windows_over_1s": sum(c > 1.0 for c in comp),
                      "per_epoch": per_epoch, "repetition_filtered_windows": filtered,
                      "names_alias_windows": alias_windows, "names_exact_tokens": exact}))


if __name__ == "__main__":
    main()
