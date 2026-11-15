#!/usr/bin/env python3
"""P0-D-prep ASR bench: faster-whisper on CPU (int8), whole-file RTF + simulated streaming.

Spike code only. Transcript text is held in memory for cross-model agreement and
is NEVER written to disk or printed (third-party audio). Only counts/metrics are
written. Each model/config runs in its own child process so peak RSS is per run.

Simulated streaming: consecutive 4 s chunks with 1 s overlap (hop 3 s). Chunk i
becomes available at media time start_i + 4 s; one sequential worker processes
chunks in order (measured back-to-back, schedule computed from measured times):
    finish_i = max(avail_i, finish_{i-1}) + proc_i ; latency_i = finish_i - avail_i
latency_i therefore includes queueing (backlog) but not capture/Twitch delay.
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
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SR = 16000


def loadavg():
    with open("/proc/loadavg") as f:
        return [float(x) for x in f.read().split()[:3]]


def vmrss_mib():
    with open("/proc/self/status") as f:
        for line in f:
            if line.startswith("VmRSS:"):
                return round(int(line.split()[1]) / 1024, 1)


def pctl(xs, q):
    if not xs:
        return None
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def norm_words(text):
    return re.sub(r"[^a-z0-9' ]+", " ", text.lower()).split()


def wer(ref, hyp):
    r, h = norm_words(ref), norm_words(hyp)
    if not r:
        return None
    prev = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        cur = [i] + [0] * len(h)
        for j in range(1, len(h) + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r[i - 1] != h[j - 1]))
        prev = cur
    return round(prev[-1] / len(r), 3)


def child(args):
    import numpy as np
    from faster_whisper import WhisperModel

    la0 = loadavg()
    with wave.open(args.wav, "rb") as w:
        assert w.getframerate() == SR and w.getnchannels() == 1 and w.getsampwidth() == 2
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
    dur = len(audio) / SR
    ru0 = resource.getrusage(resource.RUSAGE_SELF)
    t = time.perf_counter()
    model = WhisperModel(args.model, device="cpu", compute_type=args.compute_type, cpu_threads=args.threads,
                         num_workers=1, download_root=args.models_dir, local_files_only=True)
    load_s = time.perf_counter() - t
    rss_after_load = vmrss_mib()
    kw = dict(language="en", beam_size=args.beam_size, vad_filter=bool(args.vad))

    out = {"model": args.model, "threads": args.threads, "compute_type": args.compute_type,
           "beam_size": args.beam_size, "vad_filter": bool(args.vad), "audio_s": round(dur, 2),
           "load_s": round(load_s, 2), "rss_after_load_mib": rss_after_load, "loadavg_start": la0}

    if "whole" in args.modes:
        ru1 = resource.getrusage(resource.RUSAGE_SELF)
        t = time.perf_counter()
        segs, info = model.transcribe(audio, **kw)
        segs = list(segs)
        el = time.perf_counter() - t
        ru2 = resource.getrusage(resource.RUSAGE_SELF)
        cpu = (ru2.ru_utime - ru1.ru_utime) + (ru2.ru_stime - ru1.ru_stime)
        text = " ".join(s.text.strip() for s in segs)
        out["whole"] = {"elapsed_s": round(el, 2), "rtf": round(el / dur, 4), "cpu_s": round(cpu, 1),
                        "avg_cores_busy": round(cpu / el, 2), "segments": len(segs),
                        "words": len(norm_words(text)),
                        "duration_after_vad_s": round(getattr(info, "duration_after_vad", dur) or dur, 1),
                        "mean_avg_logprob": round(sum(s.avg_logprob for s in segs) / len(segs), 3) if segs else None}
        out["_text_whole"] = text  # consumed by the driver in memory only

    if "stream" in args.modes:
        win, hop = int(args.chunk_s * SR), int((args.chunk_s - args.overlap_s) * SR)
        starts = list(range(0, len(audio) - win + 1, hop))
        procs, words, empty = [], 0, 0
        texts = []
        ru1 = resource.getrusage(resource.RUSAGE_SELF)
        t_all = time.perf_counter()
        for s in starts:
            t = time.perf_counter()
            segs, _ = model.transcribe(audio[s:s + win], condition_on_previous_text=False, **kw)
            segs = list(segs)
            procs.append(time.perf_counter() - t)
            txt = " ".join(x.text.strip() for x in segs)
            texts.append(txt)
            nw = len(norm_words(txt))
            words += nw
            empty += nw == 0
        el = time.perf_counter() - t_all
        ru2 = resource.getrusage(resource.RUSAGE_SELF)
        cpu = (ru2.ru_utime - ru1.ru_utime) + (ru2.ru_stime - ru1.ru_stime)
        finish, lat, backlog_series = 0.0, [], []
        for i, (s, p) in enumerate(zip(starts, procs)):
            avail = (s + win) / SR
            finish = max(avail, finish) + p
            lat.append(finish - avail)
            if i % 10 == 9 or i == len(starts) - 1:
                backlog_series.append([round(avail, 1), round(finish - avail, 2)])
        media_s = (starts[-1] + win) / SR if starts else 0
        first10 = sum(lat[:10]) / max(1, len(lat[:10]))
        last10 = sum(lat[-10:]) / max(1, len(lat[-10:]))
        out["stream"] = {"chunk_s": args.chunk_s, "overlap_s": args.overlap_s, "chunks": len(starts),
                         "proc_p50_s": round(pctl(procs, .5), 3), "proc_p95_s": round(pctl(procs, .95), 3),
                         "proc_max_s": round(max(procs), 3),
                         "latency_p50_s": round(pctl(lat, .5), 3), "latency_p95_s": round(pctl(lat, .95), 3),
                         "latency_max_s": round(max(lat), 3),
                         "duty_cycle": round(sum(procs) / (len(starts) * hop / SR), 3),
                         "final_backlog_s": round(lat[-1], 2), "latency_first10_mean_s": round(first10, 3),
                         "latency_last10_mean_s": round(last10, 3),
                         "keeps_up": bool(sum(procs) < len(starts) * hop / SR and last10 < 2 * first10 + 1.0),
                         "backlog_series_media_s_vs_latency_s": backlog_series,
                         "elapsed_s": round(el, 1), "cpu_s": round(cpu, 1), "avg_cores_busy": round(cpu / el, 2),
                         "words": words, "chunks_without_words": empty, "media_s": media_s}
    out["peak_rss_mib"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    out["loadavg_end"] = loadavg()
    print(json.dumps(out))


def dir_size_mib(p: Path):
    tot = 0
    for f in p.rglob("*"):
        if f.is_file() or f.is_symlink():
            try:
                tot += os.path.getsize(os.path.realpath(f))
            except OSError:
                pass
    return round(tot / 2**20, 1)


def driver(args):
    from faster_whisper.utils import download_model
    import importlib.metadata as md

    models_dir = Path(args.models_dir)
    models_dir.mkdir(parents=True, exist_ok=True)
    runs = []
    for spec in args.runs.split(";"):
        # spec: model[:threads[:vad[:beam[:modes]]]]
        parts = spec.split(":")
        runs.append({"model": parts[0], "threads": int(parts[1]) if len(parts) > 1 else args.threads,
                     "vad": int(parts[2]) if len(parts) > 2 else 1,
                     "beam": int(parts[3]) if len(parts) > 3 else args.beam_size,
                     "modes": parts[4] if len(parts) > 4 else "whole,stream"})
    sizes = {}
    for m in sorted({r["model"] for r in runs}):
        t = time.perf_counter()
        path = download_model(m, cache_dir=str(models_dir))
        sizes[m] = {"repo": path.split("models--")[-1].split("/snapshots")[0].replace("--", "/")
                    if "models--" in path else path, "snapshot": Path(path).name,
                    "size_mib": dir_size_mib(Path(path)), "fetch_s": round(time.perf_counter() - t, 1)}
        print(f"model {m}: {sizes[m]}", flush=True)
    results, texts = [], {}
    for r in runs:
        cmd = [sys.executable, "-I", str(Path(__file__).resolve()), "--child", "--wav", args.wav,
               "--model", r["model"], "--threads", str(r["threads"]), "--vad", str(r["vad"]),
               "--beam-size", str(r["beam"]), "--compute-type", args.compute_type, "--models-dir", str(models_dir),
               "--chunk-s", str(args.chunk_s), "--overlap-s", str(args.overlap_s), "--modes", r["modes"]]
        t = time.perf_counter()
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode != 0:
            err = p.stderr.strip().splitlines()[-5:]
            print(f"FAILED {r}: {err}", flush=True)
            results.append({"run": r, "error": err})
            continue
        res = json.loads(p.stdout.strip().splitlines()[-1])
        key = f"{r['model']}|t{r['threads']}|vad{r['vad']}|b{r['beam']}"
        if "_text_whole" in res:
            texts[key] = res.pop("_text_whole")
        res["wall_s"] = round(time.perf_counter() - t, 1)
        results.append(res)
        brief = {k: res.get(k) for k in ("model", "threads", "vad_filter", "beam_size", "load_s", "peak_rss_mib")}
        if "whole" in res:
            brief["rtf"] = res["whole"]["rtf"]
        if "stream" in res:
            brief.update({k: res["stream"][k] for k in ("proc_p50_s", "proc_p95_s", "latency_p95_s",
                                                         "duty_cycle", "keeps_up")})
        print(json.dumps(brief), flush=True)
    ref_key = next((k for k in texts if k.startswith(args.reference + "|") and "vad1" in k), None)
    agreement = {}
    if ref_key:
        for k, v in texts.items():
            if k != ref_key:
                agreement[k] = {"wer_vs_reference": wer(texts[ref_key], v), "reference": ref_key}
    versions = {p: md.version(p) for p in ("faster-whisper", "ctranslate2", "onnxruntime", "numpy", "av",
                                            "huggingface-hub", "tokenizers")}
    report = {"label": args.label, "wav": Path(args.wav).name, "versions": versions, "models": sizes,
              "results": results, "agreement_whole_file": agreement,
              "note": "agreement = WER of each whole-file transcript against the reference MODEL output, "
                      "not against ground truth; transcripts are not stored"}
    Path(args.out).write_text(json.dumps(report, indent=1))
    print(json.dumps({"agreement": agreement}, indent=1))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--wav", required=True)
    p.add_argument("--child", action="store_true")
    p.add_argument("--model", default="base.en")
    p.add_argument("--runs", default="tiny.en;base.en;small.en",
                   help="';'-separated model[:threads[:vad[:beam[:modes]]]]")
    p.add_argument("--threads", type=int, default=4)
    p.add_argument("--vad", type=int, default=1)
    p.add_argument("--beam-size", type=int, default=5)
    p.add_argument("--compute-type", default="int8")
    p.add_argument("--chunk-s", type=float, default=4.0)
    p.add_argument("--overlap-s", type=float, default=1.0)
    p.add_argument("--modes", default="whole,stream")
    p.add_argument("--models-dir", default=str(SCRIPT_DIR / "models"))
    p.add_argument("--reference", default="small.en")
    p.add_argument("--label", default="TOOLCHAIN_SMOKE public-channel audio (not team audio)")
    p.add_argument("--out", default=str(SCRIPT_DIR / "out" / "asr_bench.json"))
    args = p.parse_args()
    child(args) if args.child else driver(args)


if __name__ == "__main__":
    main()
