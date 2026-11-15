# Twitch ingestion and evidence timing

Status: researched design, not implemented or benchmarked. Checked 2026-11-14 America/Chicago. `PROJECT_PLAN.md` is authoritative for phase order, scope, acceptance, and progress; this document supplies implementation constraints for its media phases. Resolve the actual hardware, deadline, and game in P0 before selecting models or writing a timing promise.

## Required source and adapter selection

The final demonstration must analyze audio/video delivered through Twitch. The team will broadcast its own prerecorded video through OBS. A local copy may supply test fixtures and comparison timestamps, but cannot supply the final inference input or substitute for Twitch acceptance. An OBS source screenshot or direct audio feed likewise cannot count as Twitch ingestion.

First candidate: one Python-supervised Streamlink process, feeding FFmpeg, providing one stream's audio and video. One decode path should produce transcription audio and sparse images. Pin the versions that pass the actual venue-network spike. Do not assume that a particular Twitch variant, codec, or flags copied from an old example exist.

Fallback: one designated operator uses an explicitly invoked Chrome tab-capture flow on the ordinary Twitch player. That still analyzes Twitch-delivered media. It is an operator capture role, not a request for every viewer to upload their tab. Build this fallback only if the initial spike fails or proves unreliable. If both paths fail, Twitch acceptance is blocked; retain the working UI and test fixtures without mislabeling them as the finished feature.

There is no supported technique that guarantees a third-party media client will never be blocked. Do not plan proxy rotation, account rotation, token harvesting, ad bypass tricks, or reverse engineering of private playback protections. An access rejection is a bounded diagnostic and source-adapter decision.

## What the platform actually provides

Twitch's Helix Get Streams endpoint supplies metadata; its thumbnail may be a frame from the preceding five minutes. It is unsuitable as evidence for a brief bet. EventSub reports platform events, not raw video, audio, or arbitrary gameplay results. Keep both optional for this single controlled channel. [S1, S2]

Streamlink's Twitch documentation states that ad intervals pause output and create discontinuities. It also explains that playback authentication is distinct from standard third-party application OAuth. A Helix token does not automatically solve media playback. Website session tokens are sensitive full-account credentials; they must never enter extension code, git, screenshots, URLs, or logs. Avoid making manual browser-token handling a hackathon dependency. [S3]

Chrome tab capture requires explicit user invocation. Capture can stop the tab's ordinary audio output unless routed back; an offscreen document supports the ongoing media work that a service worker cannot perform with DOM APIs. Set the supported browser baseline from documented requirements and test the exact installed Chrome. Capture must not depend on the popup staying open. [S4, S5]

## Bounded initial spike

Allocate a proposed 30–45 minutes, adjusted to the P0 deadline. Use the actual team channel, OBS file/settings, device, and network. Do not begin a general stream-downloader project.

1. Inspect Streamlink/FFmpeg versions and available stream variants. Select decodable video with legible result cues. Audio-only proves transcription, not visual evidence.
2. Produce audio and images from one Twitch feed for 10–15 minutes. Include at least one source stop/start and a network interruption.
3. Record time to first media, stalls, decode errors, audio/image alignment, recovery time, CPU, memory, and queue growth.
4. Confirm that a stall becomes a visible unhealthy state instead of silence that the model treats as an uneventful stream.
5. If access remains rejected or decoding is repeatedly unstable, choose tab capture. Record the failure and installed versions. Do not keep retrying indefinitely.

Pass requires actual Twitch media, observable discontinuities, bounded resources, and a usable timeline. This spike is not complete because the process launches or a single screenshot appears.

## Observation envelope and resource budget

Each observation needs `stream_id`, `stream_session_id`, `source_epoch`, sequence number, source kind, decoded media start/end milliseconds, server receipt UTC, gap flags, and an evidence reference. Optional source wall time must remain null unless measured or supplied by a trustworthy mapping. Keep host-local monotonic timestamps for durations; never compare monotonic values from different machines.

Use `TWITCH_STREAMLINK` or `TWITCH_TAB_CAPTURE` for final evidence. Test observations have a visibly different source kind and cannot enter final-mode publication or settlement. Create a new ingest session after restart, seek, loop, or adapter switch. Reject old-session messages even if their timestamps or text resemble current content.

Initial engineering targets, to benchmark rather than assume: mono 16 kHz PCM for ASR; approximately four-second speech chunks (test a 2–8-second range) with deduplicated overlap; sparse images around every two seconds, with extra sampling near expected result cues. Chunks and sampling cadence must adapt to observed latency and selected game. Low-resolution full frames may erase scoreboards; consider a measured crop from the same image rather than blindly sending more pixels.

Audio and images must share one timeline. Associate transcript spans with overlapping images, not whichever screenshot arrived most recently. Maintain a short bounded evidence buffer, a compact current-state summary, and recent transcript spans. Preserve original evidence references for settlement review. Do not continuously resend the entire stream history to the LLM.

