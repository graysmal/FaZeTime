# P0 media spike (P0-B-prep + P0-D-prep): TOOLCHAIN_SMOKE

Every result in this directory is **TOOLCHAIN_SMOKE**. It comes from a public Twitch channel (`summit1g`, World of Warcraft, English), not the team channel. The audio does not represent the team's challenge audio. These runs do **not** pass the P0-B or P0-D gates. The owner has since chosen the Pi as the API + STT host, so the laptop ASR numbers below are comparison data only.

- Date: 2026-11-14 ~20:17–20:45 America/Chicago (2026-11-15 02:17–02:45 UTC). Base `master@6c050307`.
- Host: Ubuntu 24.04.5 x86_64, Intel i5-1235U (10C/12T, AVX2/FMA/F16C), 38 GiB RAM, Iris Xe iGPU, no CUDA. `timedatectl` NTPSynchronized=yes. Other agents were running at the same time (mostly network-bound). The load average is recorded next to each run.
- Media policy: third-party media was kept only in `out/` (gitignored). All frames, chunks and probe JSON (which contains signed playback URLs) have been deleted. **One file is retained at the coordinator's request for the Pi benchmark:** `out/smoke/summit1g/audio.wav`. It is 16 kHz mono s16le, 179.988 s, 5,759,704 bytes, sha256 `22434150cc8653a35947db29c5b15d6d834522e3dc73d46ba75e4b1e87aa18e5`. The coordinator deletes it afterwards. No transcript text was written to any file or printed.

## Versions (exact; full freeze in `requirements.lock.txt`)

| Component | Version |
|---|---|
| Python | 3.12.3 (`/usr/bin/python3.12`), venv by uv 0.13.6 |
| streamlink | 8.6.3 |
| faster-whisper | 1.2.1 |
| ctranslate2 | 4.9.0 (CPU compute types: int8, int8_float32, int16, float32; 0 CUDA devices) |
| av (PyAV) | 19.0.2 |
| onnxruntime | 1.32.0 (Silero VAD; faster-whisper pins it to 1 intra/inter-op thread) |
| numpy | 2.5.4 |
| huggingface-hub / tokenizers | 2.4.0 / 0.23.3 |
| ffmpeg / ffprobe | Ubuntu 6.1.1-3ubuntu5 (system) |

Models are official Systran repos, cached in `models/` (gitignored). Sizes are as downloaded, and the files are the float16 CT2 weights quantized to int8 at load:

| Model | Repo @ snapshot | Size | Fetch time |
|---|---|---|---|
| tiny.en | Systran/faster-whisper-tiny.en @ 0d3d19a3 | 74.5 MiB | 31 s |
| base.en | Systran/faster-whisper-base.en @ 3d3d5dee | 140.9 MiB | 59 s |
| small.en | Systran/faster-whisper-small.en @ d1d751a5 | 463.6 MiB | 112 s |

distil-small.en was not run, because the coordinator asked for no further work.

## Reproduce

```bash
cd spikes/p0-media
~/.local/bin/uv venv --python /usr/bin/python3.12 .venv
~/.local/bin/uv pip install --python .venv/bin/python -r requirements.lock.txt   # or: streamlink faster-whisper
# variant probe (no login/token/proxy):
.venv/bin/streamlink --json https://twitch.tv/<channel>          # do not paste output: contains signed URLs
# 3-minute single-path smoke -> out/smoke/<ch>/audio.wav + frames/f_%04d.jpg (1 per 2 s):
./smoke_capture.sh <channel> 480p30 180
# supervised capture with timeline; kill streamlink mid-run from another shell:
.venv/bin/python -I capture_spike.py --channel <channel> --quality 480p30 --duration-s 130 --out out/capture_live
kill -9 "$(jq -r .source out/capture_live/pids.json)"          # ~60 s in
.venv/bin/python -I tools/check_timeline.py out/capture_live/timeline.jsonl
# offline deterministic test (source_kind=TEST_SOURCE_CMD, never Twitch evidence):
STALL_S=12 .venv/bin/python -I capture_spike.py --channel offline_test --duration-s 34 \
  --out out/test_offline2 --test-source-cmd "bash $PWD/tools/lavfi_source.sh" --max-restarts 0
# ASR bench (each run in its own child process; transcripts never stored):
.venv/bin/python -I asr_bench.py --wav out/smoke/summit1g/audio.wav --runs "tiny.en;base.en;small.en" \
  --threads 4 --out out/asr_bench_main.json
#   run spec syntax: model[:threads[:vad(0|1)[:beam[:modes]]]], e.g. "base.en:4:0" = no-VAD run
```

