# FaZeTime project plan

Version 1.0 — researched November 14, 2026. Status: planning only.

## Authority and objective

This file is the source of truth for implementation phases, scope, dependencies, and gates. Supporting documents explain how to satisfy these phases; they do not create a second roadmap. `docs/STATUS.md` records actual completion, `docs/DECISIONS.md` records choices, and `docs/HANDOFF.md` records the next action. Nothing below is evidence of implemented functionality.

Build a sideloaded Chrome extension that turns watching one Twitch stream into a shared prediction experience: an AI observes the broadcast, proposes a specific binary future event, viewers stake test credits, the system determines the outcome from subsequent evidence, and cumulative wagering establishes a chance to receive a creator FaceTime call. A later phase demonstrates an AI bookie contacting one absent consenting demo user. The goal is the FaZe sponsor's audience engagement/product prototype, with an honest explanation of possible future revenue.

The original FaZeTime document's phases 1–11 are retained in order. Phase 0 is a short prerequisite verification pass, not a competing implementation phase. Capability spikes for later integrations occur early to discover blockers, while feature implementation still broadens from the original sequence. Phase 7 is the first integrated core; phases 8–11 extend it. The initial scope is one channel, one unresolved binary market, a small invite-only demo audience, and no actual money or prize fulfillment.

## Confirmed choices and deliberate corrections

- Python backend and inference; TypeScript/React extension and dashboard. The owner's final Python choice supersedes a temporary Rust preference.
- Pi with 16 GB RAM and four laptops; assign workloads after measuring hardware. The Pi is not assumed able to transcribe and decode in real time.
- $0 default. Use verified free API allocations. Do not enable paid billing, prepay, upgrade a plan, or buy hosting under an assumed student benefit. Verified MLH sponsor credits are an alternative: current official resources advertise Vultr gift credits and a TigerData trial; record redemption/expiry and use only if they solve a measured problem (see COST_AND_CAPABILITIES).
- Team prerecorded video broadcasts via OBS to Twitch. Analyze the Twitch-delivered stream, using Streamlink or a tested operator capture of the Twitch player. Local file playback is valid for unit/quality tests only and cannot satisfy final ingestion acceptance.
- No fee. Binary pool payouts. Raffle odds use cumulative wager amounts within the stream. Details of refunds, eligibility, and draw cutoff are explicit design defaults in ECONOMICS, to confirm in P0.
- Aim for automatic proposals and resolution. Retain approval mode; enable automation only after agreed quality gates pass. Uncertainty is a legitimate result, never automatically a loss.
- Stripe sandbox/test mode only. Replace the PDF's raw credit-card fields with Stripe-managed input and provider IDs. A test payment must really reach Stripe in P6, while P1 is explicitly mock.
- Chert sponsor usage is time-limited. Group calling and identity privacy are not guaranteed by a generic FaceTime API. Manual handoff is acceptable if necessary.
- An arbitrary hosted betting URL does not establish Chrome Web Store eligibility. This is an unpacked demo; the iframe decision is an interface requirement, not a distribution workaround.

## Completion levels and scope cuts

**Core complete:** P0–P7 gates pass using Twitch media, model-derived proposal/result, server-owned wallet/pool, real Stripe sandbox top-up, and two actual browser clients. If AI quality requires approval mode, call it supervised AI, record owner acceptance, and do not label it fully automatic.

**Raffle demo complete:** P8–P9 gates pass, with weighted draw and armed spoken trigger. The winner call (P10) is deferred (D41); until it runs, the draw result is shown without a call.

**Full envisioned demo complete (prioritized expansion, D41):** P11 passes with a real single-user call, visual market/receipt, explicit verbal confirmation, backend wager, and result notification in a supported channel; P10 is not a prerequisite. A scripted call recording is supporting presentation footage, not a passed integration gate.

Do not guess how many build hours remain from the ceremony PDF. It contains a noon start, midnight end and next-day judging schedule; confirm event rules and actual remaining time. At P0 allocate the available hours approximately: 15% capability/contract setup, 45% P1–P7 core, 20% P8, P9 and P11 expansion (P10 deferred, D41), 20% integration/rehearsal buffer. These are planning proportions, not delivery promises. The owner has prioritized P11 over P10 (D41); if time is very short, ask the owner before cutting further; do not hide an uncompleted phase.

