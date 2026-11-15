# Outcome verification for game-agnostic live-stream prop bets (evidence, abstention, evaluation)

_Desk research compiled 2026-11-15 using web search and fetch only. No LLM or paid API was called. Each source's date is given inline. Items marked "(canonical; not re-fetched)" are well-known papers cited at their canonical arXiv or reference pages without being opened in this session. Most benchmark numbers describe 2025-era models (Gemini 2.x/2.5, GPT-4o/4.1, o4-mini, GPT-5, Claude 4.x). I found no published measurements of November-2026 free-tier models on 480p game HUDs, so every capability claim below must be re-measured on the project's own Twitch-ingested recordings. A coordinator-verified free-tier quota (gemini-3.5-flash-lite: 15 RPM, 250K TPM, 500 requests/day) shapes the budget recommendations in sections 7–8._

## 1. How accurately do current multimodal LLMs read game UIs (text, timers, scores, icon counts, result screens), and how do they fail?

### Takeaway
Reading large, high-contrast words (menus and result banners such as "Victory" or "Checkmate") is the strongest measured capability. Most other reads the resolver might want are weak and fail silently: small or degraded HUD text, progress bars, minimaps and tables, icon counts, analog dials, and identifying *which frame* an event occurred in. Models tend to fall back on language priors instead of reporting "unreadable". Design propositions around outcome words printed on screen and comparisons done in code. Treat counts and temporal judgments by the model as unreliable.

