# A. Multimodal streaming models and costs (as of 2026-11-14)

Scope: Gemini Live API, Gemini media token costs through generateContent, free-tier limits, continuous streaming compared with periodic uploads, and open models on the 8-vCPU CPU VM. All Google docs pages were fetched 2026-11-14 on aistudio.google.com/docs/*, and none shows a "last updated" date, so they are dated "accessed 2026-11-14". Changelog entries carry their own dates. The project's own measurements are cited from its evidence files and labelled REPORTED (project measurement).

## 1. Gemini Live API today: models, input formats, session limits, output, structured output and tools, free tier, price, latency

### Takeaway
Four models currently support the Live API: `gemini-3.8-live`, `gemini-3.8-live-extended-thinking`, `gemini-3.1-flash-live-preview` and `gemini-2.5-flash-native-audio-preview-12-2025`. Separately, `gemini-3.5-transcribe-live` is a streaming speech-to-text model. Live video is capped at 1 frame per second (JPEG/PNG). Audio+video sessions last 2 minutes without context compression, and a connection lives about 10 minutes. Output is audio, with text available only as a transcript. Function calling is supported; JSON-schema output is not documented. The free tier is "Free of charge", but its limits (concurrent sessions, TPM) are not published. That combination of hard limits and unknowns makes Live a poor fit for a 12-hour build.

### Cited Findings
- **Live models and their differences** (VERIFIED_DOC, accessed 2026-11-14) — [Live guide](https://aistudio.google.com/docs/live-guide):
  - The guide names `gemini-3.8-live`, `gemini-3.8-live-extended-thinking`, `gemini-3.1-flash-live-preview` and `gemini-2.5-flash-native-audio-preview-12-2025`.
  - `gemini-3.8-live`: interleaved thinking (omit `thinkingLevel`), proactive audio always on, function calling async by default with blocking available.
  - `gemini-3.8-live-extended-thinking`: thinking levels low/medium/high; async `NON_BLOCKING` function calling only.
  - `gemini-3.1-flash-live-preview`: thinking defaults to `minimal`; function calling is synchronous only; no proactive audio.
  - The guide says the Live API itself is in preview.
- **Release dates** (VERIFIED_DOC, changelog) — [Changelog](https://aistudio.google.com/docs/changelog):
  - `gemini-3.1-flash-live-preview` released 2026-03-26.
  - `gemini-3.5-transcribe` and `gemini-3.5-transcribe-live` GA 2026-08-26. The Live variant does streaming speech-to-text over WebSockets.
  - Gemini 3.8 Live and 3.8 Live Extended Thinking GA 2026-09-15.
  - `gemini-2.0-flash-live-001` and `gemini-live-2.5-flash-preview` shut down 2025-12-09.
  - Conflict: the changelog calls 3.8 Live GA, while the Live guide calls the Live API preview.
- **Input formats** (VERIFIED_DOC, accessed 2026-11-14) — [Live overview](https://aistudio.google.com/docs/live); [Live guide](https://aistudio.google.com/docs/live-guide):
  - Audio input is raw 16-bit little-endian PCM at 16 kHz. Other rates are resampled if labelled, e.g. `audio/pcm;rate=16000`.
  - Visual input is individual images (JPEG, or PNG per the guide) at "<= 1FPS". No maximum resolution is given; token allocation is set with `mediaResolution`.
- **Output modalities** (VERIFIED_DOC, accessed 2026-11-14) — [Live overview](https://aistudio.google.com/docs/live); [Live guide](https://aistudio.google.com/docs/live-guide):
  - Audio output is 24 kHz 16-bit PCM.
  - Native-audio models support only the AUDIO modality. Text comes through output audio transcription.
  - The overview says Live provides "text transcripts of both user input and model output".
- **Tools and structured output** (VERIFIED_DOC, accessed 2026-11-14) — [Live overview](https://aistudio.google.com/docs/live); [Live guide](https://aistudio.google.com/docs/live-guide):
  - Function calling is supported on all four Live models. The overview also names Google Search as an integrated tool.
  - Neither page mentions `response_schema` or structured JSON output, and code execution is not mentioned.
- **Session limits, connections and resumption** (VERIFIED_DOC, accessed 2026-11-14) — [Session management](https://aistudio.google.com/docs/live-session):
  - Without compression, audio-only sessions are limited to 15 minutes and audio+video sessions to 2 minutes.
  - Context window compression (a `SlidingWindow` with a configurable trigger) "extend[s] sessions to an unlimited amount of time".
  - A connection lasts "around 10 minutes". A `GoAway` message with `timeLeft` precedes termination.
  - Resumption handles arrive in `SessionResumptionUpdate` and are valid "2 hr after the last sessions termination".
  - The page's examples use the model `gemini-3.8-live`.
- **Context windows** (VERIFIED_DOC, accessed 2026-11-14) — [Live guide](https://aistudio.google.com/docs/live-guide): 128k tokens for native-audio output models and 32k for other Live models. The guide does not say which category `gemini-3.1-flash-live-preview` falls in.
- **Voice activity detection and turn coverage** (VERIFIED_DOC, accessed 2026-11-14) — [Live guide](https://aistudio.google.com/docs/live-guide):
  - Automatic VAD is on by default and can be disabled in favour of manual `activityStart`/`activityEnd`.
  - The recommended `silenceDurationMs` is 500–800 ms; the server default is about 800 ms.
  - The 3.8 models include all video frames in a turn by default. The 3.1 and 2.5 models include only detected activity by default.
- **Paid prices; the free tier is "Free of charge" for all Live, transcribe and translate models** (VERIFIED_DOC, accessed 2026-11-14) — [Pricing](https://aistudio.google.com/docs/pricing):

  | Model | Input | Output |
  |---|---|---|
  | `gemini-3.8-live`, `-extended-thinking`, `gemini-3.1-flash-live-preview` | text $0.75/1M; audio $3.00/1M or $0.005/min; image/video $1.00/1M or $0.002/min | text $4.50/1M; audio $12.00/1M or $0.018/min |
  | `gemini-3.5-transcribe-live` | audio $3.50/1M or $0.005/min | text $21.00/1M or $0.004/min |
  | `gemini-2.5-flash-native-audio-preview-12-2025` | text $0.50; audio/video $3.00 | text $2.00; audio $12.00 |

  On the free tier, content is used to improve products.
- **Free-tier limits** (VERIFIED_DOC, accessed 2026-11-14) — [Rate limits](https://aistudio.google.com/docs/rate-limits): the page mentions no Live API concurrent-session or TPM limits.
- **Latency**: neither Live page gives a latency number, only qualitative "low-latency" wording (VERIFIED_DOC, accessed 2026-11-14) — [Live overview](https://aistudio.google.com/docs/live).

### Inferences
- **Price arithmetic.** At 25 audio tokens per second (see Q2), the per-minute audio prices are consistent with the per-token prices: 1,500 tokens/min × $3.00/1M ≈ $0.0045/min, and output 1,500 × $12/1M = $0.018/min. The video quote is not: $0.002/min at $1.00/1M implies about 2,000 tokens/min (about 33 tokens/s), less than the 70 tokens/frame × 1 fps = 4,200 tokens/min that the media-resolution table implies. The per-frame budget Live uses for video is therefore uncertain.
- **Audio-only outputs.** The Live models are native-audio models whose output is AUDIO, and response schemas are undocumented. A Live proposer would have to emit markets as function calls (a `propose_market` tool with a parameter schema) and validate them server-side. That is more code and less guarantee than `response_json_schema` on generateContent.
- **Watching without commentary.** On 3.1 and 2.5, the default turn coverage counts only detected (speech) activity. If streamers stop talking, frames may never reach a model turn. On 3.8, proactive audio is always on, so the model decides when to speak. Neither matches "evaluate every N seconds and return JSON".
- **Reconnects.** An audio+video session needs compression from minute 2 and a reconnect about every 10 minutes. That is roughly 72 or more resumptions over 12 hours, each a failure point. All of this is new WebSocket code to write tonight.
- **`gemini-3.5-transcribe-live`** is a possible upgrade from local tiny.en ASR: streaming STT that is free on the free tier, about $0.54/h at paid rates ($0.30 audio + $0.24 text). Its free limits are unknown and it adds a cloud dependency, so it is a "measure within one hour or skip" option, not a must.

### Gaps
- Free-tier Live limits (concurrent sessions, TPM, session minutes per day) are not public. Only the owner's AI Studio rate-limit page could show them.
- No documented or measured Live API latency was found.
- Not verified:
  - whether the project's `models.list` includes `gemini-3.8-live` with `bidiGenerateContent`. P0-C lists only `gemini-3.5-transcribe-live` as bidi among the named models.
  - whether Live bills or limits the cumulative context on each turn, or only new tokens.
  - the maximum Live image resolution.
  - whether Google Search and code execution work on each Live model.
- The Live guide (preview) and the changelog (GA) conflict on the Live API's maturity.

## 2. Video, audio and image understanding through generateContent; what `gemini-3.5-flash-lite` and `gemini-4-hydrogen` are

### Takeaway
On Gemini 3 and 4 models, image and video token budgets are fixed per item, not per pixel:
- An image costs 1,120 tokens at the default and 280 at `low`. The project measured about 1,100 and 264.
- A video frame costs 70 tokens at default, low or medium, and 280 at `high`.
- Audio costs 25 tokens per second.

A short MP4 clip at 1 fps is therefore far cheaper per frame than stills, but much less detailed. `gemini-3.5-flash-lite` (GA 2026-07-21) defaults to `minimal` thinking and is the low-latency choice. `gemini-4-hydrogen` (GA 2026-11-12, free tier available) defaults to `high` thinking and cannot go to `minimal`, so expect higher latency. Thinking tokens also count against `max_output_tokens`.

### Cited Findings
- **Media-resolution token table for "Gemini 4 and Gemini 3 models"** (VERIFIED_DOC, accessed 2026-11-14) — [Media resolution](https://aistudio.google.com/docs/media-resolution):

  | Level | Image | Video frame | PDF |
  |---|---|---|---|
  | `unspecified` (default) | 1,120 | 70 | 560 |
  | `low` | 280 | 70 | 280 + native text |
  | `medium` | 560 | 70 | 560 + native text |
  | `high` | 1,120 | 280 | 1,120 + native text |
  | `ultra_high` | 2,240 | N/A | N/A |

  - Audio is 25 tokens/s at every level.
  - Resolution can be set per part (e.g. `"resolution": "high"` on a media object) on Gemini 4 and 3.
  - Recommendations: `low` or `medium` for general video action recognition, `high` for dense text or small details (OCR), `high` for most image analysis.
- **Project measurement on `gemini-3.5-flash-lite`** (REPORTED, project measurement 2026-11-14) — [P0-C record](../../docs/evidence/p0/P0-C-gemini.md); the low-resolution figures are from the assignment brief:
  - One 854×480 JPEG cost 1,100 prompt tokens. 2.325 s end to end. 102 output tokens.
  - `low` measured about 264 tokens, and 854×480 and 384×216 cost the same.
  - This agrees with the fixed budgets above, not with the older 258-tokens-per-768-px-tile rule recorded in [P0 docs check](../../docs/evidence/p0/P0-docs-verification.md).
- **Video-understanding page uses different numbers** (VERIFIED_DOC, accessed 2026-11-14) — [Video understanding](https://aistudio.google.com/docs/video-understanding):
  - It says "approximately 100 tokens per second of video at default (low) media resolution" and "approximately 300 tokens per second" at high.
  - It also gives older-style figures: 66 tokens/frame at low, 258 otherwise, and audio at 32 tokens/s. These conflict with the media-resolution page above.
- **Frame sampling, clipping and timestamps** (VERIFIED_DOC, accessed 2026-11-14) — [Video understanding](https://aistudio.google.com/docs/video-understanding):
  - Default sampling is 1 fps.
  - Custom `fps`, `start_offset` and `end_offset` (seconds as strings, e.g. "1200s") go in a `processing` configuration object, and apply in "static mode" only.
  - Prompts can reference `MM:SS` timestamps, and static mode adds "Timestamps ... every second".
- **Size limits and formats** (VERIFIED_DOC, accessed 2026-11-14) — [Video understanding](https://aistudio.google.com/docs/video-understanding):
  - Inline video: the table says "< 100MB", but the prose says "under 20MB total request size" (the page contradicts itself). Inline is recommended for clips under 1 minute.
  - File API: 2 GB on free and 20 GB on paid; recommended above 100 MB or 10 minutes.
  - Gemini 2.5 and later accept up to 10 videos per request.
  - Formats include mp4, webm, mov and mpeg. Live streams are not mentioned.
- **`gemini-3.5-flash-lite`**:
  - GA 2026-07-21 as a "low-cost, low-latency option for high-volume automation" (VERIFIED_DOC, changelog) — [Changelog](https://aistudio.google.com/docs/changelog).
  - Stable; inputs text, image, video, audio and PDF; output text; 1,048,576 tokens in and 65,536 out; structured output; no Live API (VERIFIED_DOC per the project planner's doc check, 2026-11-14) — [P0 docs check](../../docs/evidence/p0/P0-docs-verification.md).
  - Default thinking is "On (minimal)"; levels are minimal, low, medium and high. `minimal` is "Near-off thinking, lowest latency" (VERIFIED_DOC, accessed 2026-11-14) — [Thinking](https://aistudio.google.com/docs/thinking).
  - Paid: $0.30/1M input (text, image, video and audio) and $2.50/1M output. Free tier: "Free of charge" (Standard); Batch and Flex are not available on free (VERIFIED_DOC, accessed 2026-11-14) — [Pricing](https://aistudio.google.com/docs/pricing).
  - From 2026-12-01, requests to `gemini-2.5-flash` route to it (VERIFIED_DOC, changelog 2026-11-02) — [Changelog](https://aistudio.google.com/docs/changelog).
- **`gemini-4-hydrogen`**:
  - GA 2026-11-12. "Available on the free tier" and the default model for the Antigravity agent (VERIFIED_DOC, changelog) — [Changelog](https://aistudio.google.com/docs/changelog).
  - Model page (VERIFIED_DOC, "Latest update: November 2026") — [Hydrogen model page](https://aistudio.google.com/docs/models/gemini-4-hydrogen):
    - Stable. Inputs text, image, video, audio and PDF; output text.
    - 1,048,576 unified context. Max output 65,536 (synchronous), or up to 1,048,576 with long decode.
    - Supports structured outputs, function calling, thinking (low, medium, high, xhigh), implicit caching only, Search and Maps grounding, code execution, URL context, file search, computer use, and "agentic video understanding (defaults to static)".
    - No Live API.
  - Paid: $1.50/1M input and $7.50/1M output. Free tier: "Free of charge" (VERIFIED_DOC, accessed 2026-11-14) — [Pricing](https://aistudio.google.com/docs/pricing).
  - Default thinking is "On (high)". `minimal` is "Not supported on Gemini 4 models" (VERIFIED_DOC, accessed 2026-11-14) — [Thinking](https://aistudio.google.com/docs/thinking).
  - I did not find the phrase "recommended for new projects" on the model page or in the changelog, although the project's planner recorded it from /docs/models.
- **Thinking billing and truncation** (VERIFIED_DOC, accessed 2026-11-14) — [Thinking](https://aistudio.google.com/docs/thinking): thinking tokens are billed as output and count toward `max_output_tokens`. If the limit is hit, status is "incomplete" and output may be truncated while thinking tokens are still billed.
- **Sampling parameters deprecated** (VERIFIED_DOC, changelog 2026-07-21) — [Changelog](https://aistudio.google.com/docs/changelog): `temperature`, `top_p` and `top_k` were deprecated.
- **Interactions API** (VERIFIED_DOC, changelog) — [Changelog](https://aistudio.google.com/docs/changelog): launched 2025-12-11. Its output schema changed from `outputs` to `steps` (default 2026-05-26; legacy schema removed 2026-06-08). Generate Content API storage became on by default for new paid-tier projects on 2026-10-26.

### Inferences
- **Reconciling the two video pages.** The "~100 tokens/s default" and "~300 tokens/s high" figures match the Gemini 3/4 table: 70 + 25 audio = 95 per second, and 280 + 25 = 305 per second. The 66/258/32 figures look like leftover Gemini 2.x text. Use 70 (or 280) per frame and 25 per second of audio for 3.5 Flash-Lite, and confirm with one `usage_metadata` read on a test clip.
- **Small budget mismatch.** The measured 1,100 and 264 against the documented 1,120 and 280 may be model-specific accounting on 3.5 Flash-Lite. Plan with the documented values (slightly conservative).
- **Clips versus stills.**
  - A 10 s, 1 fps clip with no audio track costs about 700 tokens; with audio, about 950. A single default still costs 1,120. A clip gives temporal context (who won the round, a ball dropping in Peggle) at a much lower per-frame cost.
  - Reading small text (chat kill-feed, scoreboard) needs `high`: 280 per frame, or one 1,120-token still of a crop.
  - Mixing is allowed per part: a clip at default plus one high-resolution still or crop.
- **Hydrogen is a risk tonight.**
  - Default high thinking and no `minimal` mean added latency; I found no measured figure.
  - The current `max_output_tokens=1024` could be consumed by thinking, giving truncated or "incomplete" JSON.
  - If tested, set `thinking_level="low"` and raise `max_output_tokens`. Keep 3.5 Flash-Lite as the primary.
- **Temperature.** The smoke test with `temperature=0` passed, but the parameter is deprecated. Determinism cannot be assumed; rely on schema validation plus abstain rules rather than temperature.

### Gaps
- Was the legacy generateContent `video_metadata` field (fps and offsets) still accepted in google-genai 3.3.0? Not verified. The fetched page documents a `processing` object instead.
- Does 3.5 Flash-Lite support "agentic video understanding" mode? Not checked.
- No documented latency for video calls on generateContent was found.
- The inline-size contradiction (20 MB vs 100 MB) is unresolved; use 20 MB or less.
- Exact release date and knowledge cutoff for Hydrogen beyond the changelog's GA date were not checked.
- What "Gemini Decision 1" is was not checked. It is the only model with public free limits on the rate-limit page (200 RPM, 50,000 TPM, 10,000 RPD) — [Rate limits](https://aistudio.google.com/docs/rate-limits).

## 3. Free-tier rate limits: what is public, change history, 429 behaviour, and a conservative plan

### Takeaway
What is public:
- Limits are per project; RPD resets at midnight Pacific (02:00 CT tonight).
- "Specified rate limits are not guaranteed".
- Exceeding a limit returns 429 RESOURCE_EXHAUSTED.

Free-tier RPM, TPM and RPD for 3.5 Flash-Lite and Hydrogen are not published. Free quotas were reportedly cut sharply in December 2025, to as low as 20 RPD for some Flash models. Plan the judged demo to work on very few calls, and have the owner read the real number in AI Studio now.

### Cited Findings
- **Public rules** (VERIFIED_DOC, accessed 2026-11-14) — [Rate limits](https://aistudio.google.com/docs/rate-limits):
  - "Rate limits are applied per project, not per API key."
  - RPD "reset at midnight Pacific time".
  - The dimensions are RPM, TPM and RPD. Some models also have TPD.
  - Spend-based limits are evaluated over a rolling 10-minute window.
  - "Specified rate limits are not guaranteed and actual capacity may vary."
  - Free tier qualification: "Active project or free trial; some projects need verification."
- **What the page publishes** (VERIFIED_DOC, accessed 2026-11-14) — [Rate limits](https://aistudio.google.com/docs/rate-limits):
  - No free-tier numbers for Gemini 3.5 Flash-Lite or Gemini 4 Hydrogen. They appear only in Batch enqueued-token tables from Tier 1 (Flash-Lite 10,000,000; Hydrogen 3,000,000).
  - The only public free row is "Gemini Decision 1": 200 RPM, 50,000 TPM, 10,000 RPD. Gemini Omni Flash is "Not supported" on free.
  - Live API limits are not mentioned.
- **Exceeding limits** (VERIFIED_DOC, accessed 2026-11-14) — [Rate limits](https://aistudio.google.com/docs/rate-limits):
  - Exceeding any limit triggers a rate-limit error. For spend limits the API returns `429 RESOURCE_EXHAUSTED`.
  - The advice is "Wait and retry after a short period", reduce expensive requests, or request an increase.
  - `retryDelay` is not described on the page.
- **Where the numbers live** (VERIFIED_DOC per the project planner, 2026-11-14) — [P0 docs check](../../docs/evidence/p0/P0-docs-verification.md); [P0-C record](../../docs/evidence/p0/P0-C-gemini.md): numeric free limits are visible only in the owner's AI Studio (`/rate-limit`, `/usage`).
- **Documented changes** (VERIFIED_DOC, changelog) — [Changelog](https://aistudio.google.com/docs/changelog):
  - 2026-03-12: project-level spend caps.
  - 2026-03-16: usage tiers and spend caps revamped.
  - 2026-03-23: prepay and postpay plans.
  - 2026-09-18: access to 2.5 models limited to past users.
  - 2026-11-05: paid-tier Omni 1.2 Flash limits doubled.
- **December 2025 cut** (REPORTED, 2025-12-20) — [Technobezz](https://www.technobezz.com/news/google-slashes-free-gemini-api-requests-to-20-per-day-2025-12-20-gl06):
  - Headline: Google "Slashes Free Gemini API Requests to 20 Per Day".
  - Secondary blogs in the same search describe 50–80% free-tier cuts, including 2.5 Flash going from about 250 to 20–50 RPD. These figures were not independently verified.
  - The backlash is covered (REPORTED, undated) — [aiscroll](https://aiscroll.pages.dev/article/google/gemini-free-tier-cutback-backlash).
- **April 2026 restructuring** (REPORTED):
  - Pricing restructured effective 2026-04-01; "Free tier Flash-only, Pro paid-only" (2026-04-08) — [agentdeals.dev](https://agentdeals.dev/gemini-api-pricing-changes).
  - "Spend caps enforced April 1; 3.1 Pro paid-only; prepaid billing live" (2026-03-26, updated 2026-04-02) — [agentdeals.dev](https://agentdeals.dev/gemini-api-pricing-2026).
  - The search summary also noted a September 2026 guide contradicting "Pro paid-only"; it was unresolved and not opened.
- **Current worker limits** (REPORTED, project brief): 1 request per 6 s and 300 requests per Pacific day.

### Inferences
- **The worker's 300 RPD lasts 30 minutes at full cadence.** At 1 request per 6 s (600 per hour), 300 requests are used up in 30 minutes. The gating is what makes the day's budget last. Spread across the demo-day window (02:00–12:00 CT), 300 requests is an average of one call every 2 minutes.
- **The 02:00 CT reset splits the night into two quotas.** Pacific midnight is 02:00 CT on Sunday 2026-11-15 (PST is UTC−8, CST is UTC−6). Quota spent after 02:00 CT comes out of the judged demo's budget. Soak tests after 02:00 should be capped or run against replay with the model stubbed, and labelled as test mode.
- **Conservative planning assumption** (no visibility of the real numbers):
  - Treat 300 RPD as a ceiling to validate, not a guarantee.
  - Ensure a complete propose → bet → resolve cycle works with about 20 calls in the demo window. That is the lowest reported free figure, applied to a different model, and is a worst case.
  - Keep the at-most-10-RPM self-limit.
  - Reserve at least half of the day's budget for 09:00–12:00 CT.
  - Default to operator approval mode.
  - If the daily quota is exhausted, stop calling until 02:00 CT, keep the market in approval or manual mode, and void or refund rather than guess.
- **Handling 429s** (from pre-2026 experience; not re-verified this session):
  - Gemini 429 bodies typically carry `google.rpc.RetryInfo.retryDelay` and a `QuotaFailure` that names a per-minute or per-day quota.
  - Honour `retryDelay` when present. Otherwise back off exponentially with jitter (for example 6 s, 12 s, 24 s, capped at 60 s).
  - Never retry a stale proposal window; drop it.
  - Retry resolution only with the same evidence snapshot ID, so retries cannot repeat effects.
  - Treat a per-day quota violation as terminal until the reset.
- **Hidden spend.** Thinking tokens, high resolution and multi-frame calls raise TPM, not RPD. With unknown TPM, keep each call at about 3k tokens or less.

### Gaps
- Exact current free RPM, TPM and RPD for `gemini-3.5-flash-lite` and `gemini-4-hydrogen` are not public. The owner must read them at aistudio.google.com/rate-limit.
- The `retryDelay`/`RetryInfo` structure and the `QuotaFailure` quota IDs are not documented on the fetched page.
- 503 or overload behaviour on the free tier was not researched.
- Pre-December-2025 published free limits could not be re-verified this session. My training-era recollection, unverified, is about 10–15 RPM, 250k TPM and 250–1,000 RPD for Flash and Flash-Lite.
- The December 2025 cut figures come from secondary sources only. I found no official Google announcement.

## 4. Continuous streaming vs periodic frame/clip uploads for "watch a live stream and propose bets"

### Takeaway
Keep periodic generateContent calls with `response_json_schema` on `gemini-3.5-flash-lite`. Consider swapping "1–2 stills" for "a short MP4 clip at 1–2 fps plus an optional high-resolution crop". That gives more temporal context per token and cleaner evidence provenance (MM:SS within a stored clip). Continuous Live streaming burns about 342k tokens/hour at default resolution against undocumented free limits. It needs compression and roughly 72 reconnects in 12 hours, offers no documented JSON output, and is not deployable safely by the 09:00 freeze.

### Cited Findings
- Token rates for Gemini 3/4: video 70 tokens/frame (default), 280 (high); image 1,120 default and 280 low; audio 25 tokens/s (VERIFIED_DOC, accessed 2026-11-14) — [Media resolution](https://aistudio.google.com/docs/media-resolution).
- Live constraints (VERIFIED_DOC, accessed 2026-11-14):
  - Visual input "<= 1FPS" — [Live overview](https://aistudio.google.com/docs/live).
  - Audio+video sessions are 2 minutes without compression. Connections last about 10 minutes. Resumption handles are valid for 2 hours — [Session management](https://aistudio.google.com/docs/live-session).
  - Context window is 32k, or 128k for native audio. The 3.1 and 2.5 models default to activity-only turn coverage. Response schemas are undocumented — [Live guide](https://aistudio.google.com/docs/live-guide).
- Periodic generateContent features (VERIFIED_DOC, accessed 2026-11-14) — [Video understanding](https://aistudio.google.com/docs/video-understanding):
  - Custom fps and clip offsets (static mode).
  - `MM:SS` references and per-second timestamps in static mode.
  - Inline clips under 20 MB (or 100 MB per the table).
- Measured periodic call latency is about 2.3 s end to end from the laptop (REPORTED, project measurement 2026-11-14) — [P0-C record](../../docs/evidence/p0/P0-C-gemini.md).

### Inferences
- **Token burn per hour**, computed from the documented rates; INFERRED arithmetic:

  | Mode | Tokens/s | Tokens/hour | 12 hours | Notes |
  |---|---|---|---|---|
  | Live A+V, 1 fps, default video + audio | 70 + 25 = 95 | ~342k | ~4.1M | 32k context fills in ~5.5–6 min; 128k in ~22–23 min, so compression is mandatory |
  | Live A+V at high video | 280 + 25 = 305 | ~1.1M | ~13.2M | |
  | Live video only (default) / audio only | 70 / 25 | 252k / 90k | 3.0M / 1.1M | |
  | Periodic stills, today's cadence (1 call/6 s, 600/h), 1–2 default frames + ~60 s transcript | — | ~0.9–1.6M (prompt about 1.5–2.7k/call) | capped by RPD | 300 RPD lasts ~30 min at this cadence |
  | Periodic stills at `low` (2 × 280 + text) | — | ~0.4–0.6M at 600/h | capped by RPD | |
  | Periodic clip, 10 s at 1 fps default, no audio (local ASR text instead) | — | ~700 + text per call | — | 2 fps: ~1,400; `high`: ~2,800; with audio track: +250 |
  | Periodic clip, 60 s at 1 fps default, no audio | — | ~4,200 + text per call | — | Covers 1 minute for about the cost of two default stills |

- **Paid-equivalent cost of Live**, for scale only, since the free tier is "Free of charge":
  - Video: about $0.12–0.25/h. Audio: about $0.27–0.30/h. Input total about $0.4–0.55/h, or about $5–7 over 12 hours before output.
  - On the free tier the binding constraint is unknown limits, not cost.
- **Latency.**
  - Both approaches inherit Twitch's delay (6 s HLS bursts, p50 about 4 s).
  - Periodic: about 4 s Twitch + up to the 4 s ASR window + about 2 s model, so roughly 10–15 s from event to proposal candidate.
  - Live might save a few seconds of the model share only. No Live latency is documented, and its 1 fps cap means fast events between frames are invisible to it.
  - With custom `fps`, periodic clips can sample 2–5 fps briefly around a trigger.
- **Evidence provenance.**
  - Periodic calls are self-contained. Each request's inputs (clip file, frame hashes, transcript window, stream epoch and offset) can be stored, and the model can cite `MM:SS` inside the clip, which maps to stream time. This supports "evidence-gated resolution" and audit.
  - A Live session's state is cumulative, then compressed by a sliding window, so it is hard to prove which frame or utterance a model claim rests on. Untrusted stream speech also accumulates inside a long-lived context.
- **Failure modes.**
  - Live:
    - WebSocket drops and the ~10-minute GoAway.
    - Missed or expired resumption handles.
    - Compression dropping key context.
    - Activity-only turn coverage skipping silent gameplay.
    - Proactive audio speaking unprompted.
    - AUDIO-only output.
    - Undocumented structured output.
    - Unknown free concurrency or TPM.
    - "Preview" status.
  - Periodic:
    - 429 on RPM or RPD.
    - An unknown TPM ceiling.
    - Clip-encode overhead (FFmpeg segment-to-MP4, likely sub-second for 10 s at 480p; unmeasured).
    - The inline-size ambiguity.
    - Low detail at 70 tokens/frame, unsuitable for reading chat text without a `high` crop.
- **Fit for a 12-hour free-tier deadline.** Periodic, event-gated generateContent with a structured schema is the only option that reuses working code (P0-C passed).
- **Broadening beyond Minecraft without breaking the RPD budget:**
  - Run a slower generic tick, for example one clip call every 60–120 s whatever the keywords, plus faster calls when cheap local signals fire (ASR keywords, scene change).
  - Resolve from a clip plus a `high` still of whatever region shows the outcome, with an abstain path. Video tokens are cheap, so the clip approach covers more game types per call than stills.

### Gaps
- No measured latency for generateContent with an inline MP4 clip, or for Live sessions.
- Whether Live uses the same 70 or 280 per-frame budgets (the per-minute video price suggests otherwise).
- Whether `low` versus default video resolution changes OCR or recognition of Twitch game UI. No benchmark was found; it needs a test on real frames.
- Free-tier TPM for Flash-Lite. Without it, the token-heavy variants above could be throttled even under 10 RPM.

## 5. Open models on the 8-vCPU / 16 GB / no-GPU VM, and faster-whisper or whisper.cpp CPU speed

### Takeaway
I found no credible CPU benchmark for Qwen3-VL-2B/4B, Qwen2.5/3-Omni, Moondream or MiniCPM-V/-o on an 8-vCPU machine. The nearest data:
- Text-only 2B models on 8-core CPUs take about 10–15 s to first token for a 1,000-token prompt and decode at about 19–20 tokens/s.
- Only tiny SmolVLM2-256M reaches sub-second latency, under OpenVINO on an Intel CPU.

A local VLM proposer or resolver tonight is not realistic, on latency, integration risk and unknown game-screen OCR quality. Keep the VM for ASR, where faster-whisper small int8 runs at about 0.13× real time on 8 desktop threads.

### Cited Findings
- **CPU-only small-model benchmark** (REPORTED, Hostinger blog, 2026-07-29, updated 2026-07-31) — [Hostinger SLM CPU benchmark](https://www.hostinger.com/blog/slm-cpu-benchmark/):
  - Hardware: Intel Xeon (GCP, 8 cores / 16 threads, no AVX-512) and AMD EPYC VPS (8 cores / 8 threads, AVX-512).
  - Models: Qwen3.5 0.8B/2B, Gemma-4 E2B, Gemma-3n E2B and LFM2.5, at BF16, Q8 and Q4. Text only; no vision model; runtime not stated.
  - Decode: Qwen3.5-2B Q8 18.8 tokens/s, Q4 20.2, BF16 10.5.
  - Time to first token with a ~1,000-token prompt: 2–15 s. Qwen3.5-2B Q8 about 10.5 s; Gemma 3n Q8 nearly 15 s.
  - Q8 "nearly doubl[ed]" 2B throughput. Compressed models ran faster on the 16-thread Xeon than on the 8-thread EPYC.
- **SmolVLM2 on CPU** (REPORTED, search-result snippet of an HF blog, not opened, accessed 2026-11-14) — [HF blog: VLM on Intel CPUs](https://huggingface.co/blog/openvino-vlm):
  - SmolVLM2-256M on an Intel CPU: PyTorch 25.927, OpenVINO 0.738, OpenVINO 8-bit weight-only 0.482 end-to-end latency. Units are presumably seconds.
- **Other small-VLM reports** (REPORTED):
  - Jetson, not CPU (accessed 2026-11-14): SmolVLM2-2.2B averaged 12.84 s and Gemma 4 E2B 37.51 s — [DEV Community](https://dev.to/ryan_hsu_wearedge/i-ran-five-small-multimodal-models-on-a-jetson-the-fastest-one-was-not-the-best-baseline-3de1).
  - Android, third-party docs (accessed 2026-11-14): SmolVLM 500M about 7 s per image; SmolVLM 2.2B 10–15 s per image — [off-grid mobile docs](https://www.mintlify.com/alichherawalla/off-grid-mobile-ai/technical/performance-benchmarks).
- **Qwen3-VL-2B packaging** (REPORTED, search-result snippet of the official HF repo, not opened, accessed 2026-11-14) — [Qwen3-VL-2B-Thinking-GGUF](https://huggingface.co/Qwen/Qwen3-VL-2B-Thinking-GGUF):
  - The language model ships at FP16, Q8_0 and Q4_K_M, with a vision encoder (mmproj) at FP16 or Q8_0. CPU is listed among supported backends.
  - No CPU throughput figure was found.
- **Slow image encoding on CPU** (REPORTED, accessed 2026-11-14): a llama.cpp GitHub issue surfaced by search logs one image slice encoding in 82,047 ms with a BF16 mmproj running on CPU. That was for a larger Qwen3.5-9B model. The issue number was not confirmed; candidates are [#22582](https://github.com/ggml-org/llama.cpp/issues/22582), [#19345](https://github.com/ggml-org/llama.cpp/issues/19345) and [#18910](https://github.com/ggml-org/llama.cpp/issues/18910).
- **faster-whisper CPU benchmark** (VERIFIED_DOC, project README, accessed 2026-11-14; tested version faster-whisper v1.1.0) — [faster-whisper README](https://github.com/SYSTRAN/faster-whisper):
  - Setup: small model, beam 5, 13 minutes of audio, Intel Core i7-12700K, 8 threads.

  | Implementation | Precision | Time | RAM |
  |---|---|---|---|
  | openai/whisper | fp32 | 6m58s | 2,335 MB |
  | whisper.cpp | fp32 | 2m05s | 1,049 MB |
  | whisper.cpp (OpenVINO) | fp32 | 1m45s | 1,642 MB |
  | faster-whisper | fp32 | 2m37s | 2,257 MB |
  | faster-whisper | int8 | 1m42s | 1,477 MB |
  | faster-whisper (`batch_size=8`) | fp32 | 1m06s | 4,230 MB |
  | faster-whisper (`batch_size=8`) | int8 | 51s | 3,608 MB |

  - The README has no CPU numbers for medium, large or turbo. distil-large-v3 is "compatible", and `"turbo"` appears in a code example.
- **Larger Whisper models** (REPORTED, accessed 2026-11-14):
  - faster-whisper large-v3-turbo int8 took 19.591 s for the same 13-minute clip, but on a GPU — [HF discussion](https://huggingface.co/deepdml/faster-whisper-large-v3-turbo-ct2/discussions/3).
  - A German comparison reports faster-whisper CPU-only at about 3× real time for large-v3, on an Apple M5 Pro, not x86 — [promptquorum](https://www.promptquorum.com/de/power-local-llm/local-whisper-stt-comparison).

### Inferences
- **faster-whisper real-time factors** (13 min = 780 s of audio):
  - small int8: 102/780 ≈ 0.13 (about 7.6× real time).
  - batched int8: ≈ 0.065.
  - fp32: ≈ 0.20.
  - A Vultr "8 vCPU" is likely 8 hyperthreads, possibly shared, and slower than a desktop i7-12700K, so expect a worse factor. The project's own measurements on the VM supersede these.
  - medium and large-v3-turbo on CPU will be several times slower than small. turbo keeps the large encoder, which dominates CPU cost. This is not quantified here.
- **Local VLM latency estimate.** From Hostinger's 10.5 s time to first token per ~1,000 tokens (about 95 prompt tokens/s for a 2B model on 8 cores):
  - A Qwen3-VL-2B-class call with one image (several hundred visual tokens) plus about 300 transcript tokens would likely need 5–15 s of prompt processing.
  - Add vision-encoder time (can be very slow with BF16 or FP16 mmproj on CPU; prefer Q8_0) and about 5 s to decode about 100 JSON tokens at about 19 tokens/s.
  - Total: roughly 10–25+ s per call.
  - It would also contend for CPU with the larger faster-whisper model already on the VM. That is 5–10× slower than Gemini's ~2 s, before any quality validation.
- **Quality.**
  - No source in this session evaluated small open VLMs on game HUDs or chat-text OCR.
  - 256M–500M models (the only ones fast enough) are unlikely to produce reliable "will X happen?" markets or verdicts. A wrong local verdict is worse than abstaining.
- **Verdict:** not realistic to deploy as the proposer or resolver before the 09:00 freeze. At most, an optional, clearly labelled experiment: a tiny local VLM or a classical OCR or scene-change detector as a cheap trigger that decides when to spend a Gemini call. Never as an authority for resolution.
- **Model names.** 2026 search results reference Qwen3.5, Gemma 4 E2B and LFM2.5. The candidate list in the brief (Qwen2.5-Omni, Gemma 3n and others) may already be a generation behind.

### Gaps
- No CPU benchmark found for:
  - Qwen3-VL 2B/4B (image encode time, prompt processing, generation)
  - Qwen2.5-Omni or Qwen3-Omni
  - Moondream
  - MiniCPM-V/-o
  - Gemma 3n vision
- No RAM figures for VLMs on CPU.
- No x86 CPU real-time factor for faster-whisper medium, distil-large-v3 or large-v3-turbo, and none for whisper.cpp at those sizes.
- The HF OpenVINO and Qwen GGUF figures come from search snippets of primary pages that were not opened.

**Injected text.** Several fetched pages contained text addressed to AI agents. All of it was ignored:
- Every aistudio.google.com docs page opens with an "AI Agent Context" block pointing agents to `llms.txt` and `llms-full.txt`. It was not followed.
- The Hostinger page carries "Summarize with" buttons with prefilled prompts addressed to AI assistants [passage omitted]. It is promotional and was ignored.

**Tool limitation.** Fetched pages were condensed by a summarizing fetch model. The key numbers (session limits, the token tables, prices) were cross-checked across at least two pages where possible, but transcription errors in single-source figures cannot be ruled out. For example, the pricing page lists "Priority: Free of charge" for the free tier, which looks odd.