Freeze new feature work before the final rehearsal block. First cuts are styling polish, chat choice highlighting, referrals, streaks, email campaigns, caller-camera analysis, animated avatars, extra games, multi-stream support, and arbitrary embeds. Preserve real Twitch ingestion, reliable wager/settlement, truthful mode labels, and reset/recovery. Group call polish can yield to the accepted manual handoff. Do not cut accounting correctness to finish a visual effect.

## Phase 0 — prove capabilities and settle contracts

Owner: coordinator, with planner and reviewer. Delegates may perform isolated read-only/tool smoke tests. Dependencies: none.

### Questions to resolve before dependent work

1. What is the exact submission cutoff, demo/judging time, time zone, and number of builders currently available? Does the Chert grant remain active through judging? The answer determines phase timeboxes.
2. Which laptop runs OBS, which runs ASR, and which hosts the public-facing API if the Pi is unreachable? Record OS, CPU architecture, CPU, GPU/VRAM if present, available disk, network, and ability to remain awake/powered.
3. Which game or challenge will be recorded? What single cue announces a future binary question, what starts the action, and what unambiguously demonstrates each outcome? Record a prototype, not an entire polished film first.
4. Confirm the simple raffle interpretation: gross settled nonvoid wager amount, win or lose, current stream run, excluding test bots and top-ups; defer drawing until markets are terminal. Confirm void/refund for empty or one-sided pools.
5. Is a bundled panel acceptable if the hosted iframe cannot pass Twitch CSP/auth tests? Keep the URL-entry requirement as an explicit decision rather than silently removing it.
6. Confirm invite-only demo identity, opted-in team phone numbers, and no saved-card autocharge. Which phase-10/11 feature wins if the deadline forces a choice?

Do not ask again about Python, no fee, $0, mandatory Twitch, or the accepted manual call fallback.

### Work packets

- **P0-A inventory:** inspect tools/versions; create capability records. Choose Python and Node versions supported by the actual ASR, WXT, and Chert dependencies. Pin exact working versions later; avoid choosing a newest version solely for novelty.
- **P0-B Twitch:** 30–45-minute spike on the team channel. Obtain coherent audio and frames from actual Twitch for 10–15 minutes, observe a reconnect, measure startup/staleness, and create a new ingest epoch after restart. If Streamlink fails, test operator-authorized Chrome capture. If both fail, declare the core blocked; do not swap in local media as though it passed.
- **P0-C Gemini:** verify an actual API request with text, image, and structured output; read available account quotas and model access. Confirm whether student developer credits are claimed and whether activating them requires money. Prefer existing working free access. Record exact model ID and cost/limits, not a subscription marketing name.
- **P0-D ASR:** run a short representative clip with gaming audio. Compare local faster-whisper on the best laptop with whisper.cpp if needed. Measure real-time factor, p95 chunk latency where sample size supports it, important-name recognition, and sustained backlog. No performance guarantee from RAM capacity alone.
- **P0-E Chert:** obtain account docs from sponsor; verify trial expiry, recipients, line capacity, group video and the required voice/media dependencies. Make approved team-device tests only after numbers/consent are established. Prove second-call cleanup, not just first allocation. This spike does not implement P10/P11.
- **P0-F network/UI:** verify Pi reachability and HTTPS route; test WebSocket or polling through the chosen route; hosted iframe viability and third-party auth. Quick Tunnel has no SSE support, so WebSocket plus HTTP snapshots/polling is the planned transport. Keep provider credentials on trusted hosts.
- **P0-G contracts:** review CONTRACTS and ECONOMICS. Confirm keys, states, auth boundaries, refund semantics, and the phase task boundaries. Create small sanitized fixtures and an evidence template; no need for complete app scaffolding in this spike.

### Exit gate

