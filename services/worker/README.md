# FaZeTime media worker (P3)

This worker carries out Phase 3 against the frozen worker contract (CONTRACTS §9.4, §9.16; D29). It runs one Twitch capture: Streamlink feeds a single FFmpeg decode, which produces 16 kHz PCM and one JPEG every 2 s at 480p, both on a single media timeline per `source_epoch`. Local faster-whisper turns the audio into text, and the worker sends typed observations to the API. The worker has no authority over wallets, wagers or settlement. It treats transcripts and frames as untrusted data.

Status: implemented and passing deterministic offline tests. It ran on the Pi in **dry-run** against a public channel (TOOLCHAIN_SMOKE). **Unverified:** a live run against the real API, and any run on the team channel through this worker. The team channel was offline at 04:16Z.

## Layout

| Path | Role |
|---|---|
| `fazetime_worker/capture.py` | Supervised Streamlink → FFmpeg pipeline, promoted from `spikes/p0-media/capture_spike.py`. Handles epochs, discontinuity detection (`ashowinfo` pts), health, bounded local ring, and the PDT segment-delay trace |
| `fazetime_worker/asr.py` | 4 s windows with a 3 s hop, kept within one epoch. Bounded drop-oldest queue, per-window deadline, bounded decoding, overlap dedupe, repetition filter |
| `fazetime_worker/api_client.py` | §9.16 client and an ordered, bounded uplink. Retries resend the identical (epoch, sequence) body and are bounded by time |
| `fazetime_worker/pipeline.py` | Wiring between the stages, a 5 s heartbeat, and the status trace (`worker_status.jsonl`) |
| `fazetime_worker/names.py` | Deterministic name aliases for downstream (P4) matching. Transcript text itself is sent verbatim |
| `scripts/test_source_lavfi.sh` | TEST_FIXTURE source: synthetic MPEG-TS with a stall and a +5 s pts jump. It is never Twitch evidence |
| `scripts/run_pi.sh`, `scripts/stop_pi.sh` | Detached start (setsid/nohup) and graceful stop. Logs go to `~/fazetime-data/worker.log` |

## Contract mapping

- **Epochs** are `ep_<32 hex>`. A new epoch opens on:
  - process start (`PROCESS_START`);
  - every process restart (`PROCESS_RESTART`);
  - an audio pts jump larger than 0.1 s (`PTS_DISCONTINUITY`), split at the exact sample;
  - a Streamlink ad-filter or discontinuity event (`AFTER_GAP`).

  The old epoch first gets a `GAP` observation. Old epochs are never resumed: their late items are dropped locally, and queued ASR windows from an old epoch are discarded.
- **`sequence`** is a positive integer per epoch, starting at 1, shared by FRAME, TRANSCRIPT and GAP items. A frame's evidence upload and its FRAME observation use the same (epoch, sequence).
- **Media positions** are decoded sample counts. Frames are mapped to the same timeline through their pts, and `media_start_ms == media_end_ms` for a FRAME.
- **Worker health:**
  - CONNECTING: no decoded audio yet.
  - LIVE: newest decoded audio is at most 12 s old.
  - STALE: newest audio is older than 12 s. A contiguous resume returns to LIVE in the same epoch.
  - GAP: a discontinuity occurred. It is sticky and leads to a new epoch.
  - STOPPED: a process exited, connect timed out, or there was no audio for more than 30 s. A restart follows with 1/2/4/8/16/30 s backoff.

  The heartbeat goes out every 5 s and immediately on a state change (at most 1/s). It reports `gap_threshold_ms = 12000`, the ASR `asr_backlog_ms` (age of the oldest untranscribed window), and `queue_depth`. The worker reports **STALE instead of LIVE** if the ASR backlog exceeds 12 s, or if any window was skipped (overflow or waited more than 6 s) within the last 12 s. A transcript coverage hole is never presented as fresh.
- **Transcripts:**
  - One TRANSCRIPT observation per 4 s window, including an empty text for silence, so a quiet window is an explicit observation and not missing data.
  - The text is capped at 1,000 chars.
  - Flags: `DEDUPED_OVERLAP` when repeated overlap words were trimmed. `LOW_CONFIDENCE` when avg_logprob < −1.0, no_speech_prob > 0.6, or a repetition loop (compression ratio > 2.4) was removed.
  - `captured_at_utc` is the worker wall time at which the window's audio arrived.
  - `source_wall_time_utc` is always null.
- **Uplink:**
  - One ordered queue, with at most 2000 ops; registrations are never dropped.
  - Observation batches hold at most 50 items, sent within about 1 s.
  - Frames over 300 KB are not sent.
  - Only network errors, timeouts, 5xx and 429 are retried: 0.5 s doubling to a 10 s cap, giving up after 120 s for items and 600 s for registration.
  - 409 `STALE_EPOCH` and other 4xx responses are dropped, not retried.
  - The bearer token appears only in the `Authorization` header. It is never logged, printed or written.

## Configuration (environment; CLI flags override)

