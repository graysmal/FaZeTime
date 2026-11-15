#!/usr/bin/env python3
"""P0-B team-channel ASR bench (Step A of P3). Runs on the Pi against the P0-B capture chunks.

Input: the capture_spike audio ring (a_<epoch8>_<start_ms>.wav, 16 kHz mono s16) of the
TEAM channel. Each config runs in its own child process (peak RSS per config).

Per config:
  * whole-file: every epoch's audio transcribed long-form -> RTF + name statistics;
  * streaming: an excerpt cut into 4 s chunks with 1 s overlap (hop 3 s), one sequential
    worker; latency includes queueing; a drop policy (skip a chunk that waited longer than
    --max-queue-wait-s) is also simulated, as the P3 worker would do instead of growing a backlog.

Transcripts are the team's own stream; they are written only to --out-dir (gitignored/out on the
Pi). The summary JSON contains counts, variants and at most short name-matching snippets.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import resource
import subprocess
import sys
import time
import wave
from collections import Counter, defaultdict
from pathlib import Path

SR = 16000
NAMES = {"FaZeGavin": "gavin", "FaZeNeville": "neville"}


def temp_c():
    try:
        return int(open("/sys/class/thermal/thermal_zone0/temp").read()) / 1000
    except OSError:
        return None


def throttled():
    try:
        return subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return None


def loadavg():
    return [float(x) for x in open("/proc/loadavg").read().split()[:3]]


def pctl(xs, q):
    if not xs:
        return None
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo), 3)


def load_epochs(audio_dir: Path):
    import numpy as np
    groups = defaultdict(list)
    for f in audio_dir.glob("a_*_*.wav"):
        _, ep, start = f.stem.split("_")
        groups[ep].append((int(start), f))
    out = {}
    for ep, files in groups.items():
        files.sort()
        parts, expect = [], 0
        for start, f in files:
            if start != expect:
                raise SystemExit(f"non-contiguous chunks in {ep}: expected {expect} got {start}")
            with wave.open(str(f), "rb") as w:
                assert w.getframerate() == SR and w.getnchannels() == 1 and w.getsampwidth() == 2
                pcm = w.readframes(w.getnframes())
            parts.append(np.frombuffer(pcm, dtype="<i2"))
            expect = start + len(parts[-1]) * 1000 // SR
        out[ep] = np.concatenate(parts).astype(np.float32) / 32768.0
    return out


def name_stats(texts):
    """Classify name mentions. Returns counts of exact spellings and variant forms."""
    joined = " \n ".join(texts)
    low = joined.lower()
    res = {}
    for canon, base in NAMES.items():
        exact = len(re.findall(r"\b" + canon.lower() + r"\b", low))
        exact_case = len(re.findall(r"\b" + canon + r"\b", joined))
        split = len(re.findall(r"\bfaze[\s\-]+" + base + r"\b", low))
        variants = Counter()
        # any token close to the base name, with the preceding token
        toks = re.findall(r"[a-z0-9']+", low)
        for i, t in enumerate(toks):
            hit = None
            if base in t and t != "faze" + base:
                hit = t
            elif _edit(t, base) <= (1 if len(base) <= 5 else 2) and t != base:
                hit = t
            elif t == base:
                hit = t
            if hit is not None:
                prev = toks[i - 1] if i > 0 else ""
                variants[f"{prev} {hit}".strip()] += 1
            elif _edit(t, "faze" + base) <= 3 and t != "faze" + base:
                variants[t] += 1
        res[canon] = {"exact_case_insensitive": exact, "exact_case_sensitive": exact_case,
                      "split_faze_space_name": split, "top_variants": variants.most_common(8)}
    return res


def _edit(a, b):
    if abs(len(a) - len(b)) > 3:
        return 9
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] != b[j - 1]))
        prev = cur
    return prev[-1]


def child(args):
    from faster_whisper import WhisperModel
    cfg = json.loads(args.config)
    epochs = load_epochs(Path(args.audio_dir))
    t0c, thr0, la0 = temp_c(), throttled(), loadavg()
    t = time.perf_counter()
    model = WhisperModel(cfg["model"], device="cpu", compute_type="int8", cpu_threads=cfg["threads"],
                         num_workers=1, download_root=args.models_dir, local_files_only=True)
    load_s = time.perf_counter() - t
    kw = dict(language="en", beam_size=cfg.get("beam", 5), vad_filter=True)
    if cfg.get("bounded"):
        kw.update(temperature=0.0, max_new_tokens=cfg.get("max_new_tokens", 64))
    if cfg.get("hotwords"):
        kw["hotwords"] = cfg["hotwords"]
    if cfg.get("initial_prompt"):
        kw["initial_prompt"] = cfg["initial_prompt"]
    out = {"config": cfg, "load_s": round(load_s, 2), "temp_start_c": t0c, "throttled_start": thr0,
           "loadavg_start": la0}
    texts_whole = {}
    if "whole" in args.modes:
        total_audio = sum(len(a) for a in epochs.values()) / SR
        t = time.perf_counter()
        for ep, audio in sorted(epochs.items()):
            segs, _ = model.transcribe(audio, **kw)
            texts_whole[ep] = " ".join(s.text.strip() for s in segs)
        el = time.perf_counter() - t
        out["whole"] = {"audio_s": round(total_audio, 1), "elapsed_s": round(el, 1), "rtf": round(el / total_audio, 4),
                        "names": name_stats(list(texts_whole.values())),
                        "words": sum(len(x.split()) for x in texts_whole.values())}
    stream_texts = []
    if "stream" in args.modes:
        audio = epochs[args.stream_epoch]
        a0 = int(args.stream_start_s * SR)
        audio = audio[a0:a0 + int(args.stream_len_s * SR)]
        win, hop = 4 * SR, 3 * SR
        starts = list(range(0, len(audio) - win + 1, hop))
        procs = []
        for s in starts:
            t = time.perf_counter()
            segs, _ = model.transcribe(audio[s:s + win], condition_on_previous_text=False, **kw)
            segs = list(segs)
            procs.append(time.perf_counter() - t)
            stream_texts.append({"chunk_start_s": round(args.stream_start_s + s / SR, 1),
                                 "text": " ".join(x.text.strip() for x in segs),
                                 "avg_logprob": round(min((x.avg_logprob for x in segs), default=0.0), 3),
                                 "no_speech_prob": round(max((x.no_speech_prob for x in segs), default=0.0), 3)})
        # schedule without drops
        fin, lat = 0.0, []
        for s, p in zip(starts, procs):
            avail = (s + win) / SR
            fin = max(avail, fin) + p
            lat.append(fin - avail)
        # schedule with drop policy (skip chunks that waited too long in the queue)
        fin, lat_d, dropped = 0.0, [], 0
        for s, p in zip(starts, procs):
            avail = (s + win) / SR
            start = max(avail, fin)
            if start - avail > args.max_queue_wait_s:
                dropped += 1
                continue
            fin = start + p
            lat_d.append(fin - avail)
        speech = [p for p, tx in zip(procs, stream_texts) if tx["text"].strip()]
        media_s = len(starts) * hop / SR
        out["stream"] = {"excerpt": f"{args.stream_epoch}[{args.stream_start_s}s+{args.stream_len_s}s]",
                         "chunks": len(starts), "speech_chunks": len(speech),
                         "proc_p50_s": pctl(procs, .5), "proc_p95_s": pctl(procs, .95),
                         "proc_max_s": round(max(procs), 3), "speech_proc_p50_s": pctl(speech, .5),
                         "latency_p50_s": pctl(lat, .5), "latency_p95_s": pctl(lat, .95),
                         "latency_max_s": round(max(lat), 3), "final_backlog_s": round(lat[-1], 2),
                         "duty": round(sum(procs) / media_s, 3),
                         "deadline_missed_over_hop": sum(p > hop / SR for p in procs),
                         "with_drop_policy": {"max_queue_wait_s": args.max_queue_wait_s, "dropped": dropped,
                                              "latency_p95_s": pctl(lat_d, .95),
                                              "latency_max_s": round(max(lat_d), 3) if lat_d else None},
                         "names": name_stats([x["text"] for x in stream_texts]),
                         "chunks_with_exact": {c: sum(1 for x in stream_texts if c.lower() in x["text"].lower())
                                               for c in NAMES}}
    out["peak_rss_mib"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    out["temp_end_c"], out["throttled_end"], out["loadavg_end"] = temp_c(), throttled(), loadavg()
    out["_texts_whole"], out["_texts_stream"] = texts_whole, stream_texts
    print(json.dumps(out))


def driver(args):
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    configs = json.loads(Path(args.configs).read_text()) if os.path.exists(args.configs) else json.loads(args.configs)
    summary = {"label": "P0B_TEAM_CHANNEL audio (team's own stream)", "audio_dir": args.audio_dir,
               "runs": []}
    for cfg in configs:
        cmd = [sys.executable, "-I", str(Path(__file__).resolve()), "--child", "--config", json.dumps(cfg),
               "--audio-dir", args.audio_dir, "--models-dir", args.models_dir, "--modes", args.modes,
               "--stream-epoch", args.stream_epoch, "--stream-start-s", str(args.stream_start_s),
               "--stream-len-s", str(args.stream_len_s), "--max-queue-wait-s", str(args.max_queue_wait_s)]
        t = time.perf_counter()
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode != 0:
            summary["runs"].append({"config": cfg, "error": p.stderr.strip().splitlines()[-5:]})
            print("FAILED", cfg, p.stderr.strip().splitlines()[-3:], flush=True)
            continue
        res = json.loads(p.stdout.strip().splitlines()[-1])
        name = cfg["name"]
        (out_dir / f"transcript_{name}.json").write_text(json.dumps(
            {"whole": res.pop("_texts_whole"), "stream": res.pop("_texts_stream")}, indent=1))
        res["wall_s"] = round(time.perf_counter() - t, 1)
        summary["runs"].append(res)
        (out_dir / "summary.json").write_text(json.dumps(summary, indent=1))
        brief = {"name": name, "rtf": res.get("whole", {}).get("rtf"),
                 **{k: res.get("stream", {}).get(k) for k in ("speech_proc_p50_s", "proc_p95_s", "latency_p95_s",
                                                               "duty", "deadline_missed_over_hop")},
                 "temp_end": res["temp_end_c"], "thr": res["throttled_end"]}
        print(json.dumps(brief), flush=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--child", action="store_true")
    p.add_argument("--config", default=None)
    p.add_argument("--configs", default="configs.json")
    p.add_argument("--audio-dir", required=True)
    p.add_argument("--models-dir", required=True)
    p.add_argument("--modes", default="whole,stream")
    p.add_argument("--stream-epoch", default="1cca078b")
    p.add_argument("--stream-start-s", type=float, default=0.0)
    p.add_argument("--stream-len-s", type=float, default=300.0)
    p.add_argument("--max-queue-wait-s", type=float, default=6.0)
    p.add_argument("--out-dir", default="out/p0b_asr")
    args = p.parse_args()
    child(args) if args.child else driver(args)


if __name__ == "__main__":
    main()
