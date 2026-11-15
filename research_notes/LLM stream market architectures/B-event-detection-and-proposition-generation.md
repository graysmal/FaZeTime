# B. Event detection and proposition-generation patterns

_Method note (2026-11-14): arXiv abstracts were read through the arXiv export API (Atom feed) and quoted as relayed by the fetch tool's extractor, so they are abstract-level only. Kalshi and Bally PDFs were converted locally with pdftotext. Repo facts come from files read on 2026-11-14. Papers dated after mid-2026 are newer than my training data; I verified them only from their arXiv abstracts._

## 1. Which streaming / proactive video-LLM, commentary and highlight patterns transfer to detecting a "bettable setup", and what accuracy/latency do they report?

### Takeaway
From 2024 to 2026 the field settled on one architecture. A cheap "when to respond" decision runs all the time, often every frame or every second, and it is separate from an expensive "what to say" generator. Timing is still the unsolved part. The best model reaches only 52.18% Ask-F1 on AskStream, and on LiveProBench half the models respond too early more often than they miss. Several patterns carry over to a bettable-setup detector: the separate gate, waiting until there is enough evidence, stabilizing the trigger over time, and scanning at low resolution before confirming at high resolution. The models themselves need A100-class GPUs and do not carry over to a Pi plus a free-tier API.