All remaining blocking choices are answered or explicitly marked blocked with a next owner action. Twitch and Gemini/STT paths are proved or the plan reports the core cannot yet proceed. Chert can remain blocked with the accepted manual call fallback recorded. Actual deadline, machine roles, versions, model/quota and endpoint facts are written down. A failed feasibility test is a useful result; do not turn it into a false VERIFIED record.

## Phase 1 — extension with local mock interactions

Owner: extension engineer. Read ARCHITECTURE frontend boundary and CONTRACTS. No backend/provider dependency beyond the P0 UI decisions.

### Deliverables

Build one WXT/React/TypeScript unpacked Chrome extension with a popup/profile experience, FaZeTime panel above chat, resizable chat/panel split, open/close control near the chat header, Wallet and Redeem tabs, and the over-video market dropdown. Preserve Twitch video controls, keyboard focus, theater-mode behavior, and navigation.

Wallet exposes 5/10/50/custom test top-up amounts with a $5 equivalent minimum. Before P6, mock payment UI shows synthetic test controls; it must not invite real card entry. Keep the “FaZe Up!” action text. Redeem uses a tiny fixed demo catalog and generates a plainly nonredeemable random code after an idempotent mock debit. Do not scrape merch catalogs or implement external coupon fulfillment.

A market has a question, two named choices defaulting to Yes/No, amount-weighted pool bar, numeric total accepted pool volume, countdown, side selection, stake input default 500 cents, estimated gross return including stake, available balance, and a Place Bet action. Insufficient funds opens top-up; it does not guarantee the old market will remain available. A terminal banner distinguishes win, loss (“Ooohhh, so close!!”), void/refund, and unresolved.

Profile collects a display name and an optional claimed Twitch name. Under D16 there is no phone field. Demo call recipients live in local operator configuration instead. It is not verified Twitch identity. Do not collect card details in a general profile form. Profile/setup usability is distinct from authentication introduced in P2.

### Narrow tasks

P1-A mount/lifecycle shell; P1-B profile and two tabs; P1-C market interaction with deterministic fixtures; P1-D hosted iframe/auth feasibility branch if not fully settled in P0; P1-E teardown, resize, route change, full-screen handling and test labels.

A proposed hosted panel only loads the team's allowlisted HTTPS origin. No arbitrary URL fetcher or script loader. If the embed path fails, report evidence and apply the owner-selected bundled panel alternative. Keep market rendering reusable across fixtures and live contracts.

### Gate

Demonstrate install, twitch.tv channel navigation without reload, mount exactly once, close/reopen, resized chat, visible video controls, a mock wager, insufficient funds, and all terminal states. No secrets or real card inputs are present. The operator and viewer see `MOCK` clearly. Screenshot evidence plus manual navigation checks are adequate for layout; they do not complete later finance gates.

Do not build OAuth, payments, stream capture, or call logic in this phase. On Twitch DOM changes, degrade to the approved floating/bundled placement or show a recoverable error rather than repeatedly modifying the page.

## Phase 2 — server, identity, presence, and durable domain foundation

Owner: backend engineer; extension engineer consumes agreed endpoints. Read ARCHITECTURE, CONTRACTS, ECONOMICS.

### Deliverables

One FastAPI API process, one SQLite database on local persistent disk, migration/bootstrap discipline, typed validation, invite-only demo sessions, account/profile records, one stream session, extension heartbeat presence, market/wager data structures, append-only ledger operations, idempotency records, and durable domain event/outbox records. Build a minimal authenticated operator view early so later phases are inspectable.

Use operator-issued one-time enrollment codes for the small team demo unless P0 approves a different simple secure identity method. Redeem codes for opaque revocable sessions; a claimed Twitch name/phone alone cannot log into another wallet. A hosted iframe may use a short-lived single-use exchange code delivered through a verified message bridge; never put a permanent session secret in the iframe URL.

Presence uses per-device/tab heartbeats, aggregated by user/channel. Initial design target is 10–15-second heartbeats and a 45-second expiry, tuned after testing browser/background behavior. Track `last_seen`, player/page state when observable, and a separate heartbeat freshness status. Presence means the extension reports that channel open; it is not proof of attention. Multiple tabs must not create duplicate users or inflate raffle weights.

