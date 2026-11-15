# P0-B team-channel analysis and P3 model choice (Step A)

Source: the coordinator's P0-B capture on the Pi.
- Channel `fazegavin1234`, label `P0B_TEAM_CHANNEL`, 2026-11-15 03:15:23–03:31:23Z.
- `capture_spike.py`, quality `best` (= 1080p60, the only variant), 480p frames, `--ring-s 1000`.
- Data in `~/fazetime-p0b/out` on the Pi, analysed read-only. Nothing there was modified.

This is real Twitch input from the team's own stream. The ASR text is stored only in gitignored `out/` on the Pi (`~/fazetime/services/worker/out/p0b_asr*`). Only short name snippets are quoted here.

## 1. Capture timeline (`tools/check_timeline.py`: **problems: []**)

| Item | Result |
|---|---|
| Records / source kind | 1427 / `TWITCH_STREAMLINK` only |
| Attempts / epochs / restarts | 6 / 6 / 5. Every restart opened a new epoch with sequence restarting at 0 (the spike numbered sequences from 0; the worker now starts at 1) |
| Epochs with media | 1cca078b 351.3 s (88 chunks, 176 frames); 7c418634 230.0 s (58, 115); 1b77788f 360.0 s (90, 180). Total 941.3 s audio, 471 frames |
| Owner stop/start | 03:21:14.2Z Streamlink `Stream ended` (rc 0), detected as STOPPED in ~0.5 s. Three restarts at 1/2/4 s backoff each got `No playable streams found` while the channel was offline. ffmpeg exited 183 on empty input. Attempt 4 (8 s backoff) was LIVE at 03:21:40.9Z, **26.2 s** after the stop, most of it the owner's offline period. Startup was 7.9 s |
| Scheduled kill | `kill -9` Streamlink at 03:25:23.560Z, STOPPED detected at 03:25:23.686Z (**126 ms**). New epoch LIVE at 03:25:28.153Z: **recovery 4.47 s** (1 s backoff + 3.35 s startup). ffmpeg logged one concealed H.264 error from the truncated last segment |
| First audio after launch | 2.93 s / 7.94 s (just after the channel came back) / 3.35 s |
| GAP / STALE | **none.** No ads (0 `ad=True` segments), no discontinuity lines, no pts jumps, no stall over 12 s. Health went CONNECTING → LIVE → STOPPED → … only |
| Burst cadence | Median **5.99 s** (gap threshold 8.99 s = 1.5×). Audio arrival `since_prev_chunk` p50 5.27 s, p95 5.93 s, max 6.81 s. `last_media_age` while LIVE p50 1.6 s, p95 4.6 s, **max 5.35 s**, which is well inside D29's 12 s LIVE bound |
| Segment complete − HLS PDT end (est. Twitch → Pi delivery) | n=472: p50 **4.07 s**, p95 **6.02 s**, max 8.01 s, min 1.35 s. Per attempt p50 3.2 / 4.3 / 4.1 s |
| Segments | 2.000 s fMP4. One 0.334 s and one 1.0 s partial segment at stream end/start |
| CPU at 1080p60 (LIVE heartbeats, n=186, % of one core) | ffmpeg mean **59.4%**, p50 67.7%, p95 79.3%, max 93.7% (303.7% momentarily in a startup burst). Streamlink 1.7%. Supervisor 1.5% |
| Memory | ffmpeg 150–152 MiB, Streamlink 63–65 MiB, supervisor 22 MiB. Disk ring 53.9 MB for 1000 s |
| Load average (1 min) | p50 2.02, max 6.74. The Pi ASR bench overlapped part of the run |
| Frames with no media position | 2 of 471 (`BEFORE_FIRST_AUDIO`: the first frame of an attempt preceded the first audio pts). The worker now skips these |
| OBS clock overlay | **Not present.** Three frames were checked (03:15:37Z, 03:22:28Z, 03:29:45Z): team overlay plus Minecraft, no UTC clock. **End-to-end delay could not be measured.** PDT delivery delay (above) is the only latency estimate |

Problems found:
1. The watcher loops on the Pi (`while pgrep -f "capture_spike.py --channel fazegavin1234"` and the two `pgrep -f team_asr_bench.py` waiters) **match their own `bash -c` command line**, so they never finish. I did not touch them; the coordinator should kill them. Use `pgrep -f '^[^ ]*python.*capture_spike'`, or a pid file.
2. The capture's Python had no numpy, so `rms_dbfs` is null in the timeline.

## 2. ASR on the team audio (Pi 5, int8, `cpu_threads=3`, beam 5, VAD on)

Setup:
- Bench `team_asr_bench.py`, configs `configs.json`. Each config ran in its own child, one after another, with nothing else on the CPU.
- Throttled stayed `0x0` and temperature reached at most 59 °C.
- **Streaming:** epoch 1cca078b 0–240 s, 79 windows of 4 s (3 s hop), dense talking (65–71 speech windows).
- **Whole-file:** all 941 s.
- "Bounded" means `temperature=0` (no fallback), `max_new_tokens=64`. The hotwords and initial_prompt runs used `"FaZeGavin, FaZeNeville, Minecraft, 1v1"`.

