"""Deterministic consistency checks over a capture_spike timeline.jsonl (prints JSON)."""
import json
import sys
from collections import defaultdict

recs = [json.loads(l) for l in open(sys.argv[1])]
problems = []
seq = defaultdict(list)
chunks = defaultdict(list)
frames = defaultdict(list)
epoch_attempt = {}
attempt_started = {}
kinds = set()
for i, r in enumerate(recs):
    kinds.add(r["source_kind"])
    ep = r["source_epoch"]
    if ep is not None and r["sequence"] is not None:
        seq[ep].append(r["sequence"])
    if r["record_type"] == "EPOCH_START":
        if ep in epoch_attempt:
            problems.append(f"epoch reused {ep}")
        epoch_attempt[ep] = r["attempt"]
    if r["record_type"] == "PROCESS_START":
        attempt_started[r["attempt"]] = i
    if r["record_type"] in ("AUDIO_CHUNK", "FRAME") and ep in epoch_attempt:
        later = [a for a in attempt_started if a > epoch_attempt[ep] and attempt_started[a] < i]
        if later:
            problems.append(f"record for old-attempt epoch {ep[:8]} after newer attempt started (line {i})")
    if r["record_type"] == "AUDIO_CHUNK":
        chunks[ep].append((r["media_start_ms"], r["media_end_ms"], r["quality_flags"]))
    if r["record_type"] == "FRAME":
        frames[ep].append(r["media_start_ms"])
for ep, s in seq.items():
    if s != list(range(len(s))):
        problems.append(f"sequence not 0..n-1 contiguous in {ep[:8]}")
for ep, c in chunks.items():
    for (a0, a1, _), (b0, b1, _) in zip(c, c[1:]):
        if b0 != a1:
            problems.append(f"audio not contiguous in {ep[:8]}: {a1} -> {b0}")
spacing = []
for ep, f in frames.items():
    known = [x for x in f if x is not None]
    if known != sorted(known):
        problems.append(f"frame positions not monotonic in {ep[:8]}")
    spacing += [b - a for a, b in zip(known, known[1:])]
per_epoch = {ep[:8]: {"attempt": epoch_attempt.get(ep), "audio_chunks": len(chunks[ep]),
                      "audio_ms": chunks[ep][-1][1] if chunks[ep] else 0, "frames": len(frames[ep]),
                      "max_sequence": max(seq[ep]) if seq[ep] else None} for ep in epoch_attempt}
health = [(r["host_wall_utc"][11:23], r["previous_state"], r["state"], r.get("reason"))
          for r in recs if r["record_type"] == "HEALTH"]
print(json.dumps({"records": len(recs), "source_kinds": sorted(kinds), "epochs": per_epoch,
                  "frame_spacing_ms": {"min": min(spacing) if spacing else None,
                                       "max": max(spacing) if spacing else None,
                                       "n": len(spacing)},
                  "health": health, "problems": problems}, indent=1))