Implement transaction boundaries for future wagering now. P2 may expose operator-only fixture markets and test credits, but actual provider payments are P6. Introduce WebSocket domain notifications and authenticated HTTP snapshots, with monotonically increasing versions and reconnect/resync. HTTP polling is the low-risk transport fallback if a tunnel/socket fails; do not add Redis to fix one process.

### Tasks and gate

P2-A schema/auth; P2-B ledger and market transition scaffolding; P2-C presence aggregation; P2-D events/snapshots; P2-E operator health and fixture controls. Freeze contracts before splitting P2-C and frontend work.

Two real browsers observe one shared stream state. A reconnect recovers current state, not stale client truth. Stopping heartbeats expires presence. Wrong user/session cannot read another wallet or invoke operator/worker routes. Restart preserves users/balances and events. Duplicate fixture credit changes balance once. Simultaneous balance decrements cannot overdraw. Foreign keys, uniqueness, and state constraints have meaningful tests. No frontend writes a database or authoritative balance.

## Phase 3 — Twitch audio transcription and sampled visual evidence

Owner: media-AI engineer. Read INGESTION and AI_PIPELINE. Depends on P2 observation ingestion/health boundary and P0 media/STT results.

### Deliverables

One capture producer for the channel, one continuous decode path where feasible, timestamped audio chunks, local ASR, sparse sampled/cropped frames, short bounded evidence retention, and visible freshness/gap/backlog states. Use actual Twitch input. Keep ASR/FFmpeg out of the API process; the worker submits authenticated typed observations.

Every observation includes stream/run, ingest epoch, sequence, source kind, media interval, receipt time, evidence reference and quality flags. Distinguish monotonic per-host durations from shared wall time. Audio and frames must refer to the same media timeline. Deduplicate overlapping transcript text. Voice activity detection reduces work; it does not validate game facts.

P3-A capture session lifecycle; P3-B STT chunks; P3-C aligned frames and bounded retention; P3-D freshness/clock instrumentation; P3-E disconnect/restart/backpressure tests. Start with a short clip containing silence, game sounds, a named challenge, and a clear result. No embedding/vector memory is needed.

### Gate

Actual Twitch audio produces understandable timestamped text, and matching frames appear in the operator evidence view. Sustained processing stays within the measured real-time budget; otherwise relocate ASR/lower the model before proceeding. A decoder stop, ad discontinuity or network gap is detected and marked. Reconnect creates a new epoch and does not reuse old temporal context. No stale observation can be represented as fresh. Store a sanitized latency trace and versions.

Do not mark a local-file benchmark as the Twitch gate. Do not use Helix thumbnails as current outcome evidence. Do not build additional media adapters after one primary plus a necessary fallback is sufficient.

## Phase 4 — AI market proposals

Owner: media-AI engineer; backend owns acceptance and publication. Depends on P3 and typed proposal contract.

### Deliverables

A bounded perception state and proposal function using the official Google client, structured output, a narrow approved market template, cited evidence IDs, explicit resolution criteria, proposed close deadline, expected outcome horizon, and abstention. Start with one announced future challenge with an objective result. Do not start with arbitrary gaming situations.

The model receives only recent causal observations and compact state: stream/epoch, current media position, relevant transcript spans, aligned frames, known participant labels, current market state and rejected/used event fingerprints. It cannot read prerecorded future frames or the authored answer sheet. It cannot query arbitrary URLs or execute instructions spoken on stream. Reject unsupported schema, stale or mismatched evidence, duplicate event, known result, unclear subject, missing lock margin, or a second unresolved market.

First run shadow proposals visible only to the operator. Evaluate false proposals, duplicate proposals, valid abstentions, and latency on normal and adversarial clips. Then enable approval mode; automatic mode can be selected after review of the agreed evidence. This staged validation is compatible with the owner's automatic end goal.

### Tasks and gate

P4-A template/rules; P4-B compact context assembler; P4-C structured proposer; P4-D deterministic validator and publication; P4-E quality set and mode selection.

