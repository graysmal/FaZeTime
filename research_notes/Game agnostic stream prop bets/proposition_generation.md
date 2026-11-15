# Game-agnostic binary proposition generation from a live game stream

Desk research on 2026-11-15 using web search and fetch only. Each source's date is given in parentheses. "Excerpt" means the claim was seen only in a search-result summary and the page was not opened, so treat it as lower confidence. All rule texts are paraphrased.

## Q1. Which proposition taxonomy generalizes across games, and what do real markets list?

### Takeaway
Markets from sportsbooks, esports books, prediction markets and Twitch Predictions nearly all reduce to a few shapes, each tied to one discrete unit of play:
- episode outcome
- a threshold (over/under) on a counted or displayed number
- whether an event occurs in a bounded window
- a race ("which happens first")
- whether a word is spoken
- parity (odd/even)

Kalshi already defines that unit of play generically across titles: one "map" is any single completed game instance. A game-agnostic system needs the same abstraction, called an "episode" in these notes.

### Cited Findings
- **Twitch Predictions API limits.**
  - A prediction has 2 to 10 outcomes.
  - Its status moves from ACTIVE to LOCKED, then to RESOLVED or CANCELED. A LOCKED prediction still needs a winner to be chosen, or it must be cancelled.
  - Cancelling returns everyone's points. If no winner is chosen within 24 hours, the points are returned automatically.
  - A channel can run only one prediction at a time.
  - The documentation's examples use prediction windows of 60, 200 and 300 s.
  - Source: [Twitch Developers – Predictions guide](https://dev.twitch.tv/docs/api/predictions) (undated, accessed 2026-11-15).
- **Twitch's launch example.** At the 2020 soft launch, Twitch's example was whether a streamer would reach a given number of eliminations (a threshold prop). Correct predictors split all the points spent, and creators set the submission period. Source: [SlashGear](https://www.slashgear.com/twitch-is-rolling-out-a-new-points-feature-for-predicting-achievements-15647305) (Nov 2020).
- **How streamers use Predictions.** This is a commercial guide, so weigh it lightly. It lists these patterns:
  - win or lose this match
  - placement brackets (top 5, 10 or 25)
  - over/under on kills (for example, 7)
  - first elimination, winning the pistol round, topping frags or damage
  - ranking up or down today
  - speedruns: beating the personal best, time brackets, gold on a split, number of resets
  - horror games: a jump scare in the next 5 minutes, dying in a section
  - story games: which dialogue choice, whether a character survives, a first-try boss kill, which ending
  - Just Chatting: whether a guest appears, whether the stream runs past midnight

  Source: [BestTwitchExtensions predictions guide](https://besttwitchextensions-com.pages.dev/articles/twitch-predictions-complete-guide.html) (2025-12-24).
- **Polymarket esports markets.** One Counter-Strike 2 best-of-three event (1WIN vs WW Team) listed:
  - match winner
  - winner of each of maps 1 to 3
  - odd/even total rounds per map
  - odd/even total kills per map
  - a map handicap of −1.5/+1.5
  - games total over/under 2.5

  Source: [Polymarket event JSON (Gamma API)](https://gamma-api.polymarket.com/events?slug=cs2-1win-ww-2026-04-05) (event 2026-04-05).
- **Esports in-play micro-markets (sportsbooks and data feeds).**
  - PandaScore's micro-betting covers the next kill, the first tower, and whether a specific player uses a specific ability at a certain point. Source: [Dot Esports on PandaScore](https://dotesports.com/betting/esports/news/pandascore-microbetting-tool-moba) (excerpt, undated).
  - Books using official data build markets around first blood, player total kills, duels, headshots and assists. Source: [GRID](https://grid.gg/esports-in-play-betting-the-opportunity-sportsbooks-are-still-missing/) (excerpt, undated).
  - Oddin reports that live (in-play) bets reached 86% of bets in its traders' data. Source: [Oddin 2025 Esports Betting Review](https://oddin.gg/cdn/Oddin_gg_2025_Esports_Betting_Review_EN_c24ec97ec1.pdf) (excerpt, 2025).
- **Speech props as a real market type.** Kalshi's mention contract is a template: a named speaker says a named word during a named time period. It can require a minimum number of times, or accept any of several alternative words (its example is Doge/Dogecoin). Source: [Kalshi MENTION contract terms](https://kalshi-public-docs.s3.amazonaws.com/contract_terms/MENTION.pdf) (PDF generated 2026-05-06).
- **A generic unit of play.** Kalshi's ESPORTSMAPS terms define a "map" as one completed game instance within a match or series, whatever the title calls it (a "game" in LoL or Dota, a "map" in CS or Valorant, sometimes a "round"). Strikes are above, below, exactly, at least, or between. Source: [Kalshi ESPORTSMAPS contract terms](https://kalshi-public-docs.s3.amazonaws.com/contract_terms/ESPORTSMAPS.pdf) (PDF generated 2026-08-06).

### Inferences
- **A generic taxonomy that covers all the examples above:**
  - **A. Episode outcome.** Win or lose, clear or fail, survive or die, as with a moneyline or map winner.
  - **B. Threshold on a displayed number at episode end.** Totals and handicaps, placement, game clock, timer, score, HP, balls or lives left.
  - **C. Occurrence of a salient event inside an episode or time window.** First blood, a jump scare in the next 5 minutes, a "GAME OVER" or "FINAL ROUND" banner.
  - **D. Race.** First blood, first tower, first to N.
  - **E. Speech or mention.**
  - **F. Parity (odd/even) of a final displayed total.** Balanced by construction, but low drama.
  - **G. Streamer choice.** A story choice or a character pick, which the streamer controls.
- **Episode as the unit.** An episode is an attempt, round, game, level, run, hand or fight. It plays the role of Kalshi's generic "map". Every proposition should bind to exactly one episode instance, or to one explicit window measured in stream time.
- **Micro-markets depend on official low-latency data.** Next kill and ability use only work with official data feeds. They are the least transferable to sparse frames and should not be copied directly.
- **Twitch's API shape is a good default contract.** One open prediction per channel, binary outcomes, a bounded betting window, and an automatic refund if it is never resolved.

### Gaps
- I could not open the official Twitch help article. The limits of 45 characters per title, 25 per outcome, and a 30 s to 30 min window come only from the commercial guide. The developer page I fetched did not state them.
- I found no dataset of real Twitch prediction titles that shows how often each type is used.

## Q2. How do professional market makers write unambiguous resolution rules?

### Takeaway
Professional rules are parameterized templates. Each has:
- a named resolution source, ranked fallbacks, and a deadline after which the fallback applies
- an exact unit definition with explicit inclusions and exclusions
- comparison operators defined mathematically
- stated inclusive or exclusive window endpoints
- a list of edge cases (cancel, postpone, forfeit, remake, tie, format change, data unavailable), each mapped to a neutral outcome: 50-50, void, or last fair price
- a finality clause: revisions after expiry are ignored

### Cited Findings
- **Polymarket CS2 match winner.** Source: [Polymarket event JSON](https://gamma-api.polymarket.com/events?slug=cs2-1win-ww-2026-04-05) (2026-04-05; paraphrased by a summarizer from the market descriptions).
  - A match that is cancelled, tied, or delayed more than 7 days without a winner resolves 50-50.
  - If a team wins by forfeit, disqualification or walkover after the match starts, that team wins.
  - If a team withdraws before the start, the market resolves 50-50.
  - HLTV is the resolution source. If HLTV has not posted a final result within 2 hours of the end, a consensus of credible reporting, including video, may be used.
  - Minor name variants, such as abbreviations or sponsor tags, are matched to the intended team.
  - The event-level `resolutionSource` field is a Twitch channel URL. The market-level fields point to hltv.org.
- **Polymarket map-level markets** (same source):
  - A map winner market resolves 50-50 if that map is not completed for any reason.
  - Odd/even total rounds includes overtime rounds. A map that is never played, or is skipped because the series was already decided, resolves 50-50. If a map is remade, only the remake counts.
  - Odd/even total kills excludes team kills and self-inflicted deaths.
- **Third-party guides on Polymarket esports.** Markets settle on official tournament results, usually within minutes. A forfeit before the match resolves 50-50. Source: [StartPolymarket guide](https://startpolymarket.com/guides/polymarket-esports/) (third-party, undated).
- **Kalshi mention rules.** Source: [Kalshi MENTION terms](https://kalshi-public-docs.s3.amazonaws.com/contract_terms/MENTION.pdf) (PDF generated 2026-05-06).
  - **Word forms.**
    - The word must appear as a standalone unit.
    - Plural and possessive forms count.
    - Changes of tense, conjugation or derivation do not count. For example, "run" is not matched by "running" or "ran".
    - If the contract names a plural, the singular does not count.
  - **Compounds and sound-alikes.**
    - Open and hyphenated compounds count, but closed compounds do not ("fire" is not matched by "wildfire").
    - Homophones do not count. Homographs count whatever their meaning.
    - Minor unintentional mispronunciations count when the intent is clear.
    - Merriam-Webster and the OED settle disputes about compound type.
  - **Source and timing.**
    - Sources are ranked. A lower-ranked source is used only if higher ones are unavailable or insufficient.
    - A market on a live-stream or broadcast event may stay open 24 hours so an official recording can be released.
    - A cancelled event resolves to the "does not occur" strike if one is listed, otherwise to the last fair price.
    - A postponement announced to fall within 14 days keeps the market open.
    - Revisions after expiration are ignored.
- **Kalshi ESPORTSMAPS rules.** Source: [Kalshi ESPORTSMAPS terms](https://kalshi-public-docs.s3.amazonaws.com/contract_terms/ESPORTSMAPS.pdf) (PDF generated 2026-08-06).
  - **Operators.** "Above" means >, "below" means <, "exactly" means =, "at least" means ≥, and "between" is inclusive.
  - **Sources, ranked.** Organizer or league operator, then the official broadcast, then the official website or statistics platform.
  - **What counts as a map.**
    - Only completed maps count, including maps awarded by technical forfeit or admin decision.
    - A map restarted from the beginning counts once.
    - An overtime map is one map.
    - Showmatches do not count.
  - **Delays.** A series that does not start within 48 hours may resolve at the last fair price.
- **Sportsbook in-game settlement.** Midnite settles first blood on the game's own "First Blood" announcement. Its esports-specific rules override its general rules. Source: [Midnite esport rules](https://intercom.help/midnite/en/articles/2686555-general-esport-betting-rules) (excerpt, undated).
- **Sportsbook void rules (Rivalry).** Source: [Rivalry betting rules](https://rivalry-app-next-www3.pages.dev/au/bet-rules) (excerpt, undated; a direct fetch returned no rule text).
  - Bets are void if a fixture is listed with the wrong number of maps or rounds, unless this was disclosed or does not affect the market (first blood, for example).
  - If a team retires, gets an admin win, or is disqualified before all scheduled rounds of a map, bets on that map are void.
  - In Dota 2, a disconnect in the first 10 minutes without reconnection or replacement voids the map.
  - The CS2 change from a 15-round to a 12-round format voided affected markets.
  - Market rules take precedence over sport rules, which take precedence over general rules.
- **Disputes and regulation of mention markets.**
  - NPR reported a federal probe of mention markets. Source: [NPR](https://www.npr.org/2026/08/13/nx-s1-5930689/cftc-probe-mention-markets-prediction-markets-kalshi) (2026-08-13).
  - DeFi Rate reported that Kalshi pulled its sports mention markets amid a reported CFTC probe. Source: [DeFi Rate](https://defirate.com/?p=18128) (2026, exact date not seen).
  - A headline reports Kalshi language disputes over payouts. Source: [texxr](https://texxr.com/1166121/kalshi-faces-language-disputes-over-payouts) (headline only).

### Inferences
- **Map the professional pattern onto the system.**
  - **Source.** The Twitch stream itself, with channels ranked as follows:
    1. Result screen or HUD text in frames after lock.
    2. A clear verbal statement by the streamer, corroborated by a frame.
    3. Operator approval.
  - **Fallback deadline.** For example, 120 s after the expected episode end. After that the market is voided and refunded, which is the pari-mutuel equivalent of Polymarket's 50-50.
- **Fixed edge-case clauses for every template:**
  - The episode is abandoned or restarted. Only the completed instance counts; otherwise void.
  - The game or category changes, or the stream is offline longer than N seconds.
  - A tie or draw is mapped explicitly.
  - The decisive evidence is illegible.
  - The decisive evidence appeared before lock.
- **Speech props need a deterministic word matcher.** Codify Kalshi-style word-form rules as a regex: the word plus plural and possessive suffixes, open or hyphenated compounds, nothing else. Add an ASR clause: the system transcript is the source, and garbled or missing audio voids the market.
- **Word props cause disputes even with long rules.** Mention markets show this. Keep the matching simple and visible, and label speech props as for fun or controllable by the streamer.

### Gaps
- I did not see full Rivalry or Midnite rule text, or any sportsbook's exact past-posting (late bet) clause.
- The Polymarket rules above were paraphrased from the API's description fields by a summarizer, not copied verbatim.

## Q3. What does 2023–2026 research say about LLM-generated forecasting questions?

### Takeaway
LLM pipelines only produce usable, resolvable questions with heavy filtering:
- **FutureSearch (Jan 2026)** kept 1,499 of 14,073 refined candidates after four verifier agents and deduplication. Experts accepted 75.2%, and the resolution error rate was about 4.9%.
- **Chandak et al. (Dec 2025)** found about 60% of generated candidates invalid, and over 40% of selected ones initially leaked the answer.

The failure modes that transfer to this system are:
- invented resolution sources
- ambiguity
- answer leakage, meaning questions whose answer is already known
- wrong NO resolutions based on absence of evidence
- a yes-bias in model probabilities
- errors shared across model ensembles

### Cited Findings
- **FutureSearch pipeline.** Source: [Bosse et al., FutureSearch, arXiv 2601.22444](https://arxiv.org/abs/2601.22444) (2026-01-30).
  1. 2,500 news seeds go to a web-research ReAct agent, which proposes 1 to 7 proto-questions per seed.
  2. A refiner agent adds precise resolution criteria, giving 14,073 questions.
  3. Four separate verifier agents check quality, ambiguity, resolvability and triviality.
  4. Embedding plus DBSCAN clustering removes duplicates, with an LLM confirming them. 1,499 questions remain.
- **FutureSearch verifier criteria and prompt rules** (same source):
  - Quality and ambiguity are graded bad, meh, good or great, and both must be "great".
  - For resolvability, a resolver agent must answer "very certainly yes".
  - For triviality, a simple forecaster's probability is checked. The authors planned to drop questions below 2% or above 98%, but kept them because there were few.
  - Prompts required every term to be defined, UTC timestamps, a start date, and a resolution source that will still exist on the resolution date.
- **FutureSearch resolution and results** (same source):
  - Three Gemini 3 Pro agents resolve each question, and an Opus 4.5 agent breaks ties.
  - Of 149 questions rated by experts, 75.2% were accepted, 16.8% soft-rejected and 8.1% hard-rejected.
  - A manual check estimated the resolution error rate at about 4.9% (95% CI 1.6–9.8%).
  - The annulment rate was about 3.9%, against about 8% historically at Metaculus.
  - 29.1% of questions resolved YES.
- **FutureSearch failure modes** (same source):
  - "Will X happen within 3 months of an announcement" questions almost always resolve NO.
  - Resolvers wrongly resolve NO when they cannot find evidence that something happened.
  - Resolvers accept search snippets without checking that the source meets the criteria, so they rarely annul.
  - Resolver errors are correlated across models, and plurality voting cannot fully fix this.
  - Without research, models propose plausible but invalid questions and invent resolution sources.
  - Model forecasts show a yes-bias: mean forecasts of 0.37–0.42 against a 29.2% base rate.
- **Chandak et al. generation and filtering.** Source: [Chandak, Goel, Prabhu, Hardt, Geiping, arXiv 2512.25070](https://arxiv.org/abs/2512.25070) (2025-12-31).
  - The pipeline produced 744,963 candidate questions from CommonCrawl News.
  - About 40% passed the validity check. The main reason for failure was that the article did not clearly resolve the question.
  - Over 40% of selected questions initially contained the answer string. Rewriting or rejecting them removed about 90% of those cases.
  - Manual test-set filters also removed questions with multiple valid answers, questions that resolve too early, and questions about established facts.
  - The generator had to produce questions that are forward-looking and have a definite, unambiguous answer that can be resolved.
- **ForecastBench.** It is an automatically generated and regularly updated set of 1,000 forecasting questions. To prevent leakage, it includes only questions about future events with no known answer when forecasts are submitted. Source: [Karger et al., ForecastBench, arXiv 2409.19839](https://arxiv.org/abs/2409.19839) (v1 2024-09-30; v5 2025-02-28).
- **Consistency checks.** Related work exists on consistency checks for LLM forecasters. Source: [Paleka et al., arXiv 2412.18544](https://arxiv.org/abs/2412.18544) (title only; not read).

### Inferences
- **Free-form generation is risky.** Even with web research and four critic agents, about a quarter of questions were not fully accepted by experts. That supports slot-filled templates, where the LLM picks a template and fills its slots, over free-form wording.
- **Cheap structural guards before spending LLM calls on critique.** Each one targets a failure mode from the papers:
  - **Evidence anchor** (against invented sources). The referenced number, text or phrase must appear in recent evidence.
  - **Window that starts at lock** (against leakage or an already-known answer).
  - **Proof of coverage before resolving NO** (against wrong absence-of-evidence resolutions).
  - **Independent evidence channels** (against correlated model errors). Use OCR and ASR rather than several LLM votes.
  - **Bounded, ordinal use of the LLM's P(YES)** (against yes-bias).
- **Collapse the critique into one call.** Free hosted tiers limit requests per day; the model verified for this project allows 500 a day. FutureSearch's four verifier calls per question therefore cannot be afforded. Use one structured generation call with self-check fields, followed by deterministic validators. Add a second "how could this be disputed?" call only when budget allows.

### Gaps
- I found no paper on generating bets or props from live video or game streams.
- I found no measured ambiguity or dispute rates for short-horizon micro-props.

## Q4. Do products (2024–2026) auto-generate predictions from live streams or game data, and are any game-agnostic?

### Takeaway
The automatic prediction tools I found are tied to one game or platform and driven by its data feed: FACEIT, StarCraft II, Lichess, the Riot API. The only one that suggests predictions with AI, a hackathon project from July 2025, still needed human validation. AI "market generator" products from 2026 serve prediction-market operators and keep a human approval step. I found nothing that is game-agnostic and works from video plus speech.

### Cited Findings
- **FACEITSync.** It automatically creates and resolves Twitch Predictions when a FACEIT match starts, using FACEIT match data. It needs an Affiliate or Partner channel, with its bot added as a moderator. Sources: [FACEITSync automatic predictions](https://faceitsync.com/features/automatic-predictions) (excerpt; direct fetch returned 403); [FACEITSync 2026 guide](https://faceitsync.com/el/blog/guide/connect-faceit-and-twitch-automation-2026) (2026-02-17).
- **Foresee.** This open-source StarCraft II tool starts a Twitch prediction named after the in-game players when a 1v1 begins, and resolves it when the game ends. Source: [Foresee repository](https://uithub.com/leigholiver/foresee/tree/main) (excerpt, undated).
- **twitch-lichess-predictions.** A project with this name exists for chess, using Lichess. Source: [Ecosyste.ms listing](https://awesome.ecosyste.ms/projects/github.com%2Fferencovonmatterhorn%2Ftwitch-lichess-predictions) (title only).
- **PredictionLive.** This Chrome extension and backend ran ultra-short esports predictions inside Twitch, such as "who scores next?". Source: [PredictionLive on Devfolio](https://devfolio.co/projects/predictionlive-c0f8) (2025-07-13, Hacking Paris / Chiliz).
  - An AI layer parsed Riot API match logs (score, round, killfeed) to suggest predictions and detect outcomes.
  - The logs arrived 1–2 minutes late.
  - Betting closed about 4 s after each prediction was pushed, and late transactions were rejected.
  - AI suggestions and results still needed human validation. The team named data delay and the lack of publisher licensing as obstacles.
- **Streamer.bot.** It has actions to create a Twitch prediction and resolve the last one, which can be wired to other triggers. Source: [Streamer.bot docs](https://docs.streamer.bot/api/sub-actions/twitch/predictions/create-prediction) (v0.2.5).
- **K25.ai.** This Singapore start-up raised $2M (reported May 2026). It describes itself as an AI-native live-streaming and watch-to-predict platform. I could not confirm that its AI generates markets from stream content. Sources: [Signalbase](https://www.trysignalbase.com/news/funding/k25ai-secures-2); [AI Market Watch profile](https://www.ai-market-watch.com/company/k25-ai).
- **Vinfotech AI market generator** (vendor marketing). Source: [Vinfotech](https://www.vinfotech.com/insights/ai-market-generator-prediction-market-content-bottleneck) (2026-05-11).
  - It outputs titles, options, deadlines and resolution direction.
  - Quality checks flag weak, vague, repetitive or low-value questions.
  - Operators review and approve candidates, and nothing is auto-published.
  - Settlement is handled by a separate resolver.
- **TrueIGTech.** A press release announced an AI-powered market creation and auto-settlement engine for prediction-market operators. Source: [TrueIGTech press release](https://stocks.observer-reporter.com/observerreporter/article/abnewswire-2026-3-19-trueigtech-unveils-ai-powered-market-creation-and-auto-settlement-engine-for-prediction-market-operators) (2026-03-19; headline only).
- **Broadcast delay.** PandaScore says public broadcast streams on Twitch and YouTube carry a 3–4 minute delay, which makes them unsuitable for in-play models, so it sells a low-latency feed. This refers to professional esports broadcasts, which add a deliberate delay. Sources: [PandaScore odds](https://www.pandascore.co/odds); [Dot Esports](https://dotesports.com/betting/esports/news/pandascore-microbetting-tool-moba) (both excerpts; which of the two pages makes the claim is uncertain).

### Inferences
- **The approach appears novel, as far as this search reached.** A game-agnostic proposer working from the screen and the streamer's speech fills a real gap. It cannot lean on an authoritative data feed, so it must void more often than feed-driven tools.
- **Human approval is the industry norm.** Vinfotech and PredictionLive both keep it, which supports keeping approval mode available beside auto mode.
- **Streamer.bot and FACEITSync show the lifecycle to copy.** Each creates on match start, locks, and resolves on a terminal event.

### Gaps
- FACEITSync's docs (403 and a DNS failure) and the Foresee code could not be inspected, so their lock timing and handling of edge cases are unknown.
- I did not verify K25.ai's actual mechanism.

## Q5. How can bettable moments be detected without game-specific code, and how should lock deadlines and horizons be set?

### Takeaway
Bettable moments are episode boundaries and speech cues:
- **Episode boundaries:** lobby, queue, loading screen, countdown, a "Round N" or "Fight" splash, a new run, a level start, the door to a boss.
- **Speech cues:** explicit invitations, or subtle ones.

Betting must lock before any viewer could see a decisive event. Sportsbooks achieve this with market suspensions and 1–5 s bet delays on streams that run 5–8 s behind. This system lags roughly 10–20 s from event to evidence. It should therefore:
- usually propose during an intermission, for the next episode
- lock at or just after that episode starts
- require an outcome horizon several times longer than the lag
- void after the fact if the decisive evidence appears before lock plus a safety margin

### Cited Findings
- **Twitch guide timing advice.** Source: [BestTwitchExtensions guide](https://besttwitchextensions-com.pages.dev/articles/twitch-predictions-complete-guide.html) (2025-12-24, commercial).
  - **When to open:** good moments are queue times, loading screens, just before a boss, and stream milestones. Avoid opening mid-action.
  - **Window length:** 30–60 s for fast games, 2–3 min for most games, 5–10 min for story games.
  - **Cadence:** every 2–3 ranked matches, every battle-royale match, 2–4 per story session, and each speedrun attempt.
- **Sportsbook market suspension.** In-play markets are suspended the moment a triggering event happens, such as a goal, point or injury, until the price is recalculated. A market can also lock after a significant ball. Sources: [LukyCricket help](https://intercom.help/lukycricket/en/articles/16025404-live-in-play-betting-suspended-markets) (excerpt, undated); [MuddyRiverNews](https://muddyrivernews.com/gaming/how-in-play-betting-works-and-what-affects-the-odds-in-real-time/20260630081500/) (2026-06-30, excerpt).
- **Bet delay.** Vendor guides describe a deliberate 1–5 s hold on in-play bets, so a bet can be rejected if a goal happens during the delay. Sources: [SourceCodeLab](https://sourcecodelab.co/?p=113700); [Track360](https://track360.io/blog/live-in-play-betting-trading-software-stack-operator-guide-2026) (vendor, 2026, excerpt; which of the two makes the claim is not verified).
- **Stream lag at sportsbooks.** Most operators deliver in-play betting alongside streams 5–8 s behind the event. The vendor claims its own product cuts this below 0.5 s. Source: [Stats Perform](https://www.statsperform.com/?p=33709) (vendor, excerpt, undated).
- **PredictionLive timing.** Betting closed about 4 s after a prediction was pushed. Match logs 1–2 minutes old made automatic triggering hard. Source: [PredictionLive](https://devfolio.co/projects/predictionlive-c0f8) (2025-07-13).
- **Resolution grace periods.** Twitch refunds automatically after 24 hours unresolved ([Twitch Developers](https://dev.twitch.tv/docs/api/predictions)). Kalshi may keep a live-stream mention market open 24 hours for an official recording ([Kalshi MENTION](https://kalshi-public-docs.s3.amazonaws.com/contract_terms/MENTION.pdf), 2026-05-06).
- **What vision-language models can see in game video.** VideoGameQA-Bench tested 16 models on 4,786 questions from over 800 games. Source: [Taesiri et al., VideoGameQA-Bench, arXiv 2505.15952](https://arxiv.org/abs/2505.15952) (May 2025; NeurIPS 2025 Datasets & Benchmarks).
  - The best model detected glitches in video 78.1% of the time.
  - The best model reached only 45.2% on fine-grained visual regression.
  - Locating when an event starts in a video was hard for the models.

### Inferences
- **A game-agnostic moment detector** that needs no per-game code. Run cheap signals on every media burst, and call the hosted model only when they fire:
  - **S1, explicit invitation in speech.** A regex over the last 2–3 ASR chunks for phrases like "do you (guys) think", "predict", "bet", "will I", "can I", "let's see if", "chat, …". The streamer's own question becomes the candidate, mapped onto a template.
  - **S2, subtle speech cues.** "here we go", "let's go", "lock in", "focus", "one more", "last try", "first try", "new run", "reset", "gg", "queue", "next game", "boss".
  - **S3, visual boundary.**
    - A large frame-to-frame difference followed by low motion, typical of loading screens and menus.
    - Big centred text.
    - Generic words found by OCR: ROUND, FIGHT, READY, START, LOADING, VICTORY, DEFEAT, GAME OVER, LEVEL, STAGE, WAVE, MATCH FOUND, YOU DIED, CHECKMATE, WIN, LOSE.
    - Countdown digits that decrease across frames.
    - A timer or score that resets to zero.
  - **S4, heartbeat.** If no market is open, a check every 3–5 minutes lets the model classify the current phase.
  - **Gate:** call only when no market is open, the daily quota remains, and a cooldown since the last proposal (for example, 2 minutes) has passed.
- **Lock and horizon defaults** (design values, not tested):
  - **Lag and margin.**
    - L_sys is the measured lag from a stream event to the system holding processed evidence: Twitch delay, plus about 6 s of burst delivery, plus ASR and model time.
    - The margin is M = max(15 s, L_sys).
  - **Betting window by situation.**
    - Explicit invitation: 30–60 s.
    - Intermission proposal for the next episode: lock at the earlier of now + 60–120 s and the detected start of the next episode, plus a small grace.
    - Proposal during a long episode (chess, story, speedrun): window = clamp(0.1–0.2 × expected remaining time, 30 s, 180 s).
  - **Reject short horizons.** Reject a candidate unless the time from lock to decisive evidence is expected to be at least 3 × M, roughly 45–60 s or more.
  - **Cap the horizon.** Use about 30 minutes, then void.
  - **Measure in stream time.** Express windows in stream timestamps rather than wall clock, so bursty delivery does not change the outcome.
  - **Void after the fact** if the first decisive evidence has a stream timestamp no later than the stream position at lock plus M.
- **The two streamer styles.**
  - **Inviting streamer:** S1 dominates. If the streamer's question cannot be verified ("will I have fun?"), substitute the nearest verifiable template ("win this game").
  - **Subtle streamer:** rely on S3 and S4, then S2. Default to Type A at episode starts, Type B when a large persistent number is in view, and Type E using words the streamer has already been using.

### Gaps
- I found no published, game-agnostic detector of episode boundaries for game video.
- I did not research Twitch viewer-latency figures here; the 10–20 s lag above comes from the task brief, not a source.
- I found no measurements of OCR reliability on 854×480 game HUDs.

## Q6. How should propositions be constrained to stay verifiable, and which types are verifiable from sparse frames plus ASR?

### Takeaway
Use slot-filled templates whose rules text is fixed, as Kalshi does. At proposal time, require:
- an evidence anchor: the number, text or phrase actually seen in recent evidence
- a resolution plan that names the channel and what YES, NO and the end of the episode will look like

Realistic verifiability from sparse frames plus ASR, from most to least reliable:
1. persistent end screens and large or frozen numbers
2. word tokens in the transcript
3. big centred announcement text
4. small HUD numbers
5. transient events, counts, and races between transient events

### Cited Findings
- **Kalshi's template model.** Kalshi lists each market as a filled instance of a fixed contract template, with placeholders such as speaker, word, time period, match type, operator and count. Every placeholder and edge case is defined once in the template. Sources: [Kalshi MENTION](https://kalshi-public-docs.s3.amazonaws.com/contract_terms/MENTION.pdf) (2026-05-06); [Kalshi ESPORTSMAPS](https://kalshi-public-docs.s3.amazonaws.com/contract_terms/ESPORTSMAPS.pdf) (2026-08-06).
- **Free-form failures.** Without research, models invent plausible but invalid questions and resolution sources. FutureSearch's prompts therefore required defined terms, timestamps, a start date, and a source that will still exist, and it ran a separate resolvability verifier. Source: [FutureSearch, arXiv 2601.22444](https://arxiv.org/abs/2601.22444) (2026-01-30).
- **Unclear sources are the main failure.** Most generated questions (about 60%) were invalid because the source text did not clearly resolve them. Source: [Chandak et al., arXiv 2512.25070](https://arxiv.org/abs/2512.25070) (2025-12-31).
- **In-game announcements as a source.** A sportsbook settles first blood on the game's own on-screen announcement. Source: [Midnite](https://intercom.help/midnite/en/articles/2686555-general-esport-betting-rules) (excerpt).
- **Video as a fallback source.** Polymarket allows a consensus of credible reporting, including video, if its official stats source is silent for 2 hours. Source: [Polymarket event JSON](https://gamma-api.polymarket.com/events?slug=cs2-1win-ww-2026-04-05) (2026-04-05).
- **Model limits on game video.** Models handle coarse judgments reasonably (78.1% on video glitch detection) but are weak at fine-grained comparison (45.2%) and at finding when an event starts. Source: [VideoGameQA-Bench](https://arxiv.org/abs/2505.15952) (2025).
- **Wrong NO resolutions.** Absence of evidence led resolvers to wrong NO answers. Source: [FutureSearch](https://arxiv.org/abs/2601.22444) (2026-01-30).

### Inferences
- **Verifiability tiers** for 2–10 s frame sampling plus 4 s ASR chunks:
  - **Tier 1: resolve automatically.**
    - Episode outcome with a persistent result banner or screen: VICTORY or DEFEAT, YOU DIED, LEVEL COMPLETE, checkmate or resignation banners, K.O. or WIN screens, placement "#N". These stay up for seconds to tens of seconds, so sparse sampling usually catches at least one.
    - A threshold on a number that freezes at the end (chess clock, final score, final speedrun time, placement) or persists on the HUD (round score).
    - Exact word tokens in the transcript.
  - **Tier 2: resolve automatically only when two independent signals agree, otherwise approval mode or void.**
    - Big announcement text such as FINAL ROUND or FEVER.
    - Small HUD numbers, such as alive counts or HP.
    - Outcomes where the streamer's side or identity must be inferred, such as P1 or P2 in a fighting game.
  - **Tier 3: avoid in v1.**
    - Transient killfeed events.
    - "First X" races between transient events.
    - Counts not shown on screen.
    - Event timing to within a few seconds.
    - Off-screen or hidden information.
    - Outcomes that depend on chat.
- **Fields required at proposal time.** All are machine-checked:
  - `template_id`
  - `slots`
  - `episode_binding`: the episode type and the cue that marks its start
  - `evidence_anchor`: the frame timestamp and the OCR or quoted text where the quantity or cue was seen, or the transcript span
  - `resolution_plan`: the channel, plus the expected appearance of the YES state, the NO state and the end of the episode
  - `void_if`
  - `p_yes`
  - `expected_seconds_to_decisive_evidence`
  - `why_not_already_decided`
- **Deterministic validation.** Reject the candidate if any of these fail:
  - The anchor text is not found again by local OCR, or the transcript span does not exist.
  - The plan names a channel the system does not ingest.
  - A slot value falls outside its allowed set.
- **Resolution prompt.** The resolver quotes the stored plan and returns YES, NO, UNCLEAR or NOT_ENDED, with frame timestamps and the text it read. Any result without evidence after lock counts as UNCLEAR.
- **Proof of coverage for NO.** For Types C and E, NO requires continuous coverage: no media gap longer than, say, 15 s and no ASR outage across the window. Otherwise the market is void.

### Gaps
- I gathered no numbers on Whisper's accuracy at detecting single words in streamer audio with game sound behind it.
- I gathered no numbers on OCR accuracy for small HUD text at 480p.
- I found no speaker diarization option checked for attributing speech to the streamer.

## Q7. How can propositions be kept interesting and roughly balanced, and never already decided?

### Takeaway
Aim for P(YES) of roughly 0.3–0.7 by choosing the threshold, constraint or window, rather than trusting the model's raw probability, which shows a yes-bias. Start every measurement window at lock. Reject any candidate whose decisive state is already visible, or nearly so. Keep one market open at a time and pace proposals by episode.

### Cited Findings
- **Twitch guide on balance.** Source: [BestTwitchExtensions guide](https://besttwitchextensions-com.pages.dev/articles/twitch-predictions-complete-guide.html) (2025-12-24, commercial).
  - Aim for splits near 50/50, because lopsided splits such as 95/5 feel predetermined.
  - Add constraints to make outcomes less predictable, for example "win without dying".
  - Use specific thresholds and 2–3 options. Avoid predictable outcomes.
  - Decide in advance how edge cases resolve, and reword the prediction if you cannot.
  - Frequent cancellations erode trust.
- **Twitch payout.** Winners split the pool. Source: [SlashGear](https://www.slashgear.com/twitch-is-rolling-out-a-new-points-feature-for-predicting-achievements-15647305) (Nov 2020).
- **FutureSearch on triviality and bias.** Source: [FutureSearch](https://arxiv.org/abs/2601.22444) (2026-01-30).
  - Its triviality filter targeted forecasts below 2% or above 98%.
  - Model forecasts averaged 0.37–0.42 against a 29.2% YES base rate.
  - "Will X happen within a deadline" questions mostly resolved NO.
- **Leakage.** Over 40% of selected generated questions initially contained the answer. Filters also excluded questions that resolve too early and questions about established facts. Source: [Chandak et al.](https://arxiv.org/abs/2512.25070) (2025-12-31).
- **ForecastBench** admits only questions with no known answer at submission time. Source: [ForecastBench](https://arxiv.org/abs/2409.19839) (2024–2025).
- **Lines that balance markets.** Professional markets use odd/even totals, handicaps (−1.5) and lines such as over/under 2.5 to balance them. Source: [Polymarket event JSON](https://gamma-api.polymarket.com/events?slug=cs2-1win-ww-2026-04-05) (2026-04-05).

### Inferences
- **Balancing techniques:**
  - **Threshold ladder.** For Type B, have the model propose 3 thresholds from the anchored current value projected to the end of the episode, for example a chess clock of 0:30, 1:00 or 2:00. Pick the one whose estimate is closest to 0.5.
  - **Lopsided outcomes.** For Type A, if the current state is lopsided (a CS2 map at 12–3, a boss nearly dead), switch to a threshold, or skip.
  - **Probability band.** Reject estimates below 0.2 or above 0.8. This is stricter than FutureSearch's 2%/98% because the audience wants a contest.
  - **Treat probabilities as a ranking.** Because of the yes-bias, use the model's numbers ordinally. Track the realized YES rate per template and per channel, then retune windows and thresholds. For example, if Type C resolves YES only 20% of the time, lengthen its windows.
  - **Pool imbalance.** A pari-mutuel pool always pays out, but a 95/5 pool makes winners' returns trivial. Log pool splits as a balance metric.
- **Already-decided checks:**
  - Every window starts at lock, never at proposal.
  - Reject the candidate if a result screen is currently visible.
  - Reject it if the anchor shows a near-terminal state: a clock under 10 s, a score at match point with a big lead, or a boss HP bar nearly empty.
  - Apply the after-the-fact void rule from Q5.
  - For speech props, also reject words already said within the last few minutes, or tune the threshold to "at least 2 times".
- **Interest heuristics:**
  - Tie props to what the streamer just said: goals, fears, boasts.
  - Prefer horizons of 1–10 minutes.
  - Do not use the same template twice in a row, and deduplicate against recent markets as FutureSearch does.
  - Speech props are fun but the streamer controls them; label them so.

### Gaps
- I found no empirical data on how Twitch prediction pools split, or on which prop types drive participation.
- I found no source for good balance targets in pari-mutuel micro-markets.

## Q8. Recommendation: proposition taxonomy, wording templates and rules, examples across games, and build plan

### Takeaway
Build v1 as a short, deterministic pipeline that fits the verified free-tier budget of 500 model requests a day, which works out to roughly 15–60 calls per streaming hour:
1. Rule-based moment triggers.
2. One structured multimodal model call per trigger, choosing from 6 fixed templates. It returns slot values, an evidence anchor, a resolution plan, a P(YES) estimate and the expected time to resolution.
3. Deterministic validators: anchor, window, horizon, probability band, wording length, and one open market at a time.
4. Fixed rules text generated from the template.
5. A resolver that prefers deterministic checks (transcript regex, local OCR keywords). It falls back to a model verdict of YES, NO or UNCLEAR, which must cite evidence from after lock. UNCLEAR or a timeout means void and refund, or approval mode.

### Cited Findings
- **Templates over free form.** Parameterized templates with fixed edge-case rules are the professional standard. Sources: [Kalshi MENTION](https://kalshi-public-docs.s3.amazonaws.com/contract_terms/MENTION.pdf) (2026-05-06); [Kalshi ESPORTSMAPS](https://kalshi-public-docs.s3.amazonaws.com/contract_terms/ESPORTSMAPS.pdf) (2026-08-06).
- **Neutral resolution and video fallback.** Polymarket resolves uncertain cases 50-50 and allows video consensus as a fallback. Source: [Polymarket event JSON](https://gamma-api.polymarket.com/events?slug=cs2-1win-ww-2026-04-05) (2026-04-05).
- **Filtering is needed.** LLM-generated questions need structural filtering, and shared resolver errors and absence-of-evidence errors are the main risks. Sources: [FutureSearch](https://arxiv.org/abs/2601.22444) (2026-01-30); [Chandak et al.](https://arxiv.org/abs/2512.25070) (2025-12-31).
- **Twitch's lifecycle and limits.** One open prediction at a time, 2–10 outcomes, LOCKED before RESOLVED or CANCELED, and an automatic refund after 24 hours. Source: [Twitch Developers](https://dev.twitch.tv/docs/api/predictions).
- **Streamer conventions.** Short titles (45 characters, unverified), near 50/50 splits, and opening at queue or loading screens. Source: [BestTwitchExtensions](https://besttwitchextensions-com.pages.dev/articles/twitch-predictions-complete-guide.html) (2025-12-24).
- **Human approval is the norm** in comparable products. Sources: [Vinfotech](https://www.vinfotech.com/insights/ai-market-generator-prediction-market-content-bottleneck) (2026-05-11); [PredictionLive](https://devfolio.co/projects/predictionlive-c0f8) (2025-07-13).
- **Model limits on game video** argue for coarse, persistent evidence. Source: [VideoGameQA-Bench](https://arxiv.org/abs/2505.15952) (2025).
- **Free-tier budget.** gemini-3.5-flash-lite allows 15 requests per minute, 250K tokens per minute and 500 requests per day, per project. The other models on the same key have their own quotas, which are not yet known. Source: the owner's AI Studio rate-limit page, read 2026-11-15 and passed on by the coordinator (no public URL).

### Inferences

**Recommended taxonomy for v1.** Types A, B and E plus parity F are enabled; C is restricted; D and G are off.

| Type | Headline pattern | Evidence channel | Verifiability | Typical lock / horizon |
|---|---|---|---|---|
| A. Episode outcome | Will the streamer win this {episode}? | Result banner or screen, or a change in a persistent score; speech as corroboration | Tier 1 | Lock at or just after the episode starts; horizon is the episode, capped at 30 min |
| B. Threshold at episode end | Will {on-screen quantity} be {op} {K} when this {episode} ends? | OCR of a frozen or persistent number in the first frames after the end | Tier 1–2 | Same as A; K chosen from a ladder |
| C. Occurrence in a window | Will {big on-screen cue} appear before this {episode} ends / within {N} min? | OCR or model reading of large text or banners; NO needs a coverage proof | Tier 2 | Lock + window of 1–10 min |
| D. Race | Will {counter A} reach {N} before {counter B}? | Persistent counters only | Tier 2 | Off in v1 unless both are scoreboard counters |
| E. Speech | Will "{word}" be said on stream before this {episode} ends / within {N} min? | ASR transcript with a deterministic matcher | Tier 1 for detection; streamer-controllable | Counting starts at lock; 1–15 min |
| F. Parity | Will the final {total} be odd? | Final scoreboard number | Tier 1 | Filler when nothing balanced is available |
| G. Streamer choice | Will the streamer pick {X}? | Selection screen | Tier 2; streamer-controllable | Off by default |

**Template rules text.** Each template stores a short headline (45 characters or fewer, YES or NO, no negation) and fixed rules text.

- **A. Episode outcome.**
  - YES if the streamer, or the streamer's side as identified at proposal by {anchor cue}, wins the {episode} that is in progress when betting closes. If none is in progress, the next {episode} to start counts.
  - The win must be shown by {result cue} in stream frames after lock, or by a clear statement on stream corroborated by a frame.
  - NO if that {episode} ends in a loss. A draw or tie resolves {NO or VOID, fixed per template instance}.
  - VOID if the {episode} is abandoned, restarted or remade and not completed within 30 min; the game changes or the stream drops for more than 60 s; the result is not legible or confirmed within 120 s of the end; or decisive evidence appeared before lock + M.
- **B. Threshold at episode end.**
  - YES if {quantity}, as displayed at {location}, reads {more than | at least | fewer than | at most} {K} {units} in the first legible frame after the {episode} ends.
  - The operators mean >, ≥, < and ≤, as in Kalshi's definitions. Values are read exactly as displayed, for example m:ss.
  - VOID if the number is not legible within 120 s of the end, plus the VOID clauses from A.
- **C. Occurrence in a window.**
  - YES if {cue} is observed in the stream between betting close and {end}.
  - NO if the window ends without it and the stream was covered throughout, with no media gap longer than 15 s.
  - Otherwise VOID.
- **E. Speech.**
  - YES if "{word}", including its plural or possessive, is spoken in the stream audio after betting closes and before {end}, as captured by the system transcript.
  - Other forms do not count: "{word}ing", "{word}ed", and closed compounds.
  - Any voice counts, including teammates, game audio, and the streamer reading this bet aloud.
  - VOID if the audio or transcript is missing for more than 15 s in the window.
  - v1 says "on stream" rather than "the streamer says", because speaker attribution needs diarization.

**Wording rules.** The validator enforces these:
1. One subject, one condition, one episode or window. Combine conditions only if every part is visible ("win without dying" only when deaths are shown).
2. The subject is "the streamer" or "the streamer's team or side", anchored by an on-screen cue. Use player or team names only if they appear on screen.
3. "This {episode}" means the instance in progress at lock, or else the next to start. The rules say so.
4. Quantities use the on-screen label, units and format. Thresholds must be values the display can show. Operators come from a fixed list. No vague words such as "around", "a lot", "quickly" or "dominate".
5. Every window is measured in stream time from lock, and every horizon is capped.
6. Every rule names the evidence channel, what YES looks like, what NO looks like, the VOID list and the grace period.
7. The mapping of a tie or draw is always stated.
8. No hidden or off-screen information, no outcomes that depend on chat, and no outcomes that need knowledge of the game's internals.
9. Speech and choice props are tagged as controllable by the streamer.
10. Reject a proposal if its probability estimate is outside 0.2–0.8 or its horizon is under 3 × M.

**Examples across games.** Each gives the type, the proposition, and notes on evidence or voiding.

- **Chess (online blitz).**
  - A: "Will the streamer win this game?" A draw resolves NO; an aborted game is void. Evidence is the result banner.
  - B: "Will the streamer's clock show more than 1:00 when the game ends?" The clock stops at the end, so the final frame is reliable. Read the clock under the streamer's board side.
  - E: "Will 'blunder' be said before this game ends?"
  - Rejected: "castle before move 10", because the move list may not be visible and the moment is transient.
- **Counter-Strike 2.**
  - A: "Will the streamer's team win this round?" Resolve from the top-HUD round score incrementing for the streamer's side, which persists into the next round, plus the round-end banner.
  - B: "Will this map reach at least 20 total rounds?" This uses the persistent scoreboard. The horizon is long, so cap it.
  - B, Tier 2: "Will at least 3 Terrorists be alive at the end of this round?" Allow it only if frames are sampled at about 3 s or faster near the round end and the HUD alive counts are legible. Otherwise void.
  - C, Tier 2: "Will the bomb be planted this round?" Evidence is the plant announcement or text plus the HUD icon.
- **Peggle.**
  - A: "Will the streamer clear this level?" Evidence is the level-complete or try-again screen.
  - B: "Will the streamer have at least 3 balls left when this level ends?" Evidence is the ball counter.
  - B: "Will this level's score be at least 100,000?"
  - C: "Will Extreme Fever happen on this level?" Evidence is big on-screen text.
- **Fighting games (Street Fighter 6, Tekken 8, Smash).**
  - A: "Will the streamer win this match?" Anchor the streamer's side (P1 or P2 name plate) at proposal; resolve from the WIN, LOSE or K.O. result screen.
  - C: "Will this match go to a final round?" Evidence is a large FINAL ROUND splash or the round indicators.
- **Speedruns (any game with a timer or splits overlay).**
  - B: "Will this run's timer stop under 25:00?" A reset before the finish resolves NO.
  - C: "Will the streamer reset before reaching {split name shown on the overlay}?" A timer jumping back to 0 is a reset.
- **Card and roguelike games.**
  - Hearthstone or Marvel Snap, A: "Will the streamer win this game?" Evidence is the Victory or Defeat screen.
  - Slay the Spire, B: "Will the streamer have at least 40 HP after this fight?"
  - Balatro, B: "Will the streamer reach Ante 5 this run?" Evidence is the ante counter; cap the horizon.
- **Puzzle games.**
  - Tetris, B: "Will the score be at least 200,000 when this game ends?"
  - Level-based puzzle game, C: "Will the streamer complete this level within 10 minutes?" Evidence is the completion screen, with the window measured in stream time from lock.
- **Battle royale.**
  - B: "Will the streamer finish in the top 10?" Evidence is the placement number on the result screen.
  - B: "Will the streamer get at least 3 eliminations this match?" Evidence is the HUD kill counter.
- **Souls-like boss attempts.**
  - A: "Will the streamer beat this boss on this attempt?" The death banner and the victory banner are large and persistent.
  - C, Tier 2: "Will the boss's health bar drop below half this attempt?"
- **Any game, speech.** "Will 'rush' be said on stream before this match ends?" Counting starts at lock and uses the matcher defined in template E.

**Simplest Python v1** (a few hours of work):
1. **Template catalogue.** Write 6 template dataclasses (A, B, C, E, F, plus optional D). Each holds its headline pattern, rules text with `{slot}` placeholders, allowed slot values, a resolver type, default timing values, and its VOID clauses.
2. **Trigger loop.** Run on each media burst with no model call. Use regex lexicons on a rolling window of the last 2–3 ASR chunks, frame-difference and low-motion checks, and optional local OCR keyword hits. Apply the heartbeat, the cooldown and the one-open-market gate.
3. **Proposer call.** One hosted multimodal model call receives the last 30–60 s of transcript, 3–6 recent frames with their stream timestamps, and the template catalogue. It returns JSON with up to 3 candidates carrying the fields listed in Q6. Treat every input as untrusted data.
4. **Validator.** Run a JSON-schema check, the anchor re-check, the timing checks, the probability band, deduplication against recent markets, and the length limit. Pick the valid candidate whose estimate is closest to 0.5. Render the rules text from the template, never from free model prose.
5. **Resolver.**
   - Speech props: a deterministic regex over the transcript from lock to the end signal.
   - Other types: after an end-of-episode trigger (OCR result keyword, "gg" in speech, or a scene change), make 1–2 model calls with the stored resolution plan plus the frames after lock. Accept YES or NO only with cited evidence frames after lock, plus a second independent signal for Tier 2.
   - Otherwise, on timeout, void and refund or send to approval mode.
6. **Budget.** gemini-3.5-flash-lite's free tier allows 15 requests per minute, 250K tokens per minute and 500 requests per day, shared by the whole project.
   - **The daily request limit is the one that binds.** One call per media burst (about every 6 s, so 10 a minute) stays under 15 requests per minute but would use up all 500 in about 50 minutes. Call the model only on local triggers, through a token bucket of at most 15 calls a minute (at least 4 s apart).
   - **Default caps.**
     - Proposer: at most 1 call per trigger, with a cooldown of at least 120 s, and at most 20 calls an hour. The heartbeat is a proposer call, not an extra one.
     - Resolver: at most 2 calls per market, an end check plus one retry. Speech props need no call, because the regex resolves them.
     - At one market every 3–5 minutes, that is about 25–60 calls per streaming hour, so a 2-hour demo uses about 50–120.
     - That leaves most of the 500 for development and rehearsal on the same project.
   - **Combined boundary call.** The end of one episode is usually the intermission before the next. One call can therefore return both the verdict on the open market (from frames after lock) and the next candidates, as separate JSON fields with separate validators. This brings usage down to about 15–35 calls an hour.
   - **Reserve quota for resolution before opening.**
     - Never open a market unless at least 3 calls are still reserved for resolving every open market.
     - Below a daily floor (for example, 50 remaining), stop proposing and keep the rest for resolution.
     - If quota runs out, or a 429 response blocks resolution, go to approval mode or void. Never guess.
   - **Persist the usage counter.** Store requests used today, per model, in the database, because every process and test run shares the project's quota.
   - **Tokens are not the constraint.** A call with 3–6 frames at 854×480 plus about 60 s of transcript is probably a few thousand tokens (unverified; read the usage metadata on the first real call). At an average of 2 calls a minute or fewer, the 250K-token limit does not bind. It would bind only if a single call exceeded about 16K tokens while running at the full 15 requests a minute.
   - **Other models.** Do not plan around them until their quotas are verified.

**Improvements with more time:**
- **Better evidence.**
  - Local OCR for anchors and resolution, to cut hosted calls.
  - Adaptive frame sampling around a predicted episode end, for example bursting to 1 frame per second, so Tier 2 props become reliable.
  - Speaker diarization, so the rules can say "the streamer says".
  - Re-checking a Twitch VOD or clip during a resolution grace period, the equivalent of Kalshi's 24-hour recording window.
- **Better calibration and pacing.**
  - Per-channel priors for episode length and base rates.
  - Probability estimates calibrated against realized YES rates.
  - Thresholds learned from history.
  - Novelty and diversity scoring.
  - Chat activity as an extra signal for bettable moments.
- **More quality checks and market types.**
  - A FutureSearch-style second "how could this be disputed?" critic call when quota allows.
  - Multi-outcome markets.

### Gaps
- All the timing values (M, the 3 × M horizon, the 0.2–0.8 band, 15 s gaps, 120 s grace, 30 min caps) are untested design defaults, not sourced figures.
- The budget calls per hour are estimates from these defaults. I did not verify how many tokens gemini-3.5-flash-lite charges per 854×480 frame, or when the daily quota resets.
- I found no source on the time each game keeps its result screen up, or on how legible typical HUDs are at 854×480. Both need a quick test on real Twitch footage before Tier 2 props are enabled automatically.
