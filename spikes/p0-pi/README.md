# P0 Pi spike (P0-D Pi STT benchmark + P0-F tailnet transport)

**Current outcome: see [Re-run on official PSU](#re-run-on-official-psu-2026-11-15-0302-0325z) below. It supersedes the first run's ASR result.**

First run (02:43–02:56Z, original supply): the Pi ASR benchmark stopped under the throttling stop rule, so no speech-to-text throughput was measured then. The original supply browned out under load. About 2 s after a 4-thread faster-whisper run started, at 43.9 °C, `get_throttled` returned `0x50005` (under-voltage now + throttled now). The capture checks (Streamlink audio_only plus PyAV decode with no ffmpeg CLI) and the tailnet WebSocket checks passed.

All media results are **TOOLCHAIN_SMOKE**: public channel `summit1g`, not the team channel. They do not pass P0-B or P0-D.

- Dates: first run 2026-11-14 20:43–20:56 America/Chicago (2026-11-15 02:43–02:56 UTC); re-run on the official PSU 21:02–21:25 CT (03:02–03:25 UTC). Repo base `master@6c050307`. Nothing was committed.
- Host `fazetime`: Raspberry Pi 5 Model B Rev 1.1, 16 GB, Debian 13 aarch64, kernel `6.18.50+rpt-rpi-2712`, 4× Cortex-A76, `ondemand` governor (1.5 GHz idle, 2.4 GHz max). A pwm-fan is present. It read 0 rpm during the first run (SoC < 45 °C) and ramped to about 4700 rpm during the re-run. The system clock is set to **America/New_York (-05:00)**, not Central. `NTPSynchronized=yes`. Use UTC in records.
- Laptop (client side): the primary laptop (`latpop`), Ubuntu 24.04 x86_64, Python 3.12.3.
- Media policy: the 180 s WAV (`sha256 22434150…aa18e5`, copied from `spikes/p0-media/out/smoke/summit1g/audio.wav`) and the 30 s Streamlink capture were **deleted from the Pi** after the first run. The WAV was re-copied for the re-run and then deleted again, together with the laptop copy (see the re-run section). No ASR output was produced in the first run, and the re-run stored counts only. No transcript text exists in any file. Streamlink logged at info level and its output was scanned. It contains no signed URL.

## Re-run on official PSU (2026-11-15 03:02–03:25Z)

The owner fitted the official 27 W supply and rebooted at about 03:00Z. At the start (03:02:47Z): `throttled=0x0`, `max_current=5000`, EXT5V 5.154 V, 0 under-voltage events since reboot. The WAV was re-copied (same sha256). Bench script, versions and decode settings match the first run: int8, beam 5, VAD on, language en, 4 s chunks with 1 s overlap (3 s hop). One run per config, so there is no run-to-run variance estimate. Labels: TOOLCHAIN_SMOKE public-channel audio. Only 44.3 s of the 180 s WAV is speech after VAD: 27 of 59 streaming chunks contain speech and the other 32 are near-free (0.018 s). The **speech-chunk p50** column is therefore the best estimate of cost under dense commentary. Duty is Σ processing time / media time; above 1.0 the worker cannot keep up.

**Overlap with the coordinator's P0-B capture.** From about 03:16Z, the coordinator ran the real P0-B team-channel capture (1080p60, ffmpeg CLI, under `~/fazetime-p0b/`; I did not inspect it) on the same Pi. Runs marked † overlapped it.

### ASR, unloaded (nothing else running), 4 threads

| Model | Whole-file RTF | Stream proc p50 / p95 / max | Speech-chunk proc p50 (n=27) | Latency p50 / p95 / max | Duty | Peak RSS | Temp before → after (max) | Throttled |
|---|---|---|---|---|---|---|---|---|
| tiny.en | **0.0327** (5.9 s) | 0.018 / 1.17 / 1.46 s | **0.93 s** | 0.02 / 1.17 / 1.46 s | 0.155 | 350 MiB | 42.8 → 49.4 (52.1) °C | 0x0 → 0x0 |
| base.en | **0.0598** (10.8 s) | 0.018 / 2.35 / **34.2** s | **1.81 s** | 3.6 / **31.5** / 38.6 s | 0.605 | 537 MiB | 48.8 → 54.3 (57.6) °C | 0x0 → 0x0 |
| small.en (base RTF < 0.5) | **0.1716** (30.9 s) | 0.018 / 6.34 / 6.65 s | **5.05 s** (> 3 s hop) | 10.7 / 19.8 / 21.8 s | 0.812 | 932 MiB | 53.8 → 56.0 (60.9) °C | 0x0 → 0x0 |

### ASR under load, base.en

| Run | Whole-file RTF | Stream proc p50 / p95 / max | Speech-chunk p50 | Latency p50 / p95 / max | Duty | Keeps up | Peak RSS | Temp max | Throttled |
|---|---|---|---|---|---|---|---|---|---|
| 4 threads + 1 busy core (03:12:29–03:16:50Z; last ~50 s possibly †) | 0.1257 | 0.034 / 4.95 / **82.5** s | 3.20 s | 105 / **139** / 145 s | **1.342** | **no** (final backlog 66.6 s) | 563 MiB | 60.4 °C | 0x0 |
| 3 threads + 1 busy core † (03:16:50–03:19:36Z) | 0.0724 | 0.018 / 3.78 / **49.7** s | 2.10 s | 36.5 / **68.2** / 75.2 s | 0.854 | yes (backlog drained by the end) | 594 MiB | 60.9 °C | 0x0 |
| 4 threads, no synthetic load † (stream only, 03:20:08–03:22:14Z) | — | 0.018 / 3.54 / **45.4** s | 2.15 s (n=28) | 15.7 / **43.0** / 48.4 s | 0.702 | yes (backlog drained by the end) | 560 MiB | 60.9 °C | 0x0 |

- During the † 4-thread run, **system-wide** CPU (`/proc/stat`) was 89.5% of all 4 cores (3.58 cores busy). The ASR process averaged 3.0 cores, so the P0-B capture and the rest of the system used roughly 0.6 cores. That split is an inference: I did not read the P0-B processes, and the capture may have been CPU-starved. The P0-B evidence holds the real capture cost. Load average peaked at 5.3.

- Model agreement: WER of each whole-file transcript against small.en's output, not ground truth. tiny.en 0.315, base.en 0.054. base.en at 3 threads vs 4 threads: 0.0 (deterministic).
- small.en fetch: 463.6 MiB in 106.2 s (4.4 MiB/s).
- Power and thermals across all runs: 0 under-voltage events, `get_throttled` `0x0` throughout, ARM held at 2400 MHz. Max 60.9 °C. The fan ramped up to about 4700 rpm.

**Latency outlier.** One speech chunk is pathological with the default decoding. It took 34.2 s unloaded, 82.5 s and 49.7 s under load, and 9.1 s on the laptop. That single chunk causes almost all of base.en's backlog. By the same arithmetic, without it the unloaded base.en duty would be about 0.41. small.en showed no such chunk on this sample. The likely cause is faster-whisper's default temperature-fallback ladder (0.0…1.0, up to 6 re-decodes with beam/best-of 5) plus long generation. The overlap run recorded non-text diagnostics for its slowest chunks, which confirm this:
- Chunk 1 (media 3–7 s) took 45.4 s and returned **no segments at all** (0 tokens), consistent with the whole fallback ladder running and every result being rejected.
- Chunk 14 (media 42–46 s) took 20.1 s and ended at **temperature 0.4**, i.e. two fallbacks. It produced 24 tokens and 0 words.
- Both chunks contain no recognisable words (music or game noise that passed VAD).

A bounded configuration (`temperature=0`, `max_new_tokens≈64`, a per-chunk deadline that marks the chunk stale) is **UNVERIFIED**. The test was cancelled when the plan changed.

**Thread count.** With another core busy, 4 ASR threads oversubscribe the 4 cores and the worker collapses (duty 1.34, latency grows without bound). Three threads under the same synthetic load *plus* the real 1080p60 P0-B capture still kept up on average.

### Capture cost, public channel alone (summit1g 480p30, 60 s, `capture_spike.py` with ffmpeg 7.1.5 CLI, 03:05:04–03:06:05Z)

| Process | CPU mean / max (% of one core, 5 s samples) | RSS max |
|---|---|---|
| streamlink 8.6.3 | 1.2 / 9.6 % | 57.2 MiB |
| ffmpeg 7.1.5 (H.264 480p30 software decode, 16 kHz mono audio, JPEG every 2 s) | 6.7 / 9.2 % | 92.4 MiB |
| supervisor (Python) | 0.8 / 1.2 % | 37.5 MiB |
| **Total** | **≈ 8.7 % of one core** | ≈ 187 MiB |

- **Timeline checker: PASS** (`problems: []`): 1 epoch, 0 restarts, sequence 0..88, 14 audio chunks = 53,994 ms, 27 frames with spacing exactly 2000 ms, health CONNECTING → LIVE → STOPPED (DURATION_REACHED). 0 ffmpeg warnings. Ring peak 2.77 MB.
- Startup: first bytes after 11.0 s, first audio after 11.1 s, first frame after 11.2 s. 10.6 s of that came before Streamlink's `Opening stream`, during the Twitch metadata/playlist phase. This was the first Twitch request since the reboot. The small.en download ended within about ±5 s of the launch. Neither cause is isolated.
- Segment completion minus HLS PDT end: p50 4.08 s, p95 6.17 s (n=27).
- During the run: 41.1–43.3 °C, `0x0`, 0 under-voltage events.
- **Skipped:** the public-channel capture + ASR combined run was dropped on the coordinator's instruction, because P0-B measures capture cost on the real channel. 480p30 is not the team channel's load: that channel has no transcodes, so its only video is 1080p60. Its software decode on the Pi (no H.264 hardware) will cost several times more. That number belongs to the P0-B evidence, not this run.

### Re-run verdict

- **The power fault is fixed.** About 20 minutes of near-full 4-core load produced 0 under-voltage events. `get_throttled` stayed `0x0`, ARM held 2400 MHz, max 60.9 °C. End state at 03:22:57Z: 50.5 °C, `0x0`, 0 under-voltage events.
- **Can the Pi host API + capture + ASR with headroom? Yes, with tiny.en. base.en is conditional on bounded decoding. small.en, no.**
  - **tiny.en, int8: MEASURED real-time with large margin.** Speech-chunk p50 is 0.93 s per 3 s hop, the worst chunk took 1.46 s, and there were no stalls (unloaded, 4 threads). It is the least accurate: agreement WER 0.315 against small.en, versus 0.054 for base.en. tiny.en at 3 threads with capture running is **UNVERIFIED**, though its margin is large.
  - **base.en, int8, `cpu_threads=3`: average cost fits, but tail latency fails with the default decoding.** Speech chunks cost 1.8 s unloaded and 2.1 s with a busy core plus the real 1080p60 P0-B capture. That is dense-speech duty ≈ 0.7, which is thin headroom. However, music/noise chunks that hit the fallback ladder stall the single worker for 20–50 s, giving p95 latency of 31–68 s. That is unacceptable for live market timing. Bounding the decode is required before using base.en: `temperature=0` (no ladder), `max_new_tokens≈64`, a per-chunk deadline that marks the chunk stale, and a bounded queue that drops instead of building a backlog. The fix is **UNVERIFIED**; it is about a 5-minute re-test with `pi_asr_bench.py --temperature 0 --max-new-tokens 64`.
  - **Do not use `cpu_threads=4`** when anything else needs a core: duty reached 1.34 and the worker collapsed. Use 3.
  - **small.en: no.** It costs 5.05 s per speech chunk against a 3 s hop.
- **Recommended Pi config now:** tiny.en, int8, `cpu_threads=3`, VAD on, as the safe baseline. Switch to base.en at `cpu_threads=3` only after the bounded-decoding re-test passes. The laptop stays the higher-headroom ASR option (base.en duty 0.224 there, about 3.4–3.6× the Pi's speed) if the owner prefers accuracy over single-host simplicity.
- **Capture:** 480p30 costs about 9% of one core (measured). The team channel offers only 1080p60, so its decode cost is set by the P0-B evidence. If it is heavy, decoding only keyframes for the 2 s frame sampler (ffmpeg `-skip_frame nokey`, assuming a 2 s keyframe interval) is an **UNVERIFIED** option.

Media cleanup for this re-run: the Pi WAV, the capture-alone media (`out/cap_alone/{audio,frames}`, 2.8 MB) and the laptop copy `spikes/p0-media/out/smoke/summit1g/audio.wav` were all **deleted** and checked with `find`/`ls` at 03:22:57Z. Nothing under `~/fazetime-p0b/` was touched.

## Versions (exact; freeze in `requirements.pi.lock.txt`)

Identical to the laptop lock (`spikes/p0-media/requirements.lock.txt`) except that `websockets` is added. All of these are aarch64 cp312 wheels, and none was built from source.

| Component | Version / note |
|---|---|
| uv | 0.13.8 (aarch64), official installer, 3.7 s |
| Python | CPython 3.12.16 (uv-managed, 28.1 MiB, ~7 s download) at `~/fazetime-spike/uv-python` |
| faster-whisper | 1.2.1 |
| ctranslate2 | 4.9.0. CPU compute types: float32, int8, int8_float32 (**no int16 on ARM**). 0 CUDA |
| onnxruntime | 1.32.0 (CPUExecutionProvider) |
| av (PyAV) | 19.0.2, bundled libavcodec/libavformat 63.1.102, libswresample 7.1.102. AAC decoder, mov and hls demuxers present |
| numpy | 2.5.4 |
| streamlink | 8.6.3 |
| websockets | 17.4 (same version in the laptop client venv `spikes/p0-pi/.venv`) |
| huggingface-hub / tokenizers / hf-xet | 2.4.0 / 0.23.3 / 1.8.0 |
| System | no ffmpeg, no GNU `time` (`/usr/bin/time` absent), no git |

`uv pip install` of all 42 packages took 26.1 s. The anonymous Hugging Face model fetch ran at about 4 MiB/s, not the expected ~1 MB/s:

| Model | Repo @ snapshot | Size | Fetch time on Pi |
|---|---|---|---|
| tiny.en | Systran/faster-whisper-tiny.en @ 0d3d19a3 | 74.5 MiB | 18.6 s (4.0 MiB/s) |
| base.en | Systran/faster-whisper-base.en @ 3d3d5dee | 140.9 MiB | 35.5 s (4.0 MiB/s) |
| small.en | not fetched (rule never evaluated) | — | — |

## Reproduce

```bash
# from the laptop: copy spike scripts, the lock, and a 16 kHz mono s16 WAV
ssh fazetime@fazetime 'mkdir -p ~/fazetime-spike/out'
scp spikes/p0-pi/{pi_asr_bench.py,sl_pyav_test.py,ws_echo.py,requirements.pi.lock.txt} fazetime@fazetime:fazetime-spike/
scp <wav> fazetime@fazetime:fazetime-spike/out/sample.wav
# on the Pi (no sudo). Keep uv's Python and cache inside the spike dir:
curl -LsSf https://astral.sh/uv/install.sh | sh          # NOTE: also edits ~/.profile, ~/.bashrc, fish conf.d (deviation 3)
export UV_PYTHON_INSTALL_DIR=$HOME/fazetime-spike/uv-python UV_CACHE_DIR=$HOME/fazetime-spike/uv-cache UV_NO_MODIFY_PATH=1
cd ~/fazetime-spike && ~/.local/bin/uv venv --python 3.12 .venv
~/.local/bin/uv pip install --python .venv/bin/python -r requirements.pi.lock.txt
# ASR bench (each run in its own child; transcripts never stored; aborts on >80 C or any current throttle bit):
.venv/bin/python -I pi_asr_bench.py --wav out/sample.wav --runs "tiny.en;base.en" --threads 4 \
  --small-if-base-rtf-below 0.5 --models-dir $HOME/fazetime-spike/models --out out/pi_asr_bench_main.json
# loaded repeat: 1 busy core (python3 -c 'while True: pass') simulating API + capture; 4 vs 3 threads:
.venv/bin/python -I pi_asr_bench.py --wav out/sample.wav --runs "base.en:4;base.en:3" --bg-load 1 \
  --models-dir $HOME/fazetime-spike/models --out out/pi_asr_bench_load1.json
# optional bounded decoding (UNVERIFIED fix for fallback stalls): add --temperature 0 --max-new-tokens 64
# capture cost (copy spikes/p0-media/capture_spike.py + tools/check_timeline.py first); optional concurrent bench:
bash cap_run.sh alone <channel> 60            # or: bash cap_run.sh combined <channel> 150 "base.en:3:1:5:stream"
# Streamlink audio_only -> file (TTFB) -> PyAV decode; then live pipe decode (no login/token/proxy/ad flags):
.venv/bin/python -I sl_pyav_test.py --channels summit1g,shroud,zackrawrr --seconds 30 --pipe-seconds 15
# P0-F: server bound ONLY to the tailnet IPv4 (script refuses anything outside 100.64.0.0/10):
setsid nohup .venv/bin/python -I ws_echo.py --host "$(tailscale ip -4)" --port 8787 >> out/ws_echo.log 2>&1 < /dev/null &
# laptop:
curl http://fazetime:8787/healthz
spikes/p0-pi/.venv/bin/python -I spikes/p0-pi/ws_client_test.py --url ws://fazetime:8787/ws --n 20 --idle-s 120 \
  --restart-cmd "ssh -o BatchMode=yes fazetime@fazetime '<kill -TERM pid; wait; relaunch as above>'"
```

## 1. ASR bench: ABORTED (stop rule)

| Item | Measured |
|---|---|
| Config | tiny.en, compute_type=int8, cpu_threads=4, beam_size=5, language=en, vad_filter=True, 180 s WAV, whole-file then 4 s/1 s-overlap streaming |
| Before | 02:48:14Z, 42.2 °C, `0x50000`, EXT5V 5.012 V, load 0.62 |
| Abort | Monitor sample at ~2 s showed `get_throttled=0x50005` (bit 0 under-voltage **now**, bit 2 throttled **now**). The child was killed at 2.5 s, during model load or the start of the first transcribe. Max temp 43.9 °C, sampled EXT5V min 4.926 V, child RSS 289 MiB at kill, fan 0 rpm |
| After | 02:48:17Z, 42.8 °C, `0x50000` (current bits cleared at idle). dmesg: `Undervoltage detected!` 02:48:15Z, `Voltage normalised` 02:48:19Z |
| Not run (stop rule) | whole-file RTF, streaming p50/p95 latency and backlog, peak RSS during transcription, base.en, the small.en rule, the loaded-core repeat, any thread comparison |

Thermals were not the limit. The trigger is the supply, so a cooler or a lower `--max-temp-c` would not have helped. Even if the bench had not stopped, numbers taken while under-voltage-throttled would not show the Pi's real capacity.

### Power evidence (all readable without sudo)

| Check | Result |
|---|---|
| USB-PD negotiation | `/proc/device-tree/chosen/power/usbpd_power_data_objects` = all zero (**no PD contract**) |
| Firmware supply current | `/proc/device-tree/chosen/power/max_current` = **900** (mA). `usb_max_current_enable=0`, `usb_over_current_detected=0` |
| EEPROM override | `vcgencmd bootloader_config`: no `PSU_MAX_CURRENT` |
| USB loads | none attached (only xHCI host controllers) |
| EXT5V rail | idle 4.97–5.01 V; sampled min under load 4.926 V (2 s sampling misses transients) |
| `dmesg` under-voltage events (times derived from kernel uptime, ±1 s) | **12 in ~61 min of uptime** (boot 01:53:00Z): 01:53:05Z and 01:53:10Z (boot), 02:21:07Z and 02:37:43Z (before this spike), 02:44:36Z (setup window after the uv install at 02:44:03Z, during the WAV scp), 02:45:39Z and 02:45:43Z (wheel install), 02:47:12Z (single-process import check), 02:47:56Z (model fetch), 02:48:15Z (ASR start), 02:51:00Z (**single `ws_echo.py` start**), and 02:53:30Z (near idle, with no spike process starting) |

A single Python process start is enough to trip under-voltage. This is a supply or cable problem, not an ASR-specific one. It also endangers the API host role: brown-outs risk SD-card corruption, Wi-Fi drops and resets.

Laptop comparison (same WAV, same versions; from `spikes/p0-media/out/asr_bench_main.json`, TOOLCHAIN_SMOKE, i5-1235U, 4 threads, int8, VAD). Only 44.3 s of the 180 s is speech after VAD, and 34 of 59 chunks are empty, so these streaming numbers are optimistic for dense commentary:

| Model | Whole RTF | Stream proc p95 | Stream latency p95 | Duty | Peak RSS |
|---|---|---|---|---|---|
| tiny.en | 0.0091 | 0.475 s | 0.475 s | 0.065 | 471 MiB |
| base.en | 0.0175 | 1.232 s | 4.455 s (one 9.1 s outlier chunk) | 0.224 | 615 MiB |
| small.en | 0.0567 | 3.292 s | 3.855 s | 0.461 | 1046 MiB |

## 2. Streamlink + PyAV on the Pi (TOOLCHAIN_SMOKE, summit1g, 02:51:25–02:52:12Z)

| Item | Measured |
|---|---|
| Probe | first channel tried (`summit1g`) live. Variants: audio_only, 160p30, 360p30, 480p30, 720p60, 1080p60. Plugin: `Will skip ad segments` (default, no flags) |
| audio_only to file, time to first bytes | **2.169 s** after launch |
| Volume | 878,417 B in a 30 s window (32.2 s wall), 233.8 kbit/s. Reads arrive in bursts: 5 gaps > 0.5 s, median 5.89 s, max 5.93 s (same ~6 s playlist cadence as the laptop) |
| Streamlink cost | 0.83 CPU-s over 32 s (≈2.6% of one core), max RSS 55.6 MiB. rc 130 on SIGTERM (expected) |
| PyAV decode of that file to 16 kHz mono s16 | **works, no ffmpeg CLI**. Container `mov,mp4` (fMP4), AAC-LC 48 kHz stereo fltp, 1594 frames, 544,085 samples = 34.005 s (pts span 34.005 s: the start is 3 segments behind live). 0 pts jumps > 50 ms, 0 errors, int16 mono arrays. 0.247 s wall / 0.48 CPU-s (decode RTF ≈ 0.007) |
| Live pipe decode (Streamlink stdout to `av.open(pipe)`) | **works**. Demuxer opened at 1.883 s, first 16 kHz PCM at **1.884 s** after launch, 15.02 s PCM in 13.94 s wall. Streamlink 0.6 CPU-s, 57.2 MiB |
| Under-voltage during this test | none (dmesg count 11 before and after) |

Since PyAV demuxes fMP4 from a pipe, an apt ffmpeg is **not needed** for audio capture. Video frames were not tested on the Pi. The Pi 5 has no H.264 hardware decoder, and audio_only has no video. The CPU cost of software 480p30 decode plus JPEG sampling, which is about 11% of one laptop core with ffmpeg, is **unmeasured on the Pi**.

## 3. P0-F tailnet transport (laptop to Pi, 02:50:59–02:53:45Z)

The path was **DERP-relayed (`dfw`)** throughout. `tailscale ping` reported `direct connection not established` (55–78 ms disco pings), and `tailscale status` showed `relay "dfw"` at the start and end. Name resolution used MagicDNS `fazetime` → 100.81.162.34. `ss -ltn` confirmed the server listened only on `100.81.162.34:8787`. No Funnel, no `tailscale serve`, and no settings were changed.

| Check | Result |
|---|---|
| `curl http://fazetime:8787/healthz` | 200 `ok` ×5: connect 12–254 ms, total 25.2 / 269.8 / 39.9 / 35.3 / 34.6 ms. Unknown path gives 404 |
| WS connect (TCP + upgrade) | 0.112 s |
| 20-message echo (≈294 B JSON text frames) | RTT **p50 13.1 ms, p95 15.5 ms**, min 11.2, max 15.8 (n=20; p95 is effectively the 2nd-highest sample) |
| 120.1 s **true idle** (no pings either side) | survived. Next 5 messages: p50 15.7 ms, max 231.3 ms (the first message after idle is slow, probably a Wi-Fi/relay wake-up) |
| Server restart (SIGTERM → graceful close) | client got close **1001** 0.345 s after issuing the restart. That figure includes the SSH round trip. It reconnected 0.31 s later on attempt 2 (attempt 1 ConnectionRefused while the new process started) |
| After restart | 5 messages p50 13.6 ms, p95 15.4 ms |
| After stop | port closed (curl: connection refused). No spike processes running |

## Errors and deviations

1. **The ASR bench stopped because throttling was current** (`0x50005`, under-voltage). See section 1.
2. `/usr/bin/time` is absent on the Pi. My first install command used it, so the explicit `uv python install 3.12` and `uv pip install` did not run. `uv venv --python 3.12` auto-downloaded 3.12.16 anyway, and the wheel install was re-run with shell timing. There was no wheel failure.
3. The uv installer's default **PATH edit wrote outside `~/fazetime-spike`**. It appended `. "$HOME/.local/bin/env"` to `~/.profile` and `~/.bashrc` and created `~/.config/fish/conf.d/uv.env.fish`, alongside `~/.local/bin/{uv,uvx,env,env.fish}`. To revert (optional; the spike uses absolute paths): `sed -i '\|^\. "\$HOME/\.local/bin/env"$|d' ~/.profile ~/.bashrc; rm -f ~/.config/fish/conf.d/uv.env.fish`.
4. The first detached launch put `cd` inside the backgrounded job, so the PID-wait loop exited early. The bench still ran and its JSON was read directly.

## MEASURED vs UNVERIFIED

MEASURED on the Pi: the uv, CPython 3.12.16 and aarch64 wheel install without sudo, with the versions above. Model fetch speed of about 4 MiB/s. The PSU: no PD contract, 900 mA firmware limit, 12 under-voltage events, and current under-voltage throttling within 2 s of 4-thread ASR. Anonymous Streamlink audio_only (TTFB 2.17 s). PyAV file and live-pipe decode to 16 kHz mono without the ffmpeg CLI. Tailnet HTTP and WebSocket RTT, 2-minute true idle, and graceful-restart reconnect over a DERP relay.

UNVERIFIED: **all Pi ASR throughput**: RTF, chunk latency, backlog, RSS during transcription, sustained thermals, the loaded-core run, thread count and small.en. Pi behaviour on a proper PSU. Pi video decode and frame-sampling cost. Long-running Streamlink and reconnects on the Pi. A direct (non-relay) tailnet path. Any public HTTPS route for viewers or the extension (Quick Tunnel, iframe): not in scope here. Hard-crash (SIGKILL) or network-drop detection without pings. Accuracy and important-name recognition (no ground truth).

## Recommendation (first run on the original supply; superseded by the re-run verdict above)

- **Can the Pi run API + capture + ASR with headroom? Not today, and the throughput question is unanswered.** On the current supply the Pi browns out even on single-process starts. Under ASR load it becomes current-throttled within seconds. Do not assign ASR to the Pi now. Treat the Pi as an **unreliable API host until the supply is fixed**, because brown-outs mean reset, SD-corruption and Wi-Fi-drop risk during the demo. The owner's decision should be re-recorded as blocked on the PSU.
- **Interim:** run ASR on the laptop, the fallback documented in `docs/INGESTION.md`, using the laptop numbers above. Prefer the laptop for the API too until the Pi passes a clean re-run. The tailnet path (13 ms RTT, survives idle, fast reconnect) is adequate for a laptop ASR worker posting observations to a Pi API. It is relayed, so it depends on venue internet and Tailscale DERP.
- **Model and threads on the Pi: no measured basis.** If the Pi must be pre-configured before a re-run, start at base.en, int8, `cpu_threads=3`, leaving one core for the API, Streamlink and PyAV, with tiny.en as the fallback. That starting point is **UNVERIFIED**. Decide only from the loaded re-run, for example: keeps_up, duty ≤ 0.5 with one busy core, p95 chunk latency ≤ 4 s, temp < 80 °C, and `get_throttled` staying `0x0`.
- **Owner actions:**
  1. **Power supply (required):** use the official Raspberry Pi 27 W USB-C supply (5.1 V / 5 A, USB-PD), plugged directly into the Pi. Do not use a laptop port, phone charger, USB-A-to-C cable, or hub. After a reboot, check that `vcgencmd get_throttled` reads `0x0` and that `dmesg | grep -c "Undervoltage detected"` reads `0`. `od -An -tu4 --endian=big /proc/device-tree/chosen/power/max_current` should report a PD-negotiated value (5000 expected with the official supply; not verified here).
  2. Then re-run the two `pi_asr_bench.py` commands above: about 10 min, plus about 2 min to fetch small.en at the measured rate. Copy a 16 kHz mono WAV back first, because the spike WAV was deleted.
  3. **apt: none required** for the tested audio path, since the PyAV wheel bundles the FFmpeg libraries. Optional, needed only if capture keeps the ffmpeg-CLI design from `spikes/p0-media/capture_spike.py` or if `/usr/bin/time -v` measurements are wanted: `sudo apt-get install -y ffmpeg time`.

## Footprint left on the Pi

After the re-run, `~/fazetime-spike` is 1.2 GiB. It holds `.venv` 379M, `models` (tiny.en, base.en and small.en, about 680M), `uv-python` 92M, `uv-cache` 13M, and `out/` (JSON and logs only, no media). It also has the scripts `pi_asr_bench.py`, `sl_pyav_test.py`, `ws_echo.py` and `cap_run.sh`, a copy of `capture_spike.py`, and `tools/check_timeline.py`. The first-run footprint was 699 MiB. Outside it are `~/.local/bin/{uv,uvx,env,env.fish}` (32M) and the rc-file lines from deviation 3. Copies of the Pi JSON and logs are in `spikes/p0-pi/out/` (gitignored).
