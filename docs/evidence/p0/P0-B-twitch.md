# P0-B: Twitch capture on the team channel (gate evidence)

- **Phase / task / date:** P0-B. 2026-11-15 03:15–03:31Z (21:15–21:31 CT, 2026-11-14).
- **Mode:** live Twitch, channel `fazegavin1234`. The owner streamed from OBS: talking plus gameplay, with names mentioned. Label `P0B_TEAM_CHANNEL`, source `TWITCH_STREAMLINK`.
- **Host:** Raspberry Pi 5 (`fazetime`) on the official 27 W PSU. Streamlink 8.6.3 with system ffmpeg 7.1.5. The capture supervisor was promoted from `spikes/p0-media/capture_spike.py`.
- **Variants:** `audio_only` and `1080p60` only. A new channel gets no transcodes. Capture used `best`, i.e. 1080p60.

## Results

`check_timeline.py` found no problems: 1,427 records.

| Check | Result |
|---|---|
| Coherent audio + frames | 941 s of audio across 3 media epochs, plus 471 frames, all aligned to the media timeline |
| Owner stop/start of the stream (03:21:14Z) | STOPPED in about 0.5 s. Three reconnects failed with "no playable streams" (backoff 1/2/4 s). LIVE again 26.2 s later, mostly the owner's offline time; the startup itself took 7.9 s. Each restart opened a new `source_epoch` with a fresh sequence |
| Forced Streamlink kill (03:25:23.56Z) | Detected in 126 ms. A new epoch was LIVE 4.47 s later |
| GAP/STALE during LIVE | None. No ads and no discontinuities |
| Delivery cadence | Median 5.99 s between bursts. Media was at most 5.35 s old while LIVE, so the LIVE ≤12 s threshold (D29) holds |
| Twitch delivery delay | From segment completion to HLS program-date-time: p50 4.07 s, p95 6.02 s, max 8.0 s |
| CPU at 1080p60 (Pi) | ffmpeg 59% of a core on average (p95 79%), 150 MiB. Streamlink 1.7%. Keyframe-only decoding (`-skip_frame nokey`) cut ffmpeg to 3.9% on a public 1080p60 channel, at one frame per 2.000 s. This needs a 2 s OBS keyframe interval |
| Pi health | Throttling `0x0` throughout |

**Not measured:** glass-to-capture end-to-end delay. The OBS clock overlay wasn't added, so it moves to the P4 lead-in measurement.

## ASR on this audio (P0-D, team content)

Details: `spikes/p0b-team/README.md`. Transcripts stay on the Pi only.

- **Choice:** tiny.en, int8, 3 threads, beam 5, `temperature=0`, `max_new_tokens=64`, VAD on, no hotwords or prompt.
- **Load:** across 933 s, the duty cycle was 0.336, p95 per window 1.3 s, max 2.6 s, and no window over its 3 s hop.
- **base.en:** duty 0.62, with 9 of 311 windows over the hop.
- **Names:** no model spelled FaZeGavin or FaZeNeville exactly. They heard "face/phase/Faze Gavin" and "face/phase neville". Names are therefore matched after transcription against a fixed alias list (`services/worker/fazetime_worker/names.py`).
- **Prompts rejected:** decoder prompts and hotwords invented "FaZeGavin"/"1v1" loops in silence, which risks false markets.

**Verdict:** P0-B PASSED. The Twitch path is proven on the team channel, and the STT path is proven on the Pi with team audio.
