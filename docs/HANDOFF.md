# Current handoff (final checkpoint before switching to a new chat)

- **Timestamp / coordinator:** 2026-11-15 ~01:11 CT (updated mid-work on D37; see "Current work" below). Coordinator session in the Claude Code desktop app (Opus 5.5 `claude-opus-5-5`).
- **Deadline:** 12:00 CT Sun 2026-11-15. Feature freeze 09:00; rehearsals 09:00–12:00.
- **Branch:** `hackathon-build`, pushed to `origin` (graysmal/FaZeTime, a **PUBLIC** repo). Run `git log -1` for the SHA.
  - The owner authorized committing and pushing reviewed increments.
  - Scan every staged diff for names, phone numbers, IDs, private IPs and keys.
  - No key-shaped literals even in tests (push protection blocks them); never use the bypass.
- **In-flight workers:** NONE. Everything below is committed, and deployed where stated.

## What exists (see STATUS for the evidence)

| Piece | State |
|---|---|
| Extension (`apps/extension`) | P1 COMPLETE. Live builds look real (D31). One-tap **Join**, with no codes (D35), and silent re-join. Stripe test top-up handoff. 133 tests. Builds in `~/Documents/fazetime-extension{,-live,-live-pi}`, pinned ID `hodaaffdhncidmaccebmionoljljfefe` |
| Operator console (`apps/operator`) | Served from the Pi at `http://fazetime:8000/operator/`. **No sign-in** (open access). Default **demo view**: a LIVE/OFFLINE pill, one card (AI bet Approve/Reject → pool and countdown → betting closed → AI result Approve/Void → result), and Reset. The full console is at `#advanced`. 60 tests |
| API (`services/api`) | Running on the Pi, tailnet IP only, `:8000`. P2 foundation, §9.16 worker routes, §9.17 AI (APPROVAL mode), §9.18 Stripe test top-ups, D35 open access. 524 tests |
| Worker (`services/worker`) | Deployed on the Pi, **not running**. Streamlink→FFmpeg capture, ASR (remote Vultr distil-small.en with local tiny.en fallback), and the Gemini proposer and resolver (`gemini-3.5-flash-lite`). Stage 1a fixes are in. 108 tests |
| Remote ASR (`services/asr_remote`) | Vultr VM `fazetime-asr` (tailnet), distil-small.en, systemd. Pi→VM p50 1.0 s / p95 1.2 s per 4 s chunk |
| Vultr budget (D34) | Guards on the Pi (crontab `@reboot`) and the laptop. Hard stop at $85 pre-tax ($100 incl. tax), with auto-teardown at **Sun 18:00 CT**. Spend about $0.24, projected about $4.3. `infra/vultr/README.md` |
| Stripe | Test keys only. Laptop listener `infra/stripe/start_listener.sh` → Pi `/v1/webhooks/stripe`, log private. Restart it if the laptop rebooted |

Phase state:
- P0 and P1 are complete.
- P2–P6 are built, deployed and reviewed. **Their real-world gates are still pending**: the Twitch run, two real outcomes, and a 4242 checkout.
- P7–P10 have not started. P11 is cut (D17).

## How to run a live take (runbook)

1. **Laptop:**
   - Stripe listener: run `infra/stripe/start_listener.sh`; it does nothing if already running.
   - Vultr guard backup: `pgrep -af "[b]udget_guard.py"`. Restart it per `infra/vultr/README.md` if missing.
2. **Pi API health:** `ssh fazetime@fazetime 'cd ~/fazetime/services/api && scripts/pi_run.sh status'`.
3. **Owner streams with OBS** to `fazegavin1234`, with the keyframe interval set to 2 s.
4. **Start the worker:** `ssh fazetime@fazetime 'cd ~/fazetime/services/worker && scripts/run_pi.sh'`.
   - Log: `~/fazetime-data/worker.log`.
   - Stop: `scripts/stop_pi.sh`.
   - AI-only stop: `touch ~/fazetime-data/worker/AI_STOP`.
