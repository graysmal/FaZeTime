#!/usr/bin/env python3
"""D34 remote-ASR benchmark on the Vultr VM, using the team's own P0-B Twitch capture (16 kHz chunks).

Streaming mode reproduces the Pi worker: per epoch, 4 s windows with a 3 s hop (windows never span epochs),
one sequential consumer, the exact server decoding policy (`fazetime_asr_remote.engine.DECODE_KW`), the 2.4
compression-ratio filter and the worker's overlap de-duplication. Each config runs in its own child process.

Reference mode (`--reference MODEL`) transcribes each epoch span long-form with faster-whisper's default
decoding (temperature ladder, beam 5, VAD, previous-text conditioning). It is a PSEUDO-reference for relative
word-error rates, not ground truth.

Transcripts are team content: they are written only to --out-dir on the VM (deleted after the run) and are
never printed. Summary JSON holds counts and timings only.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import resource
import subprocess
import sys
import time
import wave
from collections import defaultdict
from pathlib import Path

SR = 16000
WIN_S, HOP_S = 4, 3


def pctl(xs, q):
    if not xs:
        return None
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo), 3)


def load_epochs(audio_dir: Path) -> dict[str, bytes]:
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
            parts.append(pcm)
            expect = start + (len(pcm) // 2) * 1000 // SR
        out[ep] = b"".join(parts)
    return out


def spans(epochs: dict[str, bytes], spec: str) -> dict[str, bytes]:
    if spec == "all":
        return dict(sorted(epochs.items()))
    ep, start_s, len_s = spec.split(":")
    pcm = epochs[ep]
    a, b = int(float(start_s) * SR) * 2, int((float(start_s) + float(len_s)) * SR) * 2
    return {ep: pcm[a:b]}


_WORD = re.compile(r"[a-z0-9']+")


def norm_words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


class OverlapDeduper:  # copy of services/worker/fazetime_worker/asr.py OverlapDeduper (same behaviour)
    def __init__(self, max_words: int = 8):
        self.max_words, self.prev = max_words, []

    def dedupe(self, text: str) -> str:
        raw_tokens = text.split()
        norm = [norm_words(t) for t in raw_tokens]
        flat_idx = [i for i, ws in enumerate(norm) for _ in ws]
        words = [w for ws in norm for w in ws]
        best = 0
        for k in range(min(len(self.prev), len(words), self.max_words), 0, -1):
            if self.prev[-k:] == words[:k]:
                best = k
                break
        out = text.strip()
        if best:
            out = " ".join(raw_tokens[flat_idx[best - 1] + 1:])
        self.prev = (self.prev + words)[-self.max_words * 4:] if words else []
        return out


def load_names(path: str):
    spec = importlib.util.spec_from_file_location("names", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.find_names


def peak_rss_mib():
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)


def child_stream(args):
    sys.path.insert(0, args.app_dir)
    from fazetime_asr_remote.engine import WhisperEngine
    cfg = json.loads(args.config)
    find_names = load_names(args.names_py)
    data = spans(load_epochs(Path(args.audio_dir)), args.span)
    eng = WhisperEngine(cfg["model"], cfg["threads"], 1, args.models_dir)
    win, hop = WIN_S * SR * 2, HOP_S * SR * 2
    procs, speech_procs, rows = [], [], []
    texts = {}
    names_tot = {"FaZeGavin": 0, "FaZeNeville": 0}
    names_win = {"FaZeGavin": 0, "FaZeNeville": 0}
    exact = {"FaZeGavin": 0, "FaZeNeville": 0}
    filtered_windows, aborted, load_avg = 0, False, []
    t_start = time.perf_counter()
    for ep, pcm in data.items():
        dd = OverlapDeduper()
        parts = []
        starts = list(range(0, len(pcm) - win + 1, hop))
        for s in starts:
            r = eng.transcribe(pcm[s:s + win])
            p = r.compute_ms / 1000
            procs.append(p)
            rows.append((ep, s // 2 * 1000 // SR, p))
            if r.text:
                speech_procs.append(p)
            filtered_windows += int(r.filtered_repetitive > 0)
            hits = find_names(r.text)
            for k, v in hits.items():
                names_tot[k] += v
                names_win[k] += int(v > 0)
            low = r.text.lower()
            exact["FaZeGavin"] += len(re.findall(r"\bfazegavin\b", low))
            exact["FaZeNeville"] += len(re.findall(r"\bfazeneville\b", low))
            parts.append(dd.dedupe(r.text))
            if (args.abort_p95_s and len(procs) >= args.abort_after
                    and pctl(speech_procs or procs, .95) > args.abort_p95_s):
                aborted = True
                break
        texts[ep] = " ".join(x for x in parts if x)
        if aborted:
            break
    wall = time.perf_counter() - t_start
    # queue simulation per epoch: a window is available when its last sample arrives
    lat = []
    for ep in data:
        fin = 0.0
        ep_rows = [r for r in rows if r[0] == ep]
        for _, start_ms, p in ep_rows:
            avail = start_ms / 1000 + WIN_S
            fin = max(avail, fin) + p
            lat.append(fin - avail)
    media_s = len(procs) * HOP_S
    out = {"config": cfg, "span": args.span, "engine": eng.name, "load_s": eng.load_s, "windows": len(procs),
           "speech_windows": len(speech_procs), "aborted_early": aborted,
           "proc_p50_s": pctl(procs, .5), "proc_p95_s": pctl(procs, .95), "proc_max_s": round(max(procs), 3),
           "speech_p50_s": pctl(speech_procs, .5), "speech_p95_s": pctl(speech_procs, .95),
           "latency_p95_s": pctl(lat, .95), "latency_max_s": round(max(lat), 3) if lat else None,
           "duty": round(sum(procs) / media_s, 3) if media_s else None,
           "rtf_window_audio": round(sum(procs) / (len(procs) * WIN_S), 3) if procs else None,
           "windows_over_1s": sum(p > 1.0 for p in procs), "windows_over_hop": sum(p > HOP_S for p in procs),
           "repetition_filtered_windows": filtered_windows,
           "names_alias_windows": names_win, "names_alias_hits": names_tot, "names_exact_tokens": exact,
           "words": sum(len(norm_words(t)) for t in texts.values()), "wall_s": round(wall, 1),
           "peak_rss_mib": peak_rss_mib(), "loadavg_end": open("/proc/loadavg").read().split()[:3]}
    Path(args.out_dir, f"text_{cfg['name']}_{args.span.replace(':', '_')}.json").write_text(json.dumps(texts))
    print(json.dumps(out))


def child_reference(args):
    from faster_whisper import WhisperModel
    import numpy as np
    find_names = load_names(args.names_py)
    data = spans(load_epochs(Path(args.audio_dir)), args.span)
    t = time.perf_counter()
    model = WhisperModel(args.reference, device="cpu", compute_type="int8", cpu_threads=8, num_workers=1,
                         download_root=args.models_dir, local_files_only=True)
    load_s = time.perf_counter() - t
    texts, t = {}, time.perf_counter()
    for ep, pcm in data.items():
        audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        segs, _ = model.transcribe(audio, language="en", beam_size=5, vad_filter=True)
        texts[ep] = " ".join(s.text.strip() for s in segs)
    el = time.perf_counter() - t
    audio_s = sum(len(p) // 2 for p in data.values()) / SR
    joined = " ".join(texts.values())
    Path(args.out_dir, f"ref_{args.reference}_{args.span.replace(':', '_')}.json").write_text(json.dumps(texts))
    print(json.dumps({"reference": args.reference, "span": args.span, "load_s": round(load_s, 1),
                      "elapsed_s": round(el, 1), "audio_s": round(audio_s, 1), "rtf": round(el / audio_s, 3),
                      "words": len(norm_words(joined)), "names_alias_hits": find_names(joined),
                      "names_exact_tokens": {"FaZeGavin": len(re.findall(r"\bfazegavin\b", joined.lower())),
                                             "FaZeNeville": len(re.findall(r"\bfazeneville\b", joined.lower()))},
                      "peak_rss_mib": peak_rss_mib()}))


def wer(ref: list[str], hyp: list[str]) -> tuple[int, int]:
    prev = list(range(len(hyp) + 1))
    for i in range(1, len(ref) + 1):
        cur = [i] + [0] * len(hyp)
        r = ref[i - 1]
        for j in range(1, len(hyp) + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != hyp[j - 1]))
        prev = cur
    return prev[-1], len(ref)


def score(args):
    ref = json.loads(Path(args.score_ref).read_text())
    res = {}
    for f in sorted(Path(args.out_dir).glob(f"text_*_{args.span.replace(':', '_')}.json")):
        hyp = json.loads(f.read_text())
        errs = n = 0
        for ep, rtext in ref.items():
            if ep in hyp:
                e, k = wer(norm_words(rtext), norm_words(hyp[ep]))
                errs, n = errs + e, n + k
        res[f.stem] = round(errs / n, 3) if n else None
    print(json.dumps({"pseudo_wer_vs": Path(args.score_ref).stem, "span": args.span, "wer": res}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio-dir", default="/root/bench/audio")
    ap.add_argument("--models-dir", default="/opt/fazetime-asr/models")
    ap.add_argument("--app-dir", default="/opt/fazetime-asr/app")
    ap.add_argument("--names-py", default="/root/bench/names.py")
    ap.add_argument("--out-dir", default="/root/bench/out")
    ap.add_argument("--span", default="all", help="'all' or EPOCH:START_S:LEN_S")
    ap.add_argument("--configs", help="JSON list of {name, model, threads}")
    ap.add_argument("--config", help=argparse.SUPPRESS)
    ap.add_argument("--reference", help="model for the long-form pseudo-reference")
    ap.add_argument("--score-ref", help="score text_* files against this reference json")
    ap.add_argument("--abort-p95-s", type=float, default=0.0)
    ap.add_argument("--abort-after", type=int, default=25)
    ap.add_argument("--summary", default="/root/bench/out/summary.jsonl")
    args = ap.parse_args()
    if args.config:
        return child_stream(args)
    if args.score_ref:
        return score(args)
    if args.reference and not args.configs:
        return child_reference(args)
    for cfg in json.loads(args.configs):
        cmd = [sys.executable, "-I", __file__, "--config", json.dumps(cfg)] + sum(
            ([f"--{k.replace('_', '-')}", str(v)] for k, v in vars(args).items()
             if k in ("audio_dir", "models_dir", "app_dir", "names_py", "out_dir", "span", "abort_p95_s",
                      "abort_after")), [])
        p = subprocess.run(cmd, capture_output=True, text=True)
        line = p.stdout.strip().splitlines()[-1] if p.returncode == 0 and p.stdout.strip() else json.dumps(
            {"config": cfg, "error": p.stderr.strip().splitlines()[-1:] if p.stderr else "failed"})
        with open(args.summary, "a") as f:
            f.write(line + "\n")
        print(line, flush=True)


if __name__ == "__main__":
    main()
