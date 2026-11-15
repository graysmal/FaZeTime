# Multimodal model APIs, free-tier limits and request budgets for a game-agnostic stream-watching AI (state as of 15 Nov 2026)

**Research date and method.** Research date: 2026-11-15. Desk research only; no API was called. All `aistudio.google.com/docs/*` pages were fetched on 2026-11-15, and none showed a last-updated date in the fetched text. The old `ai.google.dev/gemini-api/docs/*` URLs now return HTTP 301 to `aistudio.google.com/docs/*`.

**Label used for owner data.** **VERIFIED** marks data the coordinator relayed from the owner's own project: the signed-in AI Studio rate-limit page at aistudio.google.com/rate-limit (screenshot, read 2026-11-15 ~00:55 CT) and a `models.list` call on the team key. These project-specific figures override every third-party snapshot below. Treat all model names and limits as volatile.

## Q1. Which Gemini API models are available, and what are their free-tier limits, modalities, structured output, latency and caching?

### Takeaway
The team's no-billing project has six usable kinds of free capacity:
- Two separate 500-RPD Flash-Lite pools (3.5 and 3.1).
- Four 20-RPD Flash-class pools (3 Flash, 3.6 Flash, 3.8 Flash, 4 Hydrogen).
- Two Gemma 4 pools of 14,400 RPD each, limited by a tight 16K TPM.
- Gemini Decision 1, a new closed-set probability model at 200 RPM / 50K TPM / 10K RPD.
- Live API models with unlimited RPM and RPD, capped at 65K TPM.
- Gemini 3.5 Transcribe Live (unlimited requests, 20K TPM); the non-live Transcribe pool gets only 25 RPD.

Pro, Gemini 4 Argon/Carbon, image and Omni models are at 0 on this tier. Every Gemini 3.x Flash and Flash-Lite model accepts text, image, video, audio and PDF input and supports structured outputs. Gemma 4 on the Gemini API accepts images and system instructions; JSON-schema output is not documented, but function calling is.

### Cited Findings