For the real P0-B run on the team channel, pass `--label P0B_TEAM_CHANNEL --duration-s 900`. Also kill streamlink once and interrupt the network once. `pids.json` holds the current PIDs.

## 1. Twitch smoke (TOOLCHAIN_SMOKE, summit1g, 480p30, 02:22:36Z, load 0.91/0.97/1.08 → 1.32/1.08/1.10)

| Item | Measured |
|---|---|
| Channel probe (`--json`) | shroud, summit1g, zackrawrr live. tarik, lirik, caseoh_, jynxzi: `No playable streams found` (offline). 0.7–1.3 s per call (first call 6.9 s) |
| Variants (summit1g) | audio_only, 160p30, 360p30, 480p30, 720p60, 1080p60 (+ worst/best). shroud also had 284p30/640p30/852p30/1280p60 `_portrait` |
| Access-token flags (debug log) | `server_ads: True, show_ads: True, hide_ads: False`. Plugin logs `Will skip ad segments` (default behaviour, no flags) |
| Delivery | HLS **fMP4** segments of 2.000 s. Playlist reload every ~6 s, so **3 segments arrive per burst**. The stream starts 3 segments behind the live edge |
| Decoded input | AAC-LC 48 kHz stereo + H.264 Main 852x480 @ 30.08 fps (`mov,mp4` demuxer) |
| Time to first bytes | 1.516 s after launch (pipe meter). Streamlink `Writing stream to output` at +1.46 s |
| Output | WAV 179.988 s pcm_s16le 16 kHz mono. 90 JPEG 852x480 q5 (~41 KB each, 3.8 MiB total) |
| Throughput | 30.5 MB in, mean 1357 kbit/s. Input inter-read gaps 3.7–6.6 s every ~6 s (burst cadence), max 6.63 s |
| Ads / discontinuities | **None observed** (no `advertisement`, `Filtering out`, or `discontinuity` warning lines in 3 min + 2×65 s) |
| CPU / RSS (`/usr/bin/time -v`) | streamlink 1.8 CPU-s / 181.6 s (≈1% of one core), max RSS 57.3 MiB. ffmpeg 19.9 CPU-s / 181.5 s (≈11% of one core), max RSS 134.3 MiB |
| Errors | Streamlink exit 1 `Broken pipe` at the end. This is expected: ffmpeg `-t` finished first. ffmpeg's only warning was swscaler `deprecated pixel format` (JPEG yuvj420p, benign) |

## 2. `capture_spike.py` restart test (TOOLCHAIN_SMOKE, summit1g 480p30, 130 s from 02:34:09Z, load end 1.15/1.04/1.05)

Design: streamlink stdout feeds a Python byte pump, which feeds **one** ffmpeg. Audio goes `aresample=16000`, mono s16, `ashowinfo`, then raw PCM on stdout. Video goes `select` (≥2 s since the last frame), `showinfo`, then MJPEG on an extra pipe fd. Media positions are computed from decoded sample counts. `ashowinfo` gives the pts of every decoded audio frame. This means pts jumps are detected at an exact sample index and **never padded** (no `aresample async`). Frames are mapped onto the same timeline: `media_ms = frame_pts − epoch_base_pts`. The JSONL records carry `host_mono_ns`, `host_wall_utc`, `stream_id`, `stream_session_id`, `source_kind=TWITCH_STREAMLINK`, `source_epoch` (UUID4), `sequence` (per epoch, starting at 0), `media_start_ms`/`media_end_ms`, `source_wall_time_utc=null`, `quality_flags` and `evidence_ref`. There are 4 s WAV chunks and a 120 s ring (30 chunks + 60 frames). Playback URL query strings are redacted from logs.

