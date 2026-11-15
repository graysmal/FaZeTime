# Current handoff: checkpoint for a new chat (UI overhaul next)

- **Timestamp / coordinator:** 2026-11-15 ~04:05 CT. Coordinator session in the Claude Code desktop app (Opus 5.5 `claude-opus-5-5`).
- **Deadline:** 12:00 CT Sun 2026-11-15. Feature freeze 09:00; rehearsals 09:00–12:00. The owner already filed a Devpost placeholder and edits it before 12:00.
- **Branch:** `hackathon-build`, pushed to `origin` (graysmal/FaZeTime, a **PUBLIC** repo).
  - Run `git log -1` for the SHA. This handoff is the commit after `2ffc73b`.
  - The owner authorized committing and pushing reviewed increments.
  - Scan every staged diff for names, phone numbers, IDs, private IPs and keys. No key-shaped literals, even in tests.
- **In-flight work:** NONE.
  - **Pi worker:** stopped. `worker.env` is back on the team channel `fazegavin1234`; the D40 test has ended.
  - **Pi API:** running at `http://fazetime:8000`, tailnet only.
- **Owner preference:** use **ultracode** (Workflow multi-agent orchestration) for substantive work (saved in auto-memory). Keep the $0 spend rule.
- **Owner's next step:** a **new chat to overhaul the UI**, on top of the AI-proposal/resolution MVP and the betting MVP below.

## What exists

| Piece | State |
|---|---|
| Viewer extension (`apps/extension`) | WXT + React ShadowRoot panel on `twitch.tv/fazegavin1234`. Live builds look real (D31). One-tap Join (D35). Stripe test top-up handoff. Shows "AI is watching for the result…" after a bet's ETA (§9.20). **141 tests** |
| Operator console (`apps/operator`) | Vite + React, served by the Pi API at `http://fazetime:8000/operator/`. No sign-in (D35). Default **demo view** (`src/demo/DemoView.tsx`, `state.ts`): one card for AI bet Approve/Reject, then pool and countdown, then "AI is watching for the result…", then AI result Approve/Void, then the result; plus Reset. **`#advanced`** (`src/ui/AiPanel.tsx`) has full detail. **78 tests** |
| API (`services/api`) | FastAPI + SQLite on the Pi. P2 foundation; §9.16 worker; §9.17 AI (APPROVAL mode); §9.18 Stripe test top-ups; D35 open access. **§9.19** `GENERIC_BINARY_V1` with a 35 s close floor (D39). **§9.20** `expected_result_at_utc`. **576 tests** |
| Worker (`services/worker`) | Streamlink → FFmpeg capture, ASR (remote Vultr distil-small.en with local fallback). Profiles: `h2h` (code default) and **`generic`** (Pi `worker.env` sets it; D37). The generic profile:<br>- observer chain 3.5 → 3.1 Flash-Lite every 6 s;<br>- code reducer (rounds, score-reset boundaries);<br>- template proposer with 4 kinds;<br>- two-read resolver, decided in code;<br>- fairness margin of 20 s plus 15 s slack;<br>- 40 s minimum lead;<br>- result ETA;<br>- Twitch title/category from `streamlink --json`.<br>**160 tests** |
| Contracts package (`packages/contracts`) | Shared TS types and validators. 190 tests |
| Remote ASR | Vultr VM `fazetime-asr` (tailnet). The budget guard auto-tears it down Sun 18:00 CT (`infra/vultr/README.md`) |
| Stripe | Test keys only. Laptop listener `infra/stripe/start_listener.sh` forwards to the Pi |

Phase state: see `docs/STATUS.md`.
- P0–P1 complete.
- P2–P6 built; real-world gates pending.
- P7–P9 not started.
- **P10 deferred (D41).**
- **P11 reinstated, ahead of P10.**

## For the UI overhaul (new chat)

- **Hard design rules:**
  - D31: live builds look real. No MOCK/DEMO labels in viewer UI. One unobtrusive "test credits" note in the wallet. Stripe's own TEST MODE banner appears in Checkout.
  - The operator **demo view** stays bare-minimum. The full labels live in `#advanced`.
  - Untrusted model text (cues, rationales) is never rendered to viewers. The operator sees it as plain text only.
  - Never use wildcard extension origins.