### Cited Findings
**Separate "when" and "what" components (core pattern)**
- StreamMind uses "event-gated cognition": the "LLM is only invoked when relevant events occur". It runs at "100 fps on a single A100" (VERIFIED_DOC, arXiv 2025-03-08) — [Source](https://arxiv.org/abs/2503.06220)
- Dispider splits Perception, Decision and Reaction. One component "tracks the video stream and identifies optimal moments for interaction". Then "Once the interaction is triggered, an asynchronous interaction module provides detailed responses" (VERIFIED_DOC, arXiv 2025-01-06) — [Source](https://arxiv.org/abs/2501.03218)
- StreamBridge adds "a decoupled, lightweight activation model that can be effortlessly integrated into existing Video-LLMs". The authors report it outperforms "proprietary models such as GPT-4o and Gemini 1.5 Pro" on their streaming evaluations (VERIFIED_DOC, arXiv 2025-05-08) — [Source](https://arxiv.org/abs/2505.05467)
- VideoLLM-online (LIVE) "can support streaming dialogue in a 5-minute video clip at over 10 FPS on an A100 GPU" (VERIFIED_DOC, arXiv 2024-06-17) — [Source](https://arxiv.org/abs/2406.11816)
- MMDuet ("VideoLLM Knows When to Speak") uses a duet format where "both the user and the model can insert their text messages at any position during the video playback". It reports 76% CIDEr on YouCook2 dense captioning, 90% mAP on QVHighlights highlight detection and 25% R@0.5 on Charades-STA grounding (VERIFIED_DOC, arXiv 2024-11-27) — [Source](https://arxiv.org/abs/2411.17991)
- Aero Realtime: "each approximately 80-ms audio slot predicts either a lexical token or a silence token", so the model learns "both when to respond and what to generate". It reports "84-ms median and 173-ms P95 processing lag over 20 minutes" of streamed video (VERIFIED_DOC, arXiv 2026-08-09) — [Source](https://arxiv.org/abs/2608.08469)
- "Don't Pause" decides "when to continue speaking, start a new response, or stay silent". It reports "98.29% synchrony with video playback" at "3.89 FPS" (VERIFIED_DOC, arXiv 2026-06-05) — [Source](https://arxiv.org/abs/2606.06991)
- IPIBench reports "unstable proactive triggering" and proposes "a temporal-gating mechanism for stabilizing proactive triggering" (VERIFIED_DOC, arXiv 2026-05-26) — [Source](https://arxiv.org/abs/2605.27074)
- StreamArena "assigns latency-critical interaction and proactive monitoring to independently scheduled frontend workers". Its videos average 88.8 minutes, 243 in total (VERIFIED_DOC, arXiv 2026-08-06) — [Source](https://arxiv.org/abs/2608.05703)
- StreamPro frames the problem as deciding "when to respond, rather than merely what to respond". It reports 41.5 on StreamPro-Bench against a previous best of 10.4, and 78.9 on StreamingBench-RTVU (VERIFIED_DOC, arXiv 2026-05-11) — [Source](https://arxiv.org/abs/2605.16381)

**Benchmarks: timing is the weak point**
- OVO-Bench has 12 tasks, 644 videos and about 2,800 timestamped meta-annotations. One of its modes is "Forward active responding: delay the response until sufficient future information becomes available". Nine Video-LLMs evaluated still lag despite gains on traditional benchmarks (VERIFIED_DOC, arXiv 2025-01-09) — [Source](https://arxiv.org/abs/2501.05510)
- StreamingBench has 18 tasks, 900 videos and 4,500 QA pairs, with five questions per video asked at different time points. "even the most advanced proprietary MLLMs like Gemini 1.5 Pro and GPT-4o perform significantly below" humans (VERIFIED_DOC, arXiv 2024-11-06) — [Source](https://arxiv.org/abs/2411.03628)
- ProactiveVideoQA evaluates "autonomously determining the timing of multi-turn responses in real time during video playback". It introduces PAUC because "model responses are generated at varying timestamps" (VERIFIED_DOC, arXiv 2025-07-12) — [Source](https://arxiv.org/abs/2507.09313)
- LiveProBench scores "responding within an appropriate interval after the target event, and otherwise remaining silent", at one-second intervals. "Premature responses outnumber missed responses for half of the evaluated models" (VERIFIED_DOC, arXiv 2026-09-11) — [Source](https://arxiv.org/abs/2609.12658)
- TRACE defines "false alarms (responses emitted while no target window is currently valid and a later one remains)". It evaluates 8 systems on 1,240 records from 517 videos (VERIFIED_DOC, arXiv 2026-09-25) — [Source](https://arxiv.org/abs/2609.30670)
- AskStream adds a third action, "ask", alongside wait and answer, with 2,714 frame-level windows. "even the strongest model attains only 52.18% on our proposed Ask-F1 metric" (VERIFIED_DOC, arXiv 2026-10-28) — [Source](https://arxiv.org/abs/2610.38678)
- StreamClarify "uses the entropy of a binary pre-answer judgment as a lightweight uncertainty score". It reports up to +8.2 Macro accuracy, and its entropy-based selection is "more than 18 points higher precision than random selection" (VERIFIED_DOC, arXiv 2026-10-31) — [Source](https://arxiv.org/abs/2611.01263)
- In OmniPro, "84% of samples require audio signals" (2,700 samples, 9 sub-tasks) (VERIFIED_DOC, arXiv 2026-05-18) — [Source](https://arxiv.org/abs/2605.18577)

**Speech, game commentary and livestreams**
- LiveCC trains on streaming ASR transcripts interleaved with frames: Live-CC-5M for pre-training and Live-WhisperX-526K for SFT. Its 7B model "can surpass advanced 72B models (Qwen2.5-VL-72B-Instruct, LLaVA-Video-72B) in commentary quality" (VERIFIED_DOC, arXiv 2025-04-22) — [Source](https://arxiv.org/abs/2504.16030)
- DirCast (live esports directing plus commentary): "Every second it scans all cameras at low resolution, decides with a hold-or-switch director whether and where to cut", then "reads the chosen camera at high resolution before it speaks". It works "from the past alone". Its commentary "wins 29.2 percent of comparisons against GPT-4o" (VERIFIED_DOC, arXiv 2026-10-22) — [Source](https://arxiv.org/abs/2610.31734)
- MOBA-VL uses "game telemetry, which records exactly when each event occurs, as a supervision signal" to narrate "second by second". It reports Overall 63.25 against 55.12 for StreamingVLM, and event recall rising from 34.5 to 42.1 over SFT (VERIFIED_DOC, arXiv 2026-09-29) — [Source](https://arxiv.org/abs/2609.38428)
- Content-based gameplay narration with VLMs uses "no game-specific instrumentation, no engine telemetry". It packs "nine uniformly sampled frames into a single 3x3 image", which cuts per-minute image payloads about 9x. Reported failure modes are "hallucinated game state, resolution loss from mosaicking". The paper gives no quantitative evaluation yet (VERIFIED_DOC, arXiv 2026-08-14) — [Source](https://arxiv.org/abs/2608.14016)
- Pause-aware real-time game commentary "adjusts the next prediction timing based on the estimated duration of the previous utterance" (VERIFIED_DOC, arXiv 2026-03-03) — [Source](https://arxiv.org/abs/2603.02655)
- GameCommBench finds "live observation and strategic analysis emerging as major bottlenecks" for AI game commentary (VERIFIED_DOC, arXiv 2026-10-08) — [Source](https://arxiv.org/abs/2610.11129)
- LiViBench is a livestream benchmark in which every interactive video includes "audio, speech, and real-time comments modalities", meaning chat (VERIFIED_DOC, arXiv 2026-01-21) — [Source](https://arxiv.org/abs/2601.15016)

### Inferences
- INFERRED: A "bettable setup" is OVO-Bench's forward-active responding with one extra constraint: the outcome must still be unknown when betting closes. The two kinds of error carry very different risk. A premature trigger (banter, hypotheticals) costs a model call or an operator rejection. A late trigger (contest started, outcome visible) is the dangerous one, and the benchmark finding that models respond too early does not protect against it.
- INFERRED: These patterns can be adopted in one night, roughly in order of value:
  1. Keep the separate cheap gate in front of the proposer. A deterministic pre-filter already does this, so widen its vocabulary rather than replacing it with a model.
  2. Stabilize the trigger over time, as IPIBench does. Require the setup cue in at least 2 consecutive 4 s ASR windows, or agreement between the gate and the model.
  3. Scan at low resolution and confirm at high resolution, as DirCast does. Use `low` media resolution (about 264 tokens) for the setup check and default resolution only for the proposer call.
  4. Treat "ask" as a third action, as AskStream does. For FaZeTime that means escalating to the operator (approval mode), never acting alone.
  5. Use a binary pre-judgment as an uncertainty signal, as StreamClarify does. Have the gate model return a binary answer with its abstain reason, and escalate only on a confident YES.
- INFERRED: Every number above comes from GPU research systems on curated benchmarks. None of them measures "announced contest, result unknown" detection on raw Twitch gameplay full of banter, so expect lower precision. Generic mode should run only in SHADOW or approval mode.
- INFERRED: Speech is the earliest cue for an announced contest. LiveCC's ASR-to-frame alignment and DirCast's "from the past alone" constraint both point that way. The 4 s faster-whisper windows should drive triggering. Frames should confirm "not started / outcome not visible", and should not be used for discovery.
- INFERRED, on the side session's "periodic cheap bettable-setup pass": the decoupled always-on decision is well supported. In the literature, though, the always-on gate is local and cheap, typically per second or per frame. Using a remote LLM call as the always-on gate inverts that pattern. The remote pass should be tier 1, called after local triggers fire, plus a slow capped heartbeat (see Q3).

### Gaps
- No paper evaluates detecting "an announced or imminent contest whose result is unknown", and none reports precision or recall for proposing bets. The closest proxies are forward-active responding, proactive timing and ask/answer.
- Mechanism details inside the papers were not verified, for example VideoLLM-online's per-frame response/EOS decision and MMDuet's score heads. Only the abstract-level claims above were checked.
- Highlight detection driven by Twitch chat velocity or audio: the 2024-2026 arXiv sweep for Twitch/esports/livestream highlights and commentary returned no abstracts using chat velocity or OCR. Older chat-reaction highlight work exists but was not fetched or verified here.
- No fetched page contained text addressed to AI agents or embedded instructions.

## 2. How do real prediction and proposition markets frame "observable, objective, time-bounded" propositions, and what generic binary template follows?

### Takeaway
Every mature venue specifies the same parts:
- a named resolution source
- a payout criterion written as an observable fact
- a time bound, with trading ending before the outcome can be known
- explicit contingencies, which can be void/refund, a "last fair price" or exchange review
- voids for bets placed after the event started or was decided (past-posting)
- human review

Twitch Predictions is the closest analog: one at a time, 2–10 outcomes, lock, then resolve or cancel with a refund, and an automatic refund after 24 hours. A generic FaZeTime template should require the proposer to declare observable START, YES and NO conditions on a named evidence channel, plus standard cancellation cases. It should also void if the contest starts before betting closes.

### Cited Findings
**Twitch Predictions (closest product analog)**
- "You can provide from 2 to 10 outcomes". Broadcasters "may run only one prediction at a time". The docs' examples use windows of 60, 200 and 300 s and state no min/max (VERIFIED_DOC, Twitch dev docs, accessed 2026-11-14, undated) — [Source](https://dev.twitch.tv/docs/api/predictions)
- LOCKED ends betting early: "If locked, you must still choose a winning outcome or cancel the prediction." CANCELED means "cancel the prediction and give everyone back their Channel Points." "Points are only allocated to viewers if you select a winning outcome." "If you don't select a winning outcome within 24 hours, all points are returned to the viewers." (VERIFIED_DOC, accessed 2026-11-14) — [Source](https://dev.twitch.tv/docs/api/predictions)
- "The broadcaster's moderators and editors may create and manage the broadcaster's predictions". Predictions are "available to partners and affiliates only". The scope is `channel:manage:predictions` (VERIFIED_DOC, accessed 2026-11-14) — [Source](https://dev.twitch.tv/docs/api/predictions)
- According to a search summary, Twitch's Predictions terms say Twitch will not return points or compensate users affected by improper questions or incorrectly reported outcomes. I did not fetch the page (REPORTED, accessed 2026-11-14) — [Source](https://legal.twitch.com/legal/predictions-terms-and-conditions)

**Polymarket**
- "Markets are resolved by the UMA Optimistic Oracle" "according to the market's pre-defined rules". Winning shares pay $1 and losing shares become worthless. Proposing an outcome requires a USDC.e bond: "you will lose all of your $750 bond" if the proposal is premature or unsuccessful. A proposal enters a 2-hour challenge period in which anyone can dispute (VERIFIED_DOC, Polymarket Help Center, 2026-01-11) — [Source](https://help.polymarket.com/en/articles/13364518-how-are-prediction-markets-resolved)

**Kalshi**
- A Kalshi contract-terms PDF follows a fixed outline: Scope, Underlying, Source Agency (a ranked list such as AP, Reuters, Bloomberg and official statements), Payout Criterion, Last Trading Date/Time, Settlement Date, Expiration Date/Time, Settlement Value ($1.00), Expiration Value and Contingencies. The file served at the `MATCHUP.pdf` URL is headed "POLITICALECONOMICEVENTS" and was generated on 2026-04-08 (VERIFIED_DOC, PDF generated 2026-04-08) — [Source](https://kalshi-public-docs.s3.amazonaws.com/contract_terms/MATCHUP.pdf)
- From the same PDF:
  - "Revisions to the Underlying made after Expiration will not be accounted for".
  - "Last Trading Time will be one minute before the expected release of the final data".
  - "If an event described in the Payout Criterion occurs making any outcome impossible, or they have all occurred, expiration will be moved to an earlier date and time in accordance with Rule 7.2".
  - "If any single <component> resolves to 'No' or becomes impossible to occur, the entire Contract immediately resolves to 'No.'"
  - Under Contingencies: "Kalshi may, at its sole discretion, initiate the Market Outcome Review Process pursuant to Rule 7.1" and "If an Expiration Value cannot be determined on the Expiration Date, Kalshi has the right to determine payouts".
  - Insiders are barred from trading, for example "Campaign managers and senior campaign staff for referenced candidates".

  (VERIFIED_DOC, 2026-04-08) — [Source](https://kalshi-public-docs.s3.amazonaws.com/contract_terms/MATCHUP.pdf)
- According to a search summary, the TRUMPLID statistics contract resolves "to a last fair price set by the exchange if no data is released" (REPORTED, accessed 2026-11-14) — [Source](https://kalshi-public-docs.s3.amazonaws.com/contract_terms/TRUMPLID.pdf)

**Sportsbook house rules: past-posting, suspension and abandonment (Bally Bet Massachusetts, "Last Updated: February 6, 2025")**
- Bets accepted in these cases are voidable:
  - "On events/offers that have already been decided or concluded, or in relation to which Bally's had suspended betting."
  - "On events/offers after the event/match/offer has started (except for live betting bet types)."

  (VERIFIED_DOC, 2025-02-06) — [Source](https://massgaming.com/wp-content/uploads/Bally-Bet-House-Rules-2.6.25.pdf)
- The past-posting section covers:
  - "'Pre-match' bets placed/accepted after the event has started"
  - "'Live' bets placed/accepted at incorrect odds due to delayed or failing 'Live' coverage"
  - bets placed after "the last instance that a participant/outcome had any chance to influence" the scoring, which "will be declared void"
  - "Bally's reserves the right, to suspend, partially or completely, the betting activity at any time where it deems necessary."

  (VERIFIED_DOC, 2025-02-06) — [Source](https://massgaming.com/wp-content/uploads/Bally-Bet-House-Rules-2.6.25.pdf)
- Settlement:
  - It uses "information obtained first-hand ... through TV transmissions, streaming ... as well as official sites", and later changes to the first official result are ignored.
  - Walk-overs are void.
  - Abandoned events: offers already "decided prior to the abandonment and could not possibly be changed" settle. If the event does "not resume within 12 hours of its start time", pending offers are void.
  - If an event restarts from the beginning, unsettleable bets are "declared void regardless of whether or when the match is continued".
  - Props are defined as "a bet on a verifiable statistical result of an individual".

  (VERIFIED_DOC, 2025-02-06) — [Source](https://massgaming.com/wp-content/uploads/Bally-Bet-House-Rules-2.6.25.pdf)

**Esports betting rules (Midnite "General Esport Betting Rules", updated 2026-09-21)**
- The settlement source is "the official result as declared by the relevant governing body". For streamed events, "the result will be settled by the stream VOD (video on demand) or stream screenshots". Otherwise "the official scoreboard, broadcast, or game API". Time-based bets use the in-game clock (VERIFIED_DOC, 2026-09-21) — [Source](https://intercom.help/midnite/en/articles/2686555-general-esport-betting-rules)
- "A map is deemed to have started as soon as the game clock starts" or a player or team takes a game action such as picks, bans or purchases. "any bet placed after the actual starting time on a market that is not offered in play will be void" (VERIFIED_DOC, 2026-09-21) — [Source](https://intercom.help/midnite/en/articles/2686555-general-esport-betting-rules)
- Void and refund cases (VERIFIED_DOC, 2026-09-21) — [Source](https://intercom.help/midnite/en/articles/2686555-general-esport-betting-rules):
  - Replays: bets already decided before the incident "will stand", and the others are refunded.
  - A walkover before the map starts is refunded.
  - "Any bets that do not have a definitive result will be void and refunded".
  - A series not resumed within 48 hours is refunded.
  - Maps left unplayed because the series was already decided are refunded.
  - Cheating voids the affected map.
- Exception: for player props and H2H, "technical issues and substitutions" are not cause for voiding (VERIFIED_DOC, 2026-09-21) — [Source](https://intercom.help/midnite/en/articles/2686555-general-esport-betting-rules)
- A search summary quoted several other operator rules but did not say which page each came from:
  - A map voided for "retirement, disconnection, disqualification, walkover or other admin decision" voids match-period bets, while completed maps stand.
  - A CS competitor who disconnects "in the first 10 minutes" and cannot return voids the map.
  - A match "replayed due to a draw or a disconnection" is void and "considered as a separate live event".

  Candidate pages are listed here (REPORTED, attribution unverified, accessed 2026-11-14) — [DATA.BET rules](https://data-bet.freshdesk.com/support/solutions/articles/202000099170-esports-betting-rules); [Rivalry rules mirror](https://rivalry-app-next-www3.pages.dev/au/bet-rules)

### Inferences
- INFERRED: The common anatomy maps onto FaZeTime one to one:
  - The resolution source is the captured Twitch frames and transcript (Midnite accepts "stream VOD or stream screenshots").
  - The payout criterion is a pair of side-keyed observable predicates.
  - Last trading time is close, which must come before the contest starts (Bally and Midnite void pre-match bets placed after the start).
  - The contingencies are explicit void cases.
  - Review is operator approval, a short version of Kalshi's Market Outcome Review or Polymarket's 2-hour challenge.
  - FaZeTime already matches Twitch's one-at-a-time model and its void/refund timeout, which is stricter: 60–900 s against 24 h.
- INFERRED, the most important missing rule: a contest-start condition. Every venue voids bets placed after the start. A generic proposer has to declare an observable START condition, for example the first hit or shot, a round timer starting, or the run timer moving. Cancellation should then include "contest started before betting closed → VOID". Optionally the server could accept a worker "start observed" signal that only shortens close and never extends it. That is a contract change the coordinator has to approve.
- INFERRED: a generic binary template, sketched as "BINARY_OBSERVABLE_V1":
  - `contest_kind`: H2H, RACE, SOLO_THRESHOLD or SPLIT_TIME.
  - `sides`: A and B, or the YES and NO side of a single subject.
  - `start_condition`: observable.
  - `yes_condition` and `no_condition`: each observable, each 200 characters or fewer, each naming its own winner or state first.
  - `evidence_channel`: chosen from a small enum, for example DEATH_MESSAGE, END_SCREEN_TEXT, SCOREBOARD_COMPARE, TIMER_THRESHOLD or SPOKEN_BY_BOTH (operator-only). The resolver can then run a deterministic check and confirm with the model.
  - `cancellation_conditions`: standard list — not started by T; restart/remake/rematch before decision; disconnect/crash/stream offline (epoch change); draw/both/neither; format or participant change; evidence occluded or unreadable; outcome visible before close.
  - Lead window: close = min(expected start − margin, proposal time + X). If the expected start is under 45 s away, abstain (INSUFFICIENT_LEAD) rather than propose.
  - The resolve deadline is the expected duration plus margin, at most 900 s.
  - The NO condition must be the in-contest complement of YES. Anything else, such as neither condition by the deadline, means VOID, which follows FaZeTime's void-on-doubt rule rather than Kalshi's impossible-means-No.
- INFERRED: example propositions for a game stream (the game UI strings are unverified):
  - Minecraft 1v1, H2H, DEATH_MESSAGE: "Will A beat B in this 1v1?"
    - YES: a death message naming B killed by A after lock.
    - NO: a death message naming A killed by B.
    - Void: a death not attributed to the opponent (unless it was declared up front), a restart, no decisive message by the deadline, or fighting started before close.
  - Peggle round, SOLO_THRESHOLD, END_SCREEN_TEXT: "Will A clear this level before running out of balls?"
    - YES: the level-complete end screen.
    - NO: the out-of-balls / retry screen.
    - Void: the level was restarted or quit, or the first shot was taken before close.
    - Betting should close before the first shot, because play is visible and leaks information.
  - Peggle duel, H2H, END_SCREEN_TEXT or SCOREBOARD_COMPARE: "Will A beat B in this duel?"
    - YES/NO: the final screen ranks A above B, or B above A.
    - Void: a tie, a quit, or a restart.
  - Speedrun split, SPLIT_TIME, TIMER_THRESHOLD: "Will A reach <split> under mm:ss?"
    - YES: the split shows a time at or under the threshold.
    - NO: the split time is over the threshold, or the run resets before the split. A reset counts as NO, declared in advance.
    - Void: the stream or game crashes, or the timer overlay is unreadable.
  - Generic A vs B (race or match), H2H or RACE, END_SCREEN_TEXT:
    - YES/NO: the results screen ranks A above B, or B above A.
    - Void: a draw, a rematch before finish, a disconnect, or no start by T.
- INFERRED, on the side session's "generic binary template with observable YES/NO end conditions and cancellation cases": this matches how real venues work, but free-text predicates on their own cannot be checked by a machine. Two additions make it judgeable: a closed `evidence_channel` enum and a START condition. Without them the resolver ends up voiding most generic markets, which is safe but makes for a dull demo.
- INFERRED (optional): Kalshi's insider ban suggests one more rule. Participants named in a market should not be able to bet on it, which matters even with test credits if streamers bet live during the demo.

### Gaps
- The Twitch Help Center Predictions article did not render (JS/CSS error), so the official minimum and maximum prediction window and the title-length limits were not confirmed. The dev guide shows only examples of 60, 200 and 300 s.
- Polymarket's 50-50 or "unknown" resolution wording and its clarification process were not on the fetched page and were not verified.
- Kalshi sports matchup terms (ties, postponement, withdrawal) were not obtained, because the `MATCHUP.pdf` URL served POLITICALECONOMICEVENTS text. The "last fair price" claim is from a search summary only.
- In-play automatic suspension before dangerous events (penalties, free kicks) was not found beyond Bally's general right to suspend.
- The Peggle and speedrun UI strings (end screens, LiveSplit layout) were not researched, so the examples are illustrative.

## 3. Which cheap-gate → strong-model cascade patterns (LLM routing/abstention, event-triggered VLM calls) fit game streams, at what cost and false-negative trade-off?

### Takeaway
Cascades that can defer or abstain reliably cut cost: FrugalGPT reports up to 98% savings, RouteLLM more than 2x, and Trust-or-Escalate covers about 80% of cases at over 80% human agreement. Video systems that gate VLM calls with cheap signals report large savings: about 53% fewer VLM calls for BLUE, and a 151.79× speed-up at 97.2% accuracy for Cerberus. False negatives are rarely quantified. For FaZeTime the robust cheap gates are local:
- an ASR contest lexicon
- scene change or frame difference
- fixed-region OCR

The remote "bettable setup?" call should be event-triggered, with a slow, capped heartbeat, rather than running on a fixed short period.

### Cited Findings
**LLM cascades, routing and abstention**
- FrugalGPT: LLM fees "can differ by two orders of magnitude". It "can match the performance of the best individual LLM (e.g. GPT-4) with up to 98% cost reduction or improve the accuracy over GPT-4 by 4% with the same cost" (VERIFIED_DOC, arXiv 2023-05-09) — [Source](https://arxiv.org/abs/2305.05176)
- RouteLLM: router models "dynamically select between a stronger and a weaker LLM", which "significantly reduces costs-by over 2 times in certain cases-without compromising the quality of responses" (VERIFIED_DOC, arXiv 2024-06-26) — [Source](https://arxiv.org/abs/2406.18665)
- Token-level-uncertainty cascades: "a small model is invoked for most 'easy' instances, while a few 'hard' instances are deferred to the large model". Deferral rules improve when they use embeddings from the smaller model and intermediate layers of the larger model, not just confidence (VERIFIED_DOC, arXiv 2024-04-15) — [Source](https://arxiv.org/abs/2404.10136)
- Cascade routing unifies "routing and cascading into a theoretically optimal strategy" (VERIFIED_DOC, arXiv 2024-10-14) — [Source](https://arxiv.org/abs/2410.10347)
- Trust or Escalate uses "cheaper models as initial judges and escalate[s] to stronger models only when necessary". It "guarantees over 80% human agreement with almost 80% test coverage", while "GPT-4 almost never achieves 80% human agreement" alone. Roughly a fifth of cases are left unanswered in exchange for that guarantee (VERIFIED_DOC, arXiv 2024-07-25) — [Source](https://arxiv.org/abs/2407.18370)

**Event-triggered or filtered VLM calls in video**
- BLUE: "an estimated 53% reduction in VLM calls through packet-size-based frame skipping", with "no measurable degradation in semantic inference quality". The share of skip-heavy P-frames on CHAD rises from 1.4% to 53.2% (VERIFIED_DOC, arXiv 2026-07, per ID 2607.19515) — [Source](https://arxiv.org/abs/2607.19515)
- Cerberus "combines lightweight filtering with fine-grained VLM reasoning during online inference". It runs at "57.68 fps on an NVIDIA L40S GPU", a reported 151.79× speed-up, with "97.2% accuracy comparable to the state-of-the-art VLM-based VAD methods" (VERIFIED_DOC, arXiv 2025-10-18) — [Source](https://arxiv.org/abs/2510.16290)
- GHR-VLM: "a lightweight edge-based monitor continuously tracks door status and segments passenger clips". The system invokes "the VLM only on grounded passenger clips and contact sheets"; the saving is not quantified (VERIFIED_DOC, arXiv 2026-07-15) — [Source](https://arxiv.org/abs/2607.13569)
- Zelda "prunes similar frames" using VLM embeddings and "retrieves results 7.5x (up to 10.4x) faster for the same accuracy" (VERIFIED_DOC, arXiv 2023-05-05) — [Source](https://arxiv.org/abs/2305.03785)
- StreamMind invokes the LLM "only when relevant events occur" and runs at 100 fps on an A100 (VERIFIED_DOC, arXiv 2025-03-08) — [Source](https://arxiv.org/abs/2503.06220)
- DirCast scans at low resolution every second and reads the chosen camera at high resolution before speaking (VERIFIED_DOC, arXiv 2026-10-22) — [Source](https://arxiv.org/abs/2610.31734)
- Gameplay narration packs 9 frames into one 3x3 image, about 9x fewer image payloads per minute, at the cost of "resolution loss from mosaicking" and "hallucinated game state" (VERIFIED_DOC, arXiv 2026-08-14) — [Source](https://arxiv.org/abs/2608.14016)
- StreamClarify's binary pre-answer entropy gives more than 18 points higher precision than random selection (VERIFIED_DOC, arXiv 2026-10-31) — [Source](https://arxiv.org/abs/2611.01263)

**Current FaZeTime gate (repo)**
- Proposer stage 1 is a "Cheap deterministic pre-filter on the last ~60 s of transcript ... both known participants (alias-matched, e.g. 'face Gavin') plus a challenge keyword ('1v1', 'fight', 'versus'...)". It returns `PREFILTER_MISS` when fewer than 2 names appear or no keyword matches. Further local gates check the fingerprint, whether another market is open, and for countdown / slain / spoken-winner text (VERIFIED_DOC, repo file read 2026-11-14) — [proposer.py](../../services/worker/fazetime_worker/proposer.py)

### Inferences
- INFERRED: a proposed tiered gate for generic mode, cheapest first:
  - Tier 0 (local, free, always on):
    - An ASR lexicon of generic contest cues: "1v1", "race", "versus/vs", "first to", "best of", "who wins", "bet", "loser has to", "next round", "let's go again", "countdown".
    - Known names as score boosters, not hard requirements.
    - Scene change or frame-hash difference, since round boundaries, lobbies and loading screens are where setups happen.
    - Fixed-region OCR where a layout is known.
  - Tier 1 (remote, cheap): a "bettable setup?" check on a `low` media-resolution frame (about 264 tokens) plus the last ~30–60 s of transcript. Structured output: a binary answer, contest_kind, an abstain reason, and whether it already started. It runs only when tier 0 fires, plus a heartbeat every 2–5 minutes, under a hard hourly cap with backoff after NO.
  - Tier 2: the existing proposer at default resolution, followed by deterministic validation.
  - Tier 3: operator approval, which stays the default.
- INFERRED, budget arithmetic using the given 2 s per call and about 264 or 1,100 image tokens:
  - A fixed 30 s heartbeat is 120 calls per hour and 2,880 per day. That is about 32k image tokens per hour at `low` and about 132k at default, before transcript text.
  - A 20 s period is 180 calls per hour.
  - The free-tier RPM/RPD are unknown, so any fixed short period could exhaust a daily cap during a demo day. An event-triggered design with a slow heartbeat keeps calls in the tens per hour.
- INFERRED, on latency: about 4 s of ASR window, about 2 s per model call and 2 s frame spacing put the time from announcement to candidate at roughly 10 s. That is well inside the 45 s minimum lead, so detection latency is not the bottleneck. The bottleneck is whether players announce at least 45 s before they start. Round boundaries, lobbies and countdowns give natural lead time.
- INFERRED, robustness of gate signals in game streams:
  - ASR keywords catch announced contests well. They miss slang ("run it", "you and me") and mangled gamer tags, which is why aliases are needed.
  - Fixed-region OCR (chat death messages, timers, scoreboards) is precise within one game and layout but fails when the game changes. Peggle, for example, has no chat death messages, which is exactly the owner's worry.
  - Scene change is game-agnostic but fires on overlays and camera cuts, so use it as a trigger and never as evidence.
  - Audio energy and cheering, and chat velocity, react after events. They are good at timing resolution checks and poor at detecting setups beforehand, and chat is untrusted.
- INFERRED, the main false-negative risk: today's gate needs both known names and a fight keyword. Any game change, phrasing change or name mis-transcription produces `PREFILTER_MISS`, and the proposer never runs. That matches the owner's worry. Relaxing to names-or-generic-cues behind a tier-1 check trades more model calls (which can be capped) for recall, and approval mode still protects against bad proposals.
- INFERRED, on the side session's "~1k-token periodic pass": the cost per call is fine. The schedule is the risk. Make it event-triggered with a slow heartbeat, and keep the existing deterministic pre-filter as the fast path for the Minecraft demo.

### Gaps
- None of the cascade papers report false-negative rates for event triggers in game streams. BLUE and Cerberus are surveillance or anomaly detection, and Trust-or-Escalate is LLM-as-judge.
- Gemini free-tier RPM/RPD are unknown. Per-image token costs were taken from the task context, not verified here.
- Whisper tiny.en word error rates on gaming speech and gamer tags were not researched.

## 4. How do long-stream agents keep state and memory, and how do we avoid re-proposing an episode or proposing on stale context?

### Takeaway
Streaming agents keep a bounded recent window plus a compact structured memory: event summaries, timestamped captions, change records, or KV-cache retrieval. The newest work explicitly filters near-duplicate outputs, as in ProV-Mem's episodic memory. FaZeTime's per-run fingerprint `h2h:<sorted pair>:<challenge>` is a sound primitive for deduplication. It has two weaknesses:
- It blocks legitimate rematches within a run.
- It does not generalize beyond H2H.

A generic fingerprint should combine game, contest kind, sides and a round or attempt number. It should be paired with a "last market" state card and the existing 90 s evidence-freshness and epoch checks.

### Cited Findings
**Memory designs in long-stream video agents**
- MovieChat applies "the Atkinson-Shiffrin memory model, with tokens in Transformers being employed as the carriers of memory" (short- and long-term memory). It comes with MovieChat-1K: 1K long videos and 14K annotations (VERIFIED_DOC, arXiv 2023-07-31) — [Source](https://arxiv.org/abs/2307.16449)
- Flash-VStream "simulates the memory mechanism of human" and "achieves significant reductions in inference latency and VRAM consumption" (VERIFIED_DOC, arXiv 2024-06-12) — [Source](https://arxiv.org/abs/2406.08085)
- ReKV stores "processed video key-value caches (KV-Caches) in RAM and disk, reloading them into GPU memory as needed", with retrieval and "a sliding-window attention mechanism" (VERIFIED_DOC, arXiv 2025-03-01) — [Source](https://arxiv.org/abs/2503.00540)
- VideoAgent "constructs a structured memory to store both the generic temporal event descriptions" and object memory, queried through tools. It reports +6.6% on NExT-QA and +26.0% on EgoSchema (VERIFIED_DOC, arXiv 2024-03-18) — [Source](https://arxiv.org/abs/2403.11481)
- AVA builds "Event Knowledge Graphs (EKGs) for efficient indexing of long or continuous video streams". It reports 62.3% on LVBench, 64.1% on VideoMME-Long and 75.8% on AVA-100 (VERIFIED_DOC, arXiv 2025-05-01) — [Source](https://arxiv.org/abs/2505.00254)

**Proactive memory and de-duplication**
- ProV-Mem: "a temporal-trigger memory controls when to query the backbone and recovers from prolonged silence", and "an episodic memory determines whether to emit by filtering near-duplicate responses" (VERIFIED_DOC, arXiv 2026-10-15) — [Source](https://arxiv.org/abs/2610.23998)
- OneStreamer "produces time-grounded local-detail captions and summaries of completed events". "model-generated records complement a recent visual window", and it selects "state-change and state-persistence tokens" (VERIFIED_DOC, arXiv 2026-10-01) — [Source](https://arxiv.org/abs/2610.01762)
- TimeTraveler "stores each observed moment as a timestamp-indexed structured caption" (VERIFIED_DOC, arXiv 2026-11-07) — [Source](https://arxiv.org/abs/2611.10337)
- DeltaStreamer "continuously observes the stream and explicitly records visual changes in structured memory", with overall scores of 66.07% and 59.53% (VERIFIED_DOC, arXiv 2026-10-14) — [Source](https://arxiv.org/abs/2610.19849)
- TwinPast: in OVO-Bench and StreamingBench, "recent frames suffice for 32% of sampled historical questions" (VERIFIED_DOC, arXiv 2026-10-30) — [Source](https://arxiv.org/abs/2610.41983)
- Video-MemComp allocates the KV budget dynamically, "saving over 90% of KV memory", and raises Qwen2.5-VL-3B from 62.3% to 64.1% (VERIFIED_DOC, arXiv 2026-10-23) — [Source](https://arxiv.org/abs/2610.32784)
- MaLoW consolidates observations "into fixed-size LoRA weights" and reports +3.9% to 11.8% over prior memory approaches (VERIFIED_DOC, arXiv 2026-10-15) — [Source](https://arxiv.org/abs/2610.22070)
- ReMem's "Streaming Context Memory (SCM) continuously compresses historical context" (VERIFIED_DOC, arXiv 2026-10-05) — [Source](https://arxiv.org/abs/2610.05940)
- AURA 2.0 adds "Long-Horizon Interaction Memory (LHIM) to maintain contextual continuity" for model-initiated conversation (VERIFIED_DOC, arXiv 2026-11-12) — [Source](https://arxiv.org/abs/2611.17048)
- MemInStream separates memory limitations from understanding failures (VERIFIED_DOC, arXiv 2026-11-11) — [Source](https://arxiv.org/abs/2611.15640)
- APM-Bench reports a "clear utility--latency--storage trade-off" for persistent memory (VERIFIED_DOC, arXiv 2026-09-29) — [Source](https://arxiv.org/abs/2609.37559)

**Current FaZeTime dedupe and staleness rules (repo)**
- `fingerprint(subjects, challenge)` returns `"h2h:" + "|".join(sorted(s.lower() for s in subjects)) + ":" + challenge`, for example `h2h:fazegavin|fazeneville:minecraft-1v1`. The proposer prompt includes the last 10 used or rejected fingerprints (VERIFIED_DOC, repo file read 2026-11-14) — [proposer.py](../../services/worker/fazetime_worker/proposer.py)
- Contract §9.17 (VERIFIED_DOC, repo file read 2026-11-14) — [CONTRACTS.md §9.17](../../docs/CONTRACTS.md):
  - An episode is consumed by a PENDING, SHADOW, OPENED, EXPIRED or operator-rejected candidate. A validation rejection does not consume it.
  - Cited evidence must belong to the current epoch and arrive "within the last 90 s" (`STALE_EVIDENCE`). The 90 s limit is rechecked at approval, so the operator must approve within 90 s of the oldest evidence and 60 s of receipt.
  - Close is anchored at receipt time.
  - "Each recording take uses the same episode fingerprint, so the operator must reset the run between takes" (`DUPLICATE_EPISODE`).

### Inferences
- INFERRED: the current fingerprint has the right shape: canonical, run-scoped and consumed on proposal. Its key is too coarse for a real stream, though. A best-of-3, or a second 1v1 after the first resolves, maps to the same key and is rejected as `DUPLICATE_EPISODE`. A generic key could be `gen:<game_slug>|<contest_kind>|<sorted sides>|<ordinal>`. The ordinal would increment only when three things hold: the previous market for that key is terminal, a fresh announcement cites evidence after the previous market's terminal media time, and a scene change or round boundary sits between them. This reuses ProV-Mem's idea of filtering near-duplicates by episode while still allowing genuine rematches.
- INFERRED: to stop the proposer acting on stale context, give each tier-1 or tier-2 call a compact state card. Following OneStreamer's "summaries of completed events" plus recent window, it would hold the current game guess, the last market's question, state and terminal media time, recently used fingerprints, the time of the last scene change, and whether a contest is believed to be in progress. Require every cited evidence ID to come after the last terminal market. Summaries are model output, and therefore untrusted. They are context only and never evidence; the existing rule that evidence IDs point to raw observations already enforces this.
- INFERRED: TwinPast finds that recent frames alone answer about a third of "historical" questions. For FaZeTime's narrow job (is a contest announced, has it started, is an outcome visible), a short recent window, about 60 s of transcript plus 1–3 frames, and the state card are enough. Heavy memory architectures such as KV retrieval, LoRA memory or EKGs are out of scope for the remaining time.
- INFERRED: the past-tense, "already started" and "outcome visible" abstentions, the epoch check and the 90 s freshness rule together already cover most stale-context risks, including recaps like "remember when Gavin beat Neville". Generic mode needs these same rules plus the START condition from Q2, so that a contest already underway is never proposed.
- INFERRED, on the side session's "switchable generic mode that keeps the Minecraft path for judging": this has strong support. The deterministic H2H_WINNER_V1 path plus the death-message resolver is the only path with a precise evidence channel. Generic mode should be a separate template ID with its own fingerprint namespace, default to SHADOW or approval, and leave the judged path's code untouched.

### Gaps
- No paper addresses deduplicating repeated real-world contest episodes, such as rematches, for proposing bets. The fingerprint design here is my own reasoning from ProV-Mem-style near-duplicate filtering and the repo contract.
- Memory systems' latency and footprint on a Raspberry Pi 5 were not researched. All the cited systems run on GPUs.
- I did not check whether the backend contract allows a template other than H2H_WINNER_V1, or other fingerprint prefixes, without a contract change. Only the §9.17 lines on fingerprints, staleness and episodes were read.