5. **Console:** open `http://fazetime:8000/operator/` and click **Enable sound**. When the AI's bet card appears, click **Approve** within the countdown. Viewers (Chrome, live-pi build, **Join**) bet. After the fight the AI's result card appears; click **Approve result**.
6. **Reset for next take.** Leave **≥60 s** of stream between take 1's result speech and take 2's opening line (Stage 1a known gap).

## Next concrete actions (new session)

1. **Stage 0 is done** (500 RPD for Flash-Lite 3.5).
   - Set `FAZETIME_AI_DAILY_BUDGET=400` (and optionally `FAZETIME_AI_RESOLVER_RESERVE`, default 0.4) in `~/fazetime-data/worker.env`.
   - The quota resets at **02:00 CT**; after that, rehearsals spend demo-day requests.
2. **P6 gate.** The owner, in the extension, does Wallet → Add funds → $5 → FaZe Up! → test card 4242 4242 4242 4242.
   - Verify "Test credits added" plus exactly one `STRIPE_TEST_TOPUP` ledger credit, using operator health / reconcile or `python -m fazetime_api reconcile` on the Pi.
   - Record it in `docs/evidence/p6/`.
3. **P3/P4/P5 gates**, with the owner's two recordings (one per winner) streamed through Twitch:
   - candidate before the fight, with the lead-in measured;
   - approve;
   - two viewers bet;
   - lock;
   - resolver suggestion matches the recording;
   - approve, settle, payouts.
   Record a positive and a negative outcome in `docs/evidence/p3-p5/`, with sanitized timings and no transcripts.
4. **P7:** two consecutive full rehearsals, plus a subset of the fault drill (worker restart, viewer reload, webhook repeat). The reviewer signs off.
5. **If time remains before the 09:00 freeze:** P8 (weighted raffle draw, backend) and P9 (armed spoken "Raffle" trigger). Then P10 as a **manual** FaceTime handoff (D05/D18).
6. **After judging:** the VM is torn down automatically at 18:00 CT; run `python3 -I infra/vultr/budget_guard.py teardown` to end it early. The owner revokes the reusable Tailscale auth key.

## Current work: game-agnostic AI markets (D37), started 2026-11-15 ~00:30 CT

- **Owner direction (D37):** proposals and verification must work for any game or format. The earlier report's narrow scope (Minecraft, then any-game H2H) is superseded. D36 is superseded.
- **Research:**
  - A fresh, independent deep research ran with no project context. Notes are in `research_notes/Game agnostic stream prop bets/`: state_tracking, proposition_generation, resolution_verification, models_and_budget.
  - The report goes to `reports/Game agnostic stream prop bets.md` (being written at 01:11 CT).
- **Stage 0 done:** the owner pasted the AI Studio quota table (recorded in `docs/evidence/p0/P0-C-gemini.md`). Flash-Lite 3.5 and 3.1 have 15 RPM / 500 RPD each. Gemma 4 26B/31B have 30 RPM / 16K TPM / 14.4K RPD, but the 26B returns HTTP 500 on about half its calls.
- **Prototype** in `spikes/p4-generic/` (LOCAL FIXTURE replay only; not wired to the API or the worker):
  - `prep_fixture.py`: ASR plus 1 fps frames.
  - `fixture.py`: causal slicer.
  - `llm.py`: per-model gates.
  - `generic.py`: code-owned state reducer, observer, template proposer, extract-then-decide resolver.
  - `replay.py`: the loop.
- **Fixtures** (owner-provided Peggle recordings; never commit them) are in `~/fazetime-data/fixtures/peggle/`:
  - `verbose.mp4`, `normal.mp4`, each with a prepped dir;
  - `ground_truth.json` (coordinator labels);
  - `runs/<HHMM>/`, with calls, events and a summary.
