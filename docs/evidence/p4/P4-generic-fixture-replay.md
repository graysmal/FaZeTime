# P4/P5 generic (game-agnostic) proposer and resolver: fixture replay evidence

**LOCAL FIXTURE REPLAY. This is not the Twitch gate.** The inputs are two owner-provided Peggle recordings: `verbose` (5:08, with explicit bet invitations) and `normal` (2:57, ordinary streamer talk). They are stored outside the repo in `~/fazetime-data/fixtures/peggle/`, and no media or transcripts are committed. The ground-truth labels are the coordinator's, read from 1 fps frames, and the system never sees them.

- **Date:** 2026-11-15, 01:00–01:45 CT. Coordinator session, branch `hackathon-build`, base `373e4a1`.
- **Decisions:** D37 (game-agnostic), D39 (35 s betting window), D38 (paid fallback, deferred).
- **Design source:** `reports/Game agnostic stream prop bets.md`, with notes in `research_notes/Game agnostic stream prop bets/`.
- **Code:** `spikes/p4-generic/`
  - `prep_fixture.py`, `fixture.py`: preparation and causal slicing;
  - `generic.py`: reducer, observer, proposer, resolver;
  - `replay.py`: the loop;
  - `grade.py`: grading against the labels;
  - `llm.py`: per-model gates;
  - `probe_models.py`: model capability probe.

## What runs

- **Slicing:** a causal slicer releases each 6 s slice. Transcript words become available 1.5 s after they end, and frames after their media second. Nothing from the future is visible.
- **Observer** (`gemini-3.1-flash-lite`; Gemma 4 first is opt-in): sees 2 frames per slice, the new transcript, and a snapshot that code owns. It only describes them: screen type, boundary hint, verbatim result text, popups, HUD numbers, and the streamer's bet cue.
- **Reducer** (code, the only writer of state). It runs the episode state machine:
  - starts after 2 gameplay observations;
  - ends on a result screen or "ended" hint, 2 away-from-game observations, or a reset of a rising number such as a score falling back to about 0.
  - It also keeps per-episode number histories and the median duration of earlier episodes.
- **Proposer** (`gemini-3.5-flash-lite`): picks one of four templates and fills its slots. Code renders the question and rules.
  - The four templates: episode outcome; a number at the end being at least X; a phrase heard on stream; episode longer than X.
  - Code validates: P(YES) between 0.2 and 0.8; slots valid; tracked numbers need 2 or more reads; expected lead after lock of at least 30 s, measured against this stream's history once there is any; no repeated template; one market at a time.
- **Timing (D39):**
  - betting window of 35 s after publication;
  - void if the outcome is visible within 20 s of lock;
  - void if not settled within 300 s after lock.
- **Resolver:**
  - Speech and duration bets are settled by code.
  - Outcome and number bets get two extraction reads in parallel (`3.5-flash-lite` and `3.1-flash-lite`) on different post-end frames, and code decides. For an outcome, the reads must agree and the printed text must contain a result word.
  - Disagreement voids.
  - A number within one display unit of the line voids. A duration within ±15 s of the line voids.

## Results

### Pass 2 (45 s window, 10 s margin; Gemma-first observer on `verbose`)

