# Current handoff (final checkpoint before switching to a new chat)

- **Timestamp / coordinator:** 2026-11-15 ~00:50 CT. Coordinator session in the Claude Code desktop app (2.1.289, Opus 5.5 `claude-opus-5-5`).
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

1. **Owner, Stage 0:** read the Gemini free-tier RPM/RPD for `gemini-3.5-flash-lite` at aistudio.google.com/rate-limit.
   - Set `FAZETIME_AI_DAILY_BUDGET` (and optionally `FAZETIME_AI_RESOLVER_RESERVE`, default 0.4) in `~/fazetime-data/worker.env`.
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

## Research to build on

- `reports/LLM stream market architectures.md`, with notes in `research_notes/LLM stream market architectures/`. It is the deep research on generic, LLM-driven market proposal and resolution, delivered 2026-11-15 ~00:30 CT.
- **Recommendation:** widen to any-game head-to-heads (Stage 1) with no contract change, and leave generic binary markets until after the deadline.
- **What was decided:**
  - Stage 1 is **deferred by the owner (D36)**.
  - Stage 1a is **done** (`12d7b76`).
  - Stage 0 is open (action 1 above).

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
