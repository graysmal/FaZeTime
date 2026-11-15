# State tracking and temporal memory for a game-agnostic live-stream prop-bet AI (desk research, 15 Nov 2026)

Evidence labels: **[fetched]** means I read the primary page (often only the arXiv abstract page). **[snippet]** means I saw the claim only in a search-result summary, so verify it before relying on it. Dates are arXiv submission or publication dates. Anything before 2025 is flagged as older.

## Q1. What streaming/online video-memory architectures exist, and what do 2024–2026 benchmarks show about tracking state changes, counting and temporal order over minutes-long video?

### Takeaway
There are five families of architecture: a recency window with no memory; compressed or event-tree memory; hierarchical memory with agentic retrieval; structured object/event databases; and cascaded routing. On 2026 benchmarks, a plain 4-frame recency window beats most published streaming-memory models at questions about the current state. Every model tested, including Gemini 3 Flash/Pro and GPT-5, is poor at counting and fine temporal order over minutes, typically scoring 17–48% where humans score 79–98%. Writing event boundaries and counts down explicitly, outside the model, fixes most of the counting failure (SVCBench oracle: 3.9 rose to 81.8).

### Cited Findings
**Architectures**
- **Recency window, no memory (SimpleStream):** feeds only the last N frames, sampled at 1 fps, to an off-the-shelf VLM (Qwen2.5-VL-7B or Qwen3-VL-8B). With 4 frames on Qwen3-VL-8B it scored 67.70 on OVO-Bench (Real-Time 81.4, Backward 54.0) and 80.59 on StreamingBench. In the same tables the memory-based streaming models scored lower on OVO-Bench: HERMES-7B 59.20, StreamForest-7B 56.60, TimeChat-Online-7B 51.80, Dispider-7B 45.35, Flash-VStream-7B 27.90. On StreamingBench: HERMES 79.44, StreamForest 77.26, Dispider 67.63, Flash-VStream 23.23. [fetched; 2 Apr 2026] — [SimpleStream (HTML)](https://arxiv.org/html/2604.02317v1)
- **Memory trades off against perception.** The SimpleStream authors write that "adding more historical context can improve recall, but often weakens real-time perception":
  - StreamForest: memory +8.9, real-time perception −13.8 relative to SimpleStream.
  - HERMES: +2.4 / −6.0.
  - A Visual-RAG ablation: memory +6.6, perception −4.9.
  - Window size is non-monotonic. Qwen3-VL-8B scored 66.38 with 2 frames, 67.70 with 4, 67.37 with 8 and 67.15 with 16. Qwen2.5-VL-7B peaked at 4 frames (65.13) and fell to 61.66 at 16.
  - The authors offer "attention dilution" as the cause, explicitly as a hypothesis.

  [fetched] — [SimpleStream](https://arxiv.org/html/2604.02317v1). They also argue that memory modules should not count as progress unless they beat this baseline under the same protocol — [abstract](https://arxiv.org/abs/2604.02317)
- **Event-tree memory (StreamForest, NeurIPS 2025):** organizes the stream into an event-based tree memory at 1 fps. Self-reported scores are 77.3 StreamingBench, 60.5 OVBench and 55.6 OVO-Bench [snippet]. This differs from the 56.60 in SimpleStream's table because the protocols differ. — [StreamForest](https://arxiv.org/html/2509.24871v1); [NeurIPS page](https://papers.neurips.cc/paper_files/paper/2025/hash/6dd91fec726dbed8915a1fbadd91d1d2-Abstract-Conference.html)
- **Event-centric hierarchical memory (EventMemAgent):**
  - Short-term memory "detects event boundaries and utilizes event-granular reservoir sampling" within a fixed-length buffer.
  - Long-term memory archives past observations event by event.
  - Adds a multi-granular perception toolkit trained with agentic RL, so it needs training.
  - The abstract reports only "competitive results".

  [fetched abstract; 17 Feb 2026, rev. 11 Sep 2026] — [EventMemAgent](https://arxiv.org/abs/2602.15329)
- **Training-free hierarchical memory with agentic retrieval on a hosted model (VAM):**
  - Pipeline: online indexing, then hierarchical memory, then agentic retrieval that "searches, inspects, and verifies candidate evidence".
  - On Gemini 3 Flash it scores 68.41 OVO-Bench RT+BT average, against 67.46 for Gemini 3 Flash used end to end (about +1 point).
  - On MM-Lifelong (105.6 h over 51 days) it scores 17.11%, against 17.62% for ReMA with GPT-5.
  - No call counts or latency appear in the abstract.

  [fetched; 15 May 2026] — [VAM](https://arxiv.org/abs/2605.16481)
- **Cascaded control (R3-Streaming):** for each query it compresses memory, judges whether it is "ready to respond", and routes hard queries to a stronger model. It claims 95–96% less visual-token usage, with 57.92 on OVO-Bench and 76.36 on StreamingBench. It is RL-trained. [fetched abstract; 18 May 2026] — [R3-Streaming](https://arxiv.org/abs/2605.17921)
- **Structured database memory (VideoAgent, ECCV 2024, older):** keeps a temporal memory of short-segment captions plus an object-memory SQL database (category, CLIP features, segments where each object appears). The LLM calls tools: caption retrieval, segment localization, VQA and object-memory query. It counts objects with SQL after re-identification. — [VideoAgent paper](https://arxiv.org/pdf/2403.11481v2); [project page](https://videoagent.github.io)
- **Other training-free and trained variants [snippet]:**
  - ObjectStream (training-free latent-object memory anchors) reports +10.0 OVO-Bench Real-Time, +4.9 Backward and +2.9 StreamingBench on Qwen2.5-VL-7B — [ObjectStream](https://www.alphaxiv.org/abs/2607.28312.md)
  - VST-7B ("watch and think simultaneously") reports 79.5 StreamingBench and 59.3 OVO-Bench (Backward 56.7) [Mar 2026] — [VST](https://arxiv.org/pdf/2603.12262)

**Benchmarks: state, counting and temporal order**
- **OVO-Bench (CVPR 2025):** 644 videos and about 2,800 timestamped meta-annotations across 12 tasks in three modes: backward tracing, real-time understanding, and forward active responding ("delaying the response until enough future information is available"). Nine Video-LLMs "struggle with online video understanding", with a significant gap to humans. [fetched abstract; 9 Jan 2025] — [OVO-Bench](https://arxiv.org/abs/2501.05510)
- **SVCBench (first posted as VCBench) uses counting to probe whether a model maintains world state.**
  - Scale: 406 videos, 1,000 QA pairs, 4,576 streaming query points.
  - Overall GPA: human 96.1, Gemini-3-Flash 37.0, Doubao-Seed-1.8 36.2, Qwen3-VL-8B 31.0, Kimi-K2.5 26.4, StreamingVLM 19.1, text-only GPT-4-Turbo 18.7, Dispider 7.7.
  - Every model scored below 4 GPA on periodic-event counting (Gemini-3-Flash 3.9).
  - Online models generally scored below offline models of similar size.

  [fetched v1, 13 Mar 2026; renamed SVCBench in v3, 29 Jun 2026] — [SVCBench](https://arxiv.org/html/2603.12703v1)
- **SVCBench oracle:** giving explicit cycle-count annotations raised Gemini-3-Flash's periodic GPA from 3.9 to 81.8 and cut monotonicity violations from 43.8% to 6.2%. The authors attribute the failure to visual-temporal grounding of cycle boundaries, not to counting logic. — [SVCBench](https://arxiv.org/html/2603.12703v1)
- **SVCBench state decay:** in a rotating-camera identity test, Gemini-3-Flash fell from 76.2 GPA in the first 10 cycles to 28.3 by cycle 60 (Doubao 71.8 to 35.7; Qwen3-VL-8B 68.5 to 23.8). A blind text model reached 95.7 monotonicity from the prior "counts go up" alone, but only 4.3 update-direction accuracy. — [SVCBench](https://arxiv.org/html/2603.12703v1)
- **EC-Bench (videos over 30 min):** the best of 22 models, GPT-5, reached 29.98% enumeration and 23.74% counting, against 78.57% and 82.97% for humans. [snippet; Mar 2026; another summary says 22.70% counting] — [EC-Bench](https://www.emergentmind.com/papers/2603.29943)
- **VideoZeroBench:** Gemini-3-Pro was the best model and still answered fewer than 17% of questions under standard end-to-end QA. No model exceeded 1% when correct temporal and spatial grounding of the evidence was also required. [snippet; Apr 2026] — [VideoZeroBench](https://arxiv.org/html/2604.01569v1)
- **TimeBlind (fine-grained temporal composition, paired clips):** Gemini 3 Pro scored best at 48.2% instance accuracy, against 98.2% for humans. GPT-5 gained only 3.3 points from more frames or test-time reasoning. [snippet; Feb 2026] — [TimeBlind](https://arxiv.org/pdf/2602.00288)
- **GameplayQA (ACL 2026):** multiplayer 3D gameplay annotated at 1.22 labels/s, 2.4K QA pairs. Frontier MLLMs show "a substantial gap from human performance", failing at temporal and cross-video grounding, at attributing actions to the right agent, and at the game's decision density. [fetched abstract; 25 Mar 2026] — [GameplayQA](https://arxiv.org/abs/2603.24329)
- **EgoEsportsQA:** 1,745 QA pairs from pro matches of three FPS games. The best Video-LLM scored 71.58%. Models are stronger at "basic visual perception than in deep tactical reasoning" and "grasp overall macro-progression better than fine-grained micro-operations". [fetched abstract; 14 Apr 2026, "work in progress"] — [EgoEsportsQA](https://arxiv.org/abs/2604.12320)
- **VideoGameQA-Bench (game QA, not live state):** 9 tasks and 4,786 questions on glitch detection and bug reports. Sensitivity and specificity "need improvement", especially at the low glitch prevalence of real gameplay. [snippet; May 2025] — [VideoGameQA-Bench](https://arxiv.org/abs/2505.15952v2)
- **Temporal sampling limits (Gemini docs):**
  - At the default 1 fps, "fast action sequences may lose detail" — [Gemini video understanding](https://aistudio.google.com/docs/video-understanding)
  - The Live API (1 fps) is "unsuitable for use cases that require analyzing fast-changing video", for example high-speed sports play-by-play — [Live API limits](https://firebase.google.com/docs/ai-logic/live-api/limits-and-specs)

### Inferences
- The decisive split is between **current-state perception**, which works (about 80% on OVO-Bench real-time with 4 frames), and **memory accumulated by the model over minutes**, which does not (counting 23–37%, temporal composition at most 48%, grounded long-video QA under 17%). Design so that every resolution depends on a current or terminal on-screen reading or a transcript search, never on the model having remembered or counted across minutes.
- The SVCBench oracle result is the strongest evidence for the owner's intuition, but in a specific form. Writing boundaries and counts into code-owned state turns a near-zero task into a solvable one. Asking the model to "keep track" internally does not.
- The research streaming models (StreamForest, Dispider, Flash-VStream, StreamingVLM, VST, EventMemAgent, R3) need self-hosted GPUs, and several need training. None can run on a Pi 5 or the CPU VM, and many trail a recency baseline. Only training-free patterns transfer to a hosted-API build: a recency window, VAM-style indexing and retrieval, and VideoAgent-style structured tables.
- VAM gains only about 1 point over end-to-end Gemini 3 Flash, so multi-call agentic retrieval is not worth its request cost on a free tier.
- The planned sampling of 1 frame every 2–10 s is 2–10 times sparser than Gemini's 1 fps default. Momentary events such as a single kill, a peg hit or a blunder will often fall between frames. Restrict propositions to persistent on-screen state (scoreboards, clocks, counters, result banners) or speech.

### Gaps
- No benchmark covers what this system faces: arbitrary-game Twitch streams with ASR plus frames sampled every 2–10 s. I read only the abstracts of GameplayQA and EgoEsportsQA, so I do not have their per-model tables or the names of the games.
- The EC-Bench, VideoZeroBench, TimeBlind, VST and ObjectStream numbers come from search snippets only.
- I found no measurement of how well VLMs read HUD numbers (timers, scores) at 480p, or how that accuracy depends on frame interval.

## Q2. With hosted LLM APIs only, which persistent-state patterns work, and how do they compare on accuracy, latency, request count and failure modes?

### Takeaway
Do not have the model rewrite a world state on every slice. At 600–900 requests per hour that exhausts the flash-lite quota (500/day) within an hour. Even on Gemma 4 (14.4K requests/day, but only 16K tokens per minute) it invites drift and "context poisoning". Frequent calls are fine as long as each one is a stateless observation. The pattern with the best support is:
- an append-only, timestamped evidence and observation log;
- a small current state derived by code that records which values supersede which, plus an episode state machine;
- stateless model calls that re-read fresh frames each time (periodic re-grounding);
- at resolution time, a bounded evidence packet around the relevant moment (the anchor), not long clips.

The owner's intuition is right that something must hold state. That something should be backend code over stored evidence, not the model's memory.

### Cited Findings
**Hosted-model mechanics (Gemini)**
- **Static video input:**
  - 1 fps by default; a custom `fps` can be set (for example 0.5); clips can be cut with `start_offset`/`end_offset`; moments can be referenced in MM:SS.
  - About 100 tokens per second of video at low resolution and about 300 at high. The page's older-generation figures are 258 or 66 tokens per frame plus 32 audio tokens per second.
  - A 1M-token context holds about 3 h of video at low resolution or 1 h at high.
  - The free-tier File API accepts files up to 2 GB. Gemini 2.5 and later accept up to 10 videos per request.
  - The inline size limit is stated inconsistently on the page (20 MB in the text, 100 MB in the table).

  [fetched 15 Nov 2026; no last-updated date shown] — [Gemini video understanding](https://aistudio.google.com/docs/video-understanding)
- **Agentic video mode (`"processing": "agentic"`):**
  - The model navigates the timeline, inspects transcripts and adjusts frame rate and resolution itself.
  - Up to 88% fewer tokens on long-form content; static mode is recommended for clips under about 5 minutes.
  - Supported models listed on the page: Gemini 4 Carbon/Argon/Hydrogen, 3.8 Flash, 3.6 Flash and 3.5 Flash Lite [fetched]. A 1 Sep 2026 changelog mirror lists 3.7 Flash, 3.6 Flash and 3.5 Flash-Lite [snippet], so the names have shifted.

  — [Gemini video understanding](https://aistudio.google.com/docs/video-understanding); [changelog mirror](https://techdevnotes.com/releases/gemini-docs/20260901-180346Z-4a33992aa23f)
- **Media resolution on Gemini 3/4:**
  - Images: 280 / 560 / 1120 tokens at low / medium / high. The default is 1120. `ultra_high` (2240) is available per content item.
  - Video frames: 70 tokens at low, medium or default, and 280 at high.
  - "High" is required for "reading dense text or small details".
  - Resolution can be set per content part.

  This conflicts with the 258/66 per-frame figures on the video page, which appear to describe older models. [fetched] — [Gemini media resolution](https://aistudio.google.com/docs/media-resolution)
- **Live API:**
  - 128k-token context.
  - Sessions last about 15 min for audio only and about 2 min for audio plus video without context compression. Connections last about 10 min, with a GoAway notice about 60 s before the end.
  - Video goes in at 1 fps at 768×768.
  - Function calling is supported; structured JSON output is not.

  [fetched]. Context compression is a sliding window that keeps the system instructions, and resumption tokens are valid for 2 h [snippet]. — [Live API limits](https://firebase.google.com/docs/ai-logic/live-api/limits-and-specs); [Live session management](https://ai.google.dev/gemini-api/docs/live-session.md)
- **Free-tier daily quotas are unclear and have shrunk [snippet; sources conflict]:**
  - Forum users report Flash dropping from 250 to 20 RPD.
  - A third-party guide lists "3.8 Flash" at 5 RPM, 250k TPM and 20 RPD, and Flash-Lite models at 500 RPD.
  - Google's cached older page showed 1,500 RPD for 2.0 Flash.
  - One source says Google no longer publishes per-model free-tier RPD.

  — [Google AI forum](https://discuss.ai.google.dev/t/do-they-really-think-we-wouldnt-notice-a-92-free-tier-quota/111262); [agentdeals guide](https://agentdeals.dev/gemini-api-pricing-2026); [cached rate-limits page](https://googledevai-dot-devsite-v2-prod-3p.appspot.com/gemini-api/docs/rate-limits)
- **Verified quotas for this project's key (these supersede the snippets above).** Source: the coordinator read the owner's AI Studio rate-limit page (free tier, per project) on 2026-11-15 at about 00:50–00:55 CT. It is a private page with no public URL. Limits are RPM / TPM / RPD:
  - `gemma-4-26b-a4b-it` and `gemma-4-31b-it`: 30 / 16K / 14,400 each, as separate quotas.
  - `gemini-3.5-flash-lite` and `gemini-3.1-flash-lite`: 15 / 250K / 500 each, as separate quotas.
  - `gemini-2.5-flash` and `gemini-2.5-flash-lite`: 20 RPD.
  - Live API models (Gemini 3 Flash Live, Gemini 3.8 Live): unlimited RPD at 65K TPM.
  - `gemini-3.5/3.6/3.7/3.8-flash` and `gemini-4-*`: not yet known.

  The third-party figures of 20 RPD for 2.5 Flash and 500 RPD for Flash-Lite match these.

**Evidence on how state goes wrong**
- **StateMemBench** (234 multi-session scenarios; grading separates "current" from "superseded" answers):
  - Existing memory systems, retrieval baselines and long-context baselines all find it hard.
  - StateMem, which explicitly tracks which facts supersede which and how they depend on each other, raised current-state accuracy from 0.205 to 0.363 (DeepSeek-V4-Flash) and from 0.149 to 0.233 (Qwen-3.5-9B).
  - As a wrapper over six backends it added 32–67 points. A control matched for length and cost attributes 15–32 of those points to the structure itself rather than to extra context.

  [fetched abstract; 20 Aug 2026] — [StateMemBench](https://arxiv.org/abs/2608.19652)
- **State drift share (same paper):** about 44.4% of DeepSeek-V4-Flash's LongMemEval failures were state drift, meaning it acted on stale or superseded facts. The share was over 71.4% for multi-session questions. [snippet] — [alphaXiv listing](https://www.alphaxiv.org/abs/2608.19652)
- **StructMemEval** (ledgers, to-do lists, trees): simple retrieval-augmented LLMs struggle. Memory agents solve the tasks reliably when told how to organize memory, and LLMs "do not always recognize the memory structure when not prompted". [fetched abstract; 11 Feb 2026, v4 1 Oct 2026] — [StructMemEval](https://arxiv.org/abs/2602.11243)
- **Cost-retention study (preprint, not peer reviewed):** BM25 retrieval was the strongest cheap memory on LoCoMo. Structured fact slots were the weakest with an 8B extractor but gained 29.2 points with a 70B extractor, so extractor quality is the bottleneck. [snippet; Aug 2026] — [preprints.org](https://www.preprints.org/manuscript/202608.1369)
- **Gemini Plays Pokémon** (Gemini 2.5 technical report, Jun 2025):
  - In "context poisoning", hallucinated game state persisted in the agent's goals and summary and "can often take a very long time to undo". One example is the long hunt for a nonexistent "Tea" item.
  - A separate "Guidance Gemini" reviewed the context every 25 turns to flag hallucinations.
  - Past about 100k tokens the agent tended to repeat past actions instead of planning.

  — [dbreunig case study](https://www.dbreunig.com/2025/06/17/an-agentic-case-study-playing-pok%C3%A9mon-with-gemini.html); [How contexts fail](https://dbreunig.com/2025/06/22/how-contexts-fail-and-how-to-fix-them.html); [TechCrunch](https://techcrunch.com/2025/06/17/googles-gemini-panicked-when-playing-pokemon); [arXiv 2605.01920, which quotes the report](https://arxiv.org/pdf/2605.01920)
- Also relevant from Q1: recency windows are strong for the current state (SimpleStream), externalizing boundaries fixes counting (SVCBench), and agentic retrieval adds about 1 point (VAM). — [SimpleStream](https://arxiv.org/html/2604.02317v1); [SVCBench](https://arxiv.org/html/2603.12703v1); [VAM](https://arxiv.org/abs/2605.16481)

### Inferences
**Pattern comparison (synthesis of the findings above; latencies are unmeasured)**

| Pattern | Accuracy evidence | Requests | Failure modes | Verdict |
|---|---|---|---|---|
| A. Stateless call on a recent window (last 4–8 frames plus recent ASR) | Strong for current state: about 81 real-time on OVO-Bench (SimpleStream) | 1 per call; cadence sets the cost | Doesn't know which episode a bet belongs to, which side the streamer is on, or when the episode ended. Misses events between frames. | Use it as the observer's input, not as the whole system |
| B. LLM rewrites a JSON world state every slice | No direct test. Analogues: state drift (StateMemBench), context poisoning (Pokémon) | 600–900/h. Within Gemma 4's 14.4K RPD, but 16K TPM caps each call at about 1.8–2.7K tokens. Exhausts flash-lite's 500 RPD in 33–50 min. | Compounding errors, hallucinations that persist, stale fields | Reject the rewriting. Keep the frequent cadence for stateless observations (A + C). |
| C. Append-only evidence log, code-derived state, periodic re-grounding | Supersession structure adds 15–32 points (StateMemBench). Explicit boundaries fix counting (SVCBench oracle). | Same calls as A; the state updates themselves cost nothing | A wrong boundary or misread propagates unless code uses hysteresis and consistency checks. Needs engineering. | Recommended core |
| D. Long clip to a long-context video model at verification | Weak at counting and temporal order over minutes (EC-Bench about 23–30%, VideoZeroBench under 17%, TimeBlind 48%) | 1 per verification, but many tokens | Ungrounded "answers"; misses fast events at 1 fps; still needs episode boundaries | Use only short windows (seconds to about 1 min) around the anchor |
| E. Gemini Live API continuous session | Not benchmarked here | Unlimited RPD at 65K TPM on this key. One socket, but audio+video sessions last about 2 min uncompressed and connections about 10 min, so resumption is needed. | No JSON output (function calls could carry structure; untested); the sliding window forgets old context; unsuitable for fast video | Not on the v1 critical path. Best candidate for a later continuous observer, after a timeboxed spike. |
| F. VAM-style index plus agentic retrieval | +0.95 over Gemini 3 Flash end to end | Several calls per query | Complexity, quota | Not worth it on the free tier |

**Verdict on the owner's intuition: accept it, in this specific form.**
- A component must persist state between slices. It should be:
  - an evidence store holding every ASR chunk and a ring buffer of frames;
  - an append-only log of model observations, each citing evidence IDs;
  - a small state derived by code: current activity, the episode with its phase and boundary timestamps, participants and sides, and named on-screen quantities, each with the time it was last read;
  - an episode state machine.
- The model never "remembers". Each call re-reads fresh frames together with a compact JSON snapshot of the code's state, and returns observations. Code validates them and applies them.
- This keeps information from being lost between slices, because evidence and observations are stored and indexed. It also avoids compounding errors, because no free-text summary written by the model is ever fed back.

**Request and token arithmetic with the verified quotas (inference)**
- **Flash-lite (500 RPD) cannot host the tracker.** One call per 10 s (360/h) exhausts it in about 83 min, and one per 6 s burst in 50 min. Reserve both flash-lite quotas for proposals and resolutions.
- **On Gemma 4, requests are not the limit; tokens per minute are.** 14,400 RPD covers one call every 6 s for 24 h, and 30 RPM allows one every 2 s.
- **The cadence formula:** calls/min ≤ min(30, 0.8 × 16,000 / tokens_per_call), keeping 20% headroom, where tokens_per_call ≈ prompt and state + n_frames × tokens_per_image + ASR + output.
  - Counting output tokens toward TPM is conservative, since I could not confirm whether TPM counts them.
  - The per-image token cost of Gemma 4 through this API is unverified. Measure it from `usage_metadata` on the first calls, and let the governor adapt.
- **Example**, assuming about 300 tokens per image and a 700-token compact prompt and state (from the formula above):
  - 1 frame (about 1.4K tokens/call): about 9 calls/min, one every 6–7 s, matching Twitch's burst cadence.
  - 2 frames (about 1.8K): about 7/min, one every 8–9 s.
  - 4 frames (about 2.4K): about 5/min, one every 11–12 s.
  - A 1.5K-token prompt adds about 30–50% to each interval.
- **The frames come from one stream, so per-call frame count falls as cadence rises.** Send the newest frame plus any frame flagged by local change detection, and store everything else for resolution. Keep the prompt and state snapshot small: only the current episode, and only the quantities and phrases the open markets need. Every token in them is paid on every call against 16K TPM.
- **The second Gemma model (`gemma-4-31b-it`) has its own 16K TPM.** Use it as a role, not for round-robin. Its jobs are end-watch bursts while a market waits on an episode end, and an independent second reading of anchor quantities. Two models give independence for the "two agreeing reads" rule.

**Token arithmetic (Gemini 3/4 figures)**
- Sending frames as images: 8 frames at low (8 × 280) plus one high-resolution frame (1120) plus about 1k of state JSON plus ASR text comes to roughly 4.5–5k tokens per call.
- Alternatively, local ffmpeg can pack the frames into a short MP4 with audio stripped, for 70 tokens per frame plus native timestamps. Only the high-resolution anchor or crop frames then need to be separate image parts.

**Re-grounding rules (inference)**
- Every quantity value carries `read_at_ts` and evidence IDs.
- Values older than a time-to-live are marked stale and cannot be used to resolve a bet.
- At each episode boundary, quantities and events are reset; only activity and participants carry over.
- Model "facts" with no valid evidence ID are dropped.

### Gaps
- No study compares patterns A–F head to head on live video through a hosted API. The table is a synthesis.
- I found no authoritative latency figures for Gemini calls with many images or short videos; these need to be measured. I also found no figures for Gemini's accuracy at reading digital timers or scores at 480p.
- The quotas are now verified for Gemma 4, the flash-lite models, 2.5 Flash and the Live models. Still unknown:
  - the quotas for `gemini-3.5–3.8-flash` and `gemini-4-*`;
  - whether TPM counts output tokens;
  - how many tokens a Gemma 4 image costs, and whether Gemma 4 through this API accepts image input and JSON-schema output (if it lacks schema mode, fall back to prompted JSON with strict parsing and one retry);
  - whether the Live models can return text or function-call output, and how their 65K TPM is counted (pushed frames only, or the re-processed context as well).

## Q3. How can episode boundaries (start and end of a match, round, game or level) be detected without game-specific code, from frames plus speech?

### Takeaway
I found no source that solves game-agnostic boundary detection. A workable approach combines three layers:
- cheap local signals on the CPU: frame-change scores, static or near-uniform "menu/loading" screens, a tracked timer resetting or a score incrementing, and generic speech cues such as "GG" or "next game";
- a VLM call that classifies the screen type and reads any result banner, made only when a local signal fires or a heartbeat is due;
- a state machine in code with hysteresis and an `ended_unknown` state, whose open bets are voided.

The SVCBench evidence shows that boundary grounding is exactly where VLMs fail on their own.

### Cited Findings
- **Generic Event Boundary Detection (Kinetics-GEBD, 2021, older)** defines event boundaries as moments where humans perceive a change. That is broader than shot cuts and includes action changes, brightness shifts and a new subject appearing. [snippet] — [Kinetics-GEBD](https://arxiv.org/pdf/2101.10511v2)
- **PySceneDetect detectors:**
  - ContentDetector scores frame-to-frame color change against a fixed threshold (default 27.0).
  - AdaptiveDetector uses a rolling average of nearby frame changes as its threshold (default `adaptive_threshold` 3.0) and handles fast camera motion better in some cases.
  - HistogramDetector (default 0.05) trails the others on hard-cut F1, notably on ClipShots.

  [snippet] — [PySceneDetect detectors](https://www.scenedetect.com/docs/head/api/detectors.html); [PySceneDetect benchmarks](https://www.scenedetect.com/benchmarks/)
- **Zero-shot change points:** frozen VLM features combined with Kernel Temporal Segmentation give shot-boundary detection and scene clustering without training. It was evaluated on general video, not games. [snippet; Oct 2025] — [arXiv 2510.16781](https://arxiv.org/html/2510.16781v1)
- **Thresholding against over-segmentation:** a zero-shot summarization method marks a boundary when frame change crosses a threshold and drops segments shorter than about 5 s. [snippet; Oct 2025] — [arXiv 2510.17501](https://arxiv.org/pdf/2510.17501)
- **Audio cues (older patent):** broadcast segmentation detects "silent intermissions" when sub-band audio energy stays low for a set interval. [snippet] — [US patent 8195034](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/8195034)
- **Boundary grounding is the VLM bottleneck:** periodic counting failed (under 4 GPA) because of weak "visual-temporal grounding for cycle boundaries". Supplying the boundaries raised accuracy to 81.8. — [SVCBench](https://arxiv.org/html/2603.12703v1)
- **Event-memory systems segment the stream at detected event boundaries** (EventMemAgent short-term memory); the method is not described in the abstract. — [EventMemAgent](https://arxiv.org/abs/2602.15329)
- **"Decide when you know enough" is its own hard task:** OVO-Bench's forward active responding mode requires "delaying the response until enough future information is available", and models lag humans. — [OVO-Bench](https://arxiv.org/abs/2501.05510)
- **Native game state APIs model phases explicitly.** Counter-Strike 2 Game State Integration exposes a round phase (live or over, with an unknown fallback) and per-round bomb states (planted, defused, exploded). ESL's tournament event schema includes round start/end, plant and defuse events. These are third-party library and provider docs, not Valve's. — [CS2 GSI round model (docs.rs)](https://docs.rs/cs2-gsi/0.1.1/src/cs2_gsi/model/round.rs.html); [CounterStrike2GSI](https://github.com/antonpup/CounterStrike2GSI); [ESL event types](https://docs.api.prodb.eslgaming.com/2025-03-11/graphql/types/enums/game-event-data-game-action-type)
- **Broadcast scoreboard systems find the scoreboard region from its static elements**, or let a person designate it in a GUI, and can trigger processing from schedule (EPG) data. [snippet; patent family] — [US 11805283](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/11805283); [US 11010627 (scoreboard text region detection)](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/11010627)

### Inferences
**Generic boundary cue catalogue (no per-game code; the hints go in prompts and config)**
1. **Result or transition text:** large centered banners such as "Victory/Defeat", "Game Over", "Level Complete", "K.O.", "Checkmate"/"1-0", "<Team> Win(s)", "Round N", "Fight!", "Retry?". The VLM reads them; a CPU OCR word count can flag them as candidates.
2. **Screen-type transitions:** gameplay switching to or from result, scoreboard, menu, loading, lobby, replay or kill-cam, or non-game ("BRB" or just-chatting scenes). Menus and loading screens tend to be static (low change between frames) or near-uniform. Local diff and histogram statistics detect these cheaply.
3. **Quantity discontinuities**, a rule applied to the model's numeric readings:
   - a value of a quantity tracked as a timer jumps back toward its starting value (round timer back to the start, chess clocks back to 3:00, a speedrun timer back to 0);
   - a score or counter increments;
   - a lives or balls counter resets.

   This one rule covers CS2, chess, Peggle, fighting games and speedruns without game code.
4. **Visual discontinuities** (AdaptiveDetector-style): these are candidates only, because game cameras cut constantly.
5. **Speech cues** from ASR: "gg", "good game", "we won", "we lost", "that's game", "next game", "one more", "queue", "rematch", "reset", "new run", "round <n>", "checkmate", "resign". These are weak cues. They should trigger an observer call and never decide a boundary alone.

**Detector design**
- **Tier 0 (CPU, every frame, Pi 5 or VM):**
  - a 64×36 grayscale or HSV-histogram difference against a rolling mean;
  - a static-screen counter (N consecutive low-difference frames);
  - a near-black or near-uniform screen test;
  - an ASR keyword matcher.
- **Tier 1 (VLM, on a trigger or heartbeat):** returns `screen_type` from {gameplay, menu, lobby, loading, result, scoreboard, replay, cutscene, non_game, unknown}, an episode signal (start, end, continue or none) with evidence IDs, and any visible result verbatim.
- **Tier 2 (code state machine):**
  - **Start:** gameplay seen in at least 2 consecutive observations, or an explicit start cue together with a quantity reset.
  - **End:** a result banner, or an outcome read with evidence, or non-gameplay screens persisting for at least T seconds after `live`. In the last case, with no outcome read, the state becomes `ended_unknown`, and bets that need an outcome are voided.
  - **Next episode:** cannot start until the previous one has ended or been aborted.
  - **Hierarchy:** support `parent_id` (a match containing rounds), but in v1 each market binds to the single episode level it was proposed on.
- **Timing:** use media time (stream timestamps), not wall-clock time. Twitch's roughly 6 s bursts and several-second delay mean an end can arrive late, so resolution waits for a grace window. A gap in ingest coverage that overlaps the anchor window voids the bet.

### Gaps
- I found no benchmark or paper on detecting loading, menu or result screens across arbitrary games, zero-shot. It remains to be measured how reliably a VLM classifies screen type from 480p frames sampled every 2–10 s.
- Speech-cue precision and recall are unknown. Streamers say "gg" sarcastically and react to other people's games.

## Q4. How do automated live sports and esports commentary or analytics systems track state from broadcast video, and what transfers to arbitrary games?

### Takeaway
Production-style systems either take structured state from official feeds (game APIs and tournament data providers) and let an LLM narrate it, or build vision pipelines specific to one sport or game: scoreboard or HUD region detection, OCR, structured fields, then accuracy checks. The per-game detectors do not transfer. What transfers is the shape of the pipeline:
- treat the HUD or overlay as a state API;
- read numbers at known moments;
- validate them with temporal-consistency rules;
- feed the language model structured state rather than raw pixels, to avoid hallucinated narration.

### Cited Findings
- **Broadcast scoreboard OCR (patent family):** locate the scoreboard region, find text regions inside it, apply OCR, then generate structured sport data. The region can be found from static scoreboard elements or designated through a GUI. A sibling patent family covers "determining accuracy of sport-related information extracted from digital video frames". [snippet] — [US 11805283](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/11805283); [US 11087161](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/11087161)
- **Q3Vision (Quake III):** object detection (YOLO) plus OCR-based HUD parsing reconstructs game state not recorded in logs. OCR is "limited by low-resolution, stylized HUD fonts and visual noise". [snippet] — [Q3Vision (UTS)](https://opus.lib.uts.edu.au/handle/10453/197175)
- **League of Legends broadcasts:** an MSc thesis proposes real-time automatic event detection in videogame broadcasts and reviews text-feature analysis of sports video. [snippet; 2024 per snippet] — [Murta thesis](https://firepuma.isr.tecnico.ulisboa.pt/assets/publications/msc/Thesis_GustavoMurta55175.pdf)
- **SoccerNet Game State Reconstruction (CVPR-W 2024, older):**
  - Dataset: 200 clips of 30 s with 2.36M athlete positions labeled with role, team and jersey number, scored by the GS-HOTA metric.
  - Baseline pipeline: tracking, re-identification, team affiliation, jersey-number recognition, pitch localization and camera calibration.
  - It is "highly challenging" with a single moving camera and occlusions.

  — [SoccerNet-GSR](https://arxiv.org/html/2404.11335v1)
- **2024 GSR challenge winner:** YOLOv5m, a SegFormer camera-parameter estimator and DeepSORT. It splits and merges tracklets when jersey number and team ID are temporally consistent, an example of consistency-based correction. [snippet] — [From Broadcast to Minimap](https://arxiv.org/html/2504.06357v1)
- **Gameplay highlights:** per-game OCR is costly and "may not generalize across game UIs or languages". The authors instead fine-tune a general video-language model (X-CLIP) across games in one genre. [snippet; May 2025] — [Gameplay Highlights Generation](https://arxiv.org/html/2505.07721v1)
- **Live game commentary:** "Existing systems rely on structured game state inputs and lightweight language models". This paper generates spoken commentary directly from gameplay video and attacks latency with parallel generation and video-delay control. [snippet; Jun 2026, IJCAI 2026] — [arXiv 2606.13322](https://arxiv.org/html/2606.13322)
- **Racing-game commentary:** a feedback loop decides whether to speak or stay silent based on the system's earlier commentary. [snippet; Mar 2026] — [arXiv 2603.02655](https://arxiv.org/abs/2603.02655)
- **Robot-soccer sportscast:** a neuro-symbolic system extracts statistics from video and narrates from them, stressing hallucination-free narration. [snippet; 2026] — [arXiv 2607.14809 summary](https://tldr.takara.ai/p/2607.14809)
- **Soccer commentary demo:** a play-by-play module spots events in video frames and a retrieval module adds background commentary. [snippet; ACL 2025 demo] — [ACL 2025 demo](https://preview.aclanthology.org/ingestion-acl-25/2025.acl-demo.38.pdf)
- **Football commentary:** predicted in-game events are embedded into LLM prompt templates. [snippet; 2025] — [MDPI Mathematics 13(17) 2738](https://www.mdpi.com/2227-7390/13/17/2738)
- **Official game-state feeds:** CS2 GSI is "used during competitive tournament live streams" to show the spectated player's information. It requires configuring the game client (per the library docs), and ESL publishes structured round and bomb events. [snippet] — [CounterStrike2GSI](https://github.com/antonpup/CounterStrike2GSI); [ESL event types](https://docs.api.prodb.eslgaming.com/2025-03-11/graphql/types/enums/game-event-data-game-action-type)
- **Video-LLM gameplay pipelines are bespoke:** for example, SAM3 + SigLIP + VideoMAE + OCR + Qwen3-VL-8B with trained adapters. [snippet] — [gameplay-vision-llm](https://github.com/chasemetoyer/gameplay-vision-llm)

### Inferences
- **Transfers:**
  1. A HUD or overlay is a stable screen region whose pixels stay still while gameplay changes around it. It can be found generically from per-pixel temporal variance across about 30–60 s of frames (the static-element idea, applied to any game), then cropped and read at higher resolution.
  2. Read numbers only at moments that matter (episode start, the anchor, the end) and log the time of each reading.
  3. Validate with game-agnostic consistency rules:
     - countdown timers do not increase within a live episode;
     - scores change by small steps;
     - counts stay within bounds;
     - two readings near the anchor must agree.
  4. Feed structured state to the LLM, rather than raw frames alone, when it proposes or narrates.
- **Does not transfer:** trained per-game detectors (Quake HUD YOLO), jersey-number recognition, pitch calibration, and official data feeds. GSI and provider feeds need the streamer's client setup or tournament contracts, and they exist only per game.
- An arbitrary Twitch stream has no official feed. The VLM observer stands in for a game-state API. The project should therefore pick propositions whose resolving evidence is exactly the kind of thing a HUD or result screen shows.

### Gaps
- I found no public engineering write-up from a betting-data provider on vision-based state accuracy versus official feeds, and no measured OCR accuracy figures for esports HUDs in these sources. I read only snippets of Q3Vision.

## Q5. Should state updating, bet proposal and outcome verification be one model call or separate roles? What does the evidence say, including the effect on request counts?

### Takeaway
Separate the roles, but do not build a multi-agent system. Code orchestrates a fixed pipeline:
- an **observer**, a stateless extractor that also proposes candidate bets in the same call;
- a **reducer** in code, the only writer of state;
- a **resolver**, a fresh call that sees only the frozen bet specification and an evidence packet, or deterministic code for transcript- and time-based bets.

The evidence shows free-form multi-agent setups add little and amplify errors on sequential tasks. A centralized validator contains errors, and self-evaluation is biased. Separation adds only about 1–2 calls per bet, small next to the observation calls.

### Cited Findings
- **MAST (1,642 traces from 7 multi-agent frameworks):** performance gains on popular benchmarks "often remain minimal compared to single-agent frameworks". The paper defines 14 failure modes in 3 categories: specification and design, inter-agent misalignment, and task verification and termination. [snippet; Mar 2025, NeurIPS 2025] — [MAST](https://arxiv.org/abs/2503.13657v2)
- **"Towards a Science of Scaling Agent Systems"** (180 configurations, 5 architectures, 3 LLM families):
  - On strictly sequential reasoning, every multi-agent variant degraded performance by 39–70%. Parallelizable tasks gained, for example +81% on Finance-Agent.
  - Independent agents amplified errors 17.2 times. A centralized orchestrator held this to 4.4 times by acting as a "validation bottleneck".

  [snippet; Dec 2025, blog Jan 2026] — [arXiv 2512.08296](https://arxiv.org/abs/2512.08296v1); [Google Research blog](https://research.google/blog/towards-a-science-of-scaling-agent-systems-when-and-why-agent-systems-work/)
- **Self-preference bias (2024, older):** LLM evaluators favor their own generations, and the strength of the bias correlates linearly with their ability to recognize their own text. [snippet] — [Panickssery et al.](https://arxiv.org/html/2404.13076v1)
- **Anthropic engineering guidance (Dec 2024, older):**
  - "we recommend finding the simplest solution possible, and only increasing complexity when needed";
  - workflows are "orchestrated through predefined code paths";
  - prompt chaining can add "programmatic checks" (gates) on intermediate steps;
  - evaluator-optimizer: "one LLM call generates a response while another provides evaluation";
  - guardrails: "one model instance processes user queries while another screens them".

  [fetched] — [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)
- **A critic role catches persistent hallucinations in practice:** Gemini Plays Pokémon ran a "Guidance Gemini" that reviewed context every 25 turns. No quantitative effect was reported in what I saw. — [dbreunig case study](https://www.dbreunig.com/2025/06/17/an-agentic-case-study-playing-pok%C3%A9mon-with-gemini.html)
- **Routing hard queries to a stronger model** is part of the most token-efficient streaming design (R3-Streaming). — [R3-Streaming](https://arxiv.org/abs/2605.17921)
- **Abstention is weak across the board:**
  - MM-AQA: no system exceeds 65% on both answerable and unanswerable accuracy [snippet; Apr 2026] — [MM-AQA](https://www.alphaxiv.org/abs/2604.14799)
  - VirtueBench (CVPR 2026) tests whether long-video models correctly refuse when key frames are missing [snippet] — [VirtueBench](https://arxiv.org/html/2603.07071)
  - Absent-answer detection in video QA is a separate EMNLP 2026 benchmark [snippet] — [arXiv 2606.08239](https://arxiv.org/html/2606.08239v1)

### Inferences
- **Role split mapped to the verified quotas** (an example 4-hour streaming day with about 40 bets):

  | Role | Model (quota) | Cadence and size | Calls/day |
  |---|---|---|---|
  | Observer/tracker | `gemma-4-26b-a4b-it` (30 / 16K / 14.4K) | Every 6–12 s while an episode is live, adapted to TPM; every 30–60 s when not in a game; 1–2 frames plus compact state per call | about 1,200–2,400 (8–17% of RPD) |
  | End-watch and second reader | `gemma-4-31b-it` (30 / 16K / 14.4K) | Bursts every 5–10 s only while a market awaits an end; independent re-read of anchor quantities | about 200–600 |
  | Proposer | Piggybacked candidates from the observer, gated by code; optionally one wording/threshold call per episode on `gemini-3.5-flash-lite` | About 1 per episode | 0–60 of 500 |
  | Resolver A | `gemini-3.5-flash-lite` (15 / 250K / 500) | 1 per outcome or quantity bet; high-resolution packet of about 6–10K tokens fits 250K TPM | about 40 |
  | Resolver B (agree or void) | `gemini-3.1-flash-lite` (separate 500) | 1 per outcome or quantity bet | about 40 |
  | Deterministic | Code | Utterance and duration bets | 0 |
  | Reserve | `gemini-2.5-flash(-lite)` (20 RPD) and the unknown-quota models | Nothing on the critical path until their quotas are read | 0 |

- Settlement now has independence at no shared-quota cost: two different flash-lite models must agree, or the bet is voided.
- If Gemma 4 turns out to be poor at reading 480p HUD text, the tracker still provides boundaries and screen types. Numeric readings at the anchor then come from the high-resolution flash-lite resolver packet.
- If the Live API spike succeeds, the Gemma tracker becomes the fallback.
- **Why the resolver must be separate and minimal:**
  - Self-preference bias and context poisoning both argue against letting the call that proposed a bet, or that carries a long running narrative, judge it.
  - The resolver sees only:
    - the frozen resolution spec;
    - timestamped evidence from the anchor window, with high-resolution anchor frames or crops;
    - the ASR excerpt;
    - code-collected quantity readings with timestamps.
  - It must cite evidence IDs and quote the exact reading (for example "0:47").
  - Code then gates the answer: evidence IDs must exist and fall inside the window; numeric readings must parse and agree with another read; any failure means void.
- **Code is the orchestrator**, the centralized validator in the Google study's terms. Models have no authority over balances or settlement, which is consistent with the project's constraints. Approval mode is the human gate on resolution.
- **If budget allows:** a second, independent resolver call (a different model or prompt) with "agree or void"; a local OCR reading as a cheap second opinion on numbers; and a periodic auditor call, in the style of Guidance Gemini, that checks the derived state against fresh evidence.

### Gaps
- I found no study measuring role separation versus a single agent specifically for video verification or settlement. The evidence is from general agent benchmarks and LLM-as-judge studies.
- I found no data on whether a cross-family verifier reduces false resolutions for vision tasks.

## Q6. What generic state schema would cover chess, CS2, Peggle and similar games, and what concrete architecture should the prototype use?

### Takeaway
Use a backend-owned, evidence-indexed state with:
- stream coverage;
- activity;
- a hierarchy of episodes, each with a phase and boundary timestamps;
- generic participants with roles and sides;
- named on-screen quantities, each holding its latest reading, the time it was read and the evidence it came from;
- a short event log;
- open questions;
- markets with frozen resolution specs.

Restrict propositions to four verifiable templates:
- episode outcome;
- a quantity read at an anchor moment;
- a phrase appearing in the transcript within the episode window;
- episode duration.

These are restrictions on proposition types, not on games or formats.

### Cited Findings
- **Native game state schemas share the same core concepts:** a phase (CS2 GSI round phase live or over), discrete status fields (bomb planted, defused, exploded), and timed events (ESL round start/end, plant, defuse). These suggest the generic fields `phase`, `status` and `events`. — [CS2 GSI round model](https://docs.rs/cs2-gsi/0.1.1/src/cs2_gsi/model/round.rs.html); [ESL event types](https://docs.api.prodb.eslgaming.com/2025-03-11/graphql/types/enums/game-event-data-game-action-type)
- **Game state reconstruction treats participants generically:** athlete identity is role plus team plus number, with position over time. — [SoccerNet-GSR](https://arxiv.org/html/2404.11335v1)
- **Structured entity memory works as a precedent:** VideoAgent keeps a per-object table of category, features and segments seen, and counts with queries. — [VideoAgent](https://arxiv.org/pdf/2403.11481v2)
- **Explicit supersession tracking improves current-state answers** (StateMemBench, +15–32 points attributable to structure), and explicit counts fix counting failures (SVCBench oracle). — [StateMemBench](https://arxiv.org/abs/2608.19652); [SVCBench](https://arxiv.org/html/2603.12703v1)
- **Gemini supports MM:SS timestamp references and per-part media resolution.** That lets one request mix cheap context frames with high-resolution anchor crops. — [Gemini video understanding](https://aistudio.google.com/docs/video-understanding); [Gemini media resolution](https://aistudio.google.com/docs/media-resolution)
- **Prompting the structure matters:** LLMs often do not recognize memory structure unless told it. — [StructMemEval](https://arxiv.org/abs/2602.11243)

### Gaps
- The schema and templates below are a synthesis, untested on real Twitch streams. Expected void rates, misread rates and episode-boundary accuracy all need to be measured on recorded fixtures. Under the project's rules, local clips may serve only as test fixtures and never satisfy the Twitch acceptance gate.

### Inferences

#### Verdict
- **Recommend:** stateless VLM observer calls every 6–12 s on Gemma 4 (TPM-bound), a code-owned evidence log and derived state, an episode state machine, and a separate minimal resolver. The resolver runs on two flash-lite models that must agree or the bet is voided, over a bounded evidence packet, and is deterministic for transcript and duration bets.
- **Reject for v1:**
  - per-slice LLM world-state rewriting (quota, drift, poisoning);
  - long-context "watch everything" verification (weak counting and temporal order);
  - the Live API on the critical path. It has unlimited RPD at 65K TPM on this key, but no JSON output, 2-minute audio+video sessions without compression, about 10-minute connections and sliding-window forgetting. Make it a timeboxed spike for a continuous observer that emits observations as function calls, while code keeps owning state;
  - research streaming models (need GPUs and training);
  - agentic retrieval (about +1 point for many calls).

#### Recommended v1 architecture (Python, buildable in hours; one API process plus one worker; SQLite)
1. **Evidence store.**
   - Tables: `frames(ts_ms, path, w, h)`, `asr(t0_ms, t1_ms, text, conf)`, `coverage_gaps`.
   - Keep frames as a ring buffer of about the last 15 min on disk (300–450 JPEGs at 1 frame per 2–3 s). Keep all ASR text.
   - Evidence reference formats: `f:<ts_ms>` for a frame, `a:<t0>-<t1>` for an ASR chunk.
2. **Tier-0 local signals (CPU, every frame):**
   - downscaled difference against a rolling mean;
   - static-screen and near-uniform detection;
   - an ASR cue matcher for boundary words and for every open market's phrase.

   These produce triggers only.
3. **Observer (VLM call, stateless, JSON schema output):**
   - **Model and when it runs:**
     - `gemma-4-26b-a4b-it`, every 6–12 s while an episode is live; the governor adapts cadence to 16K TPM using measured `usage_metadata`.
     - Every 30–60 s when not in a game.
     - Immediately on a local trigger, if TPM headroom allows.
     - `gemma-4-31b-it` adds end-watch bursts every 5–10 s while a market awaits an episode end.
     - Each call carries the newest 1–2 frames plus any frame flagged by local change detection, and a HUD crop at a higher resolution when one is known. All frames stay stored for resolution.
   - **Input:**
     - the compact state snapshot (activity, the current episode with its phase and age, participants, quantity definitions with last value and age);
     - the open markets' needs (which quantities and phrases matter);
     - the new frames, each preceded by its timestamp as text;
     - the ASR text since the last call;
     - generic instructions with the screen-type taxonomy and the boundary cue catalogue.
   - **Output** (the observation schema below): screen type, episode signal, a visible outcome if any, participant and side updates, quantity readings (verbatim display plus parsed value plus a legibility flag plus a frame ID), notable events, proposal candidates, and uncertainties.
   - **Instructions:** "report only what is visible or audible in this input; cite IDs; say unknown otherwise".
4. **Reducer (code, single writer):**
   - Validate the schema and evidence IDs; reject readings that cite frames outside the input.
   - Apply consistency rules: monotonic timers within a live episode, small score steps, and at least two agreeing readings before a quantity counts as confirmed.
   - Run the episode state machine with hysteresis, including `ended_unknown`.
   - Append to `observations`, `quantity_reads` and `events`.
   - Never accept free-text "memory" from the model.
5. **Proposer (in code, fed by the observer's proposal candidates):**
   - Accept a candidate only if:
     - the episode is `live` and early;
     - the template is one of the four allowed;
     - for quantity bets, the quantity has had at least 2 legible readings in this episode (which proves this stream's layout shows it), and the threshold is not already decided by the current value and remaining time.
   - The backend sets the lock deadline in media time with a margin for Twitch delay, then freezes the resolution spec.
   - Approval mode lets the operator confirm proposals.
6. **Resolver:**
   - **Utterance bets:** whole-word, case-insensitive search of ASR text within `[episode.start_ts, episode.end_ts]`, merging adjacent chunks so a word split across two chunks is still found.
     - A YES needs one hit.
     - A NO also requires that ASR has no coverage gap in the window; otherwise void.
     - The market text should say "appears in the stream-audio transcript", because ASR does not identify who is speaking.
   - **Duration bets:** compare timestamps from a confirmed start and end; void if either is unconfirmed.
   - **Outcome and quantity bets:**
     - Wait for the episode to end plus a grace window of 10–30 s (Twitch bursts arrive late).
     - Build a packet: frames from `[end−20 s, end+20 s]`, high-resolution anchor frames or crops, the ASR excerpt, and quantity readings near the anchor.
     - Make one fresh resolver call on `gemini-3.5-flash-lite` that returns `{yes|no|void, evidence_ids, verbatim_reading, reason}`, and an independent call on `gemini-3.1-flash-lite`. They must agree, or the bet is voided.
     - Code gates: the evidence must be inside the window; numeric readings must agree with the observer's anchor readings or with a second resolver call.
     - Otherwise void. Operator approval stays available.
7. **Budget governor:**
   - Per-model RPM, TPM and RPD buckets seeded with the verified quotas:
     - Gemma 4 26B and 31B: 30 / 16K / 14.4K each;
     - 3.5 and 3.1 flash-lite: 15 / 250K / 500 each;
     - 2.5 models: 20 RPD.
   - Track actual tokens from `usage_metadata`, not estimates.
   - Priority order: resolution, then end-watch, then boundary confirmation, then heartbeat, then proposals.
   - On a 429 or a low bucket, slow the tracker first. Never borrow the resolver quota for tracking.
   - When the budget is low, stop proposing new markets. Void rather than guess if a market cannot be resolved within budget.
   - Model IDs and quotas belong in config, because names and limits have been shifting.

#### Generic state schema (`state.v1`; mutated only by backend code)
```jsonc
{
  "schema_version": "state.v1",
  "stream": {
    "stream_session_id": "twitch:<channel>:<broadcast_start>",
    "clock": "media_ms",                       // all *_ts fields are media time
    "last_frame_ts": 0, "last_asr_ts": 0,
    "coverage_gaps": [{"from_ts": 0, "to_ts": 0, "kind": "frames|asr|both"}]
  },
  "activity": {
    "kind": "game|non_game|unknown",
    "title":  {"value": "Peggle", "conf": 0.8, "read_at_ts": 0, "ev": ["f:..."]},
    "format": {"value": "single-player level", "conf": 0.6, "read_at_ts": 0, "ev": ["f:..."]}
  },
  "episodes": {
    "current_id": "ep_12",
    "items": [{
      "episode_id": "ep_12", "parent_id": null,
      "level_label": "game|match|round|level|run|hand|set|<free text>",
      "phase": "pending|live|ending|ended|ended_unknown|aborted",
      "start_ts": 0, "start_cue": "clocks reset to 3:00/3:00", "start_ev": ["f:..."],
      "end_ts": null, "end_cue": null, "end_ev": [],
      "outcome": {"status": "unknown|observed|ambiguous",
                  "for": "p_streamer|side:<id>",
                  "result": "win|loss|draw|clear|fail|finish|abandon|other|null",
                  "verbatim": null, "ev": []}
    }]
  },
  "participants": [
    {"pid": "p_streamer", "role": "self", "label": "streamer",
     "side": {"value": "black|T|P1|<free text>|null", "conf": 0.0, "read_at_ts": 0, "ev": []}},
    {"pid": "p_2", "role": "opponent|teammate|team|side|npc|environment|unknown",
     "label": "opponent", "display_name": {"value": null, "read_at_ts": 0, "ev": []}}
  ],
  "quantities": [{
    "qid": "q_clock_streamer", "name": "chess clock", "owner": "p_streamer",
    "kind": "timer_down|timer_up|counter|score|resource|percent|other",
    "unit": "seconds|count|points|hp|percent|money|unitless",
    "screen_hint": "clock next to the streamer's name, bottom right",
    "last": {"value": 83, "display": "1:23", "legible": true,
             "read_at_ts": 0, "source": "llm|ocr", "ev": ["f:..."]},
    "reads": [[0, 95], [0, 89], [0, 83]],      // bounded, per episode
    "rules": {"monotonic": "non_increasing_while_live", "min": 0, "max": null},
    "stale_after_s": 30
  }],
  "events": [{"eid": "e_301", "episode_id": "ep_12", "ts": 0, "type": "<free text>",
              "summary": "bomb planted", "actors": ["side:T"], "source": "llm|asr|rule",
              "conf": 0.6, "ev": ["f:...", "a:..."]}],   // ring buffer (e.g., last 50); never used to count
  "open_questions": [{"text": "Which side is the streamer on?", "since_ts": 0,
                      "blocks": ["template:quantity_at_anchor"]}],
  "markets": [{"market_id": "m_7", "episode_id": "ep_12", "state": "open|locked|resolving|resolved|void",
               "lock_ts": 0, "resolution_spec": {"$ref": "resolution_spec.v1"}}]
}
```

#### Observer output (`observation.v1`; validated, then applied by the reducer)
```jsonc
{
  "screen_type": "gameplay|menu|lobby|loading|result|scoreboard|replay|cutscene|non_game|unknown",
  "activity_guess": {"title": "...", "conf": 0.0, "ev": ["f:..."]},
  "episode_signal": {"signal": "none|start|end|continue|unknown", "level_label": "round",
                     "cue": "banner 'Counter-Terrorists Win'", "ev": ["f:..."]},
  "outcome_seen": {"for": "p_streamer|side:CT|unknown", "result": "win|loss|...", "verbatim": "...", "ev": ["f:..."]},
  "participants": [{"pid": "p_streamer|new", "role": "...", "side": "...", "ev": ["f:..."]}],
  "quantity_reads": [{"qid": "q_clock_streamer|new", "name": "...", "owner": "...", "display": "0:47",
                      "value": 47, "unit": "seconds", "legible": true, "ev": ["f:..."]}],
  "events": [{"type": "...", "summary": "...", "ev": ["f:...|a:..."]}],
  "proposal_candidates": [{"template": "...", "params": {}}],
  "uncertain": ["cannot tell which clock belongs to the streamer"]
}
```

#### Allowed proposition templates and frozen `resolution_spec.v1`
| Template | Example | Resolving evidence | Void when |
|---|---|---|---|
| `episode_outcome` | "Will the streamer win this game?" / "...clear this Peggle level?" | A result banner or outcome read in `[end−20 s, end+20 s]` | `ended_unknown`, ambiguous result, outcome semantics unclear (e.g., no win/loss concept), coverage gap |
| `quantity_at_anchor` | "More than 1:00 on the streamer's clock when the game ends?" / "At least 3 Terrorists alive when the round ends?" | Legible readings of the named quantity at the anchor; two must agree; display string quoted | Unreadable, readings disagree, anchor in a coverage gap, side mapping unknown |
| `utterance_in_window` | "Will the word 'rush' appear in the stream-audio transcript during this match?" | Deterministic ASR search over the episode window | NO only if ASR coverage of the window is complete; else void |
| `episode_duration` | "Will this round last longer than 1:30?" | Confirmed start and end timestamps | Either boundary unconfirmed |

```jsonc
{
  "template": "quantity_at_anchor",
  "episode_id": "ep_12", "subject": "p_streamer",
  "quantity": {"qid": "q_clock_streamer", "name": "chess clock", "unit": "seconds", "screen_hint": "..."},
  "comparator": ">", "threshold": 60,
  "anchor": {"event": "episode_end", "window_s": [-10, 5]},
  "phrase": null, "match": "whole_word_case_insensitive",
  "evidence_rule": ">=2 agreeing legible reads in anchor window, or 1 read + resolver agreement",
  "void_if": ["episode ended_unknown", "coverage gap overlaps window", "reads disagree", "no legible read", "budget exhausted"],
  "resolve_by": {"event": "episode_end", "plus_s": 120},
  "proposed_at_ts": 0, "lock_ts": 0, "spec_version": "resolution_spec.v1"
}
```
Note: with frames every 2–10 s, the "≥2 agreeing reads" rule may be unachievable for an end-of-round moment. In that case, take one high-resolution anchor read plus the resolver's agreement, or void.

#### How the schema maps to the example formats
- **Chess:**
  - Episode = a game.
  - Participants: the streamer (side black or white, read from the board orientation or name placement) and the opponent.
  - Quantities: both clocks (`timer_down`).
  - Outcome: banner verbatim (for example "Black wins by resignation", "1-0").
- **CS2:**
  - Episodes: a match containing rounds (`parent_id`).
  - Participants: sides T and CT, with the streamer's side.
  - Quantities: round timer, team scores, and alive count per side, if the HUD shows it.
  - Outcome: round-win banner.
- **Peggle:**
  - Episode = a level.
  - Participants: the streamer only (role self) and the environment.
  - Quantities: balls left, orange pegs left, score.
  - Outcome: clear or fail.
- **Fighting game:** episodes are sets or games containing rounds; quantities are health and the round timer.
- **Speedrun:** episode = a run; quantities are the run timer and split; outcomes are finish or reset (reset maps to abandon, so outcome bets are voided).
- **Card games:** episode = a game or hand; quantities include life or health totals; outcome comes from the victory or defeat screen.

#### Improvements with more time
1. **Local OCR on CPU** for numeric HUD fields. Discover HUD regions automatically from per-pixel temporal variance, then read the crops every frame, giving a second opinion for free and fewer VLM calls.
2. **A periodic auditor call** that checks derived state against fresh frames (in the style of Guidance Gemini), for example on `gemma-4-31b-it` every 5–10 min. The cross-model "agree or void" resolver has moved into v1, now that the two flash-lite quotas are separate.
3. **Short-clip verification through Gemini static video** (ffmpeg-packed MP4, `fps` set, clip offsets, MM:SS) for anchors where motion matters. Agentic mode only for windows over about 5 min.
4. **Zero-shot change-point detection** (Kernel Temporal Segmentation on SigLIP/CLIP embeddings) on the 8-vCPU VM, plus speaker diarization so utterance bets can name the streamer.
5. **A labeled fixture suite** (recorded streams with hand-labeled boundaries and outcomes) to measure void rate, wrong-resolution rate and boundary F1 before any automatic settlement. Prompt and threshold changes would be gated on these metrics.
6. **Episode hierarchy across levels** (a match bet spanning rounds), and a confidence-calibrated proposer that picks thresholds near the median of plausible outcomes.
7. **A Live API continuous observer** (Gemini 3 Flash Live or 3.8 Live; unlimited RPD at 65K TPM on this key):
   - push the sampled frames at 0.5–1 fps plus ASR text;
   - probe every 5–10 s;
   - receive observations as `report_observation` function calls;
   - handle resumption about every 10 min;
   - keep code as the state owner, because the sliding-window context forgets.

   Promote it over the Gemma tracker only if a timeboxed spike shows reliable structured output and better HUD reading.