| Fixture | Bet | Closed | Settled | Expected | Verdict |
|---|---|---|---|---|---|
| verbose | Will the streamer clear this level? (level 1) | 112.3 s | YES at 168 s ("STAGE COMPLETE!" in both reads' evidence) | YES (won at 152 s) | Correct. The outcome came 40 s after lock and was settled 16 s after the labelled end |
| verbose | Will this level last longer than 1:40? (level 2) | 234.6 s | YES at 288 s | YES (about 105 s; inside today's ±15 s void band) | Correct, but borderline; the void band was added because of it |
| verbose | Will the streamer win this level? (level 3) | 347.4 s | VOID (fixture ended) | VOID | Correct void |
| normal | Will the streamer win this level? (level 1) | 57.0 s | YES at 161 s ("LEVEL COMPLETE!" in both reads) | YES (won at 138 s) | Correct. The outcome came 81 s after lock and was settled 23 s after the labelled end |

Totals: 4 markets, 3 correct, 1 correct void, **0 wrong**. Good rejections included an outcome bet on the final ball at 288 s, rejected as `INSUFFICIENT_LEAD`.

Episode boundaries against the labels:

| Fixture | Episode | Detected | Labelled |
|---|---|---|---|
| verbose | 1 | 30–162 s | 24–152 s |
| verbose | 2 | 177–294 s (score reset) | 176–281 s |
| verbose | 3 | 300 s onward | 296 s onward |
| normal | 1 | 6–150 s | 8–138 s |

Ends are detected late, by 10–13 s: a celebration animation is still classed as gameplay, and the result screen follows.

### Pass 3 (D39 timing and the report's refinements)

The rule set for this pass:
- 35 s window, 20 s void margin, and an expected lead of at least 30 s after lock, taken from history when there is any;
- the result-word check, the number void band, and the ±15 s duration void band;
- speech bets worded "heard on stream (any voice)";
- no repeated template;
- `gemini-3.1-flash-lite` observer.

| Fixture | Bet | Published → closed | Settled | Expected | Verdict |
|---|---|---|---|---|---|
| normal | Will the streamer clear this level? | 29.1 → 64.1 s | YES at 158.5 s (both reads "LEVEL COMPLETE!") | YES (won at 138 s) | Correct. The outcome came 74 s after lock and was settled 20 s after the labelled end |
| verbose | Will the streamer win this level? (level 1) | 68.7 → 103.7 s | YES at 171.4 s | YES (won at 152 s) | Correct. The outcome came 48 s after lock and was settled 19 s after the labelled end |
| verbose | Will this level last longer than 2:00? (level 2) | 188.2 → 223.2 s | VOID (end inferred from a score reset, no result screen) | VOID (about 105 s against a 120 s line, inside the band) | Correct void |
| verbose | Will the streamer win this level? (level 3) | 318.2 → 353.2 s | VOID (fixture ended) | VOID | Correct void |

Totals: 4 markets, 2 correct, 2 correct voids, **0 wrong**. Template variety worked, putting a duration bet on level 2. Flash-Lite calls: 6 on `verbose` and 3 on `normal` for proposer and resolver, plus about 78 observer calls on `gemini-3.1-flash-lite`.

Latency per call (wall clock):

| Role | Model | p50 | p90 | Max |
|---|---|---|---|---|
| Observer, 2 frames | `gemini-3.1-flash-lite` | 2.5 s | 7.4–9.0 s | 17.5 s |
| Proposer | `gemini-3.5-flash-lite` | 1.7–2.9 s | | |
| Resolver reads (run in parallel) | 3.5 and 3.1 Flash-Lite | | | 1.0–3.4 s |

- From the triggering slice to publication (observer plus proposer) took 2.2–5.2 s, and 12.2 s once, when the observer was slow.
- From the labelled end to settlement took 19–20 s. That is the result screen arriving about 10 s after the win, plus one 6 s slice, plus the reads.
- This meets the report's approval-mode latency bar (median at most 30 s).

What the passes showed needs work:
1. **Episode ends are found 10–13 s late.** Celebration animations are classed as gameplay. The report's boundary refinement (one extra observer call on the stored frames between the last gameplay frame and the first terminal one) would tighten both duration bets and the fairness check.
2. **Observer tail latency** (p90 up to 9 s) exceeds the 6 s cadence. Live, the observer must skip a slice when the previous call is still running, rather than queue.
3. **Late invitations are ignored.** With one market at a time, invitations at 200 s and 268 s fell while an earlier market was still open. This is correct under the rules, but it means the streamer's late invitations go unused.
4. **The first `gemini-3.1-flash-lite` request of a process returned 504 (timeout)** in two of three runs. Send a warm-up request at startup.

## Observed model behaviour

- **`gemma-4-26b-a4b-it`** returned HTTP 500 on about half of its calls on 2026-11-15, 10 of 17 in pass 1. That includes a system instruction (always) and the simplest one-image request. It also once named Peggle "Puzzle Bobble". Its 14.4K RPD is real capacity, but an unreliable first hop; it is opt-in (`--observer gemma-first`).
- **`gemini-3.1-flash-lite`** as the observer: p50 about 1.7 s per call (2 frames at medium resolution), and it identified Peggle. One 504 timeout of 30 s was seen.
- **`gemini-3.5-flash-lite`** as the proposer: about 1.5 s per call.

## Limits

- **Sample size:** two recordings of one game, 4–6 markets per pass. By the rule of three, zero wrong settlements in n markets bounds the error rate only at about 3/n. This supports approval mode only (D32).
- **Missing kinds of fixture:** no chess, CS2, fighting-game or speedrun fixtures yet. Speech and number templates have barely been exercised.
- **Not wired in:** nothing here posts to the API. The API still enforces the old 45 s window floor and the `H2H_WINNER_V1` template only. Integration needs the additive generic template described in the report.
