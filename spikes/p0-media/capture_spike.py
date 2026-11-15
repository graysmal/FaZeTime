#!/usr/bin/env python3
"""P0-B-prep capture spike: supervised Streamlink -> FFmpeg with a JSONL timeline.

Spike code only (not services/worker, not a contract implementation). Results
from a public channel are TOOLCHAIN_SMOKE, not the P0-B gate.

Topology (one Twitch source, one decode path):

    streamlink --stdout https://twitch.tv/<channel> <quality>
        -> python byte pump (first-byte / input-age metering)
        -> ffmpeg -i pipe:0
             audio: aresample=16000, mono s16, ashowinfo (per decoded frame) -> stdout (raw PCM)
             video: select(>=2 s since last)[,scale], showinfo -> MJPEG on an extra pipe fd

Media positions: decoded sample count (16 kHz) relative to the current
source_epoch. ashowinfo gives the FFmpeg pts of every decoded audio frame, so
timestamp jumps (ad filtering, skipped segments) are detected at an exact
sample index and never padded with synthetic audio. Frames carry showinfo
pts and are mapped onto the same timeline: media_ms = frame_pts - epoch_base_pts.

Health: CONNECTING -> LIVE. No new audio for longer than the gap threshold
(max(--gap-s, 1.5 x observed delivery cadence)) -> GAP; > --stale-s -> STALE;
> --restart-after-s or a process exit -> STOPPED -> bounded backoff reconnect.
A NEW source_epoch (sequence and media position restart at 0) is opened on
every process restart, on every audio pts discontinuity, on Streamlink
ad-filter/discontinuity events and on resume after GAP/STALE.

No login, OAuth, browser session token, proxy, ad-related or low-latency flag
is passed to Streamlink. Default Twitch plugin behaviour only.
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import re
import shlex
import signal
import statistics
import subprocess
import sys
import threading
import time
import uuid
import wave
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:  # optional, only for chunk RMS
    import numpy as np
except Exception:  # pragma: no cover
    np = None

SCHEMA = "p0.capture_timeline.v0"
SR = 16000
CHUNK_MS = 4000
CHUNK_SAMPLES = SR * CHUNK_MS // 1000
FRAME_INTERVAL_S = 2
PTS_JUMP_TOL_S = 0.1
CLK_TCK = os.sysconf("SC_CLK_TCK")
BACKOFF_S = [1, 2, 4, 8, 16, 30]
LOG_CAP_BYTES = 5 * 1024 * 1024
URL_QUERY_RE = re.compile(r"(https?://[^\s?\"'<>]+)\?[^\s\"'<>]*")
SHOWINFO_RE = re.compile(r"Parsed_showinfo.*?\bn:\s*(\d+)\s+pts:\s*(-?\d+)\s+pts_time:\s*(-?[0-9.]+)")
ASHOWINFO_RE = re.compile(r"Parsed_ashowinfo.*?\bn:\s*(\d+)\s+pts:\s*(-?\d+)\s+pts_time:\s*(-?[0-9.]+)"
                          r".*?nb_samples:\s*(\d+)")
SEG_QUEUE_RE = re.compile(r"Queuing \w*HLSSegment\(num=(\d+),.*?duration=([0-9.]+).*?date=([0-9T:.\-]+Z|None)"
                          r".*?ad=(True|False), prefetch=(True|False)")
SEG_DONE_RE = re.compile(r"\]\s*Segment (\d+) complete")
SCRIPT_DIR = Path(__file__).resolve().parent


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def mono() -> int:
    return time.monotonic_ns()


def ms(ns):
    return None if ns is None else round(ns / 1e6, 1)


def loadavg() -> list[float]:
    with open("/proc/loadavg") as f:
        return [float(x) for x in f.read().split()[:3]]


def pctl(xs, q):
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))], 1)


def read_proc(pid: int):
    try:
        with open(f"/proc/{pid}/stat") as f:
            s = f.read()
        rest = s[s.rindex(")") + 2:].split()
        ticks = int(rest[11]) + int(rest[12])  # utime + stime
        rss = hwm = None
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    rss = int(line.split()[1])
                elif line.startswith("VmHWM:"):
                    hwm = int(line.split()[1])
        return ticks, rss, hwm
    except (FileNotFoundError, ProcessLookupError, ValueError, IndexError):
        return None


class Timeline:
    """Append-only JSONL. `sequence` is per source_epoch and strictly increasing."""

    def __init__(self, path: Path, stream_id: str, session_id: str, source_kind: str):
        self.f = open(path, "a", buffering=1, encoding="utf-8")
        self.lock = threading.Lock()
        self.seqs: dict[str, int] = {}
        self.stream_id, self.session_id, self.source_kind = stream_id, session_id, source_kind
        self.counts: dict[str, int] = {}

    def emit(self, record_type, epoch, media_start_ms=None, media_end_ms=None, t_ns=None, **fields):
        with self.lock:
            seq = None
            if epoch is not None:
                seq = self.seqs.get(epoch, -1) + 1
                self.seqs[epoch] = seq
            rec = {"schema": SCHEMA, "record_type": record_type,
                   "host_mono_ns": t_ns if t_ns is not None else mono(), "host_wall_utc": utc_now(),
                   "stream_id": self.stream_id, "stream_session_id": self.session_id,
                   "source_kind": self.source_kind, "source_epoch": epoch, "sequence": seq,
                   "media_start_ms": media_start_ms, "media_end_ms": media_end_ms,
                   "source_wall_time_utc": None}  # null: no verified source clock mapping
            rec.update(fields)
            self.f.write(json.dumps(rec, separators=(",", ":")) + "\n")
            self.counts[record_type] = self.counts.get(record_type, 0) + 1
            return rec


class Ring:
    """Bounded on-disk ring: keeps only the newest max_items files."""

    def __init__(self, max_items: int):
        self.items: deque = deque()
        self.max, self.bytes, self.evicted, self.peak_bytes = max_items, 0, 0, 0

    def add(self, path: Path, size: int):
        self.items.append((path, size))
        self.bytes += size
        while len(self.items) > self.max:
            p, s = self.items.popleft()
            try:
                p.unlink()
            except FileNotFoundError:
                pass
            self.bytes -= s
            self.evicted += 1
        self.peak_bytes = max(self.peak_bytes, self.bytes)


class CappedLog:
    def __init__(self, path: Path):
        self.f = open(path, "w", encoding="utf-8", errors="replace")
        self.n = self.dropped = 0

    def write(self, line: str):
        line = URL_QUERY_RE.sub(r"\1?<redacted>", line)  # never keep signed playback URLs
        if self.n + len(line) > LOG_CAP_BYTES:
            self.dropped += 1
            return
        self.f.write(line + "\n")
        self.n += len(line) + 1

    def close(self):
        self.f.close()


class Attempt:
    """One source+ffmpeg process pair. May contain several epochs."""

    def __init__(self, sup: "Supervisor", index: int):
        self.sup, self.index, self.tl, a = sup, index, sup.tl, sup.args
        self.lock = threading.Lock()
        self.t_launch = mono()
        self.first_byte_ns = self.last_byte_ns = None
        self.bytes_in = 0
        self.first_audio_ns = self.last_audio_ns = None
        self.first_frame_ns = None
        self.samples = 0  # decoded samples in this ffmpeg process (process-local index)
        self.epochs: list[dict] = []
        self.pending_rotate: str | None = None
        self.disc_points: deque = deque()  # (process_sample_index, jump_s)
        self.apts: deque = deque(maxlen=20000)  # per decoded frame: (start_sample_index, pts_time, nb)
        self.apts_total = 0  # samples described by ashowinfo so far
        self.buf = bytearray()
        self.epoch_emitted = 0  # samples already emitted as chunks in the current epoch
        self.epoch_first_audio_ns = None
        self.after_gap_chunks = 0
        self.prev_chunk_done_ns = None
        self.burst_starts: deque = deque(maxlen=20)
        self.frames = 0
        self.pts_q: queue.Queue = queue.Queue()
        self.ev_counts: dict[str, int] = {}
        self.ff_warnings = 0
        self.seg_info: dict[int, tuple] = {}
        self.seg_delays_ms: list[float] = []
        self.stopped_detect_ns = None
        self.startup = None
        self.resources: dict[str, dict] = {}
        self.cpu_prev: dict[str, tuple[int, int]] = {}
        self.sl_log = CappedLog(sup.out / f"source_attempt{index}.log")
        self.ff_log = CappedLog(sup.out / f"ffmpeg_attempt{index}.log")
        self._new_epoch("PROCESS_START" if index == 0 else "PROCESS_RESTART", base_samples=0)

        if a.test_source_cmd:
            src_cmd = shlex.split(a.test_source_cmd)
        else:
            src_cmd = [a.streamlink_bin, "--loglevel", "debug",
                       "--logformat", "[{asctime}][{name}][{levelname}] {message}",
                       "--logdateformat", "%H:%M:%S.%f",
                       "--stdout", f"https://twitch.tv/{a.channel}", a.quality]
        self.r_frames, w_frames = os.pipe()
        sel = f"select='isnan(prev_selected_t)+gte(t-prev_selected_t,{FRAME_INTERVAL_S})'"
        vf = sel + (f",scale=-2:{a.frame_height}" if a.frame_height else "") + ",showinfo"
        ff_cmd = [a.ffmpeg_bin, "-hide_banner", "-nostdin", "-loglevel", "level+info", "-i", "pipe:0",
                  "-filter_complex",
                  f"[0:a:0]aresample={SR},aformat=sample_fmts=s16:channel_layouts=mono,"
                  f"ashowinfo[a];[0:v:0]{vf}[v]",
                  "-map", "[a]", "-c:a", "pcm_s16le", "-f", "s16le", "pipe:1",
                  "-map", "[v]", "-fps_mode", "passthrough", "-c:v", "mjpeg", "-q:v", str(a.jpeg_q),
                  "-f", "image2pipe", f"pipe:{w_frames}"]
        self.sl = subprocess.Popen(src_cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, bufsize=0, start_new_session=True)
        self.ff = subprocess.Popen(ff_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, bufsize=0, pass_fds=(w_frames,),
                                   start_new_session=True)
        os.close(w_frames)
        self.tl.emit("PROCESS_START", self.epoch, attempt=index, source_pid=self.sl.pid,
                     ffmpeg_pid=self.ff.pid, quality=a.quality, channel=a.channel,
                     source_args=[URL_QUERY_RE.sub(r"\1?<redacted>", x) for x in src_cmd[1:]],
                     ffmpeg_args=ff_cmd[1:], loadavg=loadavg())
        (sup.out / "pids.json").write_text(json.dumps(
            {"attempt": index, "source": self.sl.pid, "ffmpeg": self.ff.pid, "supervisor": os.getpid()}))
        sup.set_state("CONNECTING", self.epoch, attempt=index)
        self.threads = [threading.Thread(target=t, daemon=True, name=t.__name__) for t in
                        (self._pump, self._sl_stderr, self._ff_stderr, self._audio, self._frames)]
        for t in self.threads:
            t.start()

    # ---- epochs and timeline mapping ----------------------------------
    @property
    def epoch(self) -> str:
        return self.epochs[-1]["id"]

    def _pts_at(self, sample_index: int):
        """FFmpeg pts (s) of a process-local sample index, or None if not described (yet/anymore)."""
        for start, pts, nb in reversed(self.apts):
            if start <= sample_index < start + nb:
                return pts + (sample_index - start) / SR
            if start + nb <= sample_index:
                return None
        return None

    def _epoch_base_pts(self, ep):
        if ep.get("base_pts") is None:
            ep["base_pts"] = self._pts_at(ep["base_samples"])
        return ep["base_pts"]

    def _new_epoch(self, reason: str, base_samples: int, **extra):
        with self.lock:
            prev = self.epochs[-1]["id"] if self.epochs else self.sup.last_epoch
            if self.epochs:
                self.epochs[-1]["end_samples"] = base_samples
                self.epochs[-1]["end_pts"] = self._pts_at(base_samples - 1) if base_samples else None
            ep = {"id": str(uuid.uuid4()), "base_samples": base_samples, "end_samples": None,
                  "base_pts": None}
            self.epochs.append(ep)
            self.epoch_emitted = 0
            self.epoch_first_audio_ns = None
            self.sup.last_epoch = ep["id"]
            self.sup.epochs_total += 1
        self.tl.emit("EPOCH_START", ep["id"], media_start_ms=0, reason=reason, previous_epoch=prev,
                     attempt=self.index, process_sample_offset=base_samples, **extra)
        print(f"{utc_now()} EPOCH_START {ep['id'][:8]} reason={reason} {extra}", flush=True)

    def _map_frame(self, pts_time):
        """Return (epoch_id, media_ms, flags) for a frame pts on the FFmpeg timeline."""
        with self.lock:
            if pts_time is None:
                return self.epoch, None, ["PTS_UNKNOWN"]
            for ep in reversed(self.epochs):
                base_pts = self._epoch_base_pts(ep)
                if base_pts is None:
                    continue
                if pts_time + 1e-6 >= base_pts:
                    flags = []
                    if ep["end_samples"] is not None:
                        end_pts = ep.get("end_pts")
                        if end_pts is not None and pts_time > end_pts + 1.0 / SR + 0.05:
                            flags.append("IN_DISCONTINUITY_HOLE")
                    return ep["id"], int(round((pts_time - base_pts) * 1000)), flags
            return self.epochs[0]["id"], None, ["BEFORE_FIRST_AUDIO"]

    # ---- threads --------------------------------------------------------
    def _pump(self):
        src, dst = self.sl.stdout, self.ff.stdin
        try:
            while True:
                b = src.read(65536)
                if not b:
                    break
                now = mono()
                if self.first_byte_ns is None:
                    self.first_byte_ns = now
                    self.tl.emit("SOURCE_EVENT", self.epoch, t_ns=now, event="FIRST_INPUT_BYTES",
                                 since_launch_ms=ms(now - self.t_launch))
                self.last_byte_ns = now
                self.bytes_in += len(b)
                mv = memoryview(b)
                while mv:
                    n = dst.write(mv)
                    mv = mv[n:]
        except (BrokenPipeError, OSError, ValueError):
            pass
        finally:
            try:
                dst.close()
            except Exception:
                pass

    def _count(self, key):
        self.ev_counts[key] = self.ev_counts.get(key, 0) + 1
        return self.ev_counts[key]

    def _sl_stderr(self):
        for raw in iter(self.sl.stderr.readline, b""):
            now = mono()
            line = raw.decode("utf-8", "replace").rstrip()
            self.sl_log.write(line)
            m = SEG_QUEUE_RE.search(line)
            if m:
                self.seg_info[int(m.group(1))] = (float(m.group(2)), m.group(3), m.group(4) == "True",
                                                  m.group(5) == "True")
                continue
            m = SEG_DONE_RE.search(line)
            if m:
                num = int(m.group(1))
                self._count("segments_completed")
                dur, date, ad, prefetch = self.seg_info.pop(num, (None, None, None, None))
                delay = None
                if date and date != "None" and dur is not None:
                    pdt = datetime.fromisoformat(date.replace("Z", "+00:00"))
                    delay = round((datetime.now(timezone.utc) - (pdt + timedelta(seconds=dur)))
                                  .total_seconds() * 1000, 1)
                    self.seg_delays_ms.append(delay)
                self.tl.emit("SEGMENT", self.epoch, t_ns=now, segment_num=num, segment_duration_s=dur,
                             hls_program_date_time=date, ad=ad, prefetch=prefetch,
                             host_complete_minus_pdt_end_ms=delay)
                continue
            if "Writing segment" in line or "Discarding segment" in line:
                self._count("segments_written" if "Writing" in line else "segments_discarded")
                continue
            ev = None
            if "Opening stream:" in line:
                ev = "STREAM_OPENED"
            elif "Detected advertisement break" in line:
                ev = "AD_BREAK_DETECTED"
            elif "Filtering out segments and pausing stream output" in line:
                ev = "OUTPUT_PAUSED_AD_FILTER"
            elif "Resuming stream output" in line:
                ev = "OUTPUT_RESUMED"
            elif "stream discontinuity" in line:
                ev = "DISCONTINUITY"
            elif "Stream ended" in line:
                ev = "STREAM_ENDED"
            elif "[error]" in line or line.startswith("error:"):
                ev = "SOURCE_ERROR"
            elif "[warning]" in line:
                ev = "SOURCE_WARNING"
            if ev:
                n = self._count(ev)
                if ev in ("AD_BREAK_DETECTED", "OUTPUT_PAUSED_AD_FILTER", "DISCONTINUITY"):
                    self.pending_rotate = ev  # no temporal stitching across this point
                if n <= 20:
                    self.tl.emit("SOURCE_EVENT", self.epoch, t_ns=now, event=ev, origin="streamlink",
                                 message=URL_QUERY_RE.sub(r"\1?<redacted>", line)[-300:],
                                 since_launch_ms=ms(now - self.t_launch))
                if ev in ("AD_BREAK_DETECTED", "OUTPUT_PAUSED_AD_FILTER"):
                    self.sup.set_state("GAP", self.epoch, reason=ev, attempt=self.index)

    def _ff_stderr(self):
        for raw in iter(self.ff.stderr.readline, b""):
            line = raw.decode("utf-8", "replace").rstrip()
            m = ASHOWINFO_RE.search(line)
            if m:
                pts_time, nb = float(m.group(3)), int(m.group(4))
                with self.lock:
                    if self.apts:
                        _, ppts, pnb = self.apts[-1]
                        jump = pts_time - (ppts + pnb / SR)
                        if abs(jump) > PTS_JUMP_TOL_S:
                            self.disc_points.append((self.apts_total, round(jump, 3)))
                    self.apts.append((self.apts_total, pts_time, nb))
                    self.apts_total += nb
                    for ep in self.epochs[-2:]:
                        self._epoch_base_pts(ep)
                continue
            m = SHOWINFO_RE.search(line)
            if m:
                self.pts_q.put((int(m.group(1)), float(m.group(3))))
                continue
            if "showinfo" in line:
                continue
            self.ff_log.write(line)
            head = line[:60]
            if "[warning]" in head or "[error]" in head or "[fatal]" in head:
                self.ff_warnings += 1
                if self.ff_warnings <= 20:
                    self.tl.emit("SOURCE_EVENT", self.epoch, event="FFMPEG_WARNING", origin="ffmpeg",
                                 message=line[-300:], since_launch_ms=ms(mono() - self.t_launch))

    def _gap_threshold_ns(self):
        a = self.sup.args
        starts = list(self.burst_starts)
        if len(starts) >= 3:
            cadence = statistics.median([b - a_ for a_, b in zip(starts, starts[1:])]) / 1e9
        else:
            cadence = a.expected_cadence_s
        if starts and self.last_audio_ns and (self.last_audio_ns - starts[-1]) > 3 * cadence * 1e9:
            cadence = 1.0  # audio has been flowing continuously: no burst cadence to tolerate
        return int(max(a.gap_s, a.gap_cadence_factor * cadence) * 1e9)

    def _audio(self):
        src = self.ff.stdout
        carry = b""
        while True:
            b = src.read(32768)
            if not b:
                break
            now = mono()
            data = carry + b
            n = len(data) - (len(data) % 2)
            carry, data = data[n:], data[:n]
            if not data:
                continue
            if self.last_audio_ns is None or now - self.last_audio_ns > 1_000_000_000:
                self.burst_starts.append(now)
            if self.first_audio_ns is None:
                self.first_audio_ns = now
                self.sup.on_first_audio(self, now)
            elif self.sup.state != "STOPPED" and (
                    self.pending_rotate or self.sup.state in ("GAP", "STALE")
                    or (now - self.last_audio_ns) > self._gap_threshold_ns()):
                reason = self.pending_rotate or "AUDIO_RESUMED_AFTER_GAP"
                gap_wall_ms = ms(now - self.last_audio_ns)
                self._flush(now, ["CLOSED_BY_GAP"])
                self._new_epoch(reason, base_samples=self.samples, gap_wall_ms=gap_wall_ms)
                self.pending_rotate = None
                self.after_gap_chunks = 2
                self.sup.set_state("LIVE", self.epoch, reason=reason, gap_wall_ms=gap_wall_ms,
                                   attempt=self.index)
            self.last_audio_ns = now
            if self.epoch_first_audio_ns is None:
                self.epoch_first_audio_ns = now
            self.buf += data
            with self.lock:
                self.samples += len(data) // 2
            self._drain(now)

    def _drain(self, now):
        while True:
            ep = self.epochs[-1]
            buf_start = ep["base_samples"] + self.epoch_emitted
            buf_end = buf_start + len(self.buf) // 2
            with self.lock:
                disc = self.disc_points[0] if self.disc_points else None
            if disc is not None and disc[0] <= ep["base_samples"]:
                with self.lock:
                    self.disc_points.popleft()
                continue
            if disc is not None and disc[0] <= buf_end:
                with self.lock:
                    self.disc_points.popleft()
                k = disc[0] - buf_start
                flags = ["CLOSED_BY_PTS_DISCONTINUITY"]
                if k < 0:  # chunk spanning the jump was already emitted
                    flags.append("LATE_SPLIT")
                    k = 0
                if k:
                    self._write_chunk(bytes(self.buf[:2 * k]), now, flags + ["PARTIAL"])
                    del self.buf[:2 * k]
                self._new_epoch("AUDIO_PTS_DISCONTINUITY", base_samples=buf_start + k,
                                pts_jump_s=disc[1])
                self.after_gap_chunks = 2
                continue
            if len(self.buf) >= 2 * CHUNK_SAMPLES:
                self._write_chunk(bytes(self.buf[:2 * CHUNK_SAMPLES]), now, [])
                del self.buf[:2 * CHUNK_SAMPLES]
                continue
            break

    def _flush(self, now, flags):
        if self.buf:
            self._write_chunk(bytes(self.buf), now, flags + ["PARTIAL"])
            self.buf.clear()

    def _write_chunk(self, pcm: bytes, now: int, flags: list[str]):
        n = len(pcm) // 2
        start_ms = self.epoch_emitted * 1000 // SR
        end_ms = (self.epoch_emitted + n) * 1000 // SR
        self.epoch_emitted += n
        epoch = self.epoch
        fname = f"a_{epoch[:8]}_{start_ms:09d}.wav"
        path = self.sup.audio_dir / fname
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(pcm)
        size = path.stat().st_size
        self.sup.audio_ring.add(path, size)
        rms_dbfs = None
        if np is not None and n:
            x = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
            rms = float(np.sqrt(np.mean(x * x))) / 32768.0
            rms_dbfs = round(20 * np.log10(rms), 1) if rms > 0 else -120.0
        flags = list(flags)
        if self.after_gap_chunks > 0:
            flags.append("AFTER_GAP")
            self.after_gap_chunks -= 1
        if self.sup.state == "STOPPED":
            flags.append("DRAINED_AFTER_STOP")
        arrival = ms(now - self.prev_chunk_done_ns) if self.prev_chunk_done_ns else None
        self.prev_chunk_done_ns = now
        wmm = round((now - self.epoch_first_audio_ns) / 1e6 - end_ms, 1) if self.epoch_first_audio_ns else None
        self.tl.emit("AUDIO_CHUNK", epoch, media_start_ms=start_ms, media_end_ms=end_ms, t_ns=now,
                     samples=n, sample_rate=SR, evidence_ref=f"audio/{fname}", bytes=size,
                     rms_dbfs=rms_dbfs, since_prev_chunk_ms=arrival, wall_minus_media_ms=wmm,
                     quality_flags=flags, attempt=self.index)

    def _frames(self):
        buf = bytearray()
        while True:
            try:
                b = os.read(self.r_frames, 65536)
            except OSError:
                break
            if not b:
                break
            buf += b
            while True:
                s = buf.find(b"\xff\xd8")
                if s < 0:
                    del buf[:-1]
                    break
                if s > 0:
                    del buf[:s]
                e = buf.find(b"\xff\xd9", 2)
                if e < 0:
                    break
                jpg = bytes(buf[:e + 2])
                del buf[:e + 2]
                self._on_frame(jpg)
        try:
            os.close(self.r_frames)
        except OSError:
            pass

    def _on_frame(self, jpg: bytes):
        now = mono()
        try:
            n, pts_time = self.pts_q.get(timeout=5)
        except queue.Empty:
            n, pts_time = None, None
        # the 0.5 s audio pts for this region may lag the frame slightly; wait briefly
        deadline = now + 3_000_000_000
        while pts_time is not None and mono() < deadline:
            with self.lock:
                covered = self.apts and self.apts[-1][1] + self.apts[-1][2] / SR >= pts_time
            if covered:
                break
            time.sleep(0.05)
        epoch, media_ms, flags = self._map_frame(pts_time)
        if self.first_frame_ns is None:
            self.first_frame_ns = now
        self.frames += 1
        tag = f"{media_ms:09d}" if media_ms is not None else f"unk{self.frames:06d}"
        fname = f"f_{epoch[:8]}_{tag}.jpg"
        path = self.sup.frames_dir / fname
        path.write_bytes(jpg)
        self.sup.frame_ring.add(path, len(jpg))
        self.tl.emit("FRAME", epoch, media_start_ms=media_ms, media_end_ms=media_ms, t_ns=now,
                     evidence_ref=f"frames/{fname}", bytes=len(jpg), ffmpeg_frame_n=n,
                     ffmpeg_pts_s=pts_time, sample_interval_s=FRAME_INTERVAL_S, quality_flags=flags,
                     attempt=self.index)

    # ---- resources / shutdown ------------------------------------------
    def sample_resources(self):
        out = {}
        for name, pid in (("source", self.sl.pid), ("ffmpeg", self.ff.pid), ("supervisor", os.getpid())):
            r = read_proc(pid)
            if r is None:
                continue
            ticks, rss, hwm = r
            now = mono()
            cpu = None
            if name in self.cpu_prev:
                pt, pn = self.cpu_prev[name]
                if now > pn:
                    cpu = round((ticks - pt) / CLK_TCK / ((now - pn) / 1e9) * 100, 1)
            self.cpu_prev[name] = (ticks, now)
            out[name] = {"cpu_pct": cpu, "rss_mib": round(rss / 1024, 1) if rss else None,
                         "hwm_mib": round(hwm / 1024, 1) if hwm else None}
            agg = self.resources.setdefault(name, {"cpu": [], "rss_max": 0, "hwm_max": 0})
            if cpu is not None:
                agg["cpu"].append(cpu)
            agg["rss_max"] = max(agg["rss_max"], out[name]["rss_mib"] or 0)
            agg["hwm_max"] = max(agg["hwm_max"], out[name]["hwm_mib"] or 0)
        return out

    def media_pos_ms(self):
        return (self.epoch_emitted + len(self.buf) // 2) * 1000 // SR

    def shutdown(self, reason: str):
        self.sample_resources()
        if self.sl.poll() is None:
            self.sl.terminate()
            try:
                self.sl.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.sl.kill()
                self.sl.wait(timeout=5)
        try:  # ffmpeg exits by itself on EOF once the source is gone
            self.ff.wait(timeout=6)
        except subprocess.TimeoutExpired:
            self.ff.terminate()
            try:
                self.ff.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.ff.kill()
                self.ff.wait(timeout=5)
        for t in self.threads:
            t.join(timeout=5)
        self._drain(mono())
        self._flush(mono(), ["CLOSED_BY_STOP"])
        self.sl_log.close()
        self.ff_log.close()
        self.tl.emit("PROCESS_EXIT", self.epoch, attempt=self.index, reason=reason,
                     source_rc=self.sl.returncode, ffmpeg_rc=self.ff.returncode, bytes_in=self.bytes_in,
                     decoded_audio_ms=self.samples * 1000 // SR, frames=self.frames,
                     epochs=[e["id"] for e in self.epochs], source_event_counts=self.ev_counts,
                     ffmpeg_warnings=self.ff_warnings,
                     log_lines_dropped={"source": self.sl_log.dropped, "ffmpeg": self.ff_log.dropped})


class Supervisor:
    def __init__(self, args):
        self.args = args
        self.out = Path(args.out)
        self.audio_dir, self.frames_dir = self.out / "audio", self.out / "frames"
        for d in (self.audio_dir, self.frames_dir):
            d.mkdir(parents=True, exist_ok=True)
        kind = "TEST_SOURCE_CMD" if args.test_source_cmd else "TWITCH_STREAMLINK"
        self.tl = Timeline(self.out / "timeline.jsonl", f"twitch:{args.channel}",
                           args.stream_session_id or str(uuid.uuid4()), kind)
        self.audio_ring = Ring(max(1, int(args.ring_s * 1000 // CHUNK_MS)))
        self.frame_ring = Ring(max(1, int(args.ring_s // FRAME_INTERVAL_S)))
        self.state = None
        self.state_lock = threading.Lock()
        self.stop_flag = threading.Event()
        self.last_epoch = None
        self.epochs_total = 0
        self.attempt_stats: list[dict] = []
        self.pending_recovery_from_ns = None
        self.transitions: list[dict] = []

    def set_state(self, state: str, epoch: str, **fields):
        with self.state_lock:
            if state == self.state:
                return
            prev, self.state = self.state, state
        rec = self.tl.emit("HEALTH", epoch, state=state, previous_state=prev, **fields)
        self.transitions.append({"host_wall_utc": rec["host_wall_utc"], "host_mono_ns": rec["host_mono_ns"],
                                 "state": state, "previous_state": prev, "epoch": epoch, **fields})
        print(f"{rec['host_wall_utc']} HEALTH {prev} -> {state} {fields}", flush=True)

    def on_first_audio(self, att: Attempt, now: int):
        st = {"attempt": att.index,
              "first_byte_after_launch_ms": ms(att.first_byte_ns - att.t_launch) if att.first_byte_ns else None,
              "first_audio_after_launch_ms": ms(now - att.t_launch)}
        if self.pending_recovery_from_ns is not None:
            st["recovery_stop_detect_to_first_audio_ms"] = ms(now - self.pending_recovery_from_ns)
            self.pending_recovery_from_ns = None
        att.startup = st
        self.set_state("LIVE", att.epoch, **st)

    def heartbeat(self, att: Attempt):
        now = mono()
        res = att.sample_resources()
        self.tl.emit("HEALTH_HEARTBEAT", att.epoch, t_ns=now, state=self.state, attempt=att.index,
                     media_pos_ms=att.media_pos_ms(),
                     last_media_age_ms=ms(now - att.last_audio_ns) if att.last_audio_ns else None,
                     last_input_age_ms=ms(now - att.last_byte_ns) if att.last_byte_ns else None,
                     wall_minus_media_ms=round((now - att.epoch_first_audio_ns) / 1e6 - att.media_pos_ms(), 1)
                     if att.epoch_first_audio_ns else None,
                     gap_threshold_ms=ms(att._gap_threshold_ns()), bytes_in=att.bytes_in, frames=att.frames,
                     pts_queue_depth=att.pts_q.qsize(), pending_pcm_bytes=len(att.buf),
                     ring={"audio_files": len(self.audio_ring.items), "frame_files": len(self.frame_ring.items),
                           "bytes": self.audio_ring.bytes + self.frame_ring.bytes,
                           "evicted": self.audio_ring.evicted + self.frame_ring.evicted},
                     resources=res, loadavg=loadavg())

    def watch(self, att: Attempt, t_end: int) -> str:
        a = self.args
        stale_ns = int(a.stale_s * 1e9)
        restart_ns, connect_ns = int(a.restart_after_s * 1e9), int(a.connect_timeout_s * 1e9)
        next_hb = mono() + int(a.heartbeat_s * 1e9)
        att.sample_resources()
        while True:
            now = mono()
            if self.stop_flag.is_set():
                self.set_state("STOPPED", att.epoch, reason="SIGNAL", attempt=att.index)
                return "SIGNAL"
            if now >= t_end:
                self.set_state("STOPPED", att.epoch, reason="DURATION_REACHED", attempt=att.index)
                return "DURATION_REACHED"
            sl_rc, ff_rc = att.sl.poll(), att.ff.poll()
            if sl_rc is not None or ff_rc is not None:
                which = "SOURCE_EXITED" if sl_rc is not None else "FFMPEG_EXITED"
                att.stopped_detect_ns = now
                self.set_state("STOPPED", att.epoch, reason=which, source_rc=sl_rc, ffmpeg_rc=ff_rc,
                               attempt=att.index, media_pos_ms=att.media_pos_ms(),
                               last_media_age_ms=ms(now - att.last_audio_ns) if att.last_audio_ns else None)
                return which
            if att.first_audio_ns is None:
                if now - att.t_launch > connect_ns:
                    att.stopped_detect_ns = now
                    self.set_state("STOPPED", att.epoch, reason="CONNECT_TIMEOUT", attempt=att.index)
                    return "CONNECT_TIMEOUT"
            else:
                age = now - att.last_audio_ns
                gap_ns = att._gap_threshold_ns()
                if age > restart_ns:
                    att.stopped_detect_ns = now
                    self.set_state("STOPPED", att.epoch, reason="NO_MEDIA_TIMEOUT", attempt=att.index,
                                   last_media_age_ms=ms(age))
                    return "NO_MEDIA_TIMEOUT"
                if age > max(stale_ns, gap_ns) and self.state != "STALE":
                    self.set_state("STALE", att.epoch, reason="NO_NEW_AUDIO", last_media_age_ms=ms(age),
                                   media_pos_ms=att.media_pos_ms(), attempt=att.index)
                elif age > gap_ns and self.state == "LIVE":
                    self.set_state("GAP", att.epoch, reason="NO_NEW_AUDIO", last_media_age_ms=ms(age),
                                   gap_threshold_ms=ms(gap_ns), media_pos_ms=att.media_pos_ms(),
                                   attempt=att.index)
            if now >= next_hb:
                self.heartbeat(att)
                next_hb += int(a.heartbeat_s * 1e9)
            time.sleep(0.1)

    def run(self) -> int:
        a = self.args
        t0 = mono()
        t_end = t0 + int(a.duration_s * 1e9)
        label = a.label or ("TEST_SOURCE_CMD" if a.test_source_cmd else "TOOLCHAIN_SMOKE")
        self.tl.emit("RUN_START", None, channel=a.channel, quality=a.quality, duration_s=a.duration_s,
                     gap_s=a.gap_s, gap_cadence_factor=a.gap_cadence_factor, stale_s=a.stale_s,
                     restart_after_s=a.restart_after_s, ring_s=a.ring_s, chunk_ms=CHUNK_MS,
                     frame_interval_s=FRAME_INTERVAL_S, loadavg=loadavg(), label=label)
        restarts, backoff_i, index = 0, 0, 0
        while True:
            att = Attempt(self, index)
            reason = self.watch(att, t_end)
            live_s = (att.last_audio_ns - att.first_audio_ns) / 1e9 if att.first_audio_ns else 0
            att.shutdown(reason)
            res = {k: {"cpu_mean": round(sum(v["cpu"]) / len(v["cpu"]), 1) if v["cpu"] else None,
                       "cpu_max": max(v["cpu"]) if v["cpu"] else None,
                       "rss_max_mib": v["rss_max"], "hwm_max_mib": v["hwm_max"]}
                   for k, v in att.resources.items()}
            self.attempt_stats.append({
                "attempt": index, "stop_reason": reason, "startup": att.startup,
                "first_frame_after_launch_ms": ms(att.first_frame_ns - att.t_launch) if att.first_frame_ns else None,
                "live_s": round(live_s, 1), "bytes_in": att.bytes_in, "decoded_audio_s": round(att.samples / SR, 1),
                "frames": att.frames, "epochs": len(att.epochs), "source_event_counts": att.ev_counts,
                "ffmpeg_warnings": att.ff_warnings, "source_rc": att.sl.returncode, "ffmpeg_rc": att.ff.returncode,
                "segment_complete_minus_pdt_end_ms": {"n": len(att.seg_delays_ms), "p50": pctl(att.seg_delays_ms, .5),
                                                      "p95": pctl(att.seg_delays_ms, .95),
                                                      "max": max(att.seg_delays_ms) if att.seg_delays_ms else None},
                "resources": res})
            if reason in ("DURATION_REACHED", "SIGNAL") or mono() >= t_end:
                break
            if restarts >= a.max_restarts:
                self.tl.emit("RUN_GIVE_UP", self.last_epoch, restarts=restarts)
                print("giving up after max restarts", flush=True)
                break
            if live_s >= 60:
                backoff_i = 0
            delay = BACKOFF_S[min(backoff_i, len(BACKOFF_S) - 1)]
            backoff_i += 1
            restarts += 1
            self.pending_recovery_from_ns = att.stopped_detect_ns or mono()
            self.tl.emit("RECONNECT_SCHEDULED", self.last_epoch, delay_s=delay, restart_number=restarts)
            if self.stop_flag.wait(timeout=delay):
                break
            index += 1
        summary = {"label": label, "source_kind": self.tl.source_kind, "channel": a.channel,
                   "quality": a.quality, "duration_s": a.duration_s, "restarts": restarts,
                   "epochs_total": self.epochs_total, "attempts": self.attempt_stats,
                   "record_counts": self.tl.counts,
                   "health_transitions": [{k: v for k, v in t.items() if k != "host_mono_ns"}
                                          for t in self.transitions],
                   "ring": {"audio_files": len(self.audio_ring.items), "frame_files": len(self.frame_ring.items),
                            "bytes": self.audio_ring.bytes + self.frame_ring.bytes,
                            "peak_bytes": self.audio_ring.peak_bytes + self.frame_ring.peak_bytes,
                            "evicted": self.audio_ring.evicted + self.frame_ring.evicted},
                   "loadavg_end": loadavg(), "wall_s": round((mono() - t0) / 1e9, 1)}
        self.tl.emit("RUN_END", self.last_epoch, summary=summary)
        (self.out / "summary.json").write_text(json.dumps(summary, indent=1))
        print(json.dumps(summary, indent=1), flush=True)
        return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--channel", required=True)
    p.add_argument("--duration-s", type=float, default=120)
    p.add_argument("--quality", default="480p30")
    p.add_argument("--out", default=None)
    p.add_argument("--gap-s", type=float, default=5.0, help="minimum no-new-audio time before GAP")
    p.add_argument("--gap-cadence-factor", type=float, default=1.5,
                   help="GAP threshold is max(gap-s, factor x median delivery-burst interval)")
    p.add_argument("--expected-cadence-s", type=float, default=6.0,
                   help="assumed burst interval until 3 bursts are observed (measured ~6 s with defaults)")
    p.add_argument("--stale-s", type=float, default=15.0)
    p.add_argument("--restart-after-s", type=float, default=30.0)
    p.add_argument("--connect-timeout-s", type=float, default=60.0)
    p.add_argument("--max-restarts", type=int, default=6)
    p.add_argument("--ring-s", type=float, default=120.0)
    p.add_argument("--frame-height", type=int, default=0, help="0 = native variant height")
    p.add_argument("--jpeg-q", type=int, default=5)
    p.add_argument("--heartbeat-s", type=float, default=5.0)
    p.add_argument("--stream-session-id", default=None)
    p.add_argument("--label", default=None, help="evidence label; default TOOLCHAIN_SMOKE")
    p.add_argument("--streamlink-bin", default=str(SCRIPT_DIR / ".venv" / "bin" / "streamlink"))
    p.add_argument("--ffmpeg-bin", default="ffmpeg")
    p.add_argument("--test-source-cmd", default=None,
                   help="OFFLINE TEST ONLY: command whose stdout replaces Streamlink; records are "
                        "labelled source_kind=TEST_SOURCE_CMD and are never Twitch evidence")
    args = p.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_]{1,25}", args.channel):
        p.error("channel must be a Twitch login name")
    if args.out is None:
        args.out = str(SCRIPT_DIR / "out" / "capture" /
                       f"{args.channel}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}")
    sup = Supervisor(args)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: sup.stop_flag.set())
    return sup.run()


if __name__ == "__main__":
    sys.exit(main())