Show an actual Twitch-fed proposal before the recorded action begins, with enough measured lead-in for users to act. Include negative cases: unrelated speech, hypothetical/past tense event, outcome already revealed, repeated clip, prompt injection, stale frame, malformed output and rate limit. No unsafe false-open passes the release fixture set. Report the sample count and limited scope instead of claiming general accuracy. Model self-confidence is not a substitute for these tests.

A provider error pauses proposals; it cannot silently publish a canned proposal as AI output. Canned fixtures are labeled and remain a separate mode.

## Phase 5 — outcome evidence and settlement decisions

Owner: media-AI engineer with backend engineer and independent reviewer. Depends on immutable P4 market criteria.

### Deliverables

State transitions from locked to evaluating to resolved or void, with separate model recommendation and deterministic financial action. Resolver examines subsequent evidence within the correct stream/epoch, answers YES/NO/WAIT/UNRESOLVABLE with cited evidence, checks the predefined success/failure criteria, and flags contradictions/gaps. Do not infer a loss just because time elapsed, the streamer yelled, chat celebrated, or the model guessed.

Use the same model in a separate bounded resolver role initially; extra models do not automatically make the result correct. Require an observable decisive cue appropriate to the recorded challenge. When evidence is absent, contradictory, stale or obscured, the market stays pending. An operator can review it only before the frozen resolution deadline. At that deadline the market is voided and every stake refunded (CONTRACTS §9.3). The timeout is part of the market rules before opening, not invented after seeing which side has money.

P5-A result evidence envelope; P5-B resolver; P5-C deterministic state/criteria gate; P5-D operator evidence approval; P5-E economic settlement preview and repeated-event tests. P6 wires full payment-funded wagering, but the settlement function should already be exercised with fixture stakes.

### Gate

Complete one positive and one negative outcome from held-out, paced test observations, then the actual Twitch rehearsal. Demonstrate an unknown/gap case refusing automatic settlement. The same event cannot settle twice; a late model reply for an old market/version is ignored. A settlement cannot be reversed by a subsequent duplicate model result. If quality is inadequate, record owner-selected approval mode rather than reducing evidence rules until tests pass.

## Phase 6 — Stripe test top-ups and real server wagering

Owner: integrations and backend engineers, extension engineer for checkout handoff. Read INTEGRATIONS and ECONOMICS. Depends on P2 ledger and P4/P5 state contracts.

### Deliverables

Stripe-hosted sandbox Checkout for approved top-up values; raw-body-verified webhooks; idempotent paid-session fulfillment; real backend wager acceptance; pool totals/estimated returns; deterministic no-fee payouts or refunds; optional demo coupon redemption using the same ledger discipline.

Test card entry happens only on Stripe's page. Never add PAN/CVC fields to user schema. Server decides amount/currency/user mapping; return-page query parameters do not credit wallets. The pending-credit UI waits for a verified provider-paid state. Use Stripe CLI forwarding for local work if suitable, or a tested public route; keep webhook signing secrets tied to the actual route.

Wager acceptance atomically checks server deadline, market state/version, balance and idempotency, then moves funds into escrow and records the wager/event. No late Checkout or voice completion backdates a wager. Multiple winning wagers get their share of the final pool with integer rounding and deterministic remainder allocation. Gross return includes principal. Current-pool previews include the contemplated new stake and are explicitly estimates.

### Tasks and gate

P6-A Checkout creation/confirmation; P6-B webhook fulfillment; P6-C wager transaction; P6-D payout/refund; P6-E UI replacement of mocks; P6-F economics review.

Demonstrate one genuine Stripe sandbox paid event credited once, rejected payment, delayed webhook, redirect without payment, duplicate event and same payment through distinct event IDs. Test double-submit, competing wagers, close race, repeated settlement, restart recovery, empty/one-sided pool, rounding, insufficient balance and late top-up. Balances reconcile with immutable ledger entries. No live keys or real charges. Mock payment success alone cannot pass this phase.

## Phase 7 — wire and stabilize the integrated core

Owner: coordinator and reviewer. All P1–P6 gates must be evidenced.

### Deliverables