- **Fixture replay results** (`docs/evidence/p4/P4-generic-fixture-replay.md`):
  - Pass 1 opened 0 markets; that was fixed.
  - Pass 2: 4 markets, 3 correct, 1 correct void.
  - **Pass 3** (D39 35 s window, 20 s void margin, the report's refinements): 4 markets, 2 correct, 2 correct voids, **0 wrong**.
  - Bets are published 2–5 s after their trigger, and settled 19–20 s after the labelled end.
  - Run outputs: `~/fazetime-data/fixtures/peggle/runs/0122-v3/` (grade with `spikes/p4-generic/grade.py`).
- **Known gaps:**
  - Episode ends are found 10–13 s late; boundary refinement is the fix.
  - Observer p90 latency is 7–9 s, so live it must skip busy slices.
  - The first 3.1 Flash-Lite call 504s; send a warm-up request.
  - One market at a time means late invitations are ignored.
  - Only Peggle has been tested.
- **Paid fallback (D38, deferred):** Vultr Serverless Inference, only with a fresh owner OK.
- **Sponsor deck scan:** Gemini's free tier is the only card-free multimodal option. Vultr Serverless Inference is per-token ($0.55 per million in, $2.75 per million out). The owner confirmed the Devpost placeholder was submitted before midnight; the final edit is due before 12:00.
- **Next:** owner decision on integration. Proposed path, in the report's build order:
  - Port `spikes/p4-generic` into `services/worker/fazetime_worker/generic/` as a worker profile.
  - Make an additive CONTRACTS §9.17 change: generic template IDs carrying the frozen spec and its hash; one subject or none instead of the H2H pair; a generic episode fingerprint; the window floor lowered to 35 s (D39).
  - Have the console show the generic question and rules.
  - Ship `episode_outcome` and `utterance` in APPROVAL mode first.
  - The H2H path stays until the replacement passes a Twitch run.

## Earlier research (superseded on scope by D37)

- `reports/LLM stream market architectures.md`, with notes in `research_notes/LLM stream market architectures/`. Its Stage 1 (any-game H2H) was deferred (D36). Stage 1a is done (`12d7b76`).

## Environment facts

- **`.env.local` (laptop, mode 600; names only):** `GEMINI_API_KEY`, `CHERT_API_KEY`, `CHERT_PROJECT_ID`, `CHERT_LINE_NUMBER`, `DEMO_CALL_ALLOWLIST`, `STRIPE_SECRET_KEY` (test), `STRIPE_WEBHOOK_SECRET`, `TAILSCALE_AUTH_KEY`, `VULTR_API_KEY` (access list `129.107.192.0/24`), `ASR_REMOTE_TOKEN`.
- **Pi `~/fazetime-data/` (mode 600):**
  - `api.env`: `FAZETIME_AI_MODE_DEFAULT=APPROVAL`, `FAZETIME_STRIPE_ENV_FILE`, `FAZETIME_OPEN_ACCESS=1`;
  - `stripe.env`;
  - `worker.env`: API base, worker token, stream ID `str_dcf14fde37d544be9b1bac9668938eae`, channel, Gemini key, streamlink path, models dir, `ASR_REMOTE_URL`, `ASR_REMOTE_TOKEN`;
  - `vultr.env`.
- **Pi access:** key-auth `ssh fazetime@fazetime` only. Never a password or sudo.

## Do not repeat / known failures

- **Capture:**
  - Never use a GAP/STALE threshold of 6 s or less: Twitch delivers media in bursts about 6 s apart.
  - Never use the WAL journal mode (D23).
  - Never pass `--twitch-disable-ads`.
  - Never run `cpu_threads=4` on the Pi alongside other load.
- **ASR:** never use decoder prompts or hotwords; they hallucinated "FaZeGavin" and "1v1". Never commit third-party media or any transcripts.
- **Process checks:** `pgrep -f` in a one-liner matches its own shell's command text. Use a script file plus the `[x]` bracket trick.
- **Browser APIs:** `crypto.randomUUID` is undefined on the plain-http tailnet origin. The console needs `src/polyfills.ts` as the first import.
- **Origins:** never use wildcard extension origins.
- **Vultr:** never create a resource without `check-create` and the `fazetime` tag.
- **Approval timing:** the approval window is short (minimum lead 30 s). A recording needs ≥2 min of setup between the announcement and "3, 2, 1, fight!" for a comfortable approval window.