| Item | Attempt 0 | Attempt 1 (after kill) |
|---|---|---|
| First input bytes after launch | 1522.6 ms | 1403.1 ms |
| First decoded audio after launch | 1560.1 ms | 1438.2 ms |
| First frame after launch | 1644.3 ms | 1488.8 ms |
| Stop | `kill -9` streamlink at 02:35:15.221Z. STOPPED detected at 02:35:15.249Z (**~29 ms**), reason SOURCE_EXITED rc −9. ffmpeg drained and exited 0. The last partial chunk was flagged `CLOSED_BY_STOP, PARTIAL, DRAINED_AFTER_STOP` | DURATION_REACHED (streamlink rc 130 on SIGTERM) |
| Recovery | STOPPED-detect → first audio of the new epoch = **2439 ms** (1 s backoff + 1.44 s startup) | n/a |
| Epoch | 5b05b2f1, seq 0..105, 66.0 s audio, 33 frames | **new** 2a5ffc8c, seq restarted at 0, media restarted at 0, 66.0 s, 33 frames |
| Segment complete − HLS PDT end (est. Twitch→host delivery) | p50 3.07 s, p95 5.09 s, max 5.19 s (n=33) | p50 3.85 s, p95 5.78 s, max 5.85 s (n=33) |
| streamlink CPU mean/max, RSS | 1.5% / 12.4% (startup), 57.3 MiB | 1.5% / 11.4%, 57.2 MiB |
| ffmpeg CPU mean/max, RSS | 9.9% / 15.4%, 132.8 MiB | 11.7% / 22.4%, 132.8 MiB |
| supervisor CPU mean, RSS | 1.7%, 37.6 MiB | 1.9%, 38.6 MiB |

The CPU% figures are per core (100% = one core), from `/proc` samples every 5 s. ffmpeg RSS rose from about 98 to 133 MiB over the first minute in each attempt. Its plateau beyond 3 minutes is unverified. The disk ring peaked at 6.69 MB (30 WAV + 60 JPEG at 852x480), with 10 files evicted. `tools/check_timeline.py` found no problems. It confirmed sequences contiguous per epoch, audio contiguous within each epoch, frame spacing exactly 2000 ms (62 intervals), no old-epoch records after the new attempt, and one source_kind. The health path was CONNECTING→LIVE→STOPPED→CONNECTING→LIVE→STOPPED, with no false GAP.

**Offline deterministic test** (`TEST_SOURCE_CMD`, synthetic lavfi MPEG-TS, NOT Twitch). A 12 s delivery stall raised GAP after 9.07 s (threshold 9.0 s). On resume, a new epoch opened (`AUDIO_RESUMED_AFTER_GAP`). A +4.952 s pts jump opened a new epoch (`AUDIO_PTS_DISCONTINUITY`), and the post-jump frames mapped to media 22 ms, 2022 ms, and so on. A source exit led to STOPPED, then a restart in a new epoch.

Findings that change the plan's assumptions:
- **A fixed 5 s "no new audio" GAP rule false-triggers on every cycle with default Streamlink.** Audio arrives in ~6 s bursts (up to 6.6 s apart). The spike therefore uses `gap = max(--gap-s 5, 1.5 × median burst interval)`, which measured ~9.0 s. STALE is `max(15 s, gap)`, and a restart follows 30 s without audio. Getting real 5 s detection would probably need the generic HLS option `--hls-playlist-reload-time segment`. This is untested because of the no-flags instruction, so it is a coordinator decision.
- The evidence age when a 4 s chunk completes is roughly the segment delivery delay (p50 3–4 s, p95 5–6 s, measured against PDT) plus up to 4 s of chunk accumulation. Encoder and ingest delay before Twitch stamps PDT also adds to it, and that part is unmeasured.

## 3. ASR bench (TOOLCHAIN_SMOKE audio, CPU, compute_type=int8, cpu_threads=4, beam_size=5, language=en, vad_filter=True)

Whole-file run: the full 179.99 s WAV in one call. Streaming run: 59 consecutive 4 s chunks with a 1 s overlap (hop 3 s), each a separate `transcribe(condition_on_previous_text=False)`. The processing times were measured back-to-back. Latency is computed for a single sequential worker and includes queueing (backlog), but not capture delay. "Duty" is Σproc / media time.

