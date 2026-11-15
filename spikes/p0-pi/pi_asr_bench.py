#!/usr/bin/env python3
"""P0-D Pi ASR bench: faster-whisper on Raspberry Pi 5 CPU (int8), whole-file RTF + simulated streaming.

Spike code only (not application code). Adapted from spikes/p0-media/asr_bench.py (laptop) so the
numbers are comparable. Additions for the Pi:
  * a monitor thread sampling SoC temperature, throttle flags, ARM clock, EXT5V rail, fan RPM,
    load average, child RSS and MemAvailable every --sample-s seconds;
  * hard stop: temp > --max-temp-c or any *current* throttle bit (get_throttled & 0xF) kills the
    run and skips the remaining runs;
  * vcgencmd temp/throttled recorded before and after every model run;
  * --bg-load N spawns N `python3 -c 'while True: pass'` busy loops for the duration of each run
    (simulates API + capture holding about one core);
  * --small-if-base-rtf-below X: download and run small.en only if base.en whole-file RTF < X.

Transcript text is held in memory for cross-model agreement only. It is NEVER written to disk or
printed (third-party audio). Each model/config runs in its own child process so peak RSS is per run.

Simulated streaming: consecutive 4 s chunks with 1 s overlap (hop 3 s). Chunk i becomes available at
media time start_i + 4 s; one sequential worker processes chunks in order (measured back-to-back,
schedule computed from measured times):
    finish_i = max(avail_i, finish_{i-1}) + proc_i ; latency_i = finish_i - avail_i
latency_i therefore includes queueing (backlog) but not capture/Twitch delay.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import resource
import subprocess
import sys
import threading
import time
import wave
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SR = 16000


def utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def loadavg():
    with open("/proc/loadavg") as f:
        return [float(x) for x in f.read().split()[:3]]


def vmrss_mib(pid="self"):
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return round(int(line.split()[1]) / 1024, 1)
    except OSError:
        return None


def mem_available_mib():
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith("MemAvailable:"):
                return round(int(line.split()[1]) / 1024)


def vc(*args):
    try:
        return subprocess.run(["vcgencmd", *args], capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception as e:  # noqa: BLE001 - spike diagnostics
        return f"ERR {e}"


def soc_temp_c():
    m = re.search(r"temp=([\d.]+)", vc("measure_temp"))
    return float(m.group(1)) if m else None


def throttled():
    m = re.search(r"throttled=(0x[0-9a-fA-F]+)", vc("get_throttled"))
    return int(m.group(1), 16) if m else None


def arm_mhz():
    m = re.search(r"=(\d+)", vc("measure_clock", "arm"))
    return round(int(m.group(1)) / 1e6) if m else None


def ext5v():
    m = re.search(r"=([\d.]+)V", vc("pmic_read_adc", "EXT5V_V"))
    return round(float(m.group(1)), 3) if m else None


def fan_rpm():
    for p in glob.glob("/sys/devices/platform/cooling_fan/hwmon/hwmon*/fan1_input"):
        try:
            return int(open(p).read().strip())
        except OSError:
            pass
    return None


def thermal_snapshot():
    t = throttled()
    return {"utc": utc(), "temp_c": soc_temp_c(), "throttled": hex(t) if t is not None else None,
            "throttled_current_bits": hex(t & 0xF) if t is not None else None, "arm_mhz": arm_mhz(),
            "ext5v_v": ext5v(), "fan_rpm": fan_rpm(), "loadavg": loadavg(), "mem_available_mib": mem_available_mib()}


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


# ----------------------------------------------------------------------------------------- child
def child(args):
    import numpy as np
    from faster_whisper import WhisperModel

    la0 = loadavg()
    with wave.open(args.wav, "rb") as w:
        assert w.getframerate() == SR and w.getnchannels() == 1 and w.getsampwidth() == 2
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
    dur = len(audio) / SR
    t = time.perf_counter()
    model = WhisperModel(args.model, device="cpu", compute_type=args.compute_type, cpu_threads=args.threads,
                         num_workers=1, download_root=args.models_dir, local_files_only=True)
    load_s = time.perf_counter() - t
    rss_after_load = vmrss_mib()
    kw = dict(language="en", beam_size=args.beam_size, vad_filter=bool(args.vad))
    if args.temperature is not None:  # single value disables faster-whisper's temperature-fallback ladder
        kw["temperature"] = args.temperature
    if args.max_new_tokens:
        kw["max_new_tokens"] = args.max_new_tokens

    out = {"model": args.model, "threads": args.threads, "compute_type": args.compute_type,
           "beam_size": args.beam_size, "vad_filter": bool(args.vad), "audio_s": round(dur, 2),
           "temperature": args.temperature if args.temperature is not None else "default ladder 0.0..1.0",
           "max_new_tokens": args.max_new_tokens or None,
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
        out["_text_whole"] = text  # consumed by the driver in memory only, never stored

    if "stream" in args.modes:
        win, hop = int(args.chunk_s * SR), int((args.chunk_s - args.overlap_s) * SR)
        starts = list(range(0, len(audio) - win + 1, hop))
        procs, words, empty, diag = [], 0, 0, []
        ru1 = resource.getrusage(resource.RUSAGE_SELF)
        t_all = time.perf_counter()
        for s in starts:
            t = time.perf_counter()
            segs, _ = model.transcribe(audio[s:s + win], condition_on_previous_text=False, **kw)
            segs = list(segs)
            procs.append(time.perf_counter() - t)
            nw = len(norm_words(" ".join(x.text.strip() for x in segs)))
            words += nw
            empty += nw == 0
            # non-text diagnostics only: final decode temperature (>0 means fallback happened), token/word counts
            diag.append({"chunk": len(procs) - 1, "media_start_s": round(s / SR, 1), "proc_s": round(procs[-1], 3),
                         "max_temperature": max((x.temperature for x in segs), default=None),
                         "tokens": sum(len(x.tokens) for x in segs), "words": nw,
                         "max_compression_ratio": round(max((x.compression_ratio for x in segs), default=0), 2)})
        el = time.perf_counter() - t_all
        ru2 = resource.getrusage(resource.RUSAGE_SELF)
        cpu = (ru2.ru_utime - ru1.ru_utime) + (ru2.ru_stime - ru1.ru_stime)
        finish, lat, backlog_series = 0.0, [], []
        for i, (s, p) in enumerate(zip(starts, procs)):
            avail = (s + win) / SR
            finish = max(avail, finish) + p
            lat.append(finish - avail)
            if i % 5 == 4 or i == len(starts) - 1:
                backlog_series.append([round(avail, 1), round(finish - avail, 2)])
        media_s = (starts[-1] + win) / SR if starts else 0
        first10 = sum(lat[:10]) / max(1, len(lat[:10]))
        last10 = sum(lat[-10:]) / max(1, len(lat[-10:]))
        speech = [p for p in procs if p > 0.1]
        out["stream"] = {"chunk_s": args.chunk_s, "overlap_s": args.overlap_s, "chunks": len(starts),
                         "proc_p50_s": round(pctl(procs, .5), 3), "proc_p95_s": round(pctl(procs, .95), 3),
                         "proc_max_s": round(max(procs), 3),
                         "proc_chunks_over_0.1s": len(speech),
                         "proc_p50_s_chunks_over_0.1s": round(pctl(speech, .5), 3) if speech else None,
                         "latency_p50_s": round(pctl(lat, .5), 3), "latency_p95_s": round(pctl(lat, .95), 3),
                         "latency_max_s": round(max(lat), 3),
                         "duty_cycle": round(sum(procs) / (len(starts) * hop / SR), 3),
                         "final_backlog_s": round(lat[-1], 2), "latency_first10_mean_s": round(first10, 3),
                         "latency_last10_mean_s": round(last10, 3),
                         "keeps_up": bool(sum(procs) < len(starts) * hop / SR and last10 < 2 * first10 + 1.0),
                         "backlog_series_media_s_vs_latency_s": backlog_series,
                         "elapsed_s": round(el, 1), "cpu_s": round(cpu, 1), "avg_cores_busy": round(cpu / el, 2),
                         "words": words, "chunks_without_words": empty, "media_s": media_s,
                         "chunks_with_fallback_temperature": sum(1 for d in diag if (d["max_temperature"] or 0) > 0),
                         "slowest_chunks": sorted(diag, key=lambda d: -d["proc_s"])[:3]}
    out["peak_rss_mib"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    out["loadavg_end"] = loadavg()
    print(json.dumps(out))


# ---------------------------------------------------------------------------------------- driver
class Monitor(threading.Thread):
    """Samples Pi health while a child runs; trips `abort` on temp/throttle limits."""

    def __init__(self, pid, max_temp, every):
        super().__init__(daemon=True)
        self.pid, self.max_temp, self.every = pid, max_temp, every
        self.samples, self.abort, self.stop_evt = [], None, threading.Event()

    def run(self):
        t0 = time.perf_counter()
        while not self.stop_evt.is_set():
            th = throttled()
            s = {"t_s": round(time.perf_counter() - t0, 1), "temp_c": soc_temp_c(), "throttled": th,
                 "arm_mhz": arm_mhz(), "ext5v_v": ext5v(), "fan_rpm": fan_rpm(), "load1": loadavg()[0],
                 "child_rss_mib": vmrss_mib(self.pid), "mem_available_mib": mem_available_mib()}
            self.samples.append(s)
            if s["temp_c"] is not None and s["temp_c"] > self.max_temp:
                self.abort = f"temp {s['temp_c']} C > {self.max_temp} C"
            elif th is not None and th & 0xF:
                self.abort = f"current throttle bits {hex(th & 0xF)} (get_throttled={hex(th)})"
            if self.abort:
                return
            self.stop_evt.wait(self.every)

    def summary(self):
        xs = self.samples
        if not xs:
            return {}
        f = lambda k: [x[k] for x in xs if x.get(k) is not None]  # noqa: E731
        return {"n": len(xs), "temp_c_max": max(f("temp_c"), default=None),
                "arm_mhz_min": min(f("arm_mhz"), default=None), "arm_mhz_max": max(f("arm_mhz"), default=None),
                "ext5v_v_min": min(f("ext5v_v"), default=None), "fan_rpm_max": max(f("fan_rpm"), default=None),
                "load1_max": max(f("load1"), default=None), "child_rss_mib_max": max(f("child_rss_mib"), default=None),
                "mem_available_mib_min": min(f("mem_available_mib"), default=None),
                "throttled_union": hex(__import__("functools").reduce(lambda a, b: a | b, f("throttled"), 0))}


def dir_size_mib(p: Path):
    tot = 0
    for f in p.rglob("*"):
        if f.is_file() or f.is_symlink():
            try:
                tot += os.path.getsize(os.path.realpath(f))
            except OSError:
                pass
    return round(tot / 2**20, 1)


def fetch(m, models_dir, sizes):
    from faster_whisper.utils import download_model
    t = time.perf_counter()
    path = download_model(m, cache_dir=str(models_dir))
    sizes[m] = {"repo": path.split("models--")[-1].split("/snapshots")[0].replace("--", "/")
                if "models--" in path else path, "snapshot": Path(path).name,
                "size_mib": dir_size_mib(Path(path)), "fetch_s": round(time.perf_counter() - t, 1),
                "fetched_utc": utc()}
    sizes[m]["mib_per_s"] = round(sizes[m]["size_mib"] / max(sizes[m]["fetch_s"], 0.01), 2)
    print(f"model {m}: {sizes[m]}", flush=True)


def parse_spec(spec, args):
    parts = spec.split(":")
    return {"model": parts[0], "threads": int(parts[1]) if len(parts) > 1 else args.threads,
            "vad": int(parts[2]) if len(parts) > 2 else 1,
            "beam": int(parts[3]) if len(parts) > 3 else args.beam_size,
            "modes": parts[4] if len(parts) > 4 else "whole,stream"}


def run_one(r, args, models_dir):
    cmd = [sys.executable, "-I", str(Path(__file__).resolve()), "--child", "--wav", args.wav,
           "--model", r["model"], "--threads", str(r["threads"]), "--vad", str(r["vad"]),
           "--beam-size", str(r["beam"]), "--compute-type", args.compute_type, "--models-dir", str(models_dir),
           "--chunk-s", str(args.chunk_s), "--overlap-s", str(args.overlap_s), "--modes", r["modes"]]
    if args.temperature is not None:
        cmd += ["--temperature", str(args.temperature)]
    if args.max_new_tokens:
        cmd += ["--max-new-tokens", str(args.max_new_tokens)]
    before = thermal_snapshot()
    loads = [subprocess.Popen(["python3", "-c", "while True: pass"]) for _ in range(args.bg_load)]
    t = time.perf_counter()
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    mon = Monitor(p.pid, args.max_temp_c, args.sample_s)
    mon.start()
    while p.poll() is None:
        if mon.abort:
            p.kill()
            break
        time.sleep(0.5)
    stdout, stderr = p.communicate()
    mon.stop_evt.set()
    mon.join(timeout=10)
    wall = round(time.perf_counter() - t, 1)
    for lp in loads:
        lp.kill()
        lp.wait()
    after = thermal_snapshot()
    base = {"run": r, "bg_load_procs": args.bg_load, "thermal_before": before, "thermal_after": after,
            "monitor": mon.summary(), "wall_s": wall}
    if mon.abort:
        base["aborted"] = mon.abort
        print(f"ABORTED {r}: {mon.abort}", flush=True)
        return base, None
    if p.returncode != 0:
        base["error"] = stderr.strip().splitlines()[-5:]
        print(f"FAILED {r}: {base['error']}", flush=True)
        return base, None
    res = json.loads(stdout.strip().splitlines()[-1])
    text = res.pop("_text_whole", None)
    res.update(base)
    brief = {k: res.get(k) for k in ("model", "threads", "vad_filter", "beam_size", "load_s", "peak_rss_mib")}
    if "whole" in res:
        brief["rtf"] = res["whole"]["rtf"]
    if "stream" in res:
        brief.update({k: res["stream"][k] for k in ("proc_p50_s", "proc_p95_s", "latency_p95_s",
                                                     "duty_cycle", "keeps_up")})
    brief.update({"temp_max": res["monitor"].get("temp_c_max"), "arm_mhz_min": res["monitor"].get("arm_mhz_min"),
                  "throttled_after": after["throttled"], "bg_load": args.bg_load})
    print(json.dumps(brief), flush=True)
    return res, text


def driver(args):
    import importlib.metadata as md

    models_dir = Path(args.models_dir)
    models_dir.mkdir(parents=True, exist_ok=True)
    runs = [parse_spec(s, args) for s in args.runs.split(";") if s]
    report = {"label": args.label, "wav": Path(args.wav).name, "started_utc": utc(),
              "host": {"model": open("/proc/device-tree/model").read().strip("\x00\n"),
                       "uname": " ".join(os.uname()), "nproc": os.cpu_count(),
                       "governor": open("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor").read().strip()},
              "versions": {p: md.version(p) for p in ("faster-whisper", "ctranslate2", "onnxruntime", "numpy", "av",
                                                      "huggingface-hub", "tokenizers")},
              "python": sys.version.split()[0], "bg_load_procs": args.bg_load, "models": {}, "results": [],
              "note": "agreement = WER of each whole-file transcript against the reference MODEL output, "
                      "not against ground truth; transcripts are not stored"}
    out_path = Path(args.out)

    def save():
        out_path.write_text(json.dumps(report, indent=1))

    for m in sorted({r["model"] for r in runs}):
        fetch(m, models_dir, report["models"])
    save()
    texts, stop = {}, None
    queue = list(runs)
    small_checked = False
    while queue and not stop:
        r = queue.pop(0)
        res, text = run_one(r, args, models_dir)
        report["results"].append(res)
        save()
        if res.get("aborted"):
            stop = res["aborted"]
            break
        key = f"{r['model']}|t{r['threads']}|vad{r['vad']}|b{r['beam']}|load{args.bg_load}"
        if text is not None:
            texts[key] = text
        if (args.small_if_base_rtf_below and not small_checked and r["model"] == "base.en"
                and "whole" in res):
            small_checked = True
            rtf = res["whole"]["rtf"]
            decision = rtf < args.small_if_base_rtf_below
            report["small_en_rule"] = {"base_en_rtf": rtf, "threshold": args.small_if_base_rtf_below,
                                       "run_small_en": decision}
            print(f"small.en rule: base.en RTF {rtf} < {args.small_if_base_rtf_below} -> {decision}", flush=True)
            if decision:
                fetch("small.en", models_dir, report["models"])
                save()
                queue.append(dict(r, model="small.en"))
    if stop:
        report["stopped"] = stop
    ref = next((k for k in texts if k.startswith(args.reference + "|")), None) or \
        next((k for k in texts if k.startswith("base.en|")), None)
    report["agreement_whole_file"] = {k: {"wer_vs_reference": wer(texts[ref], v), "reference": ref}
                                      for k, v in texts.items() if ref and k != ref}
    report["finished_utc"] = utc()
    save()
    print(json.dumps({"agreement": report["agreement_whole_file"], "stopped": stop}, indent=1))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--wav", required=True)
    p.add_argument("--child", action="store_true")
    p.add_argument("--model", default="base.en")
    p.add_argument("--runs", default="tiny.en;base.en", help="';'-separated model[:threads[:vad[:beam[:modes]]]]")
    p.add_argument("--threads", type=int, default=4)
    p.add_argument("--vad", type=int, default=1)
    p.add_argument("--beam-size", type=int, default=5)
    p.add_argument("--compute-type", default="int8")
    p.add_argument("--chunk-s", type=float, default=4.0)
    p.add_argument("--overlap-s", type=float, default=1.0)
    p.add_argument("--modes", default="whole,stream")
    p.add_argument("--models-dir", default=str(SCRIPT_DIR / "models"))
    p.add_argument("--reference", default="small.en")
    p.add_argument("--small-if-base-rtf-below", type=float, default=0.0)
    p.add_argument("--temperature", type=float, default=None,
                   help="single decode temperature (disables the fallback ladder); default = faster-whisper ladder")
    p.add_argument("--max-new-tokens", type=int, default=0, help="cap generated tokens per chunk; 0 = no cap")
    p.add_argument("--bg-load", type=int, default=0)
    p.add_argument("--max-temp-c", type=float, default=80.0)
    p.add_argument("--sample-s", type=float, default=2.0)
    p.add_argument("--label", default="TOOLCHAIN_SMOKE public-channel audio (not team audio)")
    p.add_argument("--out", default=str(SCRIPT_DIR / "out" / "pi_asr_bench.json"))
    args = p.parse_args()
    child(args) if args.child else driver(args)


if __name__ == "__main__":
    main()
