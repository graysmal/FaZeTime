#!/usr/bin/env python3
"""Fixture prep for the game-agnostic proposer/resolver replay (D37).

LOCAL FIXTURE ONLY. This never satisfies the Twitch ingestion gate (AGENTS fixed constraints, D05).

Given one local video, writes the following outside the repository (media and transcripts are never committed):
  <out>/probe.json            ffprobe summary
  <out>/audio.wav             16 kHz mono PCM
  <out>/transcript.json       faster-whisper segments with word timestamps, in media seconds
  <out>/frames/f_000123.jpg   one 854x480 JPEG per media second (the number is the media second)

Run with the worker venv (it has faster-whisper):
  services/worker/.venv/bin/python -I spikes/p4-generic/prep_fixture.py VIDEO OUT_DIR [--model small.en]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MODELS_DIR = REPO / "spikes" / "p0-media" / "models"  # HF cache layout with tiny.en, base.en, small.en


def run(cmd: list[str]) -> str:
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


def probe(src: Path) -> dict:
    raw = json.loads(run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(src)]))
    out = {"duration_s": float(raw["format"].get("duration", 0.0)), "size_bytes": int(raw["format"].get("size", 0)),
           "streams": []}
    for s in raw.get("streams", []):
        out["streams"].append({k: s.get(k) for k in ("index", "codec_type", "codec_name", "width", "height",
                                                     "avg_frame_rate", "sample_rate", "channels", "duration")})
    return out


def extract_audio(src: Path, wav: Path) -> None:
    run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
         str(wav)])


def extract_frames(src: Path, frames: Path, height: int) -> int:
    frames.mkdir(parents=True, exist_ok=True)
    # fps=1 puts frames at media seconds 0, 1, 2, ...; -frame_pts makes the file number that second.
    run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vf", f"fps=1,scale=-2:{height}", "-q:v", "4",
         "-frame_pts", "1", str(frames / "f_%06d.jpg")])
    return len(list(frames.glob("f_*.jpg")))


def transcribe(wav: Path, model: str, threads: int) -> dict:
    from faster_whisper import WhisperModel

    import wave

    import numpy as np

    m = WhisperModel(model, device="cpu", compute_type="int8", cpu_threads=threads, num_workers=1,
                     download_root=str(MODELS_DIR), local_files_only=True)
    # Decode the WAV ourselves: the venv's PyAV is newer than faster-whisper's decode_audio() expects.
    with wave.open(str(wav), "rb") as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    audio = pcm.astype(np.float32) / 32768.0
    segs, info = m.transcribe(audio, language="en", beam_size=5, vad_filter=True, word_timestamps=True,
                              condition_on_previous_text=False)
    out = []
    for s in segs:
        out.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip(),
                    "no_speech_prob": round(s.no_speech_prob, 3), "avg_logprob": round(s.avg_logprob, 3),
                    "words": [{"start": round(w.start, 2), "end": round(w.end, 2), "word": w.word.strip(),
                               "p": round(w.probability, 3)} for w in (s.words or [])]})
    return {"model": f"faster-whisper {model} int8", "duration_s": info.duration,
            "vad_kept_s": getattr(info, "duration_after_vad", None), "segments": out}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--model", default="small.en")
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--height", type=int, default=480)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    timings = {}

    t = time.monotonic()
    p = probe(a.video)
    (a.out / "probe.json").write_text(json.dumps(p, indent=1))
    timings["probe_s"] = round(time.monotonic() - t, 1)
    print("probe", json.dumps(p))

    t = time.monotonic()
    wav = a.out / "audio.wav"
    extract_audio(a.video, wav)
    timings["audio_s"] = round(time.monotonic() - t, 1)

    t = time.monotonic()
    n = extract_frames(a.video, a.out / "frames", a.height)
    timings["frames_s"] = round(time.monotonic() - t, 1)
    print("frames", n, timings)

    t = time.monotonic()
    tr = transcribe(wav, a.model, a.threads)
    timings["asr_s"] = round(time.monotonic() - t, 1)
    tr["timings"] = timings
    (a.out / "transcript.json").write_text(json.dumps(tr, indent=1))
    print("asr segments", len(tr["segments"]), "timings", timings)


if __name__ == "__main__":
    main()