Bound queue depth and memory. A slow worker must mark observations stale and stop new proposals, not process an ever-growing backlog while presenting itself as live. Place decoding/ASR on a laptop if the Pi fails the real-time benchmark; 16 GB RAM alone says nothing about CPU, codec acceleration, wheels, or thermal headroom. Use Python process supervision and explicit health status, with TypeScript only for browser capture/UI. No Rust service or distributed media platform is needed.

For tab capture, decide and test the transport: continuous demux of MediaRecorder output or a PCM-plus-image path. MediaRecorder blobs are not guaranteed to be independent playable files. Verify chunk ordering, reconnect behavior, backpressure, navigation, Stop Capture, permission refusal, and local audio. A capture tab closing must immediately mark the stream unhealthy.

## Clock discipline and market safety

OBS playback, backend Twitch playback, individual viewers, and server wall time differ. Wi-Fi proximity does not synchronize them. Twitch's embedded-player API exposes live latency statistics, but its current-time method is for VODs; moreover the embed SDK is not automatically available on Twitch's own page. Do not base correctness on an undocumented live-player timestamp. [S6]

The server owns the opening and lock deadlines and checks the lock atomically when accepting a wager. Client countdowns are estimates for presentation. Pausing video, refreshing, reconnecting, or changing a system clock cannot reopen acceptance.

Before publishing, require fresh continuous evidence, a supported future challenge, an objective resolution rule, and enough time for a user to act. The LLM proposes; deterministic validation decides whether the proposed market is admissible. Its timeout must not override server limits. Automatic operation is the desired outcome once the quality gate in `PROJECT_PLAN.md` passes. Before that gate, a review step may expose evidence and uncertainty; a manual action must be labeled as such.

Use a scripted long setup for the first event. Measure setup-cue-to-proposal time through Twitch, ASR, model, server, and UI. Then choose the prerecorded lead-in long enough for the measured worst relevant delay, human betting time, and a documented margin. Do not hardcode a supposedly safe duration from this plan. A spontaneous 1v3 often ends before the pipeline can offer it; it is not the initial acceptance case.

The source file is known in advance only to the test author/operator. Final-mode inference must not receive future frames, authored answers, hidden outcome annotations, or a precomputed transcript beyond the live evidence boundary. Test fixtures may use ground truth for evaluation, but keep it outside the model prompt and runtime state.

If an actual media discontinuity compromises an open or locked/unsettled market, stop acceptance and void/refund its reservations through the normal idempotent ledger path. Do not guess an outcome or stitch across missing evidence. No refunded/void stake contributes raffle weight. Finalized valid settlements are immutable; a later unrelated gap does not reverse them. Restart establishes a new ingest session, flushes temporal context, and requires fresh healthy evidence before another market opens. Repeated video loops must not repeat earlier bets, calls, or raffle draws.

## Recovery and diagnostics

Expose `CONNECTING`, `LIVE`, `GAP`, `STALE`, and `STOPPED`, plus last media age, last transcript age, queue depth, active session, and source kind. Process liveness alone is not media freshness. Add bounded retry/backoff and a clear operator-visible failure. Helix calls, if used, follow rate-limit headers and wait on 429; those rules do not constitute a playback retry strategy. [S7]

Test these failures before acceptance: decoder killed; ten-second connectivity loss; duplicate chunk; old-session chunk; paused source; loop; capture permission denied; capture tab closed; model timeout; service-worker termination. None may fabricate results, accept late bets, duplicate refunds, or add raffle weight from voided stakes. Recovery may resume ingestion automatically, but new markets require restored freshness and a new valid future event.

## Sources

- S1: https://dev.twitch.tv/docs/api/reference/streams — metadata and thumbnail freshness.
- S2: https://dev.twitch.tv/docs/eventsub/ and https://dev.twitch.tv/docs/eventsub/handling-websocket-events — notifications, duplicates, recovery.
- S3: https://streamlink.github.io/cli/plugins/twitch.html and https://streamlink.github.io/cli.html — Twitch limitations, codecs, output and retries.
- S4: https://developer.chrome.com/docs/extensions/reference/api/tabCapture/ — user invocation, audio and stream IDs.
- S5: https://developer.chrome.com/docs/extensions/reference/api/offscreen and https://developer.chrome.com/docs/extensions/develop/concepts/service-workers/lifecycle — offscreen/media lifetime and worker persistence.
- S6: https://dev.twitch.tv/docs/embed/video-and-clips/ — live versus VOD player statistics.
- S7: https://dev.twitch.tv/docs/api/guide — rate limits.
- Media building blocks: https://ffmpeg.org/ffmpeg-protocols.html and https://ffmpeg.org/ffmpeg-filters.html — inspect the installed binary's actual capabilities.