- **What the UI reads** (CONTRACTS §9.3, §9.17, §9.19, §9.20):
  - market `question`, `yes_label`/`no_label`, `criteria.YES/NO` (rules text), `state`, `close_at_utc`, `expected_result_at_utc` (viewers: only LOCKED/EVALUATING), `pool`, `winning_side`, `void_reason`;
  - operator candidates: `template_id`, `generic.kind`, `close_in_s`;
  - for generic candidates the console approves with `close_in_s` = the candidate's value, so the window counts from approval.
- **Build and deploy:**
  - **Console:** run `cd apps/operator && npm run build`, then `rsync -a --delete apps/operator/dist/ fazetime@fazetime:fazetime/apps/operator/dist/`. There is no API restart for static files; hard-refresh the page.
  - **Extension:** run `cd apps/extension && npm run build:live:pi && npm run copy:live:pi`. That writes `~/Documents/fazetime-extension-live-pi`. Then reload it in `chrome://extensions`, keeping the pinned ID `hodaaffdhncidmaccebmionoljljfefe`.
  - Mock builds are for development only (MOCK labelled).
- **Tests:** `npx vitest run` and `npx tsc --noEmit` in each app.

## How to run a live take (runbook)

1. **Laptop:**
   - Stripe listener: `infra/stripe/start_listener.sh`.
   - Vultr guard backup: `pgrep -af "[b]udget_guard.py"`; restart it per `infra/vultr/README.md` if missing.
2. **Pi API health:** `ssh fazetime@fazetime 'cd ~/fazetime/services/api && scripts/pi_run.sh status'`.
3. **Stream:** the owner streams with OBS to `fazegavin1234`, keyframe interval **2 s**. Any game works under the generic profile.
4. **Start the worker:** `ssh fazetime@fazetime 'cd ~/fazetime/services/worker && scripts/run_pi.sh'`.
   - Log: `~/fazetime-data/worker.log`.
   - AI trace, including the proposer's reasons: `~/fazetime-data/worker/ai_trace.jsonl`.
   - Stop with `scripts/stop_pi.sh`. **Stop it between takes:** the observer uses about 600 Flash-Lite calls per hour of play, against 500 a day per model.
5. **Console** at `http://fazetime:8000/operator/`: approve the AI's bet within its countdown. Viewers bet (extension, Join). After the round, approve the AI's result.
   - A bet needs stakes on both sides, or it voids `EMPTY_POOL` at lock.
   - Give each round at least 2 min of play, because bets need a lead of at least 40 s after lock.
6. **Reset for the next take** in the console.

## Next concrete actions

1. **UI overhaul** (owner, new chat).
2. **P6 gate:** one real 4242 test checkout, credited exactly once (Wallet → Add funds → $5 → 4242 4242 4242 4242). Record it in `docs/evidence/p6/`.
3. **P3–P5 gates on the team channel:** one positive and one negative real outcome through Twitch.
   - A third-party negative outcome is recorded in `docs/evidence/p3-p5/P3-P5-live-twitch-generic.md`.
   - The tuned worker settings (3.5 first, 6 s, 10 s timeout) are not yet re-measured live.
4. **P7** rehearsals plus a fault-drill subset. Then P8/P9 if time allows. Then **P11** (absent-viewer bookie, D41) before P10, which is deferred.
5. **Known AI gaps:**
   - Round ends are detected 10–20 s late (no boundary refinement).
   - Gemini free tier is flaky (5xx bursts); the chain fallback covers it.
   - Streams with no rounds (survival games) need fixed-window bet templates.
   - Paid fallback D38 (Vultr Serverless) only with a fresh owner OK.
6. **After judging:** the VM is torn down automatically at 18:00 CT. The owner revokes the reusable Tailscale auth key.

## Research and evidence