| Variable | Meaning |
|---|---|
| `FAZETIME_API_BASE` | e.g. `http://fazetime:8000`. **Unset means dry-run**: everything is written to `<data>/uplink_dryrun.jsonl` |
| `FAZETIME_WORKER_TOKEN` | `fzk_…` MEDIA_WORKER token from `uv run python -m fazetime_api issue-worker-token`. Never commit or print it |
| `FAZETIME_STREAM_ID` | `str_…` stream ID from the API |
| `FAZETIME_TWITCH_CHANNEL` | Default `fazegavin1234`. Quality defaults to `best`; the team channel has 1080p60 only |
| `FAZETIME_ASR_MODEL` / `FAZETIME_ASR_THREADS` | Default `tiny.en` / `3` (see Step A) |
| `FAZETIME_ASR_MODELS_DIR` | Directory holding plain CT2 model dirs (`<dir>/tiny.en/model.bin`). If missing, the official Systran repo is used |
| `FAZETIME_ASR_HOTWORDS` | Default none. **Do not set** for the demo; see the hallucination finding below |
| `FAZETIME_WORKER_DATA_DIR` | Local ring, timelines, logs and status. Default `~/fazetime-data/worker` |
| `FAZETIME_STREAMLINK_BIN`, `FAZETIME_FFMPEG_BIN`, `FAZETIME_WORKER_HOST_ID` | Optional overrides |

Decoding defaults: `int8`, `beam_size=5`, `temperature=0` (no fallback ladder), `max_new_tokens=64`, `vad_filter=True`, `condition_on_previous_text=False`. The window is 4000 ms with a 3000 ms hop. The queue holds at most 4 windows, and a window that waited more than 6 s is dropped.

## Run

```bash
# laptop (dev): tests (32: units, fake-API client, ~40 s offline end-to-end with real FFmpeg)
cd services/worker && uv sync && uv run pytest
# dry run against a TEST_FIXTURE source (no Twitch, no API, fake ASR):
uv run python -m fazetime_worker run --dry-run --asr-engine fake --duration-s 40 \
  --test-source-cmd "bash $PWD/scripts/test_source_lavfi.sh" --data-dir out/fixture

# Pi (no sudo). Python 3.12 via uv; the venv lives in services/worker/.venv:
cd ~/fazetime/services/worker
UV_PYTHON_INSTALL_DIR=$HOME/fazetime-spike/uv-python UV_NO_MODIFY_PATH=1 ~/.local/bin/uv sync --frozen
# models: plain CT2 dirs under services/worker/models/<name>/ (copied from the spike's Systran snapshots)
.venv/bin/python -m fazetime_worker check                       # validates env/config, never prints the token
scripts/run_pi.sh                                               # live: reads ~/fazetime-data/worker.env (chmod 600) if present
scripts/run_pi.sh --dry-run --duration-s 900                    # no API yet: uplink recorded locally
tail -f ~/fazetime-data/worker.log; scripts/stop_pi.sh
```

`worker.env` (chmod 600, never committed):
`FAZETIME_API_BASE=http://fazetime:8000`, `FAZETIME_WORKER_TOKEN=fzk_…`, `FAZETIME_STREAM_ID=str_…`.

## Measured (Pi 5, 2026-11-15)

- **Frame decode cost at 1080p60.** Public channel `summit1g` (TOOLCHAIN_SMOKE), worker in dry-run with fake ASR, 30 s CPU windows:
  - Full decode: ffmpeg **49.6% and 55.7%** of one core. P0-B on the team channel measured a 59.4% mean.
  - `-skip_frame:v nokey` (the default here): **3.9% and 3.9%**, about 13× less. Frames were still exactly every 2000 ms, because that channel's keyframe interval is 2 s, and averaged ~60 KB at 480p.
  - **The team channel's keyframe interval is unverified.** OBS "auto" keyframes can be about 4 s. Set OBS keyframe interval = 2 s, or run with `--no-keyframes-only`.
- **ASR on the team's P0-B audio:** see `spikes/p0b-team/README.md`. tiny.en int8 with 3 threads and bounded decoding: speech-chunk p50 0.96 s, p95 1.23 s, max 2.5 s, duty 0.30, no window over the 3 s hop.

## Known limits

- One ffmpeg, so a decode stall stalls both audio and frames. It is detected as STALE and then STOPPED, followed by a restart.
- While Streamlink reports an ad-filter pause, the state is GAP. In that state the no-media restart limit is 180 s instead of 30 s, so the worker does not loop through reconnects into another preroll. This is untested live: no ads were seen on any channel so far.
- An ad pause followed by a pts jump can open two epochs in quick succession (AFTER_GAP, then PTS_DISCONTINUITY 0.1–0.2 s later). Both are correct and both void, but the first epoch is tiny.
- faster-whisper cannot be interrupted mid-window. The deadline is enforced by bounded decoding plus dropping windows that waited more than 6 s.
- Overlap dedupe is text-based (suffix/prefix match of up to 8 words), so a word cut at a window edge can still repeat.
