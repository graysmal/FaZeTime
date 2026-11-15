"""Supervised capture: one Streamlink -> FFmpeg decode path, epochs, health, bounded local ring.

Promoted from spikes/p0-media/capture_spike.py (P0-B verified on the team channel, 2026-11-15).

    streamlink --stdout https://twitch.tv/<channel> <quality>     (or a TEST_FIXTURE command)
      -> byte pump (first-byte / input-age metering)
      -> ffmpeg -i pipe:0
           audio: aresample=16000, mono s16, ashowinfo (pts of every decoded frame) -> stdout PCM
           video: [-skip_frame:v nokey] select(>= interval since last), scale=-2:H, showinfo -> MJPEG fd

Media positions are decoded sample counts within the current source_epoch (never wall time).
ashowinfo pts give exact discontinuity points: audio is never padded with synthetic silence.
Frames are mapped onto the same timeline via their pts: media_ms = frame_pts - epoch_base_pts.

Worker health (D29, CONTRACTS §9.4):
  CONNECTING  new epoch, no decoded audio yet
  LIVE        newest decoded audio <= live_max_s old (default 12 s; Twitch delivers ~6 s bursts)
  STALE       newest decoded audio older than live_max_s (contiguous resume returns to LIVE, same epoch)
  GAP         a discontinuity was detected in this epoch (pts jump, Streamlink ad filtering or
              discontinuity); sticky; the next media opens a NEW epoch
  STOPPED     a process exited, connect timeout, or no media for > stopped_after_s -> restart with backoff
Every process (re)start and every discontinuity opens a NEW source_epoch; old epochs are never resumed.

No login, OAuth, browser session token, proxy, ad-related or low-latency flag is passed to Streamlink.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import re
import shlex
import statistics
import subprocess
import threading
import time
import wave
from collections import deque
from pathlib import Path
from typing import Protocol

from .config import Config
from .util import CpuMeter, loadavg, mono_ns, new_epoch_id, redact_urls, utc_now

log = logging.getLogger("fazetime.capture")

SR = 16000
CHUNK_MS = 4000  # local ring chunk size only (ASR windows are cut separately)
PTS_JUMP_TOL_S = 0.1
BACKOFF_S = [1, 2, 4, 8, 16, 30]
SHOWINFO_RE = re.compile(r"Parsed_showinfo.*?\bn:\s*(\d+)\s+pts:\s*(-?\d+)\s+pts_time:\s*(-?[0-9.]+)")
ASHOWINFO_RE = re.compile(r"Parsed_ashowinfo.*?\bn:\s*(\d+)\s+pts:\s*(-?\d+)\s+pts_time:\s*(-?[0-9.]+)"
                          r".*?nb_samples:\s*(\d+)")
SEG_QUEUE_RE = re.compile(r"Queuing \w*HLSSegment\(num=(\d+),.*?duration=([0-9.]+).*?date=([0-9T:.\-]+Z|None)"
                          r".*?ad=(True|False)")
SEG_DONE_RE = re.compile(r"\]\s*Segment (\d+) complete")
GAP_EVENTS = {"AD_BREAK_DETECTED", "OUTPUT_PAUSED_AD_FILTER", "DISCONTINUITY"}


class CaptureSink(Protocol):
    def on_epoch(self, epoch: str, reason: str, previous: str | None, variant: str | None,
                 started_at_utc: str) -> None: ...

    def on_pcm(self, epoch: str, pcm: bytes, media_start_ms: int, t_ns: int, captured_at_utc: str) -> None: ...

    def on_frame(self, epoch: str, jpeg: bytes, media_ms: int, width: int, height: int,
                 captured_at_utc: str, flags: list[str]) -> None: ...

    def on_gap(self, epoch: str, media_ms: int, reason: str, captured_at_utc: str) -> None: ...

    def on_state(self, state: str, epoch: str | None, info: dict) -> None: ...


def jpeg_size(data: bytes) -> tuple[int, int] | None:
    """(width, height) from the first SOFn marker, or None."""
    i = 2
    n = len(data)
    while i + 9 < n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            h = (data[i + 5] << 8) | data[i + 6]
            w = (data[i + 7] << 8) | data[i + 8]
            return w, h
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seglen = (data[i + 2] << 8) | data[i + 3]
        i += 2 + seglen
    return None


class Timeline:
    """Local diagnostic JSONL (bounded by rotation). Not the API record; contains no transcript text."""

    def __init__(self, path: Path, max_bytes: int = 20 * 1024 * 1024):
        self.path, self.max_bytes = path, max_bytes
        self.lock = threading.Lock()
        self.f = open(path, "a", buffering=1, encoding="utf-8")

    def emit(self, record_type: str, **fields):
        rec = {"record_type": record_type, "host_mono_ns": fields.pop("t_ns", None) or mono_ns(),
               "host_wall_utc": utc_now(), **fields}
        line = json.dumps(rec, separators=(",", ":"))
        with self.lock:
            if self.f.tell() + len(line) > self.max_bytes:
                self.f.close()
                os.replace(self.path, self.path.with_suffix(".jsonl.1"))
                self.f = open(self.path, "a", buffering=1, encoding="utf-8")
            self.f.write(line + "\n")

    def close(self):
        with self.lock:
            self.f.close()


class Ring:
    """Bounded on-disk ring of the newest files."""

    def __init__(self, max_items: int):
        self.items: deque = deque()
        self.max, self.bytes, self.evicted = max_items, 0, 0
        self.lock = threading.Lock()

    def add(self, path: Path, size: int):
        with self.lock:
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


class _CappedLog:
    def __init__(self, path: Path, cap: int = 5 * 1024 * 1024):
        self.f = open(path, "w", encoding="utf-8", errors="replace")
        self.n, self.cap, self.dropped = 0, cap, 0

    def write(self, line: str):
        line = redact_urls(line)
        if self.n + len(line) > self.cap:
            self.dropped += 1
            return
        self.f.write(line + "\n")
        self.n += len(line) + 1

    def close(self):
        self.f.close()


class Attempt:
    """One source + ffmpeg process pair. May contain several epochs (split at discontinuities)."""

    def __init__(self, cap: "Capture", index: int):
        self.cap, self.cfg, self.index = cap, cap.cfg, index
        self.lock = threading.Lock()
        self.t_launch = mono_ns()
        self.first_byte_ns = self.last_byte_ns = None
        self.bytes_in = 0
        self.first_audio_ns = self.last_audio_ns = None
        self.samples = 0
        self.epochs: list[dict] = []
        self.pending_rotate: str | None = None
        self.disc_points: deque = deque()
        self.apts: deque = deque(maxlen=20000)
        self.apts_total = 0
        self.ring_buf = bytearray()
        self.epoch_ring_emitted = 0
        self.epoch_samples = 0
        self.burst_starts: deque = deque(maxlen=20)
        self.frames = 0
        self.frames_skipped = 0
        self.pts_q: queue.Queue = queue.Queue(maxsize=1000)
        self.ev_counts: dict[str, int] = {}
        self.seg_info: dict[int, tuple] = {}
        self.seg_delays_ms: deque = deque(maxlen=300)
        self.stopped_detect_ns = None
        self.startup: dict | None = None
        self.ad_paused = False  # Streamlink is filtering ad segments: output is paused on purpose
        self.src_log = _CappedLog(cap.data_dir / f"source_attempt{index % 10}.log")
        self.ff_log = _CappedLog(cap.data_dir / f"ffmpeg_attempt{index % 10}.log")
        self._new_epoch("PROCESS_START" if index == 0 else "PROCESS_RESTART", base_samples=0)
        c = self.cfg
        if c.test_source_cmd:
            src_cmd = shlex.split(c.test_source_cmd)
        else:
            src_cmd = [c.streamlink_bin, "--loglevel", "debug",
                       "--logformat", "[{asctime}][{name}][{levelname}] {message}",
                       "--logdateformat", "%H:%M:%S.%f",
                       "--stdout", f"https://twitch.tv/{c.channel}", c.quality]
        self.r_frames, w_frames = os.pipe()
        # keyframes ~2 s apart are not always >= 2.000 s apart; full decode can hit the interval exactly
        gap = max(0.1, c.frame_interval_s - (0.1 if c.keyframes_only else 0.0))
        sel = f"select='isnan(prev_selected_t)+gte(t-prev_selected_t,{gap:.2f})'"
        vf = sel + (f",scale=-2:{c.frame_height}" if c.frame_height else "") + ",showinfo"
        ff_cmd = [c.ffmpeg_bin, "-hide_banner", "-nostdin", "-loglevel", "level+info"]
        if c.keyframes_only:
            ff_cmd += ["-skip_frame:v", "nokey"]
        ff_cmd += ["-i", "pipe:0", "-filter_complex",
                   f"[0:a:0]aresample={SR},aformat=sample_fmts=s16:channel_layouts=mono,ashowinfo[a];[0:v:0]{vf}[v]",
                   "-map", "[a]", "-c:a", "pcm_s16le", "-f", "s16le", "pipe:1",
                   "-map", "[v]", "-fps_mode", "passthrough", "-c:v", "mjpeg", "-q:v", str(c.jpeg_q),
                   "-f", "image2pipe", f"pipe:{w_frames}"]
        self.src = subprocess.Popen(src_cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, bufsize=0, start_new_session=True)
        self.ff = subprocess.Popen(ff_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   bufsize=0, pass_fds=(w_frames,), start_new_session=True)
        os.close(w_frames)
        cap.tl.emit("PROCESS_START", attempt=index, source_pid=self.src.pid, ffmpeg_pid=self.ff.pid,
                    source_kind=c.source_kind, quality=c.quality, keyframes_only=c.keyframes_only,
                    source_args=[redact_urls(x) for x in src_cmd[1:]], ffmpeg_args=ff_cmd[1:], loadavg=loadavg())
        cap.set_state("CONNECTING", self.epoch, {"attempt": index})
        self.threads = [threading.Thread(target=t, daemon=True, name=f"cap-{t.__name__}") for t in
                        (self._pump, self._src_stderr, self._ff_stderr, self._audio, self._frames)]
        for t in self.threads:
            t.start()

    # ---- epochs ------------------------------------------------------------------------------------
    @property
    def epoch(self) -> str:
        return self.epochs[-1]["id"]

    def _pts_at(self, sample_index: int):
        for start, pts, nb in reversed(self.apts):
            if start <= sample_index < start + nb:
                return pts + (sample_index - start) / SR
            if start + nb <= sample_index:
                return None
        return None

    def _base_pts(self, ep):
        if ep.get("base_pts") is None:
            ep["base_pts"] = self._pts_at(ep["base_samples"])
        return ep["base_pts"]

    def _new_epoch(self, reason: str, base_samples: int, **extra):
        with self.lock:
            prev = self.epochs[-1]["id"] if self.epochs else self.cap.last_epoch
            if self.epochs:
                self.epochs[-1]["end_samples"] = base_samples
                self.epochs[-1]["end_pts"] = self._pts_at(base_samples - 1) if base_samples else None
            ep = {"id": new_epoch_id(), "base_samples": base_samples, "end_samples": None, "base_pts": None}
            self.epochs.append(ep)
            self.epoch_ring_emitted = 0
            self.epoch_samples = 0
            self.cap.last_epoch = ep["id"]
            self.cap.epochs_total += 1
        started = utc_now()
        self.cap.tl.emit("EPOCH_START", source_epoch=ep["id"], reason=reason, previous_epoch=prev,
                         attempt=self.index, process_sample_offset=base_samples, **extra)
        log.info("epoch %s reason=%s previous=%s %s", ep["id"], reason, prev, extra or "")
        variant = None if self.cfg.test_source_cmd else self.cfg.quality
        self.cap.sink.on_epoch(ep["id"], reason, prev, variant, started)

    def _map_frame(self, pts_time):
        with self.lock:
            if pts_time is None:
                return self.epoch, None, ["PTS_UNKNOWN"]
            for ep in reversed(self.epochs):
                base_pts = self._base_pts(ep)
                if base_pts is None:
                    continue
                if pts_time + 1e-6 >= base_pts:
                    flags = []
                    end_pts = ep.get("end_pts")
                    if ep["end_samples"] is not None and end_pts is not None and pts_time > end_pts + 0.05:
                        flags.append("IN_DISCONTINUITY_HOLE")
                    return ep["id"], int(round((pts_time - base_pts) * 1000)), flags
            return self.epochs[0]["id"], None, ["BEFORE_FIRST_AUDIO"]

    def media_pos_ms(self) -> int:
        return self.epoch_samples * 1000 // SR

    # ---- threads -----------------------------------------------------------------------------------
    def _pump(self):
        src, dst = self.src.stdout, self.ff.stdin
        try:
            while True:
                b = src.read(65536)
                if not b:
                    break
                now = mono_ns()
                if self.first_byte_ns is None:
                    self.first_byte_ns = now
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

    def _src_stderr(self):
        for raw in iter(self.src.stderr.readline, b""):
            line = raw.decode("utf-8", "replace").rstrip()
            self.src_log.write(line)
            m = SEG_QUEUE_RE.search(line)
            if m:
                if len(self.seg_info) > 200:
                    self.seg_info.clear()
                self.seg_info[int(m.group(1))] = (float(m.group(2)), m.group(3), m.group(4) == "True")
                continue
            m = SEG_DONE_RE.search(line)
            if m:
                self._count("segments_completed")
                dur, date, ad = self.seg_info.pop(int(m.group(1)), (None, None, None))
                if date and date != "None" and dur is not None:
                    from datetime import datetime, timedelta, timezone
                    pdt = datetime.fromisoformat(date.replace("Z", "+00:00"))
                    delay = (datetime.now(timezone.utc) - (pdt + timedelta(seconds=dur))).total_seconds() * 1000
                    self.seg_delays_ms.append(round(delay, 1))
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
            if ev == "OUTPUT_PAUSED_AD_FILTER":
                self.ad_paused = True
            elif ev == "OUTPUT_RESUMED":
                self.ad_paused = False
            if ev:
                n = self._count(ev)
                if n <= 20:
                    self.cap.tl.emit("SOURCE_EVENT", source_epoch=self.epoch, event=ev, message=redact_urls(line)[-300:],
                                     since_launch_ms=round((mono_ns() - self.t_launch) / 1e6, 1))
                if ev in GAP_EVENTS and self.first_audio_ns is not None:
                    self.pending_rotate = "AFTER_GAP"
                    if self.cap.state != "GAP":
                        self.cap.report_gap(self.epoch, self.media_pos_ms(), ev)

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
                        self._base_pts(ep)
                continue
            m = SHOWINFO_RE.search(line)
            if m:
                try:
                    self.pts_q.put_nowait((int(m.group(1)), float(m.group(3))))
                except queue.Full:
                    pass
                continue
            if "showinfo" in line:
                continue
            self.ff_log.write(line)
            head = line[:60]
            if "[error]" in head or "[fatal]" in head or "[warning]" in head:
                if self._count("FFMPEG_WARNING") <= 20:
                    self.cap.tl.emit("SOURCE_EVENT", source_epoch=self.epoch, event="FFMPEG_WARNING",
                                     message=line[-300:])

    def _audio(self):
        src = self.ff.stdout
        carry = b""
        while True:
            b = src.read(32768)
            if not b:
                break
            now = mono_ns()
            data = carry + b
            n = len(data) - (len(data) % 2)
            carry, data = data[n:], data[:n]
            if not data:
                continue
            if self.last_audio_ns is None or now - self.last_audio_ns > 1_000_000_000:
                self.burst_starts.append(now)
            if self.first_audio_ns is None:
                self.last_audio_ns = now  # set before first_audio_ns: the watcher reads both
                self.first_audio_ns = now
                self.cap.on_first_audio(self, now)
            elif self.pending_rotate and self.cap.state != "STOPPED":
                reason = self.pending_rotate
                self.pending_rotate = None
                self._flush_ring(["CLOSED_BY_GAP"])
                self._new_epoch(reason, base_samples=self.samples,
                                gap_wall_ms=round((now - self.last_audio_ns) / 1e6, 1))
                self.cap.set_state("LIVE", self.epoch, {"reason": reason, "attempt": self.index})
            elif self.cap.state == "STALE":
                self.cap.set_state("LIVE", self.epoch, {"reason": "AUDIO_RESUMED", "attempt": self.index,
                                                        "stall_ms": round((now - self.last_audio_ns) / 1e6, 1)})
            self.last_audio_ns = now
            with self.lock:
                self.samples += len(data) // 2
            self._deliver(data, now)

    def _deliver(self, data: bytes, now: int):
        """Split PCM at discontinuity points; hand each epoch's contiguous PCM to the sink and ring."""
        captured = utc_now()
        while data:
            ep = self.epochs[-1]
            start_idx = ep["base_samples"] + self.epoch_samples
            end_idx = start_idx + len(data) // 2
            with self.lock:
                while self.disc_points and self.disc_points[0][0] <= ep["base_samples"]:
                    self.disc_points.popleft()
                disc = self.disc_points[0] if self.disc_points else None
            if disc is not None and disc[0] < end_idx:
                with self.lock:
                    self.disc_points.popleft()
                k = max(0, disc[0] - start_idx)
                if k:
                    self._emit_pcm(ep, data[:2 * k], now, captured)
                    data = data[2 * k:]
                old = self.epoch
                self._flush_ring(["CLOSED_BY_PTS_DISCONTINUITY"])
                self.cap.report_gap(old, self.media_pos_ms(), "PTS_DISCONTINUITY")
                self._new_epoch("PTS_DISCONTINUITY", base_samples=start_idx + k, pts_jump_s=disc[1])
                self.cap.set_state("LIVE", self.epoch, {"reason": "PTS_DISCONTINUITY", "attempt": self.index})
                continue
            self._emit_pcm(ep, data, now, captured)
            data = b""

    def _emit_pcm(self, ep, pcm: bytes, now: int, captured: str):
        start_ms = self.epoch_samples * 1000 // SR
        self.epoch_samples += len(pcm) // 2
        self.cap.sink.on_pcm(ep["id"], pcm, start_ms, now, captured)
        self.ring_buf += pcm
        while len(self.ring_buf) >= 2 * SR * CHUNK_MS // 1000:
            n = 2 * SR * CHUNK_MS // 1000
            self._write_ring(bytes(self.ring_buf[:n]), [])
            del self.ring_buf[:n]

    def _flush_ring(self, flags):
        if self.ring_buf:
            self._write_ring(bytes(self.ring_buf), flags + ["PARTIAL"])
            self.ring_buf.clear()

    def _write_ring(self, pcm: bytes, flags):
        n = len(pcm) // 2
        start_ms = self.epoch_ring_emitted * 1000 // SR
        self.epoch_ring_emitted += n
        path = self.cap.audio_dir / f"a_{self.epoch}_{start_ms:09d}.wav"
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(pcm)
        self.cap.audio_ring.add(path, path.stat().st_size)
        self.cap.tl.emit("AUDIO_CHUNK", source_epoch=self.epoch, media_start_ms=start_ms,
                         media_end_ms=start_ms + n * 1000 // SR, quality_flags=flags)

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
            if len(buf) > 8 * 1024 * 1024:  # corrupt stream guard
                buf.clear()
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
        try:
            _, pts_time = self.pts_q.get(timeout=5)
        except queue.Empty:
            pts_time = None
        deadline = mono_ns() + 3_000_000_000
        while pts_time is not None and mono_ns() < deadline:
            with self.lock:
                covered = self.apts and self.apts[-1][1] + self.apts[-1][2] / SR >= pts_time
            if covered:
                break
            time.sleep(0.05)
        epoch, media_ms, flags = self._map_frame(pts_time)
        self.frames += 1
        size = jpeg_size(jpg)
        if media_ms is None or size is None or epoch != self.cap.sequencer_epoch():
            self.frames_skipped += 1  # no position on the current timeline: never uploaded
            return
        path = self.cap.frames_dir / f"f_{epoch}_{media_ms:09d}.jpg"
        path.write_bytes(jpg)
        self.cap.frame_ring.add(path, len(jpg))
        self.cap.tl.emit("FRAME", source_epoch=epoch, media_ms=media_ms, bytes=len(jpg), ffmpeg_pts_s=pts_time,
                         quality_flags=flags)
        self.cap.sink.on_frame(epoch, jpg, media_ms, size[0], size[1], utc_now(), flags)

    # ---- resources / shutdown ---------------------------------------------------------------------
    def shutdown(self, reason: str):
        if self.src.poll() is None:
            self.src.terminate()
            try:
                self.src.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.src.kill()
                self.src.wait(timeout=5)
        try:
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
        self._flush_ring(["CLOSED_BY_STOP"])
        self.src_log.close()
        self.ff_log.close()
        self.cap.tl.emit("PROCESS_EXIT", attempt=self.index, reason=reason, source_rc=self.src.returncode,
                         ffmpeg_rc=self.ff.returncode, bytes_in=self.bytes_in,
                         decoded_audio_ms=self.samples * 1000 // SR, frames=self.frames,
                         frames_skipped=self.frames_skipped, epochs=[e["id"] for e in self.epochs],
                         source_event_counts=self.ev_counts)


class Capture:
    def __init__(self, cfg: Config, sink: CaptureSink, sequencer_epoch=lambda: None):
        self.cfg, self.sink = cfg, sink
        self.sequencer_epoch = sequencer_epoch  # callable -> epoch currently accepted downstream
        self.data_dir = Path(cfg.data_dir)
        self.audio_dir, self.frames_dir = self.data_dir / "ring" / "audio", self.data_dir / "ring" / "frames"
        for d in (self.audio_dir, self.frames_dir):
            d.mkdir(parents=True, exist_ok=True)
        self.tl = Timeline(self.data_dir / "capture_timeline.jsonl")
        self.audio_ring = Ring(max(1, int(cfg.ring_s * 1000 // CHUNK_MS)))
        self.frame_ring = Ring(max(1, int(cfg.ring_s // cfg.frame_interval_s)))
        self.state: str | None = None
        self.state_lock = threading.Lock()
        self.stop_flag = threading.Event()
        self.last_epoch: str | None = None
        self.epochs_total = 0
        self.attempt: Attempt | None = None
        self.restarts = 0
        self.pending_recovery_from_ns = None
        self.cpu = CpuMeter()

    # ---- state ---------------------------------------------------------------------------------------
    def set_state(self, state: str, epoch: str | None, info: dict):
        with self.state_lock:
            if state == self.state and not info.get("force"):
                return
            prev, self.state = self.state, state
        self.tl.emit("HEALTH", state=state, previous_state=prev, source_epoch=epoch, **info)
        log.info("health %s -> %s epoch=%s %s", prev, state, epoch, info)
        self.sink.on_state(state, epoch, {"previous_state": prev, **info})

    def report_gap(self, epoch: str, media_ms: int, reason: str):
        self.set_state("GAP", epoch, {"reason": reason, "media_ms": media_ms})
        self.sink.on_gap(epoch, media_ms, reason, utc_now())

    def on_first_audio(self, att: Attempt, now: int):
        st = {"attempt": att.index,
              "first_byte_after_launch_ms": round((att.first_byte_ns - att.t_launch) / 1e6, 1)
              if att.first_byte_ns else None,
              "first_audio_after_launch_ms": round((now - att.t_launch) / 1e6, 1)}
        if self.pending_recovery_from_ns is not None:
            st["recovery_stop_to_first_audio_ms"] = round((now - self.pending_recovery_from_ns) / 1e6, 1)
            self.pending_recovery_from_ns = None
        att.startup = st
        self.set_state("LIVE", att.epoch, st)

    def burst_cadence_s(self) -> float | None:
        att = self.attempt
        if att is None:
            return None
        starts = list(att.burst_starts)
        if len(starts) < 3:
            return None
        return round(statistics.median([b - a for a, b in zip(starts, starts[1:])]) / 1e9, 2)

    def status(self) -> dict:
        """Snapshot for the heartbeat (CONTRACTS §9.16 item 2) and local diagnostics."""
        att = self.attempt
        now = mono_ns()
        if att is None:
            return {"state": self.state or "STOPPED", "source_epoch": None, "last_media_end_ms": None,
                    "last_input_age_ms": None}
        return {
            "state": self.state or "CONNECTING",
            "source_epoch": att.epoch,
            "last_media_end_ms": att.media_pos_ms() if att.first_audio_ns else None,
            "last_media_age_ms": int((now - att.last_audio_ns) / 1e6) if att.last_audio_ns else None,
            "last_input_age_ms": int((now - att.last_byte_ns) / 1e6) if att.last_byte_ns else None,
            "burst_cadence_s": self.burst_cadence_s(),
            "attempt": att.index, "restarts": self.restarts, "epochs_total": self.epochs_total,
            "frames": att.frames, "frames_skipped": att.frames_skipped,
            "segment_delay_ms_p50": statistics.median(att.seg_delays_ms) if att.seg_delays_ms else None,
        }

    def resources(self) -> dict:
        att = self.attempt
        out = {}
        if att is not None:
            for name, pid in (("source", att.src.pid), ("ffmpeg", att.ff.pid)):
                r = self.cpu.sample(pid)
                if r:
                    out[name] = r
        r = self.cpu.sample(os.getpid())
        if r:
            out["worker"] = r
        return out

    # ---- supervisor ----------------------------------------------------------------------------------
    def _watch(self, att: Attempt, t_end: int | None) -> str:
        c = self.cfg
        live_ns, stop_ns, connect_ns = int(c.live_max_s * 1e9), int(c.stopped_after_s * 1e9), int(c.connect_timeout_s * 1e9)
        while True:
            now = mono_ns()
            if self.stop_flag.is_set():
                return "SIGNAL"
            if t_end is not None and now >= t_end:
                return "DURATION_REACHED"
            sl_rc, ff_rc = att.src.poll(), att.ff.poll()
            if sl_rc is not None or ff_rc is not None:
                att.stopped_detect_ns = now
                return "SOURCE_EXITED" if sl_rc is not None else "FFMPEG_EXITED"
            if att.first_audio_ns is None or att.last_audio_ns is None:
                if now - att.t_launch > connect_ns:
                    att.stopped_detect_ns = now
                    return "CONNECT_TIMEOUT"
            else:
                age = now - att.last_audio_ns
                # during a Streamlink ad pause the state is already GAP; restarting would only fetch
                # another preroll, so wait up to ad_pause_max_s before treating it as a dead source
                limit = int(c.ad_pause_max_s * 1e9) if att.ad_paused else stop_ns
                if age > limit:
                    att.stopped_detect_ns = now
                    return "NO_MEDIA_TIMEOUT"
                if age > live_ns and self.state == "LIVE":
                    self.set_state("STALE", att.epoch, {"reason": "NO_NEW_AUDIO", "last_media_age_ms": int(age / 1e6),
                                                        "attempt": att.index})
            time.sleep(0.1)

    def run(self, duration_s: float | None = None) -> None:
        t_end = None if duration_s is None else mono_ns() + int(duration_s * 1e9)
        backoff_i, index = 0, 0
        self.tl.emit("RUN_START", config={k: v for k, v in self.cfg.public_dict().items()
                                          if not k.startswith("asr_")})
        while not self.stop_flag.is_set():
            att = Attempt(self, index)
            self.attempt = att
            try:
                reason = self._watch(att, t_end)
            except Exception:  # a supervisor bug must become a restart, never a silent dead capture
                log.exception("capture watcher failed; restarting the attempt")
                att.stopped_detect_ns = mono_ns()
                reason = "SUPERVISOR_ERROR"
            live_s = (att.last_audio_ns - att.first_audio_ns) / 1e9 if att.first_audio_ns else 0
            self.set_state("STOPPED", att.epoch, {"reason": reason, "attempt": att.index,
                                                  "source_rc": att.src.poll(), "ffmpeg_rc": att.ff.poll()})
            att.shutdown(reason)
            if reason in ("DURATION_REACHED", "SIGNAL") or (t_end is not None and mono_ns() >= t_end):
                break
            if self.restarts >= self.cfg.max_restarts:
                log.error("giving up after %d restarts", self.restarts)
                break
            if live_s >= 60:
                backoff_i = 0
            delay = BACKOFF_S[min(backoff_i, len(BACKOFF_S) - 1)]
            backoff_i += 1
            self.restarts += 1
            self.pending_recovery_from_ns = att.stopped_detect_ns or mono_ns()
            self.tl.emit("RECONNECT_SCHEDULED", delay_s=delay, restart_number=self.restarts)
            if self.stop_flag.wait(timeout=delay):
                break
            index += 1
        self.tl.emit("RUN_END", restarts=self.restarts, epochs_total=self.epochs_total)

    def stop(self):
        self.stop_flag.set()