One run from team OBS broadcast through Twitch capture, transcription/vision, proposal, user wager, deadline lock, result evidence, settlement and visible receipt across two actual clients. Integrate operator health, mode display, evidence inspection, current pool, wallet ledger view, source age, API quota counters, and controlled reset. At least one run uses Stripe-funded test credits; rehearsals may use labeled seeded credits to avoid wasting time.

Fault drill: disconnect viewer, kill API after commit, restart worker, interrupt media during outcome, repeat webhook, allow a delayed AI response, reset while a call/payment job is pending. Ensure jobs remain bound to their original demo run and old callbacks cannot mutate the new run. Do not wipe databases with pending Stripe fulfillment; a reset creates a new run and archives the old one.

### Gate

At least two consecutive full rehearsals on the venue network using actual Twitch, with recoverable failures and no duplicate balances/settlements. Report measured source-to-proposal/result latency and the chosen approval/automatic mode. Viewer refresh yields authoritative state. No provider secret appears in browser bundle/logs. Reviewer signs the core gate. Prepare a backup recording of a real successful run if desired, clearly distinguished from live execution.

Do not add phase-8+ features until the core gate passes or the owner explicitly chooses a documented partial prototype.

## Phase 8 — cumulative-spend raffle

Owner: backend engineer. Depends on terminal wager records and stream-run boundaries from P7.

### Deliverables

Aggregate each eligible real demo user's accepted stake cents in settled nonvoid markets during the current stream run. Winning and losing stakes count equally. Deposits, refunds, voids, coupons, unaccepted intentions, earlier runs and simulated bots do not count. This is gross wagering turnover, not net loss. Do not introduce tickets, streak multipliers, or caps without an owner decision.

At draw, require no unresolved market and freeze eligible user IDs and integer weights in one transaction. Probability is user weight / sum of eligible weights. Zero weight means no draw. Use a cryptographically secure bounded integer and stable cumulative ordering; persist result, random draw, snapshot and unique draw operation. Repeated trigger returns the existing draw. A call failure does not redraw.

### Gate

Worked example: eligible stakes 1000/3000/6000 cents produce 10%/30%/60% chances, regardless of wallets or outcomes. Splitting a wager does not increase cumulative weight. Refunds remove eligibility; prior stream runs/bots excluded. Boundary draws pick correct users, zero pool yields explicit empty state, concurrent triggers produce exactly one winner. Statistical sampling is optional support, not a substitute for interval correctness.

The demo's pool bots may affect payout estimates but cannot receive calls or be silently included in advertised raffle odds. Show the denominator for the eligible raffle population separately from betting pool volume.

## Phase 9 — armed spoken raffle trigger

Owner: media-AI engineer and backend engineer. Depends on P3 final transcripts and P8.

### Deliverables

Operator explicitly arms one draw for the current run. Finalized Twitch transcript containing the agreed standalone trigger “Raffle” in the expected cue window creates a deduplicated trigger request. Handle case/punctuation, overlap duplicates, delayed text, and repeated video loops. A simple deterministic phrase check is enough; do not spend model calls to recognize a literal keyword.

Require correct stream and current ingest epoch. The bookie's TTS, browser UI, other microphone inputs and chat must not feed this trigger path. If unsettled wagers remain, show `waiting for market completion` and retain one pending trigger; after terminal state, create the frozen snapshot once. Do not select using unknown future spend.

### Gate

A real Twitch spoken cue produces one draw; repeat recognition, multiple consumers and clip replay do not draw again. Unarmed speech does nothing. A stale previous-epoch cue is rejected. Reset requires explicit new run/arming. A manual operator trigger can exist as a clearly identified operational fallback, but it does not pass the spoken-trigger gate.

## Phase 10 — contact the raffle winner and streamer (DEFERRED, D41)

Deferred by the owner on 2026-11-15; specification retained. Do not start without a new owner assignment.

Owner: integrations engineer; reviewer observes actual devices. Depends on persisted P8 winner, P9 trigger and verified Chert line facts.

### Deliverables