- `reports/Game agnostic stream prop bets.md` with `research_notes/Game agnostic stream prop bets/`: the D37 design.
- `docs/evidence/p4/P4-generic-fixture-replay.md`: fixture replays and the local end-to-end runs.
- `docs/evidence/p3-p5/P3-P5-live-twitch-generic.md`: the live Twitch take.
- `spikes/p4-generic/`: the prototype, `replay.py`/`grade.py`, `e2e_operator.py`, `stake_both_sides.py`. The fixtures live outside the repo in `~/fazetime-data/fixtures/peggle/`.
- The earlier report (`reports/LLM stream market architectures.md`) is superseded on scope by D37.

## Environment facts

- **`.env.local` (laptop, mode 600; names only):** `GEMINI_API_KEY`, `CHERT_API_KEY`, `CHERT_PROJECT_ID`, `CHERT_LINE_NUMBER`, `DEMO_CALL_ALLOWLIST`, `STRIPE_SECRET_KEY` (test), `STRIPE_WEBHOOK_SECRET`, `TAILSCALE_AUTH_KEY`, `VULTR_API_KEY` (access list `129.107.192.0/24`), `ASR_REMOTE_TOKEN`.
- **Pi `~/fazetime-data/` (mode 600):**
  - `api.env`: `FAZETIME_AI_MODE_DEFAULT=APPROVAL`, `FAZETIME_STRIPE_ENV_FILE`, `FAZETIME_OPEN_ACCESS=1`.
  - `worker.env`: API base, worker token, stream ID `str_dcf14fde37d544be9b1bac9668938eae`, channel `fazegavin1234`, Gemini key, streamlink path, models dir, `ASR_REMOTE_URL`, `ASR_REMOTE_TOKEN`. A D37 block: `FAZETIME_AI_PROFILE=generic`, observer models `gemini-3.5-flash-lite,gemini-3.1-flash-lite`, `FAZETIME_AI_DAILY_BUDGET=420`, `FAZETIME_AI_RESOLVER_RESERVE=0.1`, `FAZETIME_AI_TIMEOUT_S=10`, `FAZETIME_AI_MIN_INTERVAL_S=4.2`, `FAZETIME_AI_OBSERVER_INTERVAL_S=6`. Backups: `worker.env.pre-d37`, `worker.env.pre-latency`.
  - `stripe.env`, `vultr.env`.
  - DB backups `backup-pre-d37-*.db` and `backup-pre-920-*.db`.
- **Pi access:** key-auth `ssh fazetime@fazetime` only. Never a password or sudo. The Pi is a plain file copy, not a git checkout: deploy with `rsync`, excluding `.venv`, `var/`, `models/`, `out/` and `bench/`.
- **Gemini free tier** (verified, `docs/evidence/p0/P0-C-gemini.md`): Flash-Lite 3.5 and 3.1 at 15 RPM / 500 RPD each. Gemma 4 at 14.4K RPD, but HTTP 500 on about half its calls.

## Do not repeat / known failures

- **Capture:**
  - Never use a GAP/STALE threshold of 6 s or less; Twitch bursts arrive about 6 s apart.
  - Never use the WAL journal mode (D23).
  - Never pass `--twitch-disable-ads`.
  - Never run `cpu_threads=4` on the Pi alongside other load.
- **ASR:** never use decoder prompts or hotwords. Never commit third-party media or any transcripts.
- **Gemini:**
  - The client timeout must be **at least 10 s**; 8 s gave HTTP 400 on every call.
  - Gemma: no system instruction, and expect 500s.
  - The first 3.1 call of a process may 504.
- **Worker wiring:** the uplink must post through `EvidenceTap`, or the AI never sees acknowledged frames. This is fixed and has a regression test.
- **Fixture runs:** a TEST_FIXTURE file that ends restarts the source, which creates a new epoch and voids the open market. Loop it (`-stream_loop 1`).
- **Process checks:** `pgrep -f`/`pkill -f` in a one-liner matches its own shell's command text, including later commands on the same line. Kill in a separate command.
- **Browser APIs:** `crypto.randomUUID` is undefined on the plain-http tailnet origin. The console needs `src/polyfills.ts` first.
- **Origins:** never use wildcard extension origins.
- **Vultr:** never create a resource without `check-create` and the `fazetime` tag.
