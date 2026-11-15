"""Wires capture -> ASR -> uplink, plus the 5 s heartbeat (CONTRACTS §9.16)."""
from __future__ import annotations

import json
import logging
import os
import signal
import threading
import time
from pathlib import Path

from .api_client import ApiClient, DryRunClient, FrameOp, ObservationOp, RegisterEpoch, Uplink
from .asr import AsrWorker, BoundedQueue, FakeEngine, FasterWhisperEngine, Window, Windower
from .capture import Capture
from .config import Config
from .util import EpochSequencer, StaleEpochError, loadavg, mono_ns, utc_now

log = logging.getLogger("fazetime.worker")
MAX_FRAME_BYTES = 300 * 1024


class Pipeline:
    """Capture sink + ASR publisher. All callbacks are thread-safe (queues and locks only)."""

    def __init__(self, cfg: Config, engine=None, client=None):
        self.cfg = cfg
        self.data_dir = Path(cfg.data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.seq = EpochSequencer()
        if client is None:
            client = (DryRunClient(self.data_dir / "uplink_dryrun.jsonl") if cfg.dry_run
                      else ApiClient(cfg.api_base, cfg.token, cfg.http_timeout_s))
        self.client = client
        self.uplink = Uplink(client, cfg.stream_id or "str_" + "0" * 32, max_queue=cfg.uplink_queue_max,
                             batch_max=cfg.batch_max_items, batch_wait_s=cfg.batch_max_wait_s)
        self.queue = BoundedQueue(cfg.asr_queue_max)
        self.windower = Windower(cfg.asr_window_ms, cfg.asr_hop_ms, self.queue.put)
        if engine is None:
            engine = (FakeEngine() if cfg.asr_engine == "fake" else
                      FasterWhisperEngine(cfg.asr_model, cfg.asr_threads, cfg.asr_beam, cfg.asr_temperature,
                                          cfg.asr_max_new_tokens, cfg.asr_hotwords, cfg.asr_initial_prompt,
                                          str(cfg.models_dir) if cfg.models_dir else None))
        self.asr = AsrWorker(engine, self.queue, self.seq.is_current, self.publish_transcript, cfg.asr_max_wait_s,
                             cfg.asr_low_logprob, cfg.asr_high_no_speech)
        self.capture = Capture(cfg, self, sequencer_epoch=lambda: self.seq.current)
        self.stop_flag = threading.Event()
        self.counts = {"frames_too_large": 0, "late_items_dropped": 0, "gaps": 0, "heartbeats_ok": 0,
                       "heartbeats_failed": 0}
        self._hb_lock = threading.Lock()
        self._last_hb_ns = 0
        self.status_path = self.data_dir / "worker_status.jsonl"

    # ---- CaptureSink -------------------------------------------------------------------------------
    def on_epoch(self, epoch, reason, previous, variant, started_at_utc):
        self.seq.open(epoch)
        self.queue.drop_epochs_except(epoch)
        self.uplink.put(RegisterEpoch({
            "schema_version": 1, "stream_id": self.uplink.stream_id, "source_epoch": epoch,
            "source_kind": self.cfg.source_kind, "reason": reason, "variant": variant,
            "host_id": self.cfg.host_id, "started_at_utc": started_at_utc}))

    def on_pcm(self, epoch, pcm, media_start_ms, t_ns, captured_at_utc):
        self.windower.feed(epoch, pcm, media_start_ms, t_ns, captured_at_utc)

    def on_frame(self, epoch, jpeg, media_ms, width, height, captured_at_utc, flags):
        if len(jpeg) > MAX_FRAME_BYTES:
            self.counts["frames_too_large"] += 1
            return
        try:
            seq = self.seq.next(epoch)
        except StaleEpochError:
            self.counts["late_items_dropped"] += 1
            return
        self.uplink.put(FrameOp(epoch, seq, media_ms, width, height, jpeg, captured_at_utc, flags))

    def on_gap(self, epoch, media_ms, reason, captured_at_utc):
        try:
            seq = self.seq.next(epoch)
        except StaleEpochError:
            self.counts["late_items_dropped"] += 1
            return
        self.counts["gaps"] += 1
        self.uplink.put(ObservationOp(epoch, {
            "sequence": seq, "kind": "GAP", "media_start_ms": media_ms, "media_end_ms": media_ms,
            "captured_at_utc": captured_at_utc, "source_wall_time_utc": None, "quality_flags": [],
            "transcript": None, "evidence_id": None, "gap": {"reason": reason[:64]}}))

    def on_state(self, state, epoch, info):
        if state in ("GAP", "STOPPED", "STALE", "LIVE"):
            threading.Thread(target=self.send_heartbeat, daemon=True, name="hb-now").start()

    # ---- ASR publisher -----------------------------------------------------------------------------
    def publish_transcript(self, w: Window, text, avg_logprob, no_speech_prob, model, flags, latency_ms):
        try:
            seq = self.seq.next(w.epoch)
        except StaleEpochError:
            self.counts["late_items_dropped"] += 1
            return
        self.uplink.put(ObservationOp(w.epoch, {
            "sequence": seq, "kind": "TRANSCRIPT", "media_start_ms": w.media_start_ms,
            "media_end_ms": w.media_end_ms, "captured_at_utc": w.captured_at_utc, "source_wall_time_utc": None,
            "quality_flags": sorted(set(flags)),
            "transcript": {"text": text, "avg_logprob": avg_logprob,
                           "no_speech_prob": None if no_speech_prob is None else min(1.0, max(0.0, no_speech_prob)),
                           "model": model[:64], "language": "en"},
            "evidence_id": None, "gap": None}))

    # ---- heartbeat / status ---------------------------------------------------------------------------
    def heartbeat_body(self) -> dict:
        st = self.capture.status()
        epoch = st["source_epoch"]
        registered = self.uplink.is_registered(epoch)
        state = st["state"] if registered else "CONNECTING"
        now = mono_ns()
        live_ns = int(self.cfg.live_max_s * 1e9)
        if state == "LIVE" and (self.queue.backlog_ms(now) > self.cfg.live_max_s * 1000
                                or (self.queue.last_drop_ns and now - self.queue.last_drop_ns < live_ns)):
            state = "STALE"  # ASR is not keeping up: windows were skipped; never present that as LIVE
        return {
            "schema_version": 1, "stream_id": self.uplink.stream_id,
            "source_epoch": epoch if registered else None,
            "worker_state": state,
            "last_media_end_ms": st["last_media_end_ms"] if registered else None,
            "last_input_age_ms": st["last_input_age_ms"],
            "asr_backlog_ms": self.queue.backlog_ms(), "queue_depth": self.queue.depth(),
            "gap_threshold_ms": int(self.cfg.live_max_s * 1000), "host_id": self.cfg.host_id,
            "host_wall_utc": utc_now(),
        }

    def send_heartbeat(self):
        with self._hb_lock:
            if mono_ns() - self._last_hb_ns < 1_000_000_000:  # at most 1/s (state changes trigger extras)
                return
            self._last_hb_ns = mono_ns()
            res = self.uplink.heartbeat(self.heartbeat_body())
            self.counts["heartbeats_ok" if res.ok else "heartbeats_failed"] += 1
            if not res.ok:
                log.warning("heartbeat failed: %s %s", res.status or res.error, res.code)

    def status(self) -> dict:
        return {"at": utc_now(), "capture": self.capture.status(), "resources": self.capture.resources(),
                "asr": self.asr.stats() | {"queue_depth": self.queue.depth(), "backlog_ms": self.queue.backlog_ms(),
                                           "partial_windows_discarded": self.windower.discarded_partial},
                "uplink": self.uplink.stats | {"depth": self.uplink.depth(), "last_error": self.uplink.last_error,
                                               "server_current_epoch": self.uplink.server_current_epoch},
                "counts": self.counts, "loadavg": loadavg()}

    def _loop(self):
        next_hb = mono_ns()
        next_status = mono_ns() + 30_000_000_000
        while not self.stop_flag.is_set():
            now = mono_ns()
            if now >= next_hb:
                self.send_heartbeat()
                next_hb = now + int(self.cfg.heartbeat_s * 1e9)
            if now >= next_status:
                self._write_status()
                next_status = now + 30_000_000_000
            self.stop_flag.wait(0.25)

    def _write_status(self):
        st = self.status()
        try:
            if self.status_path.exists() and self.status_path.stat().st_size > 20 * 1024 * 1024:
                os.replace(self.status_path, self.status_path.with_suffix(".jsonl.1"))
            with open(self.status_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(st, separators=(",", ":")) + "\n")
        except OSError:
            log.exception("status write failed")
        c, a, u = st["capture"], st["asr"], st["uplink"]
        log.info("status state=%s epoch=%s media_ms=%s asr_p95=%sms backlog=%sms dropped=%s/%s/%s uplink=%s acc=%s",
                 c.get("state"), c.get("source_epoch"), c.get("last_media_end_ms"), a.get("proc_ms_p95"),
                 a.get("backlog_ms"), a.get("dropped_full"), a.get("dropped_stale"), a.get("dropped_superseded"),
                 u.get("depth"), u.get("obs_accepted"))

    # ---- lifecycle ----------------------------------------------------------------------------------
    def run(self, duration_s: float | None = None) -> dict:
        log.info("worker start %s", json.dumps(self.cfg.public_dict(), default=str))
        self.uplink.start()
        self.asr.start()
        loop = threading.Thread(target=self._loop, daemon=True, name="heartbeat")
        loop.start()
        try:
            self.capture.run(duration_s)
        finally:
            self.stop_flag.set()
            loop.join(timeout=2)
            self.asr.stop_flag.set()
            self.asr.join(timeout=30)
            self.send_heartbeat_final()
            self.uplink.drain(timeout_s=15)
            self.uplink.stop()
            self.uplink.join(timeout=5)
            self._write_status()
            self.capture.tl.close()
        return self.status()

    def send_heartbeat_final(self):
        with self._hb_lock:
            self._last_hb_ns = 0
        self.send_heartbeat()

    def stop(self, *_):
        self.capture.stop()


def install_signal_handlers(p: Pipeline):
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, p.stop)