### Cited Findings
**Game-specific: VideoGameQA-Bench (arXiv May 2025; NeurIPS 2025 Datasets & Benchmarks)**
- Scale: 9 tasks, 4,786 questions, 2,236 image and 1,200 video samples from 800+ games — [arXiv](https://arxiv.org/html/2505.15952v2); [NeurIPS](https://proceedings.neurips.cc/paper_files/paper/2025/hash/db2cf8f479a96cb83329f5e193318a29-Abstract-Datasets_and_Benchmarks_Track.html).
- Models: 11 proprietary and 5 open-weight models were evaluated (secondary summary) — [The Moonlight](https://www.themoonlight.io/review/videogameqa-bench-evaluating-vision-language-models-for-video-game-quality-assurance).
- UI unit tests (questions about interface elements) were harder than scene ("visual") unit tests. Gemini-2.5-Pro scored 40.0% on UI vs 53.0% on visual; GPT-4.1 scored 28.0% vs 43.0% — [arXiv](https://arxiv.org/html/2505.15952v2).
- Models handled plain text and simple game menus reasonably well. Performance dropped on large tables, progress bars and minimaps — [arXiv](https://arxiv.org/html/2505.15952v2).
- Counting and object-direction answers were inconsistent even on simple questions. Errors were worse when the property was small or visually ambiguous, but they also occurred in clear scenes — [arXiv](https://arxiv.org/html/2505.15952v2).
- Temporal localization was poor:
  - GPT-4.1 detected the glitch in 72 of 100 videos but found the correct frame in only 19 of those (26.5%).
  - The best needle-in-a-haystack score (event located within a 5 s margin) was 36.0%, by Gemini-2.0-Flash.
  - [arXiv](https://arxiv.org/html/2505.15952v2)
- Hallucinated positives (reporting clipping that is not there) were the most common false positives, and GPT-4o frequently refused video queries — [arXiv](https://arxiv.org/html/2505.15952v2).
- Video input:
  - Only Gemini models received native video. Others received frames: 1 fps for proprietary models, 5–10 frames per video for open models.
  - The authors name loss of temporal context and audio under frame sampling as a major limitation.
  - A manual check found 95% of glitches still visible at 1 fps.
  - [arXiv](https://arxiv.org/html/2505.15952v2)
- Best scores on other tasks: image glitch detection 82.8% (GPT-4o), video glitch detection 78.1% (Gemini-2.5-Pro), visual regression 45.2% (o4-mini) — [arXiv](https://arxiv.org/html/2505.15952v2).

**OCR in general**
- OCRBench v2 (arXiv Jan 2025; NeurIPS 2025 D&B) — [arXiv](https://arxiv.org/pdf/2501.00321); [NeurIPS](https://proceedings.neurips.cc/paper_files/paper/2025/hash/8c2e6bb15be1894b8fb4e0f9bcad1739-Abstract-Datasets_and_Benchmarks_Track.html):
  - It has 31 scenarios and 10,000 human-verified QA pairs.
  - In the original evaluation, 36 of 38 models scored below 50/100.
  - Text recognition scores were generally higher than parsing and localization scores.
- An aggregator snapshot lists a top English OCRBench v2 score of 70.7 (Qwen3.7 Plus) and parsing scores often below 41. It also notes that models strong at recognition can still fail reasoning tasks. Snapshot dates are mixed and I did not verify it against the official leaderboard — [BenchmarkList](https://benchmarklist.com/benchmarks/ocrbench_v2_en/).
- KIE-HVQA, from "Seeing is Believing? Mitigating OCR Hallucinations in MLLMs" (arXiv Jun 2025; NeurIPS 2025) — [arXiv](https://arxiv.org/html/2506.20168v2); [NeurIPS poster](https://neurips.cc/virtual/2025/poster/117155):
  - Under blur, occlusion, glare or low contrast, MLLMs fall back on language priors (OCR hallucination) instead of refusing or hedging on unreadable regions.
  - The authors' RL-trained 7B model reports about a 28% absolute gain in hallucination-free accuracy over GPT-4o. One third-party summary gives 22% instead.

**Counting**
- CountQA (arXiv Aug 2025) has 1,500+ real-world counting questions with clutter and occlusion. The best of 15 MLLMs reached 42.9%, and accuracy fell as the counts rose — [arXiv](https://arxiv.org/abs/2508.06585v1); [Google Research](https://research.google/pubs/pub1042117/).
- VLMCountBench (arXiv Oct 2025): counting was reliable with a single shape type but failed substantially when several shape types were combined (1–20 objects per type) — [arXiv](https://arxiv.org/abs/2510.04401v1).
- "[De|Re]constructing VLMs' Reasoning in Counting" (arXiv Oct 2025): seven VLMs were highly sensitive to object number and type, spatial arrangement and distractors — [arXiv](https://arxiv.org/abs/2510.19555v1).

**Clocks**
- ClockBench (Sep 2025) — [The Decoder](https://the-decoder.com/even-the-best-ai-models-cant-reliably-read-the-clock/); [OfficeChai](https://officechai.com/ai/theres-now-a-benchmark-that-assesses-ai-models-on-their-ability-to-read-analog-clocks):
  - It asks 720 questions about 180 analog clocks.
  - Humans scored 89.1%. The best model, Gemini 2.5 Pro, scored 13.3%; GPT-5 8.4%, Claude 4.1 Opus 5.6%, Grok 4 0.7%.
  - Model misses were often 1–3 hours off.
  - When a model read the clock correctly, its follow-up time arithmetic was fine, so the bottleneck is perception.

**Temporal reasoning over frames**
- Vinoground (arXiv Oct 2024) uses minimal caption pairs that differ only in event order. Most models scored at random chance on its video score — [arXiv](https://arxiv.org/html/2410.02763v1).
- TIME / TIMEBench (arXiv Mar 2025) filters out questions answerable from a single frame. Even advanced video-LLMs scored close to random baselines on the remaining temporal questions (per summary) — [arXiv](https://arxiv.org/html/2503.09994v1); [AlphaXiv](https://alphaxiv.org/benchmarks/harbin-institute-of-technology/timebench).
- VECTOR (arXiv Dec 2025): video LLMs often fail to identify the order of events — [arXiv](https://arxiv.org/abs/2512.08979v1).
- TVBench (2024; summary updated Nov 2025): only Tarsier-34B and Gemini 1.5 Pro exceeded random by more than 20 points (secondary summary) — [Emergent Mind](https://api.emergentmind.com/topics/tvbench).

### Inferences
- **Result banners are the safest read.** A result banner is a large-text recognition problem, which is the best-measured sub-skill in both OCRBench v2 and VideoGameQA-Bench. Prefer propositions whose outcome the game prints in words.
- **Digital timers and scores need extra gates.** They are OCR problems, not ClockBench's analog-dial problem. But at 854x480 after JPEG compression, small HUD digits become "degraded text", where KIE-HVQA shows models guess rather than abstain. Gate them with a region crop and upscale, two agreeing reads, and a comparison done in code. ClockBench suggests arithmetic is not the weak point, but code is free and deterministic.
- **Counting small HUD icons is not automatically resolvable.** Examples are CS2 alive-player avatars, HP pips and cards in hand. They combine the two weakest measured skills: counting and small elements.
- **Ask about one frame at a time.** Never ask the model "when did X happen" or "which came first" across a frame sequence. Ask what each frame ID shows and let code order observations by media timestamp. If several frames share one request, key outputs by frame ID; weak temporal grounding suggests cross-frame mix-ups are possible.
- **No answer means no evidence.** A refusal, invalid JSON or "unreadable" maps to "no evidence" (keep WAITing). It never maps to NO.
- **Measure the chosen model yourself.** The likely workhorse is gemini-3.5-flash-lite, the only model with a usable free quota per the coordinator. I found no OCR, counting or game-UI numbers for it. A Lite-tier model may be weaker than the larger models measured above, though newer generations may be stronger. Neither direction is verified, so only the project's own labeled evaluation (section 7) gives a usable number.

### Gaps
- I found no benchmark of reading digital game timers, scoreboards or alive-player icons at 480p, and none comparing a cropped, upscaled region against full-frame input.
- I found no November-2026 numbers for current free-tier hosted models on any of these tasks.
- One secondary ClockBench report gives a conflicting 40.5% for Gemini 2.5 Pro with an unclear metric. I could not trace it to a source, so the 13.3% headline is used.

## 2. How reliable is ASR keyword spotting for "will the streamer say X" bets?

### Takeaway
Whisper hallucinates often on non-speech audio, but the hallucinations concentrate in a small repertoire of recurring outputs, so a specific rare target word is unlikely to be invented at random. The larger risks are:
- biasing the decoder by putting the keyword in its prompt or hotwords;
- near-homophones;
- the word being spoken by someone other than the streamer;
- false negatives from noise and chunk boundaries.

Recommended handling:
- Use exact normalized matching against a word-form list frozen at proposal time.
- Confirm every YES hit by re-transcribing the surrounding audio locally.
- Allow NO only when transcript coverage of the whole window is proven complete.
- Never make the decision with LLM judgment or fuzzy matching.

### Cited Findings
- Careless Whisper (arXiv Feb 2024; experiments in 2023) — [arXiv](https://arxiv.org/html/2402.08021v2):
  - About 1% of transcriptions contained entire hallucinated phrases or sentences that were not in the audio in any form.
  - 38% of the hallucinations included explicit harms.
  - Hallucinations were associated with longer non-vocal durations.
- Barański et al. (arXiv Jan 2025; ICASSP 2025) tested Whisper large-v3 on non-speech audio from AudioSet, MUSAN, UrbanSound8K and FSD50K — [arXiv](https://arxiv.org/abs/2501.11378):
  - 121,378 of 301,317 inferences (40.3%) hallucinated text, and 9.1% of those looped.
  - Of 41,231 unique outputs, the 1,270 that recur account for 67.08% of hallucinations.
  - The same file hallucinates differently when cut to different lengths.
  - A "Bag of Hallucinations" post-filter (a list of frequent hallucinated outputs) reduced WER.
- Gating ASR with voice-activity detection keeps silence and non-speech away from the recognizer, which removes the most common hallucination trigger (vendor explainer; secondary) — [Soniox](https://soniox.com/wiki/asr-hallucinations).
- Noise-agnostic multitask Whisper (arXiv Jan 2025): a deployed open-vocabulary Whisper "call for help" detector produced more false alarms in real conditions, which the authors attribute to microphone and environmental noise. A noise-classification head reduced them — [arXiv](https://arxiv.org/html/2501.11631v1).
- Massive Open-Vocabulary KWS (arXiv Jun 2026): Whisper prompt conditioning with large, uncurated keyword lists is fragile, sensitive to spurious matches, and degraded ASR on the authors' corpus — [arXiv](https://arxiv.org/pdf/2606.11279).

### Inferences
- **Keep the authoritative transcript unprimed.** Do not put the target word into Whisper's initial prompt or hotwords. That conditioning is the mechanism the June 2026 paper found produces spurious matches. If priming is wanted for recall, use the primed pass only as a trigger and confirm on an unprimed pass.
- **Matching is code, not an LLM.**
  - Normalize the transcript: case-fold, strip punctuation, match on word boundaries.
  - Match against a list of accepted surface forms frozen at proposal time, for example `rush, rushes, rushed, rushing`.
  - Do not use an LLM judge for the match. It may accept near-synonyms, injected speech can steer it, and it spends a scarce hosted request.
  - Use fuzzy or phonetic matching only to queue a confirmation. It collides with real near-words such as "brush" and "crush".
- **Confirm YES hits locally ($0 hosted cost).**
  - Re-transcribe a window of roughly 10–20 s centered on the hit, with different segmentation and decoding: no prompt, beam search, word timestamps, and a larger local model if CPU time allows.
  - Require the word to appear again, inside a VAD-detected speech region.
  - Barański found that segmentation changes Whisper's output, which makes a differently segmented pass a meaningful independence check.
- **Chunk boundaries.** With chunks of about 4 s, a word can be split across two chunks. Match on concatenated adjacent chunks or on overlapping windows to limit false negatives.
- **Attribution is unverifiable from one mixed audio track.** The transcript also captures teammates on voice chat, game voice lines, text-to-speech donations and videos played on stream. Without diarization, word the criterion as "the word is audible on stream (any speaker)", or send "the streamer said" bets to human approval.
- **Disallow some target words:**
  - words appearing in known recurring hallucinations (check the paper's Bag-of-Hallucinations list);
  - very short or function words;
  - words the game or teammates say routinely. Domain knowledge, unsourced: "rush" is a standard Counter-Strike callout, so teammate hits are likely.
- **YES and NO are asymmetric.**
  - YES needs one confirmed hit inside the interval from lock to window end.
  - NO is an absence claim. It needs the window to have ended plus proof that every speech region in it was transcribed: no missing HLS segments and no dropped ASR chunks. Otherwise the market is UNRESOLVABLE.
- **Integrity.** The streamer fully controls "say X" outcomes. That is acceptable with test money, but the demo should not present these as skill bets.

### Gaps
- I found no measured false-positive or false-negative rates for Whisper-family keyword spotting on game-stream audio (game sound effects, music, voice comms).
- I found no homophone-confusion rates for specific target words.
- I did not inspect the exact contents of the Bag-of-Hallucinations list.

## 3. Which verification patterns reduce false settlements?

### Takeaway
The evidence supports combining these patterns:
1. Freeze a machine-checkable resolution spec at lock.
2. Have the model only *extract* per frame: verbatim text, raw values and flags.
3. Let deterministic code apply the rule.
4. Require a decisive terminal cue, seen after lock in at least two frames or reads, with matching identity anchors.
5. Require positive evidence for the losing side too. A visual bet never resolves NO because a YES cue is absent.
6. Use speech only as corroboration.
7. Keep explicit WAIT / YES / NO / UNRESOLVABLE states, with a hard deadline that voids.

Prediction-market disputes show that ambiguous wording and post-lock reinterpretation, not reading errors, cause most controversy. When in doubt, void rather than reinterpret.

### Cited Findings
- MLLM-as-a-Judge (arXiv Feb 2024; ICML 2024): multimodal judges showed egocentric, position and length biases, hallucinations and inconsistent judgments. Pairwise comparisons came closer to human agreement than batch rankings (secondary summary) — [arXiv](https://arxiv.org/pdf/2402.04788); [AlphaXiv overview](https://alphaxiv.org/overview/2402.04788v3).
- JudgeAnything (arXiv Mar 2025): judge alignment with humans degraded for video and audio tasks (secondary summary) — [The Moonlight](https://www.themoonlight.io/review/judge-anything-mllm-as-a-judge-across-any-modality).
- MM-JudgeBias (ACL 2026) evaluated 26 MLLM judges on nine compositional bias types, using controlled perturbations of query, image and response — [ACL Anthology](https://aclanthology.org/2026.acl-long.1162.pdf).
- Text LLM judges such as GPT-4 reached over 80% agreement with humans, about the human-to-human level, but showed position, verbosity and self-enhancement biases (Zheng et al., arXiv Jun 2023; canonical, not re-fetched) — [arXiv](https://arxiv.org/abs/2306.05685).
- Semantic entropy (Nature, Jun 2024) — [OATML](https://oatml.cs.ox.ac.uk/publications/202406_FarquharKossenKuhn_HallucinatingLLMs.html); [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC11186750):
  - Method: sample several answers, cluster them by meaning, and treat high entropy as a confabulation flag.
  - It needs no task-specific data.
  - The authors note it targets one error class (confabulation), not every kind of error — [Oxford CS](https://www.cs.ox.ac.uk/news/2345-full.html); [Axios](https://www.axios.com/2024/06/21/ai-chatbots-uncertainty-hallucinations-detection).
- Self-consistency: a majority vote over several sampled reasoning paths improves accuracy (Wang et al., arXiv Mar 2022; canonical, not re-fetched) — [arXiv](https://arxiv.org/abs/2203.11171).
- Product analog, Twitch Predictions:
  - A LOCKED prediction must still be resolved with a winning outcome or CANCELED, and CANCELED returns everyone's points — [Twitch API docs](https://dev.twitch.tv/docs/api/predictions).
  - A prediction cannot be canceled after it has been resolved and points paid out — [Twitch Predictions Terms](https://legal.twitch.com/legal/predictions-terms-and-conditions).
  - Unresolved predictions were automatically refunded after 24 h (Nov 2020 report; current policy not verified) — [Tubefilter](https://www.tubefilter.com/2020/11/13/twitch-launches-predictions-feature-channel-points/amp/).
- Prediction-market dispute cases:
  - Jun 2024: Polymarket publicly contradicted UMA's resolution of its Barron Trump/DJT market — [The Block](https://www.theblock.co/post/302171/polymarket-contradicts-umas-resolution-on-barron-trumps-involvement-with-djt-token).
  - Mar 2025: a large UMA token holder allegedly swung the resolution of a Ukraine minerals-deal market. Polymarket called it unprecedented and refused refunds — [The Block](https://www.theblock.co/news/ecosystems/2025-03-26-polymarket-says-governance-attack-by-uma-whale-to-hijack-a-bets-resolution-is-unprecedented-348171); [Web3 Is Going Great](https://web3isgoinggreat.com/single/polymarket-governance-attack).
  - 2025: a roughly $237M market on whether Zelenskyy would wear a suit resolved "No" amid controversy — [Decrypt](https://decrypt.co/329210/polymarket-rules-no-237m-controversial-bet-over-zelenskyys-suit?amp=1).
  - 2026: a MicroStrategy Bitcoin-sale market was disputed after a late rules clarification tied resolution to when a sale was confirmed rather than when it happened. It went to a UMA vote. This comes from crypto-press reports, which give conflicting market sizes — [DeFi Rate](https://defirate.com/news/polymarket-trader-loses-500k-loss-after-rules-change-microstrategy-btc-market/); [Blockport](https://blockport.io/latest-news/polymarket-150m-bitcoin-sale-dispute-uma-vote/).

### Inferences
- **Extract-then-decide is the core pattern.**
  - The model returns per-frame JSON: verbatim on-screen strings, the raw digit string of each named field, and booleans such as `game_screen_visible`, `replay_or_killcam_indicator` and `unreadable`.
  - The model is never asked "did YES win?"
  - Code normalizes the strings, matches them against the spec's frozen YES, NO and VOID literals, parses numbers and applies the comparator.
  - This takes judge biases out of the decision, makes the rule unit-testable, and keeps model output away from settlement authority (see section 6).
- **Independent reads.**
  - Prefer two *different* frames of a persistent terminal screen, for example the first cue frame and one 2–6 s later, over two samples of the same image. Errors on the same pixels are likely correlated. This is an inference: semantic entropy and self-consistency show the value of agreement, not of independence.
  - Require 2-of-2 agreement for automatic settlement. On disagreement, WAIT for more frames; if reads still disagree at the deadline, void.
  - Use low temperature.
  - Agreement filters confabulation but not consistent errors.
- **Positive decisive cue on both sides.** A visual bet resolves NO only on a positive NO cue: "Defeat", "Black wins", or the opposing team's win banner. Only speech NO is absence-based, and it requires coverage proof.
- **Cross-modal checks.** Streamer speech ("gg", "I lost") may trigger an extraction call or corroborate a result. It never decides one. If speech contradicts the screen, escalate or void.
- **Temporal grounding in code.**
  - Record the lock time (t_lock), the last frame showing the game in progress (t_prev), and the first terminal cue (t_end).
  - Require t_lock < t_prev < t_end.
  - This proves the outcome was not visible at lock and that the cue belongs to this event.
- **Freeze the spec at lock and never clarify it afterward.** The MicroStrategy case shows post-hoc clarification generates disputes. If the spec cannot be applied as written (draw, abort, remake or disconnect not covered), void, just as a Twitch prediction is canceled.
- **Approval mode.** The supervised-mode output is a *proposed* outcome plus an evidence bundle a human can check in seconds: frame thumbnails, media timestamps, verbatim reads and the transcript snippet.

### Gaps
- I found no published evaluation of LLM- or VLM-resolved betting on live video. The recommendations above extrapolate from benchmarks, judge-reliability studies and prediction-market practice.
- I found no quantitative evidence on how much two-frame agreement reduces VLM misreads of game text.

## 4. Does verification need state tracking over time, or is a short window around the end enough?

### Takeaway
Every market needs a thin, *code-side* tracker of:
- lock time;
- identity anchors;
- last in-progress frame;
- first terminal cue;
- ingest coverage.

The deciding *value*, however, should be read from a short window at or after the terminal cue, ideally a frozen final display. A model should not infer it from a long frame sequence. Propositions that depend on long-horizon state are the riskiest, because they need complete coverage. Examples: "did X ever happen this match", speech NO, cumulative counts.

### Cited Findings
- Event-order and temporal reasoning is at or near chance for many video LLMs: [Vinoground](https://arxiv.org/html/2410.02763v1) (Oct 2024), [TIME](https://arxiv.org/html/2503.09994v1) (Mar 2025), [VECTOR](https://arxiv.org/abs/2512.08979v1) (Dec 2025), and [TVBench](https://api.emergentmind.com/topics/tvbench) (secondary).
- On game video, GPT-4.1 found the correct frame for only 26.5% of the glitches it detected, and the best model placed an event within a 5 s margin only 36.0% of the time — [VideoGameQA-Bench](https://arxiv.org/html/2505.15952v2).
- Frame sampling loses temporal context and audio. Even so, 1 fps kept 95% of glitches visible in that benchmark; this project's 0.1–0.5 fps is 2–10 times sparser — [VideoGameQA-Bench](https://arxiv.org/html/2505.15952v2).
- How the audio is segmented changes Whisper's output — [Barański et al.](https://arxiv.org/abs/2501.11378).

### Inferences
- **A short window suffices** when the game leaves a persistent decisive screen:
  - chess result modals;
  - fighting-game win screens;
  - card-game victory or defeat screens;
  - round-win banners plus the score increment;
  - speedrun timers that freeze on the final split;
  - speech YES (the window around the confirmed hit).
- **State tracking is required for:**
  - (a) Anti-replay and identity: the anchors seen at lock (opponent name, map, round number, scoreline) must match at t_end.
  - (b) Detecting an outcome already decided at lock.
  - (c) Transient end cues, where the end is inferred from a state change, such as a new round starting, and the outcome is read from the scoreline.
  - (d) Speech NO, which needs coverage of the whole window.
  - (e) "At end" values the game does not keep on screen after the end.
- **Last-known values are not safe bounds unless the quantity is provably monotone.** Domain knowledge, unsourced: chess clocks with increment can *increase*. A 1:30 reading before the end does not prove the final clock exceeds 1:00, and a 0:45 reading proves it is under 1:00 only when there is no increment. Game-agnostic code cannot know monotonicity, so the v1 rule is: decide only from a direct read of the final displayed value at or after the terminal cue; otherwise void.
- **Precise-moment ambiguity** (domain knowledge, unsourced). In CS2, players can still die in the post-round period after the win banner appears, so "alive at the end of the round" needs a defined instant. Every "state at moment M" bet needs M defined by an observable cue.
- **Adaptive sampling is free; hosted calls are not.**
  - Decode frames locally at a higher rate (for example 1–2 fps) when the end looks near: the clock is low, a perceptual-hash jump signals a scene change, or ASR hears "gg" or "checkmate".
  - Run free local filters on those frames.
  - Send only the 1–3 best candidate frames to the hosted model.
- **Use media timestamps** (HLS segment or program time), not wall-clock time, to order lock and evidence. Twitch delivers media late and in bursts, and some streamers add deliberate delay. Whether Twitch playlists expose `EXT-X-PROGRAM-DATE-TIME` is unverified here and should be checked during ingest work.

### Gaps
- I found no data on how long result screens persist across games, or on how often streamers skip them instantly. Both determine the miss rate at 2–10 s sampling.

## 5. How should proposition types be ranked by verifiability? Which should be disallowed, and which need the proposer to name its evidence?

### Takeaway
Rank propositions on three questions:
- Does the game *print* the outcome as large text on a persistent screen?
- Is the decisive moment marked by an observable cue?
- Is the deciding read text recognition (good), or counting, spatial or temporal reasoning (bad)?

Every proposal should carry a machine-checkable resolution spec that names its evidence. Tier-2 types should open only if a pre-lock readability check succeeds on the live stream. This keeps the restriction "as loose as the evidence allows", per stream, without game-specific code.

### Cited Findings
- On game frames, plain text and simple menus are read reasonably well; tables, progress bars and minimaps are not. Counting is inconsistent, small or ambiguous elements are worst, and spatial orientation and posture questions fail — [VideoGameQA-Bench](https://arxiv.org/html/2505.15952v2).
- Recognition is the strongest OCR sub-skill; parsing and localization are weaker — [OCRBench v2](https://arxiv.org/pdf/2501.00321).
- Degraded text produces confident hallucination rather than refusal — [KIE-HVQA](https://arxiv.org/html/2506.20168v2).
- In-the-wild counting reaches 42.9% at best — [CountQA](https://arxiv.org/abs/2508.06585v1). It breaks down when object types are mixed — [VLMCountBench](https://arxiv.org/abs/2510.04401v1).
- The best model reads analog dials 13.3% of the time — [ClockBench via The Decoder](https://the-decoder.com/even-the-best-ai-models-cant-reliably-read-the-clock/).
- Event ordering is near chance — [Vinoground](https://arxiv.org/html/2410.02763v1); [VECTOR](https://arxiv.org/abs/2512.08979v1).
- Ambiguous wording and post-hoc clarification drive market disputes — [Decrypt](https://decrypt.co/329210/polymarket-rules-no-237m-controversial-bet-over-zelenskyys-suit?amp=1); [DeFi Rate](https://defirate.com/news/polymarket-trader-loses-500k-loss-after-rules-change-microstrategy-btc-market/).

### Inferences
The table ranks types from most to least verifiable. Game-UI examples are illustrative domain knowledge, not sourced; the pre-lock readability check is what verifies them on each stream.

| Tier | Proposition type | Examples | Why | Mode |
|---|---|---|---|---|
| 1 | Terminal outcome printed as words on a persistent screen; both outcomes have a positive cue | Chess result modal ("…wins", "You lost"); fighting game "K.O." then a winner screen; card game Victory/Defeat; CS2 round-win banner plus score increment ("Will Terrorists win this round?") | Large-text recognition is the strongest skill; the cue is decisive and persistent; a second cue (score change) often allows a cross-check | Auto-eligible after evaluation, with all gates |
| 1b | Speech keyword, YES side | "Will the word 'rush' be audible on stream during this match?" | Deterministic match plus local re-transcription | YES auto-eligible; NO only with proven full coverage |
| 2 | Threshold on a *frozen* terminal numeric readout | Final chess clock > 1:00 (only if the clock stays on the result screen); final speedrun timer < X; final score ≥ N | One short OCR read and a code comparison, but small digits at 480p are risky | Opens only if the pre-lock readability check passes; void within one display unit of the threshold or if reads disagree; supervised by default |
| 2 | Distinctive text event during the window | "ACE", "New Record", "Achievement unlocked", "Perfect" | Text recognition, but the event may be transient and missed by sparse sampling | Supervised; needs adaptive sampling |
| 3 | Count of small icons or objects at an instant | "≥3 Terrorists alive at round end"; cards in hand; pegs left | Counting plus small elements; the instant itself needs a definition | Human approval only, or disallow |
| 3 | Continuous or graphical readouts; spatial or board state | Health bar < 25%; minimap position; "Will the streamer castle?" | Progress bars, minimaps and spatial reasoning are weak | Human approval only, or disallow |
| 3 | Transient action events and ordering | Headshot; 10-hit combo; "X before Y" | Sparse frames miss them; temporal ordering is near chance | Disallow in v1 |
| X | Subjective, hidden, external or chat-decided outcomes | "Will the streamer rage?"; opponent's hidden cards; outcome only stated verbally; post-stream stats sites; anything already decided at lock | Not observable or not attributable | Disallow |

- **Every proposal must name its evidence** in a frozen, code-validated `ResolutionSpec`. The spec contains:
  - `prop_type`, which must be on the allowlist;
  - exact YES, NO and VOID literals, for example `YES: ["you won", "white wins"]`, `NO: ["you lost", "black wins"]`, `VOID: ["draw", "aborted", "stalemate"]`;
  - for numeric types: the field label, a region hint, the display format, the comparator and the threshold;
  - the observable cue that marks the decisive moment;
  - identity anchors observed before lock;
  - a maximum duration or deadline;
  - the frame IDs used for the pre-lock readability check.

  Code rejects incomplete specs and types not on the allowlist.
- **Readability pre-check (makes Tier 2 data-driven).** Before a numeric bet opens, two extraction reads of two different recent frames must return the same parseable value for the named field, and the value must be plausible (for example, a running clock changing in the expected direction). If this fails, the proposer must choose a Tier-1 type instead.
- **Prefer reformulations that move a bet up a tier.** "Will the Terrorists win this round?" (banner plus score) is Tier 1; "≥3 Terrorists alive at round end" is Tier 3. Likewise, "Will the streamer win?" is Tier 1, while "Will they win with more than 1:00 on the clock?" is only Tier 2, and only if the clock stays visible on the result screen.

### Gaps
- I did not research, per game, whether result screens and frozen final values persist (for example, whether a given chess site keeps clocks visible on its result modal). The pre-check is designed to discover this empirically per stream.

## 6. How robust is this to adversarial input (prompt injection, spoofed result screens, replays)?

### Takeaway
Assume injected instructions in screen text, overlays or speech *will* sometimes steer the model. The 2025 benchmarks report attack success or deception rates between 23% and 100% depending on the setting, and system-prompt defenses help little. Safety must come from the architecture:
- The model only extracts; code decides from a frozen spec.
- A decision needs multiple corroborating cues plus identity and temporal anchors.
- Chat is never an input.
- Anything anomalous goes to a human or voids.

Staged result screens and replays cannot be fully excluded automatically, which is one reason approval mode must remain available.

### Cited Findings
- VPI-Bench (arXiv Jun 2025): prompt injections embedded visually in rendered UIs deceived computer-use agents up to 51% of the time and browser-use agents up to 100% on some platforms. System-prompt defenses gave only limited improvement — [arXiv](https://arxiv.org/abs/2506.02456v1).
- AgentTypo (arXiv Oct 2025): optimized typographic text embedded in images raised image-only attack success on GPT-4o agents from 23% to 45%, with consistent results on GPT-4V, GPT-4o-mini, Gemini 1.5 Pro and Claude 3 Opus — [AI Topics](https://aitopics.org/doc/arxivorg:8DFDAB12); [papers.cool](https://papers.cool/arxiv/2510.04257).
- CrossInject (arXiv Apr 2025): cross-modal injections raised attack success by at least 26.4% over earlier attacks — [arXiv](https://arxiv.org/abs/2504.14348v1).
- Imperceptible visual prompt injections have been reported against closed MLLMs including GPT-4o and Claude models (Aug 2025). The database entry notes the findings were not independently verified — [Promptfoo LM Security DB](https://www.promptfoo.dev/lm-security-db/vuln/invisible-visual-prompt-injection-fe828a0d).
- Indirect prompt injection: instructions planted in data that an LLM-integrated application processes can hijack it (Greshake et al., arXiv Feb 2023; canonical, not re-fetched) — [arXiv](https://arxiv.org/abs/2302.12173).
- A design-level defense, CaMeL, separates control flow from untrusted data so that injected content cannot change what the program does (Debenedetti et al., arXiv Mar 2025; canonical, not re-fetched) — [arXiv](https://arxiv.org/abs/2503.18813).

### Inferences
- **Threats and mitigations:**
  1. *Injection through speech, on-screen text or overlays.* Label frames and transcript as untrusted data in the prompt and ask only for transcription. Give the output schema no "outcome" or "instruction" field, and have code ignore unexpected fields. Model output has no settlement authority.
  2. *Chat.* Never feed chat to the resolver. It adds injection surface and provides no unique evidence.
  3. *An injection that makes the model "see" a fake "Victory".* Corroborate with:
     - a local OCR engine, which cannot be instructed and fails differently;
     - a second cue, such as the score increment;
     - an anchor match;
     - the t_prev/t_end continuity check.
  4. *Staged or spoofed result screens*, such as an overlay image, an alert graphic, or the streamer holding up a phone. Require that:
     - the cue appears inside the game-capture region;
     - in-progress frames of the same game precede it;
     - anchors match;
     - the cue persists across at least two frames.

     Some risk remains, and the backstop is supervised mode plus test money.
  5. *Replays, highlights, VODs, post-game analysis boards and killcams.* Discard the evidence if the schema flag `replay_or_killcam_indicator` is set, if anchors mismatch, or if the round number goes backwards. The decisive cue must also be first seen after lock.
  6. *An outcome already known at lock (past-posting).* Void if any terminal cue has a media timestamp earlier than t_lock plus a margin.
  7. *Insiders.* The streamer controls "say X" outcomes and could throw a game. This is acceptable with test money, but the demo should say so.
- **Resampling is not independence.** Multiple reads of the *same* injected frame reproduce the same injected answer. Independence must come from different frames, a different reader (local OCR), or a different modality.
- **Route anomalies to the operator queue instead of auto-settling.** Anomalies include a cue with no plausible lead-up, changed anchors, disagreeing reads, and speech that contradicts the screen.

### Gaps
- I found no studies specifically on prompt injection through ASR transcripts of live speech, or on spoofed game result screens. Both threats are extrapolated from the visual and indirect prompt-injection literature.

## 7. How should the proposer and resolver be evaluated on a small labeled set of recordings?

### Takeaway
The primary safety metric is the wrong-settlement rate on decided markets, reported with an upper confidence bound. Alongside it, report coverage (one minus the void rate), per-type breakdowns, latency and results on a red-team set. By the rule of three, zero wrong settlements in n decided markets bounds the true rate at about 3/n with 95% confidence. A hackathon-sized set of 30–60 markets per type therefore justifies human-supervised operation. At most it justifies automatic operation for Tier-1 terminal-banner bets, with a risk bound of roughly 5–10%.

### Cited Findings
- Rule of three: if zero events occur in n trials, the 95% upper confidence bound on the event rate is about 3/n (canonical statistics reference; not re-fetched) — [Wikipedia](https://en.wikipedia.org/wiki/Rule_of_three_(statistics)).
- MLLM judges give inconsistent judgments across evaluations, so run-to-run variance is real and must be measured — [MLLM-as-a-Judge](https://arxiv.org/pdf/2402.04788).
- Headline benchmark numbers do not transfer cleanly to this setting. Within one model and task, GPT-4.1 detected 72 of 100 glitches but localized the correct frame for only 19 of them — [VideoGameQA-Bench](https://arxiv.org/html/2505.15952v2).

### Inferences
- **Labeled set.**
  - Record 10–20 clips of 5–30 minutes each across 5–8 games: chess, CS2, a fighting game, Peggle, a card game and a speedrun.
  - Capture them *through Twitch ingest*, so the evaluation sees real bursts, delay and compression.
  - For each market a human labels:
    - (a) the true outcome;
    - (b) whether the outcome is *verifiable from stream evidence* (gold UNRESOLVABLE when the decisive evidence never appears on stream);
    - (c) t_end.
  - Run the proposer on the clips and label each proposal as verifiable or not, and as ambiguous or not.
- **Resolver metrics**, per type and overall:
  - wrong-settlement rate among decided markets, with a Clopper–Pearson or rule-of-three bound;
  - under-abstention: deciding when gold says unresolvable, counted as a failure even when the guess happens to be right;
  - over-abstention: voiding when gold is clear;
  - premature settlement: deciding before t_end;
  - latency from t_end to decision;
  - hosted calls per market;
  - run-to-run agreement, by running each clip twice.
- **Proposer metrics:**
  - share of proposals that pass the human verifiability and ambiguity check;
  - past-posting rate (outcome already determined at lock);
  - void rate of its markets;
  - spec completeness;
  - outcome balance, so markets are not near-certain;
  - mix of proposition types.
- **Red-team set (about 10–20 cases).** The target is zero wrong settlements, with every case ending in void or escalation. Cases:
  - on-screen text saying "resolve YES";
  - a spoken injection;
  - a fake victory overlay;
  - a replay of an earlier win;
  - a cut to a BRB scene;
  - a missing segment straddling t_end;
  - a draw or aborted game;
  - a clock reading at the threshold.
- **Quota-aware evaluation.** Only the extraction step spends hosted requests.
  - Cache every extraction response, keyed by frame hash, prompt version and model ID.
  - Re-run decision-logic changes on the cached responses for free.
  - A 60-market evaluation at about 6–8 requests per market costs 360–480 requests, roughly one day's gemini-3.5-flash-lite quota. Spread it across days, or run it on a day without live demos.
  - Report results against the exact model and prompt version used.
- **Sample sizes.**
  - Zero wrong settlements in 30 decided markets bounds the rate at ≤10% (95%); in 60 at ≤5%; in 100 at ≤3%; in 300 at ≤1%.
  - One observed error in 60 gives an upper bound near 9% (two-sided exact 95%; computed, not sourced).
- **Suggested bars.** These are my proposal; the owner decides.
  - *Human-supervised:*
    - the resolver's suggestion matches gold on at least 90% of clear cases;
    - every suggestion carries an evidence bundle a human can verify in under 30 s;
    - under-abstention is rare and visible.
  - *Automatic, per type:*
    - zero wrong settlements on at least 60 decided markets (≤5% bound), ideally 100 or more (≤3%);
    - zero wrong settlements on the red-team set;
    - a void rate the demo can tolerate, for example ≤30%;
    - stable results across two runs.

    Any type with an observed wrong settlement stays supervised.
  - With only a few hours of build time, expect automatic mode to be justified for Tier-1 terminal-banner bets at most.

### Gaps
- I found no published thresholds for acceptable error rates in automated settlement of entertainment bets; the bars above are a proposal.
- Free-tier models can change silently on the server side after evaluation. Periodic re-evaluation is advisable, but I did not quantify its cost.

## 8. Synthesis: recommended v1 resolution workflow, ranking summary, abstain and void rules, and improvements with more time

### Takeaway
Build a small, deterministic Python state machine around one structured extraction call per candidate frame. It settles automatically only for allowlisted Tier-1 types after every gate passes. Everything else goes to the operator. It voids on timeout, coverage gaps, disagreement, anomalies or a spec mismatch. This is buildable in a few hours because the hard parts (matching, comparison and gating) are plain code over JSON.

### Cited Findings
- Extraction is most reliable for large printed text and least reliable for counts, temporal judgments and degraded text — [VideoGameQA-Bench](https://arxiv.org/html/2505.15952v2); [KIE-HVQA](https://arxiv.org/html/2506.20168v2); [CountQA](https://arxiv.org/abs/2508.06585v1).
- Judge biases argue for making decisions in code — [MLLM-as-a-Judge](https://arxiv.org/pdf/2402.04788).
- Visual injection results argue for giving the model no settlement authority — [VPI-Bench](https://arxiv.org/abs/2506.02456v1); [CaMeL](https://arxiv.org/abs/2503.18813).
- Whisper's hallucination patterns argue for VAD gating, unprimed confirmation and proof of coverage — [Barański et al.](https://arxiv.org/abs/2501.11378); [Careless Whisper](https://arxiv.org/html/2402.08021v2).
- Twitch Predictions already follows the lock, then resolve-or-cancel, then refund-on-timeout model — [Twitch API](https://dev.twitch.tv/docs/api/predictions); [Tubefilter](https://www.tubefilter.com/2020/11/13/twitch-launches-predictions-feature-channel-points/amp/).
- Disputes come from ambiguity and post-hoc clarification — [DeFi Rate](https://defirate.com/news/polymarket-trader-loses-500k-loss-after-rules-change-microstrategy-btc-market/).
- Free-tier quota, verified by the coordinator from the owner's Google AI Studio rate-limit page (private page, read 2026-11-15): gemini-3.5-flash-lite allows 15 requests/min, 250K tokens/min and 500 requests/day per project. gemini-2.5-flash and gemini-2.5-flash-lite allow only 20 requests/day. Other models on the key have separate quotas that are not yet known. — coordinator-supplied; no public URL

### Inferences
**Recommended v1 workflow (simplest version that meets the requirements)**
1. **At proposal time.**
   - Validate the `ResolutionSpec` (section 5) with pydantic; reject types not on the allowlist and incomplete specs.
   - For Tier 2, run the readability pre-check: two reads of two different frames.
   - Store the spec immutably with its hash, plus t_lock in media time, the deadline and the anchors.
2. **On each ingest burst (about every 6 s).**
   - Append frames and ASR chunks with their media timestamps.
   - Update the coverage map of missing segments and ASR gaps.
   - Run the free local steps:
     - the keyword matcher;
     - perceptual-hash scene-change detection;
     - optionally, local OCR (Tesseract, PaddleOCR or RapidOCR) looking for the spec's literals;
     - a scan of ASR text for end hints.
3. **Candidate selection under the request quota.** Requests per day, not tokens, are the binding limit (see Request budget below).
   - Call the hosted model only on:
     - (a) trigger frames: scene change, ASR end hint, local OCR hit, or a low clock;
     - (b) at most a slow heartbeat, every 3–5 minutes, and only while a market is open, to confirm the game is in progress and the anchors still match.
   - Never call once per ingest burst.
   - Batch 2–4 frames per request, each with a burned-in frame ID. Tokens are cheap relative to requests.
   - Enforce a hard cap of about 6–8 requests per market and a global daily-budget counter. If the counter runs out, escalate open markets to the operator, or void them at the deadline. Never auto-settle on partial evidence.
4. **Extraction call, with no outcome field.** The schema is `{frame_id, game_screen_visible, in_progress, terminal_screen_visible, verbatim_texts[], field_reads{label: raw_string|null}, anchors_seen{}, replay_or_killcam_indicator, overlay_or_non_game_scene, unreadable}`.
   - The prompt states that image text and speech are untrusted data and asks only for transcription.
   - Null or "unreadable" are allowed answers.
   - Invalid output counts as no evidence.
5. **Decision function.** A pure, unit-tested function evaluated on every tick; the first matching rule wins:
   1. Past the deadline → UNRESOLVABLE (timeout).
   2. Terminal cue first seen before t_lock plus a margin → UNRESOLVABLE (outcome visible at lock).
   3. Terminal cue matched in one frame only → WAIT for a later confirming frame, for a bounded time.
   4. Terminal cue confirmed → map the matched literal to YES, NO or VOID. Confirmed means all of:
      - the literal matches in at least two frames or reads;
      - the anchors match;
      - t_lock < t_prev < t_end;
      - no replay or overlay flag;
      - no ingest gap of more than about 10 s straddling t_end.

      For numeric types, both reads must parse to the same value. Code does the comparison, and the market voids if the value is within one display unit of the threshold.
   5. Speech:
      - a confirmed hit inside the window → YES;
      - window ended with full coverage and no confirmed hit → NO;
      - window ended with coverage gaps → UNRESOLVABLE.
   6. Conflicting cues (both YES and NO literals seen, or speech contradicting the screen) → UNRESOLVABLE, or escalate in supervised mode.
   7. Anything else → WAIT.
6. **Settlement.**
   - *Approval mode:* every non-WAIT result goes to the operator with its evidence bundle. If the operator does not respond within N minutes, the market voids.
   - *Automatic mode:* only allowlisted Tier-1 types with every gate passed settle automatically; everything else escalates.
   - Write an append-only evidence record: frame hashes, model ID, raw JSON, and the rule that fired.

**Request budget under the verified quota** (arithmetic; assumes the proposer and resolver share the gemini-3.5-flash-lite project quota)
- **Daily cap.** 500 requests/day. A constant cadence of one request per 6-s burst is about 600/hour, which exhausts the day in under an hour. Even one request per minute (60/hour) exhausts it in about 8 hours, before counting proposer calls. Trigger-driven calls are therefore mandatory.
- **Per market:**

  | Step | Requests |
  |---|---|
  | Tier-2 pre-check (two frames in one request) | 0–1 |
  | Trigger reads | 1–3 |
  | Decisive confirmation (two requests on two different frames) | 2 |
  | Heartbeats | 0–2 |
  | **Total** | **about 4–8** |

  At 8 requests per market, 500/day covers about 60 markets, minus proposer usage. At a few markets per hour over a 4-hour demo (12–20 markets), the resolver needs roughly 50–160 requests, which fits with headroom for the proposer and retries.
- **15 RPM** easily absorbs the burst of 2–4 requests at the decisive moment. Add a simple token-bucket limiter and back off on HTTP 429. A 429 means WAIT, never NO.
- **250K TPM** is not binding: 15 requests/min at 16K tokens each is 240K. Batching frames therefore trades plentiful tokens for scarce requests.
- **Optional second model.** If quota allows, reserve the small separate quota (gemini-2.5-flash, 20/day) as an *independent second reader* for decisive frames on the highest-value markets. A different model is a better independence check than resampling the same one, but 20/day covers only about 20 markets.
- **Lite-tier capability is unverified.** The benchmark numbers in section 1 come from larger models. That strengthens the case for local OCR corroboration, code-side gates and supervised mode by default.

**Ranking summary.** From most to least verifiable (full table in section 5):
1. Printed terminal outcome with a positive cue for both sides.
2. Speech keyword, YES side; the NO side needs proven coverage.
3. Frozen terminal numeric threshold, gated by the pre-check.
4. Persistent text events, supervised.
5. Icon counts, continuous bars, board or spatial state, and transient or ordering events: human-only or disallowed.
6. Subjective, hidden, external, chat-decided, or already-decided outcomes: disallowed.

**Abstain and void rules.** WAIT is the default state; UNRESOLVABLE means everyone is refunded.
- V1: the hard deadline passes without a confirmed decisive cue.
- V2: the decisive cue predates lock, so the outcome was knowable at lock.
- V3: an ingest or coverage gap straddles t_end, or, for speech NO, any speech region in the window was not transcribed.
- V4: reads still disagree after K attempts, or the value is unreadable or unparseable.
- V5: the outcome is not covered by the spec (draw, abort, remake, disconnect, forfeit), unless the spec maps it explicitly.
- V6: anchor mismatch, a replay, killcam or VOD indicator, or a non-game scene at the decisive moment.
- V7: conflicting decisive cues, or speech that contradicts the screen.
- V8: a numeric value within one display unit of the threshold.
- V9: the model keeps refusing, or keeps returning invalid output, for the decisive frames.
- V10: the stream goes offline or ends, or the streamer switches game, before the decisive cue.
- V11: the operator voids the market.
- Two prohibitions always apply:
  - Never resolve a visual bet NO because a YES cue is absent.
  - Never accept clarifications to the spec after lock.

**Improvements with more time**
- Crop and upscale the named region, and fetch source-quality renditions only for decisive frames.
- Make local OCR a required second reader for banners and digits.
- Send a short native video clip around t_end (Gemini-style video input) to catch transient cues.
- Add speaker diarization or voice enrollment so that "the streamer said" bets become possible.
- Learn calibrated per-type thresholds from the labeled set (selective prediction or conformal abstention).
- Add a replay and scene classifier.
- Cache, per stream, what that stream's result screen looks like. This is learned automatically, so it stays game-agnostic.
- Score disagreement across multiple samples, in the style of semantic entropy.
- Collect larger evaluation sets to push per-type error bounds toward 1%.

### Gaps
- Per-model free-tier quotas for other models on the key are not yet known (coordinator, 2026-11-15). The per-frame image token cost on gemini-3.5-flash-lite was not verified here. It matters only if requests carry many frames, because 15 RPM × 16K tokens stays under the 250K TPM limit (arithmetic).
- I found no published benchmark numbers for gemini-3.5-flash-lite on OCR, counting or game-UI tasks.
- I found no source on whether local OCR engines read stylized game fonts well enough to serve as the second reader; this is an untested assumption.