| Model | Load s | Whole-file s (RTF) | Peak RSS MiB | Stream proc p50 / p95 / max s | Stream latency p50 / p95 / max s | Duty | Final backlog s | Chunks w/o words | Cores busy (whole / stream) | WER vs small.en* | Load avg start→end |
|---|---|---|---|---|---|---|---|---|---|---|---|
| tiny.en | 0.31 | 1.63 (0.0091) | 471 | 0.012 / 0.475 / 0.503 | 0.012 / 0.475 / 0.503 | 0.065 | 0.01 | 34/59 | 3.78 / 5.46 | 0.288 | 2.73→3.37 |
| base.en | 0.33 | 3.16 (0.0175) | 615 | 0.018 / 1.232 / **9.114** | 0.162 / 4.455 / 9.114 | 0.224 | 0.01 | 34/59 | 3.99 / 4.43 | 0.054 | 3.37→6.76 |
| small.en | 0.83 | 10.21 (0.0567) | 1046 | 0.018 / 3.292 / 3.459 | 0.157 / 3.855 / 4.384 | 0.461 | 0.01 | 33/59 | 3.97 / 4.17 | reference | 6.76→6.93 |

\* The WER column measures agreement with the small.en output on the same audio. It is not accuracy against ground truth.

Backlog over media time (media s → latency s), sampled every 10 chunks:
- tiny: 31→0.01, 61→0.01, 91→0.01, 121→0.49, 151→0.01, 178→0.01
- base: 31→0.02, 61→0.02, 91→0.02, 121→0.98, 151→0.01, 178→0.01
- small: 31→0.02, 61→0.02, 91→0.01, 121→3.69, 151→0.01, 178→0.01

How to read these numbers:
- **Speech is sparse in this clip.** Silero VAD kept 44.3 s of 180 s, and 33–34 of 59 chunks produced no words. The p50 numbers are therefore the VAD-only fast path. The p95 is the real per-speech-chunk cost. Every model "kept up" only because of the silence.
- With **continuous speech**, the duty would be about p95 / 3 s hop. That is ≈0.16 for tiny, ≈0.41 for base and ≈1.1 for small. **small.en with 4 threads would fall behind** on continuous speech on this laptop.
- base.en had one **9.1 s outlier chunk**, probably temperature fallback or a repetition loop on game audio. Without a per-chunk time limit or fallback cap, a single bad chunk creates seconds of backlog.
- `cpu_threads=4` does not cap CPU at 4 cores. Streaming runs used 4.2–5.5 cores, counting VAD and other runtime threads. Load rose to ~7 during small.en, mostly from the bench itself.
- No no-VAD run, beam_size=1, thread sweep, or distil-small.en was run. The coordinator stopped new work.

Laptop comparison recommendation: **base.en, int8, cpu_threads=4, vad_filter=True**. Add a hard per-chunk processing deadline and cap the temperature fallback (for example `temperature=0` or beam 1, still to be measured). Keep tiny.en as the fallback if latency matters more than agreement (0.29 vs 0.05 disagreement). This was measured on non-representative public-channel audio. Important-name and negation accuracy are unknown, and the Pi will be several times slower until measured.

## Verified vs unverified

VERIFIED on this laptop (TOOLCHAIN_SMOKE):
- Anonymous Streamlink 8.6.3 got Twitch HLS media with default plugin behaviour. One Streamlink→FFmpeg path produced 16 kHz mono PCM and 2 s JPEGs.
- The supervisor detected a process kill (~29 ms), went through STOPPED, reconnected after 1 s backoff, and recovered in 2.44 s with a new epoch and a fresh sequence. Disk use was bounded by the 120 s ring.
- faster-whisper 1.2.1 / CTranslate2 4.9.0 install and run on CPU int8 with the numbers above.

UNVERIFIED / not tested:
- The team channel, OBS output, and venue network: the actual P0-B gate.
- A live ad break or discontinuity: none occurred. Only the synthetic jump was tested.
- A mid-stream fMP4 init-segment change: likely an ffmpeg exit, which goes to the restart path.
- A network interruption, `--hls-playlist-reload-time segment`, other qualities (720p60 CPU cost), and RSS plateau over 10–15 min.
- Whether Twitch PDT matches the broadcaster's wall clock. An OBS clock overlay is needed to check it.
- ASR accuracy: no ground truth exists, and agreement is model-vs-model only. Important-name and negation recognition, team audio, distil-small.en, thread sweep, whisper.cpp, and **all Pi numbers** are also unverified.
