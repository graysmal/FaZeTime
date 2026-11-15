#!/usr/bin/env python3
"""Pi capture capability check: Streamlink audio_only -> file (time to first bytes), then PyAV decode of
that file to 16 kHz mono s16 PCM with NO ffmpeg CLI; optionally a live pipe decode (streamlink stdout ->
PyAV) to measure time to first decoded audio.

Spike code only. Public channel, anonymous, default plugin behaviour: no login, token, proxy, or ad flags.
Third-party media stays in ./out and is deleted after the run; no transcript is produced. Streamlink runs at
--loglevel info and any URL query string in its log is redacted.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import resource
import signal
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


def utc():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def redact(s):
    return re.sub(r"(https?://[^\s?]+)\?\S+", r"\1?<redacted>", s)


def vc(*a):
    try:
        return subprocess.run(["vcgencmd", *a], capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception as e:  # noqa: BLE001
        return f"ERR {e}"


def health():
    try:
        uv = subprocess.run(["dmesg"], capture_output=True, text=True, timeout=5).stdout.count("Undervoltage detected")
    except Exception:  # noqa: BLE001
        uv = None
    return {"utc": utc(), "temp": vc("measure_temp"), "throttled": vc("get_throttled"),
            "dmesg_undervoltage_count": uv, "loadavg": open("/proc/loadavg").read().split()[:3]}


def start_streamlink(sl, ch, log_lines):
    cmd = [sl, "--loglevel", "info", "--stdout", f"https://twitch.tv/{ch}", "audio_only"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def pump():
        for raw in p.stderr:
            log_lines.append(f"{time.perf_counter():.3f} {redact(raw.decode(errors='replace').rstrip())}")
    threading.Thread(target=pump, daemon=True).start()
    return p


def stop_and_reap(p):
    if p.poll() is None:
        p.send_signal(signal.SIGTERM)
    try:
        _, status, ru = os.wait4(p.pid, 0)
        p.returncode = os.waitstatus_to_exitcode(status)
        return {"rc": p.returncode, "cpu_s": round(ru.ru_utime + ru.ru_stime, 2),
                "max_rss_mib": round(ru.ru_maxrss / 1024, 1)}
    except ChildProcessError:
        return {"rc": p.returncode}


def fetch(a, ch, out_file):
    log = []
    t0 = time.perf_counter()
    p = start_streamlink(a.streamlink, ch, log)
    timer = threading.Timer(a.seconds + a.max_startup_s, lambda: p.poll() is None and p.kill())
    timer.start()
    first, nbytes, reads = None, 0, []
    with open(out_file, "wb") as f:
        while True:
            chunk = p.stdout.read1(65536)
            now = time.perf_counter() - t0
            if not chunk:
                break
            if first is None:
                first = now
            f.write(chunk)
            nbytes += len(chunk)
            reads.append(now)
            if now - first >= a.seconds:
                break
    wall = time.perf_counter() - t0
    timer.cancel()
    proc = stop_and_reap(p)
    gaps = sorted(b - a_ for a_, b in zip(reads, reads[1:]) if b - a_ > 0.5)
    return {"channel": ch, "launch_to_first_bytes_s": round(first, 3) if first is not None else None,
            "bytes": nbytes, "wall_s": round(wall, 2), "kbit_s": round(nbytes * 8 / 1000 / max(wall - (first or 0), 0.1), 1),
            "read_gaps_over_0.5s": {"n": len(gaps), "max_s": round(gaps[-1], 2) if gaps else None,
                                    "median_s": round(gaps[len(gaps) // 2], 2) if gaps else None},
            "streamlink": proc, "log_tail": [l.split(" ", 1)[1] for l in log[-8:]]}


def decode_file(path):
    import av
    ru0 = resource.getrusage(resource.RUSAGE_SELF)
    t = time.perf_counter()
    c = av.open(str(path))
    s = c.streams.audio[0]
    cc = s.codec_context
    info = {"container": c.format.name, "codec": cc.name, "in_rate": cc.sample_rate,
            "in_layout": cc.layout.name if cc.layout else None, "in_format": cc.format.name if cc.format else None,
            "video_streams": len(c.streams.video)}
    res = av.AudioResampler(format="s16", layout="mono", rate=16000)
    n_frames = n_out = 0
    first_pts = last_end = None
    jumps, errors, dtype_ok = 0, [], True
    try:
        for fr in c.decode(s):
            n_frames += 1
            if fr.pts is not None and fr.time_base is not None:
                st = float(fr.pts * fr.time_base)
                if first_pts is None:
                    first_pts = st
                if last_end is not None and abs(st - last_end) > 0.05:
                    jumps += 1
                last_end = st + fr.samples / fr.sample_rate
            for o in res.resample(fr):
                arr = o.to_ndarray()
                dtype_ok &= arr.dtype.name == "int16" and arr.shape[0] == 1
                n_out += o.samples
        for o in res.resample(None):
            n_out += o.samples
    except Exception as e:  # noqa: BLE001 - record decoder failures
        errors.append(repr(e)[:200])
    c.close()
    ru1 = resource.getrusage(resource.RUSAGE_SELF)
    info.update({"decoded_frames": n_frames, "out_samples_16k_mono": n_out, "out_duration_s": round(n_out / 16000, 3),
                 "pts_span_s": round(last_end - first_pts, 3) if first_pts is not None else None,
                 "pts_jumps_over_50ms": jumps, "out_dtype_s16_mono": dtype_ok, "errors": errors,
                 "decode_wall_s": round(time.perf_counter() - t, 3),
                 "decode_cpu_s": round((ru1.ru_utime - ru0.ru_utime) + (ru1.ru_stime - ru0.ru_stime), 3)})
    return info


def decode_pipe(a, ch):
    """Live path without ffmpeg CLI: streamlink stdout -> PyAV demux/decode -> 16 kHz mono."""
    import av
    log = []
    t0 = time.perf_counter()
    p = start_streamlink(a.streamlink, ch, log)
    timer = threading.Timer(a.pipe_seconds + a.max_startup_s, lambda: p.poll() is None and p.kill())
    timer.start()
    out = {"channel": ch}
    try:
        c = av.open(p.stdout, mode="r")
        out["opened_s"] = round(time.perf_counter() - t0, 3)
        s = c.streams.audio[0]
        res = av.AudioResampler(format="s16", layout="mono", rate=16000)
        n_out, first = 0, None
        for fr in c.decode(s):
            for o in res.resample(fr):
                if first is None:
                    first = time.perf_counter() - t0
                n_out += o.samples
            if n_out >= a.pipe_seconds * 16000:
                break
        out.update({"launch_to_first_pcm_s": round(first, 3) if first else None, "container": c.format.name,
                    "codec": s.codec_context.name, "pcm_s": round(n_out / 16000, 2),
                    "wall_s": round(time.perf_counter() - t0, 2)})
        c.close()
    except Exception as e:  # noqa: BLE001
        out["error"] = repr(e)[:300]
    timer.cancel()
    out["streamlink"] = stop_and_reap(p)
    out["log_tail"] = [l.split(" ", 1)[1] for l in log[-5:]]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--channels", default="summit1g,shroud,zackrawrr")
    ap.add_argument("--seconds", type=float, default=30)
    ap.add_argument("--pipe-seconds", type=float, default=15)
    ap.add_argument("--max-startup-s", type=float, default=30)
    ap.add_argument("--streamlink", default=str(Path(__file__).resolve().parent / ".venv" / "bin" / "streamlink"))
    ap.add_argument("--out-dir", default=str(Path(__file__).resolve().parent / "out"))
    a = ap.parse_args()
    od = Path(a.out_dir)
    od.mkdir(exist_ok=True)
    rep = {"label": "TOOLCHAIN_SMOKE public channel (not team channel)", "health_before": health(), "attempts": []}
    media = od / "sl_audio_only.bin"
    for ch in a.channels.split(","):
        r = fetch(a, ch, media)
        rep["attempts"].append(r)
        print(json.dumps({k: r[k] for k in ("channel", "launch_to_first_bytes_s", "bytes", "kbit_s")}), flush=True)
        if r["bytes"] > 0:
            rep["fetch"] = r
            break
    if "fetch" in rep:
        rep["decode_file"] = decode_file(media)
        print(json.dumps(rep["decode_file"]), flush=True)
        if a.pipe_seconds > 0:
            rep["decode_pipe"] = decode_pipe(a, rep["fetch"]["channel"])
            print(json.dumps(rep["decode_pipe"]), flush=True)
    media.unlink(missing_ok=True)
    rep["media_deleted"] = not media.exists()
    rep["health_after"] = health()
    (od / "sl_pyav_test.json").write_text(json.dumps(rep, indent=1))
    print(json.dumps({"health_before": rep["health_before"], "health_after": rep["health_after"]}))


if __name__ == "__main__":
    main()