**Project rate limits** — VERIFIED ([owner's AI Studio rate-limit page](https://aistudio.google.com/rate-limit), relayed by coordinator, 2026-11-15)

| Model | RPM | TPM | RPD | Notes |
|---|---|---|---|---|
| gemini-3.5-flash-lite | 15 | 250K | 500 | |
| gemini-3.1-flash-lite | 15 | 250K | 500 | Separate pool |
| Gemma 4 26B | 30 | 16K | 14.4K | Each Gemma model has its own pool; TPM is the binding limit |
| Gemma 4 31B | 30 | 16K | 14.4K | Separate pool |
| Gemini 3 Flash, 3.6 Flash, 3.8 Flash, Gemini 4 Hydrogen, Robotics ER 2 Preview | 5 | 250K | 20 | Per model |
| Gemini 2.5 Flash | 5 | 250K | 20 | |
| Gemini 2.5 Flash-Lite | 10 | 250K | 20 | |
| Gemini 3.5 Transcribe (non-live) | 3 | 10K | 25 | |
| Gemini Decision 1 (category "Decisions API") | 200 | 50K | 10K | |
| Gemini 3 Flash Live, 3.8 Live, 3.8 Live Extended Thinking | Unlimited | 65K | Unlimited | |
| Gemini 2.5 Flash Native Audio Dialog | Unlimited | 1M | Unlimited | |
| Gemini 3.5 Transcribe Live, 3.5 Live Translate | Unlimited | 20K | Unlimited | |
| Gemini 2.5 Pro, 3.1 Pro, 4 Argon, 4 Carbon, all image and Omni models | 0 | 0 | 0 | Not available on this tier |

**Models this key can see** — VERIFIED (`models.list` on the team key, relayed by coordinator; no quota used)
- The generateContent models are: `gemini-2.5-flash`, `gemini-2.5-flash-lite`, `gemini-2.5-pro`, `gemini-3.1-flash-lite`, `gemini-3.5-flash`, `gemini-3.5-flash-lite`, `gemini-3.6-flash`, `gemini-3.7-flash`, `gemini-3.8-flash`, `gemini-4-argon`, `gemini-4-carbon`, `gemini-4-hydrogen`, `gemini-omni-flash-preview`, `gemma-4-26b-a4b-it` and `gemma-4-31b-it`.
- `models.list` shows models whose quota is 0, so being listed does not mean being usable.

**What the public docs say about the catalogue**
- `gemini-3.5-flash` and `gemini-3.7-flash` do not appear on the public models page. — [Gemini models](https://aistudio.google.com/docs/models)
- Deprecations: `gemini-2.5-flash` auto-routes to `gemini-3.5-flash-lite` on 1 Dec 2026, and `gemini-2.5-pro` auto-routes to `gemini-3.8-flash`. — [Gemini models](https://aistudio.google.com/docs/models)
- Shut down: `gemini-2.0-flash(-lite)`, `gemini-3-pro-preview` and `gemini-3.1-flash-lite-preview`. — [Gemini models](https://aistudio.google.com/docs/models)

**Gemini 3.x Flash and Flash-Lite model pages**
- `gemini-3.8-flash`:
  - Inputs: text, image, video, audio and PDF. Output: text only. Limits: 1,048,576 input and 65,536 output tokens.
  - Supports structured outputs, context caching, function calling and the Batch API. It does not support the Live API.
  - Thinking levels are low, medium and high. "Minimal is not supported and returns an error."
  - Latest update: September 2026.

  — [Gemini 3.8 Flash](https://aistudio.google.com/docs/models/gemini-3.8-flash)
- `gemini-3.6-flash` and `gemini-3.5-flash-lite`: same inputs and limits as 3.8 Flash. Both support structured outputs, context caching, function calling and thinking; neither supports the Live API. Both were last updated July 2026. 3.6 Flash is described as a previous-generation Flash model that is still supported for production use. — [Gemini 3.6 Flash](https://aistudio.google.com/docs/models/gemini-3.6-flash); [Gemini 3.5 Flash-Lite](https://aistudio.google.com/docs/models/gemini-3.5-flash-lite)
- `gemini-3.7-flash`:
  - An official page exists: inputs text, image, video, audio and PDF; thinking low, medium or high (default medium); minimal not supported.
  - Status conflict in search snippets: the Japanese "what's new" page says it is generally available, while the Hindi version says it has been discontinued and its users are routed to 3.8 Flash.
  - A third-party gateway lists its release date as 13 Aug 2026.

  — [Gemini 3.7 Flash](https://ai.google.dev/gemini-api/docs/models/gemini-3.7-flash); [Vercel listing](https://vercel.com/ai-gateway/models/gemini-3.7-flash)

**Gemma 4 on the Gemini API**
- The API serves only `gemma-4-31b-it` and `gemma-4-26b-a4b-it`. — [Run Gemma with the Gemini API](https://ai.google.dev/gemma/docs/core/gemma_on_gemini_api?hl=en)
- Supported: image input, system instructions, function calling, a thinking toggle (`thinking_level` "high" or "minimal") and search grounding.
- Video, audio, JSON mode and `response_schema` are not mentioned.

  — [Run Gemma with the Gemini API](https://ai.google.dev/gemma/docs/core/gemma_on_gemini_api?hl=en)
- Model card:
  - 26B A4B is a mixture-of-experts model with 3.8B active parameters; 31B is dense.
  - Both take text and image input. They have no audio input. Video is handled as frames (up to 60 s at 1 FPS).
  - Context: 256K tokens.
  - Visual token budget per image can be 70, 140, 280, 560 or 1120.
  - Function calling is native; structured output is not mentioned.
  - MMMU Pro: 73.8% for 26B A4B and 76.9% for 31B.

  — [Gemma 4 model card](https://ai.google.dev/gemma/docs/core/model_card_4)
- Gemma vision guide:
  - Measured image tokens per budget: 70→64, 140→121, 280→256, 560→529.
  - The budget is set through `image_processor.max_soft_tokens` in transformers. No Gemini-API control is mentioned and no default is stated.
  - The examples prompt for "```json" and extract it with a regex; no guaranteed structured mode is described.

  — [Gemma image understanding](https://ai.google.dev/gemma/docs/capabilities/vision/image?hl=en)
- Reliability signal: a Google developer-forum thread titled "Constant 500s on Gemma 4" runs to at least 3 pages. Title only; not read. — [Google AI forum](https://discuss.ai.google.dev/t/constant-500s-on-gemma-4/140940?page=3)

**Gemini Decision 1 (what "Decisions API" is)**
- Released 11 Nov 2026.
- `gemini-decision-1` answers closed-set questions:
  - "noul" (probability that a yes/no condition holds);
  - "choice" (2–255 options, with probabilities);
  - "score" (ordered rubric).
- It takes up to 1,000 questions per call over text, image, audio, video and PDF input of up to 256K tokens.
- Every answer carries a 0–1 confidence. There is no abstain output; Google suggests routing low-confidence cases to a fallback or a human.
- Latency is 150–250 ms end to end (self-reported) and nearly flat from 1 to 100 questions.
- Call shape: `genai.Client(http_options={"api_version": "v1beta"})` then `client.decisions.create(model=..., input=[...], questions={...})`.

  — [Google blog: Gemini Decisions API](https://blog.google/innovation-and-ai/technology/developers-tools/gemini-decisions-api/)
- Secondary reports bound the yes/no probability to 0.01–0.99 and use inconsistent type names (`yes_no`, `boolean`). This comes from a search snippet; the page was not fetched. — [Simon Willison, 11 Nov 2026](https://simonwillison.net/2026/Nov/11/gemini-decisions-api/)

**Other facts**
- On the free tier, "Content used to improve our products". — [Pricing](https://aistudio.google.com/docs/pricing)
- Gemini 3.6+ and 4 ignore `temperature`, `topP` and `topK`, and "will return 400 errors in a future release". Lower thinking to reduce latency. — [Troubleshooting](https://aistudio.google.com/docs/troubleshooting)
- The Batch API is not available on the free tier. — [Memetik, 1 Oct 2026](https://www.memetik.ai/guides/gemini-api-free-tier-limits)
- Team measurement (from the assignment brief): `gemini-3.5-flash-lite` with one 854x480 frame and JSON-schema output took 2.3 s and about 1,100 input tokens.

### Inferences
- **Daily request budget across pools** (separate model pools in one project, not quota evasion):
  - generateContent:
    - about 1,000 Flash-Lite RPD across the two Flash-Lite pools;
    - 80 Flash-class RPD (3 Flash, 3.6 Flash, 3.8 Flash and 4 Hydrogen at 20 each);
    - 28,800 Gemma RPD, which TPM limits to roughly 5–9 calls per minute per model.
  - Decisions API: 10,000 Decision RPD.
  - Live API: unlimited requests.
- **Models to avoid:**
  - 2.5 models: deprecated, re-routing on 1 Dec, and only 20 RPD.
  - `gemini-3.5-flash` and `gemini-3.7-flash`: listed by `models.list`, but their limits weren't visible and they're absent from the public catalogue.
  - Pro and Argon/Carbon models: 0 quota.
- **Thinking settings.** Don't send thinking level "minimal" to 3.8 or 3.7 Flash, because it returns an error; use low. For Gemma, "minimal" disables thinking.
- **Structured output.** It is documented for all 3.x Flash and Flash-Lite models. For Gemma, use one declared function whose parameter schema is the state schema. Calling it returns schema-shaped arguments. Alternatively prompt for JSON and validate with Pydantic. Treat any parse failure as "no update" (abstain).

### Gaps
- Gemini-API latency for Gemma 4, 3.8 Flash and 4 Hydrogen. Gemma 4's 500-error rate in November 2026.
- Whether the Gemma Gemini-API endpoint honours `media_resolution` or a per-image visual budget, and its default budget.
- Whether `response_json_schema` or forced function calling (`tool_config` mode ANY) works for Gemma on the Gemini API.
- Decision API parameter names and the minimum `google-genai` SDK version. Whether `gemini-decision-1` appears under a non-generateContent method in `models.list`.

## Q2. How does the free tier count images, video and audio, and how are limits scoped and reset?

### Takeaway
On Gemini 3.x and 4 models, the `media_resolution` setting fixes the token cost of each image, regardless of pixel size:

| `media_resolution` | Image | Video frame |
|---|---|---|
| default | 1,120 | 70 |
| `low` | 280 | 70 |
| `medium` | 560 | 70 |
| `high` | 1,120 | 280 |
| `ultra_high` | 2,240 | n/a |

Audio costs 25 tokens/s, and video is sampled at 1 FPS. Gemma 4 images cost about 64–1,100 tokens depending on the visual budget. Limits are per project and per model, each dimension trips on its own, and RPD resets at midnight Pacific.
- Flash-Lite and Flash are bound by requests per day.
- Gemma is bound by TPM (16K).
- The Live models are bound only by TPM (65K).

### Cited Findings
- The media-resolution table above is the official one for Gemini 3.x and 4.
  - `ultra_high` can be set only per content item.
  - Levels can be mixed per item within one request.
  - Use `high` for images, `low` or `medium` for general video description, and `high` for dense text in frames.

  — [Media resolution](https://aistudio.google.com/docs/media-resolution)
- The video page gives older figures that conflict with this table: 66 or 258 tokens per frame, audio at 32 tokens/s, and about 100 tokens/s (low) or about 300 tokens/s (high). — [Video understanding](https://aistudio.google.com/docs/video-understanding)
- Gemma 4 image token counts: budget 70→64, 140→121, 280→256, 560→529 (and up to 1120). — [Gemma image understanding](https://ai.google.dev/gemma/docs/capabilities/vision/image?hl=en)
- Scope and reset:
  - "Rate limits are applied per project, not per API key".
  - Exceeding any one limit errors.
  - TPM counts input tokens.
  - "RPD quotas reset at midnight Pacific time".
  - Limits "are not guaranteed".

  — [Rate limits](https://aistudio.google.com/docs/rate-limits)
- 403 `FREE_TIER_VERIFICATION_REQUIRED` is fixed by verifying with a mobile device; billing, the doc's other option, is excluded here. — [Troubleshooting](https://aistudio.google.com/docs/troubleshooting)
- Gemma 4's 16K TPM limit — VERIFIED ([owner's AI Studio page](https://aistudio.google.com/rate-limit))

### Inferences
- **The team's ~1,100 tokens per frame** is the default 1,120-token image budget. `low` (280 tokens) is a quarter of that, and `medium` (560) is the sensible choice when HUD digits matter.
- **Gemma calls must be small to fit 16K TPM.** For example, one frame at budget 280 (~256 tokens) plus ~1.3K tokens of state, instructions and ASR is ~1.6K tokens, so about 10 calls per minute. One frame at 1,120 plus 1.3K is ~2.4K, so about 6 calls per minute. Because the default Gemma budget on the API is unknown, measure one call's `usage_metadata` first.
- **Flash-Lite TPM is not the constraint.** 15 RPM × 6K tokens is 90K, under 250K. Batch many frames per request.
- **Decision 1's 50K TPM** allows about 40 calls per minute of ~1.2K tokens each.
- **Live streaming cost**, assuming the Gemini 3.x token rates apply to Live:
  - continuous 1 FPS video at low or default resolution plus audio is about 70 × 60 + 25 × 60 ≈ 5.7K input tokens per minute;
  - at high frame resolution it is about 18.3K per minute;
  - both are under 65K TPM, if per-turn context re-counting does not multiply this (see Q3).
- **Reset time.** Midnight Pacific in November 2026 (PST, UTC−8) is 08:00 UTC. Key the quota ledger to the Pacific date.

### Gaps
- Whether Live models use the 3.x media-resolution token table.
- Whether Decision 1 bills images by that table.
- Whether cached tokens count toward TPM.

## Q3. Can a model ingest short video clips with audio directly, and is the Live API a practical continuous state tracker?

### Takeaway
**Short clips: yes.** Every Gemini model accepts inline MP4 or WebM clips with audio (keep requests under about 20 MB), with custom FPS and clipping. Gemini 3.x defaults cost about 95 tokens/s, so roughly 950 tokens for 10 s and 2,850 for 30 s, or about 305 tokens/s at `high`. Clip latency is undocumented.

**Live API: plausible but risky.** On this project it has unlimited RPM and RPD (65K TPM). It takes continuous JPEG or PNG frames (at most 1 FPS) plus 16 kHz PCM audio. It cannot return text-only responses: native-audio models are audio-out only. Text comes from output transcription, and structured data comes from asynchronous function calls (3.8 Live). Operating constraints:
- Audio+video sessions die after 2 minutes unless context-window compression is on.
- Connections drop after about 10 minutes, so the client must reconnect with a resumption handle (valid 2 hours).
- The context window is 128K tokens for native-audio models.

**Verdict for v1.** Keep the Live API off the critical path. A 60–90-minute spike is worth it, because an unlimited-request continuous tracker would remove the RPD problem.

### Cited Findings
**Clips through generateContent**
- All Gemini models process video, with audio processed as part of it. — [Video understanding](https://aistudio.google.com/docs/video-understanding)
- Use static mode for clips under about 5 minutes and latency-sensitive work. Set `fps` and `start_offset`/`end_offset` in the `processing` object. — [Video understanding](https://aistudio.google.com/docs/video-understanding)
- Inline input is best for videos under 1 minute; the page says both under 100 MB and under 20 MB. The Files API allows 2 GB on the free tier. — [Video understanding](https://aistudio.google.com/docs/video-understanding)
- Supported MIME types include video/mp4, video/mpeg, video/webm, video/mov and video/3gpp. MPEG-TS is not listed. — [Video understanding](https://aistudio.google.com/docs/video-understanding)
- Decision 1 accepts video and audio. — [Google blog](https://blog.google/innovation-and-ai/technology/developers-tools/gemini-decisions-api/)
- Gemma 26B and 31B take no audio. — [Gemma 4 model card](https://ai.google.dev/gemma/docs/core/model_card_4)

**Live API**
- Protocol and inputs: a stateful WebSocket. Inputs are 16-bit PCM audio at 16 kHz, JPEG frames at no more than 1 FPS, and text. The tech spec lists audio output only (24 kHz). Function calling and Google Search are supported. — [Live API](https://aistudio.google.com/docs/live)
- Output modality:
  - Native-audio output models "only support `AUDIO` response modality"; text-only output is not supported.
  - For text, use output audio transcription.

  — [Live API capabilities guide](https://aistudio.google.com/docs/live-guide)
- Input handling:
  - Frames are sent as JPEG or PNG images at no more than 1 FPS through realtime input.
  - `mediaResolution` in the session config sets the tokens per frame.
  - Audio is tokenized at a fixed rate.

  — [Live API capabilities guide](https://aistudio.google.com/docs/live-guide)
- Turn-taking:
  - Automatic voice-activity detection (VAD) is on by default and configurable.
  - Manual `activityStart`/`activityEnd` is possible.
  - Text turns can be sent with `send_client_content`; on 3.8 models, `turn_complete=true` interrupts generation.
  - "Proactive audio", where the model may choose not to respond to irrelevant input, is permanently on for 3.8 Live and not supported on 3.1 Flash Live Preview.

  — [Live API capabilities guide](https://aistudio.google.com/docs/live-guide)
- Asynchronous function calling:
  - 3.8 Live supports it by default (`NON_BLOCKING`, scheduling `SILENT`/`WHEN_IDLE`/`INTERRUPTED`).
  - 3.8 Live Extended Thinking is asynchronous only, with no scheduling options.
  - 3.1 Flash Live Preview is synchronous only.

  — [Live API capabilities guide](https://aistudio.google.com/docs/live-guide)
- Context window and usage:
  - 128K tokens for native-audio output models, 32K for other Live models.
  - Usage arrives periodically in `usageMetadata` (`totalTokenCount`, per-modality breakdown).
  - The page doesn't say whether each turn re-counts the accumulated context.
  - The page carries a "Live API preview" callout.

  — [Live API capabilities guide](https://aistudio.google.com/docs/live-guide)
- Session limits:
  - Without compression, audio-only sessions last 15 minutes and audio+video sessions 2 minutes.
  - With context-window compression, sessions have no time limit.
  - A connection lasts about 10 minutes, and a GoAway message with `timeLeft` arrives before it closes.
  - Resumption tokens are valid for 2 hours.
  - The examples use `gemini-3.8-live`.

  — [Live session management](https://aistudio.google.com/docs/live-session)
- Live TPM and request limits — VERIFIED ([owner's AI Studio page](https://aistudio.google.com/rate-limit)):
  - Unlimited RPM and RPD for every Live model.
  - 65K TPM for 3 Flash Live, 3.8 Live and 3.8 Live Extended Thinking.
  - 1M TPM for 2.5 Flash Native Audio Dialog.
  - 20K TPM for 3.5 Transcribe Live.

### Inferences
- **Clips.** Twitch HLS segments are usually MPEG-TS, so remux the last N segments with `ffmpeg -c copy` to MP4, or re-encode to 480p at 1–2 FPS (about 1–3 MB).
  - A clip costs one request, like a batch of frames; its gain is audio and motion, not fewer requests.
  - For clocks and scores, use `high` video resolution or add one `high` still frame.
  - Keep local Whisper ASR for timestamped transcript evidence and zero-quota keyword triggers.
- **Live tracker design, if pursued.** Use one `gemini-3.8-live` session:
  - Input: 1 FPS JPEG at low or medium resolution, plus the Twitch audio as 16 kHz PCM, both converted with ffmpeg.
  - Session config: context-window compression on, session resumption on, and output audio transcription.
  - Declare NON_BLOCKING functions with `SILENT` scheduling, such as `report_state_delta(...)` and `flag_event(kind, evidence_ts)`.
  - Every 15–30 s, nudge the model with a text turn through `send_client_content`: "call report_state_delta if anything changed".
  - Treat every call as an untrusted proposal that the backend checks.
  - Ignore audio output.
  - The session's context is lossy under compression, so the canonical state must live outside the session.
- **Live risks:**
  1. Output is audio-first, so function calls are the only structured channel and their timing is model-driven.
  2. Reconnects every ~10 minutes and the compression and resumption logic add WebSocket complexity in a few-hour build.
  3. Per-turn token accounting is undocumented. If each turn re-counts a 32–64K-token context, 65K TPM supports only about 1–2 turns per minute.
  4. Stream audio is treated as "user" speech, so the streamer or chat audio can try to steer the model (prompt injection). Backend gates must hold.
  5. The API is labelled preview.
- **Which Live model.** "Gemini 3 Flash Live" in the AI Studio table is probably `gemini-3.1-flash-live-preview`, which has synchronous function calls and no proactive audio; this mapping is an inference. Prefer 3.8 Live. 2.5 Flash Native Audio Dialog has 1M TPM but is a December 2025 preview in a family being deprecated.
- **Free continuous ASR.** Gemini 3.5 Transcribe Live (unlimited requests, 20K TPM) could replace CPU Whisper. Audio at 25 tokens/s is about 1.5K tokens per minute.

### Gaps
- Whether Live TPM counts per-turn context re-processing.
- Whether 3.8 Live emits function calls reliably without human speech.
- Whether 3.8 Live accepts PNG frames at medium resolution or above, and with what token cost.
- Concurrent-session caps.
- Clip-request latency for generateContent.

## Q4. What other free options exist (other providers' no-billing tiers; open-weight VLMs on CPU, Pi 5 or laptops)?

### Takeaway
Nothing outside Google matches the project's free multimodal capacity.
- OpenRouter's free tier is 20 RPM and 50 RPD. Its 1,000 RPD tier needs a $10 top-up, which is excluded.
- Groq, Cerebras, NIM and Cloudflare have generous text tiers, but free vision support is unconfirmed. Gemma 4 26B-A4B listings on OpenRouter (free) and Cloudflare Workers AI are leads for an outage fallback.
- Local CPU VLMs are too slow for the main loop: a Pi 5 ingesting one image with Gemma 4 E2B took about 15 s, or about 32 s with a verbose answer.

### Cited Findings
- Free provider tiers as of 24 Sep 2026; figures checked against March–April 2026 sources:

  | Provider | Free limits |
  |---|---|
  | OpenRouter | 20 RPM, 50 RPD (1,000 RPD only after a one-time $10 top-up) |
  | Groq | 30 RPM, 1,000 RPD |
  | Cerebras | 30 RPM, ~1M tokens/day |
  | Mistral | ~1B tokens/month (requires opting into training) |
  | NVIDIA NIM | ~1,000 requests/day |
  | Cloudflare Workers AI | ~10K neurons/day |
  | Cohere | ~100 requests/day (non-commercial) |

  Only Google AI Studio is named as clearly vision-capable. — [OpenRouter: Free LLM APIs compared](https://openrouter.ai/blog/tutorials/free-llm-apis-compared/)
- Gemma 4 26B-A4B is listed as `google/gemma-4-26b-a4b-it:free` on OpenRouter and as `@cf/google/gemma-4-26b-a4b-it` on Cloudflare Workers AI. These are search-result listings, not fetched; image support and limits are unverified. — [OpenRouter model page](https://openrouter.ai/google/gemma-4-26b-a4b-it:free); [Cloudflare listing](https://www.ayautomate.com/free-models/cloudflare-workers-ai-cf-google-gemma-4-26b-a4b-it)
- Pi 5 (8 GB), CPU, measured 26 Jul 2026:
  - Gemma 4 E2B in 4-bit on llama.cpp, using 3 threads.
  - Prompt: 177 tokens, including 169 image tokens. Prefill took 15 s.
  - Decode: 189 tokens in 17 s.
  - "A vision prompt runs at 85.5 ms per token against 24.0 ms for text".
  - The author frames Pi agents as running "a few times an hour".

  — [Rovai](https://mjrovai.com/articles/slm-on-raspberry-pi-mtp/)
- Gemma 4 E2B text benchmark on a Pi 5: LiteRT-LM prefill 99 tok/s and decode 9 tok/s; llama.cpp Q4_0 prefill 24 tok/s and decode 4 tok/s. Search summary; not fetched and undated. — [Raspberry Pi](https://www.raspberrypi.com/news/mastering-edge-ai-on-raspberry-pi-with-litert-and-gemma/)

### Inferences
- **Local VLMs.** On a Pi 5, at most about 3 short yes/no checks per minute, so a local VLM can only be an optional fallback that is allowed to abstain. Local classical CV — frame-diff, scene-change and perceptual-hash detection — plus ASR keyword spotting is the right pre-filter.
- **Outage fallback.** OpenRouter's 50 free RPD can serve as a last-resort second opinion only if a free vision model is live that day. Keep it off the critical path.

### Gaps
- Not confirmed:
  - a free Groq vision model;
  - Cerebras serving Gemma 4 31B with image input on its free tier (its [image-inputs page](https://inference-docs.cerebras.ai/capabilities/image-inputs) was not fetched);
  - Mistral vision on the Experiment tier.
- GitHub Models status conflicts: unverified search snippets say it was retired on 30 Jul 2026, but the OpenRouter blog still lists it.
- No CPU benchmarks were found for SmolVLM, Moondream or Qwen3-VL on an 8-vCPU x86 VM or a laptop.

## Q5. Which request-budgeting designs work, and how many requests per hour do they need?

### Takeaway
1. Detect change locally.
2. Batch every frame and ASR chunk since the last call into one request.
3. Call generative models on events plus a slow heartbeat.
4. Spend the Flash-class pools only on resolution.

A per-burst cadence (~600 req/h) is affordable only with Decision 1 (10K RPD), with the two Gemma pools alternated under small TPM-bounded calls, or with the Live API, which has no request limit. The two Flash-Lite pools give about 1,000 requests per day in total: about 120 req/h for about 8 h, or about 40 req/h for about 25 h.

### Cited Findings
- One request can carry multiple media items, each at its own resolution. — [Media resolution](https://aistudio.google.com/docs/media-resolution)
- Decision 1 handles up to 1,000 questions per call; shared input is billed once and latency is flat from 1 to 100 questions. — [Google blog](https://blog.google/innovation-and-ai/technology/developers-tools/gemini-decisions-api/)
- Pool limits — VERIFIED ([owner's AI Studio page](https://aistudio.google.com/rate-limit)):

  | Pool | RPM | TPM | RPD |
  |---|---|---|---|
  | Flash-Lite (3.5 and 3.1, separate pools) | 15 | 250K | 500 |
  | Flash-class (3 Flash, 3.6 Flash, 3.8 Flash, 4 Hydrogen), each | 5 | – | 20 |
  | Gemma 4 (26B and 31B), each | 30 | 16K | 14.4K |
  | Decision 1 | 200 | 50K | 10K |
  | Live | Unlimited | 65K | Unlimited |

### Inferences
**Cadence against budgets (Twitch bursts arrive about every 6 s)**

| Cadence | Req/h | One Flash-Lite pool (500) | Both Flash-Lite pools (1,000) | Notes |
|---|---|---|---|---|
| Every 6 s | 600 | 0.8 h | 1.7 h | Decision 1 lasts 16.7 h. Alternating the Gemma pools needs ≤3.2K tokens per call |
| Every 12 s | 300 | 1.7 h | 3.3 h | One Gemma pool needs ≤3.2K tokens per call and lasts 48 h |
| Every 30 s | 120 | 4.2 h | 8.3 h | |
| Every 60 s | 60 | 8.3 h | 16.7 h | |
| Events plus heartbeat | 20–60 | 8–25 h | 16–50 h | |

**Pre-filters (game-agnostic)**
- Frame-diff or scene-change score.
- Perceptual-hash "new screen" detection.
- ASR keyword and regex triggers: gg, win/won, lose/lost, checkmate, resign, victory, defeat, round, game over, let's go, spoken scores and times.
- A jump in audio energy.
- Timing: at least 15 s debounce between calls and a 120–300 s heartbeat.

**Batching**
- Send every frame since the last call (≤8, at low or medium) plus timestamped ASR plus the previous state JSON.
- Get back a structured state delta with optional proposal-opportunity and resolution-evidence fields.

**Adaptive cadence**
- Allowed rate = `(remaining_RPD − reserve) / remaining_planned_hours`.
- Speed up near expected resolutions. Drop to heartbeat-only on menus or no-game screens.
- Reserve about 20% of Flash-Lite plus all Flash-class pools for resolution.

**Game tempo**
- Blitz chess, Peggle and fighting games can produce 6–20 resolvable events per hour.
- With one open market at a time, expect about 2–10 proposals and 2–10 resolutions per hour.
- The 80 Flash-class RPD covers that for about 8–40 h.

**Risks**
- Chess changes little visually, so the heartbeat and ASR triggers carry it.
- CS2's fast cuts need the debounce and hourly caps.
- Measure trigger rates on recorded fixtures. Fixtures are fine for tuning, but acceptance still needs Twitch.

### Gaps
- No published trigger-rate data exists for game-agnostic pre-filters.
- Multi-frame Flash-Lite latency, Gemma latency, Gemma's 500-error rate and Live per-turn token accounting are all unmeasured.

## Q6. How should the system behave on rate-limit errors (429) or provider outages?

### Takeaway
1. Enforce budgets on the client with a per-model ledger keyed to the Pacific day, a reserve for resolution, and TPM-aware pacing for Gemma and Live.
2. Retry only transient errors (429, 408, 5xx) with capped exponential backoff and jitter.
3. Fail over along per-role model chains that apply the same evidence gates.
4. When no gated answer exists, abstain: stop proposing, keep the market unresolved, and hand it to approval mode with the stored evidence.

Never retry 400 or 403 errors, and never link billing.

### Cited Findings
- For 429 `RESOURCE_EXHAUSTED` and 503 `UNAVAILABLE`, back off exponentially (1, 2, 4, 8 s) with jitter and a maximum retry count. — [Troubleshooting](https://aistudio.google.com/docs/troubleshooting)
- Retry only 429, 408 and 5xx, never 400, 402 or 403. — [Troubleshooting](https://aistudio.google.com/docs/troubleshooting)
- The Python SDK retries up to 4 times by default, starting at about 1 s with a 60 s maximum. — [Troubleshooting](https://aistudio.google.com/docs/troubleshooting)
- 403 "Free tier unavailable" cannot be fixed with a new key; the only documented fix is billing. — [Troubleshooting](https://aistudio.google.com/docs/troubleshooting)
- Any single limit trips an error, RPD resets at midnight Pacific, and limits are not guaranteed. — [Rate limits](https://aistudio.google.com/docs/rate-limits)
- Live connections end after about 10 minutes with a GoAway warning; resumption tokens last 2 hours. — [Live session management](https://aistudio.google.com/docs/live-session)
- Gemma 4 has a reported pattern of 500 errors (forum thread title). — [Google AI forum](https://discuss.ai.google.dev/t/constant-500s-on-gemma-4/140940?page=3)

### Inferences
**Pacing and error handling**
- Stop at about 90% of each verified RPD.
- Pace Gemma by tokens: `Σ input tokens per rolling 60 s ≤ ~14K`.
- Use additive-increase/multiplicative-decrease (AIMD) on 429s.
- Treat repeated 429s late in the day as daily exhaustion and turn that pool off until 08:00 UTC.
- Reuse each job's durable operation ID on retry, so an effect is never applied twice.

**Fallback chains**
- State: 3.5 Flash-Lite → 3.1 Flash-Lite → Gemma 26B → Gemma 31B → Decision-only phase questions → local-only mode with a visible "AI degraded" label.
- Proposer: pauses when the budget is under the reserve or the state is stale.
- Resolver: Decision 1 + 3.8 Flash → 4 Hydrogen / 3.6 Flash / 3 Flash → 3.5 Flash-Lite with `ultra_high` frames → operator queue.

**When to abstain**
- A gap in observation covers the moment of the outcome.
- Evidence is stale.
- A single model asserts the outcome without cited frame IDs, timestamps and quotes.
- A schema parse fails.

**Deferred resolution.** Keep a 10–15-minute on-disk ring buffer of frames and ASR, so a blocked resolution can run later against the evidence captured at the moment. Past the deadline, the backend's product policy decides between manual resolution and void/refund.

**Live sessions.** On GoAway, reconnect with the resumption handle. If resumption fails, the external state store stays authoritative and the tracker falls back to Flash-Lite cadence.

### Gaps
- The `/docs/api-errors` page was not fetched. Unconfirmed: whether 429 bodies carry `RetryInfo.retryDelay`, and per-minute versus per-day quota IDs.

## Q7. What model assignment per role and request budget per hour should the prototype use? (synthesis)

### Takeaway
**v1 build.** Build Design B first. It uses only the working generateContent path, and Design A is the same code with a timer trigger. Role assignment:
- **State tracker:** local pre-filters plus event-triggered `gemini-3.5-flash-lite`, overflowing to `gemini-3.1-flash-lite`.
- **Proposer:** `gemini-3.5-flash-lite`, picking schema-constrained generic templates.
- **Resolver:** `gemini-decision-1` probability inside an abstain band, AND a Flash-class verifier (`gemini-3.8-flash`, then `gemini-4-hydrogen`, `gemini-3.6-flash`, then 3 Flash) that must agree with cited evidence.

**Spikes, each timeboxed.** Decision 1 triage (Design C); a Gemma 4 high-frequency tracker (Design D); a 3.8 Live continuous tracker (Design E).

### Cited Findings
- Pool limits: VERIFIED in Q1 ([owner's AI Studio page](https://aistudio.google.com/rate-limit)).
- Image token costs: low 280, medium 560, high 1,120, ultra_high 2,240. — [Media resolution](https://aistudio.google.com/docs/media-resolution)
- Gemma 4 image budgets: about 64–1,100 tokens. — [Gemma image understanding](https://ai.google.dev/gemma/docs/capabilities/vision/image?hl=en)
- Decision 1 latency and multi-question calls. — [Google blog](https://blog.google/innovation-and-ai/technology/developers-tools/gemini-decisions-api/)
- Live async function calls and session limits. — [Live API capabilities guide](https://aistudio.google.com/docs/live-guide); [Live session management](https://aistudio.google.com/docs/live-session)

### Inferences
**Model assignment per role**

| Role | Primary | Fallback | Inputs per call | Gate |
|---|---|---|---|---|
| Pre-filter (every frame) | Local frame-diff, scene change, perceptual hash, ASR keywords | – | – | No quota spent |
| Triage (C) | `gemini-decision-1`: game-phase choice, plus yes/no on "results screen", "clock or score visible" and "streamer appears to have won" | Design B triggers | 1 frame at medium plus 2 ASR chunks | Only decides when to call a generative model |
| State tracker | `gemini-3.5-flash-lite`: JSON state delta, thinking low, no temperature parameter | 3.1 Flash-Lite → Gemma 26B (function-call schema) → local-only | ≤8 frames at low or medium, ASR with timestamps, previous state | Schema-valid output, else no update |
| Proposer | `gemini-3.5-flash-lite`: template ID plus parameters from a generic catalogue (win/lose game or round; game length over N minutes; final clock or score over X); the backend validates | Pause | State plus 1–2 frames | Fresh state and no open market |
| Resolver | Two-key: `gemini-decision-1` yes/no on the exact market question over the evidence, AND `gemini-3.8-flash` verifying with cited frame IDs and quotes | 4 Hydrogen / 3.6 Flash / 3 Flash → 3.5 Flash-Lite with `ultra_high` → operator queue | 2–4 evidence frames at high or ultra_high from the best stream variant, plus ASR around the event | Both agree and p ≥ ~0.95 or ≤ ~0.05 (calibrate on fixtures); else abstain |

**Request budget per hour of stream (verified pools)**

| Design | Calls per hour | Daily budget lasts | Detection latency | Build effort and risk |
|---|---|---|---|---|
| **A. 30-s batches, Flash-Lite only** | Flash-Lite: 120 (5 frames at medium, ~4–5K tokens); Flash-class: 2–10 | Flash-Lite ~4.2 h on one pool, 8.3 h on both; Flash-class 80 RPD | ≤30 s plus Twitch delay plus ~2–3 s | ~2 h; low risk |
| **B. Event-triggered plus heartbeat (recommended v1)** | Flash-Lite: 30–60, capped at 60 (≥15 s debounce, 120 s heartbeat; proposals and resolution checks ride along or add 2–10); Flash-class: ≤3–10 | Flash-Lite 8–17 h on one pool, 17–33 h on both | ~6–20 s after a trigger | ~3–4 h; trigger tuning needed |
| **C. Decision triage plus Flash-Lite plus verifier** | Decision 1: 300–600 (~1.2K tokens each, ≤12K of the 50K TPM); Flash-Lite: 15–40; resolution: 2–10 Decision 1 plus ≤3–10 Flash-class | Decision 1 16.7–33 h; Flash-Lite 12–33 h on one pool | ~6–12 s | B plus ~1–2 h; depends on a 4-day-old API |
| **D. Gemma high-frequency tracker** | Gemma 26B: 300 (every 12 s, ≤3.2K tokens per call; 1 frame at budget 280–560 plus state plus ASR); alternating 26B and 31B gives 600 per-burst calls at ≤3.2K tokens each; Flash-Lite only for proposals (~10) | Gemma 48 h per pool; Flash-Lite days | ~6–12 s plus unknown Gemma latency | ~3 h; JSON-schema support, latency and 500-error rate unverified |
| **E. 3.8 Live continuous tracker** | 1 session (unlimited requests); about 5.7K–18K input tokens per minute of streamed video and audio against 65K TPM, plus unknown per-turn context accounting; nudge turns every 15–30 s | Unlimited RPD; TPM-bound | ~1–5 s after media arrives (unmeasured) | ~4–6 h; WebSocket, compression, reconnect and injection risk; preview API |

**Clip variant (B, C or D).** Send the last 20 s as remuxed MP4 at high video resolution instead of frames (~6K tokens on Flash-Lite). This adds audio cues at the same RPD. Gemma 26B and 31B can't take audio.

**Day-one checks**
1. Measure 3.5 Flash-Lite latency with 1, 4 and 8 frames, and with one 20 s clip.
2. Spike `client.decisions.create` with one frame and three questions.
3. On `gemma-4-26b-a4b-it`, measure `usage_metadata` tokens for one 854x480 frame, test function-call-as-schema and `response_json_schema`, and measure latency and error rate over about 20 calls (≈0.3% of RPD).
4. Test whether `medium` or `high` reads a chess clock and a CS2 scoreboard.
5. Run a 10-minute 3.8 Live session to observe `usageMetadata` growth, function-call behaviour and GoAway/resumption.

### Gaps
- Decision 1 calibration on game frames, and the abstain thresholds, need fixture validation.
- Gemma and Live latency are unmeasured. Live per-turn token accounting is unknown.