| Config | Whole-file RTF | Speech-window p50 | Window p95 / max | Latency p95 / max | Duty | > 3 s windows | Peak RSS |
|---|---|---|---|---|---|---|---|
| tiny.en default decoding | 0.172 | 0.97 s | 1.22 / **7.87** s | **4.02** / 7.87 s | 0.345 | 3 | 588 MiB |
| **tiny.en bounded** | 0.114† | 0.96 s | 1.23 / 2.53 s | **1.23** / 2.53 s | **0.300** | **0** | 580 MiB |
| tiny.en bounded + hotwords | 0.056† | 0.97 s | 1.22 / 1.50 s | 1.22 / 1.50 s | 0.298 | 0 | 580 MiB |
| tiny.en bounded + initial_prompt | 0.059† | 1.01 s | 1.23 / 1.50 s | 1.23 / 1.50 s | 0.308 | 0 | 578 MiB |
| base.en bounded | 0.252† | 1.80 s | 2.34 / 4.63 s | 2.34 / 4.63 s | 0.579 | 2 | 646 MiB |
| base.en bounded + hotwords | 0.161† | 1.94 s | 2.69 / 3.67 s | 2.69 / 3.67 s | 0.613 | 1 | 701 MiB |
| base.en bounded + initial_prompt | 0.182† | 1.91 s | 2.70 / 3.62 s | 2.70 / 3.62 s | 0.612 | 1 | 699 MiB |

† Long-form whole-file with `max_new_tokens=64` truncates each 30 s window of dense speech. The word count fell from 2078 to 1491 for tiny, so these RTFs understate the cost. Streaming windows of 4 s (~10–20 tokens) are not truncated. **Streaming is the relevant mode.**

With the drop policy (skip a window that waited more than 6 s), 0 windows were dropped in every config.

### Names: real mentions vs decoder-prompt hallucination

The first 240 s contain 5 windows with an acoustic "Gavin" mention, found by any config run without a prompt. FaZeNeville is not mentioned in that excerpt.

| Config | Exact `FaZeGavin` in mention windows | Any "gavin" in mention windows | `FaZeGavin` inserted elsewhere | Repetition-loop windows (compression ratio > 2.4) | Whole-file longest same-token run |
|---|---|---|---|---|---|
| tiny default / bounded | 0/5 | 4/5 | 0 | 0 | 6 / 8 |
| tiny + hotwords / + prompt | 4/5 | 5/5 | 0 | 1 / 1 | **78 / 26 × "fazegavin"** |
| base bounded | 0/5 | 5/5 | 0 | 3 ("Okay. Okay…", "All right…") | 128 × "ha" |
| base + hotwords / + prompt | 4/5 | 5/5 | **3** | **10** ("1v1, 1v1, …", "5v1, …", "FaZeGavin, FaZeGavin, …") | **128 × "fazegavin"** |

Without a prompt, the misspellings are: "face, Gavin", "phase Gavin", "Faze Gavin", "Please Gavin", and "face dab in" (tiny, one miss). Whole-file Neville came out as "face neville" (tiny default, 3×) and "phase neville" (base, 2×). With hotwords, both models produced **zero** Neville variants.

The decoder prompt fixes the spelling, but it **fabricates prompt words on noise and silence**:
- "Hey FaZeGavin" where the other configs heard "If he's yelling"
- a "FaZe" fragment in silent windows
- "1v1, 1v1, …" loops

A fabricated "1v1" or name could trigger a false market proposal, so **no decoder prompt**. Canonicalise names after ASR instead (`fazetime_worker/names.py`, which matches every no-prompt variant above), and drop repetition loops by compression ratio.

### Full-length streaming (all 3 epochs, 933 s, 311 windows; tiny and base bounded, no prompt; run 04:18–04:33Z)

| Model | Duty (weighted) | Window p95 per epoch | Max per epoch | Windows > 3 s hop | "Gavin" windows (alias) | Exact `FaZeGavin` | Neville windows (alias) | Exact `FaZeNeville` |
|---|---|---|---|---|---|---|---|---|
| tiny.en bounded | **0.336** | 1.31 / 1.26 / 1.26 s | 2.21 / 2.63 / 2.10 s | **0** | 14 | 0 | 1 ("phase neville") | 0 |
| base.en bounded | 0.624 | 2.35 / 2.35 / 2.34 s | 4.05 / 4.66 / 4.65 s | 9 | 16 | 0 | 1 ("faze neville") | 0 |

- The ground-truth mention count is unknown; the names come up "at random".
- Common no-prompt forms: "it's/that's Gavin", "thanks Gavin", "face, Gavin", "phase Gavin", "Faze Gavin", "phase/faze neville".
- Throttled `0x0` throughout, max 58.4 °C.

## 3. Recommendation for P3 (Pi)

**tiny.en, int8, `cpu_threads=3`, beam 5, `temperature=0` (no fallback), `max_new_tokens=64`, VAD on, no hotwords or initial_prompt.**

Window settings:
- 4 s windows with a 3 s hop.
- Repetition filter at compression ratio 2.4.
- Queue of at most 4 windows; drop a window that waited more than 6 s.

Name matching uses deterministic aliases downstream.

Why:
- Duty is 0.30 with dense team speech, with p95 1.23 s and a maximum of 2.5 s per window. No window exceeded the 3 s hop.
- Bounded decoding removed the default ladder's 7.9 s stalls.
- Its CPU footprint is about 1 core, leaving room for the API and capture. Capture costs ~0.04 core with keyframe-only frames, or ~0.6 core with full 1080p60 decode.

base.en with bounded decoding also fits:
- Duty 0.58, p95 2.3 s, maximum 4.6 s, 2 windows over the 3 s hop.
- It hears "Gavin" 5/5 instead of 4/5.
- But it produces more repetition loops, and its budget is thin next to the API.

Keep base.en as an option only if P4 shows that tiny misses cue phrases.