Preferred: one verified Chert outbound group video call to the opted-in winner and streamer/team stand-in. Use documented per-line group capability, not two independent calls presumed mergeable. The call is a separate durable job associated with the draw; only call lifecycle transitions advance its state. Allocation is not answer, bridge readiness is not proof both humans joined.

Confirm identity visibility on both iPhones. Do not promise hidden personal numbers until tested. Agent video can show a winner card; do not require an animated avatar. Disable wagering tools in mixed group audio because it does not identify an authenticated speaker.

If group capability or two-way video fails, use the owner-accepted manual FaceTime handoff, identify it as manual and leave Chert automation marked blocked. A single-user Chert host demonstration is an optional partial sponsor integration, not proof of a two-human bridge.

### Gate

For automated status, both approved phones exchange actual media and can hear/see the intended participants, then hang up and release the line; a second attempt succeeds. Duplicate draw delivery causes no extra dial. Record exact provider/version/line capability and trial expiry. For accepted manual status, preserve the real draw and document the manual step without calling automated telephony complete.

## Phase 11 — absent-viewer AI bookie

Owner: integrations engineer, backend engineer and reviewer. Depends on P2 presence, P6 wagers, P7 integrity, and verified Chert line facts (P0-E); P10 is deferred (D41), so P11 must prove call cleanup and a second-call release itself. This is a distinct expansion, prioritized over P10, not required to prove the narrow core.

### Deliverables

When a suitable long-window market opens, choose at most one highest eligible cumulative-spend user who is absent under the heartbeat TTL, opted in, verified, outside cooldown, not already called for this market, and reachable on an approved demo number. Select in backend code. If nobody qualifies, do nothing. Cancel a pending unsent invitation if presence returns; do not repeatedly harass a reconnected user.

Single-user FaceTime agent receives a frozen compact market/user envelope and narrow tools: get current market/balance, prepare a wager intent, confirm intent, and cancel. It may explain the question and current estimated pool return; it must not promise fixed odds. Publish a live market/receipt card over video to satisfy the visual concept if the sponsor confirms this meets its criterion.

The user saying “bet ten on Banks” creates a pending intent, not a completed transaction. Read back side, stake, market and deadline; require explicit confirmation bound to that call and intent. The backend rechecks deadline/balance/version at commit. Call audio is not identity proof; the call job is bound to a preverified account. Group calls cannot access the wager tool.

Insufficient funds: offer a Stripe test Checkout handoff and re-confirm a fresh intent after verified credit if the market is still open. Do not silently withdraw from a saved card. Saved-card off-session test charging is deferred unless explicitly requested later, since it adds authentication/failure cases without proving the bookie concept.

Use Gemini Live through a verified LiveKit agent if the account/free quota supports it; otherwise select an explicitly tested STT/LLM/TTS pipeline. Chert's transport grant does not automatically cover voice-model or LiveKit usage. No new paid provider as an unapproved fallback.

### Gate

One actual consenting absent user receives a call for a still-open market, sees the current card, confirms a valid wager, and receives a backend-confirmed receipt. Negative cases include ambiguous amount, changed choice, no confirmation, reconnect, repeated tool call, late confirmation, insufficient funds, stale quote, presence returning, line busy, rejected call and zero remaining call quota. None causes an unintended or duplicate wager.

Result notification uses an actually enabled channel: in-call card/audio if still connected, extension receipt on return, or iMessage only if outbound sending is verified. Do not promise a free shared line can initiate messages. The long lead-in must cover dial/answer/conversation latency; if a short market closes, the correct result is refusal, not backdating.

## Phase gate review and expansion beyond this plan

Each gate record names commit, versions, mode, exact test result and unresolved limitations. Coordinator updates STATUS only after review. A phase can be `BLOCKED`, `PARTIAL`, or `COMPLETE_WITH_ACCEPTED_FALLBACK`; reserve `COMPLETE` for its actual acceptance criteria.

After P11, broader work is a new owner-directed plan: additional games and markets, improved evidence calibration, verified Twitch account linking, richer creator tooling, retention experiments, or multi-channel operation. Do not assume production money, Chrome Web Store distribution, unrestricted outreach, or additional cloud spending is the next authorized step.

