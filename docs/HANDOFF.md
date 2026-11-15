# Current handoff (checkpoint for context reset)

- **Timestamp / coordinator:** 2026-11-14 ~22:55 CT. Coordinator session in the Claude Code desktop app (2.1.289, Opus 5.5 `claude-opus-5-5`).
- **Deadline:** 12:00 CT Sun 2026-11-15. Feature freeze 09:00; rehearsals 09:00–12:00.
- **Branch:** `hackathon-build`, pushed to `origin` (graysmal/FaZeTime, a **PUBLIC** repo). Run `git log -1` for the exact SHA.
  - The owner authorized committing and pushing coherent, reviewed increments.
  - Scan the staged diff before every push: no names, phone numbers, IDs, IPs of private hosts, or keys.
  - No key-shaped literals even in tests; push protection blocks them, and the bypass is never used.

## Phase state

See STATUS for the evidence.

| Phase | State |
|---|---|
| P0 | COMPLETE_WITH_ACCEPTED_FALLBACK (Chert: manual FaceTime) |
| P1 | COMPLETE (mock gate). D31: the live UI looks real, with a single "test credits" note |
| P2 | Built and reviewed (accept with limitations). Fixes merged; two-browser e2e 31/31; API running on the Pi. Remaining for the P2 gate: an owner-run multi-laptop check against the Pi |
| P3 | Worker built (33 tests) and API routes live. Remaining: a live run on the Pi against the Pi API with the team channel |
| P4/P5 | In progress. Contract frozen (CONTRACTS §9.17) |
| P6 | Adapter merged (CONTRACTS §9.18). Wiring in progress |
| P7–P11 | Not started. P11 is the first cut (D17); P10 is a manual FaceTime handoff |

## In-flight workers

They report to THIS session, and their work is uncommitted on disk.

If the session resets before a worker reports: run `git status`, review the diff in that worker's paths, and re-run its tests. Then either finish the work or re-delegate it with the same packet, summarised from this table.

| Worker | Paths (sole owner) | Task / expected result |
|---|---|---|
| Backend P4/P5 | `services/api/fazetime_api/ai.py`, `migrations/0004_ai.sql`, `tests/test_ai*.py`; edits to `domain.py`, `api_operator.py`, `views.py`, `worker.py`, README | §9.17 worker proposals and resolutions, operator candidates, resolutions and ai-mode (AUTOMATIC only with `FAZETIME_ALLOW_AUTOMATIC`); settle `note`; operator health with modes, worker detail and limits. Full suite must pass |
| Stripe P6-C/D | `fazetime_api/topups.py`, `migrations/0005_topups.sql`, `tests/test_topups*.py`, `api_viewer.py` top-up stubs, `integrations/**` | `POST /v1/topups`, `GET /v1/topups/{id}`, `POST /v1/webhooks/stripe` per §9.18. It reports a `payment_mode(services)` call site for the coordinator to wire into `views.py` |
| AI P4/P5 (worker) | `services/worker/fazetime_worker/{gemini,proposer,resolver,context}.py` + tests; edits to `pipeline.py`, `config.py`, README, pyproject/uv.lock (`google-genai==3.3.0`) | Gemini proposer (deterministic pre-filter, H2H_WINNER_V1, abstention) and resolver (YES/NO/WAIT/UNRESOLVABLE with evidence). Rate limit and daily budget; ≤6 live calls in smoke tests |
| Vultr ASR | `services/asr_remote/**`; `services/worker/fazetime_worker/asr_remote.py` + `tests/test_asr_remote.py` (new files only) | faster-whisper service on VM `fazetime-asr`: tailnet-only `:8090`, bearer `ASR_REMOTE_TOKEN`, systemd. Model chosen by benchmark on team audio. Client with circuit breaker and local tiny.en fallback. **The coordinator wires the client into `pipeline.py` afterwards** |

The two `services/api` workers share `main.py`, `ids.py`, `config.py` and `schemas.py` with append-only edits. Migration numbers are fixed: 0004 = AI, 0005 = top-ups.

## Deployed state

- **Pi `fazetime`** (key-auth `ssh fazetime@fazetime`; never a password or sudo):
  - **API:** `http://fazetime:8000` (tailnet IP only), code digest `99feda70f09dc5f6`, equivalent to `dcd699e`. Data in `~/fazetime-data`. Control: `services/api/scripts/pi_run.sh start|stop|status|restart`.
  - **Origins:** `https://www.twitch.tv` and `chrome-extension://hodaaffdhncidmaccebmionoljljfefe`.
  - **DONE ~23:15 CT:**
    - Redeployed the AI and top-up API (commit `76508bd`). `~/fazetime-data/api.env` (600) sets `FAZETIME_AI_MODE_DEFAULT=APPROVAL` and the Stripe env file `~/fazetime-data/stripe.env` (600).
    - Health: ai_mode APPROVAL, payment_mode STRIPE_TEST, automatic not allowed.
    - The operator console is served at `http://fazetime:8000/operator/`.
    - Stream `fazegavin1234` is created (`str_dcf14fde37d544be9b1bac9668938eae`).
    - **The owner's operator invite** is in `~/Documents/fazetime-operator-invite.txt` (600). A second, automation operator session is in the coordinator's scratchpad.
    - **Stripe listener** runs on the laptop via `infra/stripe/start_listener.sh` → `http://fazetime:8000/v1/webhooks/stripe`. Its log is private.
  - **Worker:** `~/fazetime-data/worker.env` (600) holds the API base, worker token, stream ID, channel, Gemini key, streamlink path and models dir. `fazetime_worker check` reports no problems. **Not running yet**; start it with `scripts/run_pi.sh` when the owner streams. Remote ASR wiring is pending the Vultr worker.
  - **Vultr budget guard:** runs via `~/fazetime/infra/vultr/start_guard.sh` (crontab `@reboot`), log `~/fazetime-data/vultr-guard.log`.
- **Vultr:**
  - VM `fazetime-asr`: tailnet MagicDNS `fazetime-asr`, plan `voc-c-8c-16gb-150s-amd`, $0.219/h, tag `fazetime`.
  - Spend $0.24 at 22:50 CT; projected about $4.45 to the deadline.
  - Hard stop $85 pre-tax ($100 incl. tax, D34). Auto-teardown Sun 18:00 CT.
  - Guards on the Pi and the laptop (`~/.local/state/fazetime/vultr-guard.log`). Runbook: `infra/vultr/README.md`.
- **Laptop `latpop`:**
  - Extension builds in `~/Documents/fazetime-extension{,-live,-live-pi}` (ID `hodaaffdhncidmaccebmionoljljfefe`).
  - Stripe CLI 1.55.11 at `~/.local/bin/stripe`; use `--api-key` from the environment, no login.
  - OBS 32.2 for streaming the recordings.

**`.env.local` keys** (names only): `GEMINI_API_KEY`, `CHERT_API_KEY`, `CHERT_PROJECT_ID`, `CHERT_LINE_NUMBER`, `DEMO_CALL_ALLOWLIST`, `STRIPE_SECRET_KEY` (test), `STRIPE_WEBHOOK_SECRET` (CLI, device `fazetime-api`), `TAILSCALE_AUTH_KEY` (reusable, 90 days; revoke after the event), `VULTR_API_KEY` (access list `129.107.192.0/24`), and `ASR_REMOTE_TOKEN` (being added by the Vultr worker).

## Next concrete actions, in order

1. **Review each worker report:** run the tests, read the diffs, rule on contract questions, commit and push.
2. **Wire up the Stripe and Vultr code:**
   - Stripe `payment_mode` call site in `views.py`.
   - The remote ASR client in the worker `pipeline.py`: remote first, with the local tiny.en fallback.
3. **Deploy to the Pi:**
   1. API (applies migrations 0004 and 0005).
   2. The operator dist.
   3. Bootstrap the operator: the owner's invite goes to `~/Documents/fazetime-operator-invite.txt` (mode 600).
   4. Worker token and stream.
   5. Start the worker.
   6. Run `stripe listen --device-name fazetime-api --forward-to http://fazetime:8000/v1/webhooks/stripe` on the laptop.
4. **First real end-to-end** with the owner streaming a recording: Twitch → Pi transcript and frames → Gemini candidate → operator approves → two laptops bet → lock → result suggestion → operator approves → settle. Record the P4/P5 evidence and the measured lead-in.
5. **P6 gate:** one 4242 test checkout credited exactly once, plus the negative cases.
6. **P7:** two consecutive full rehearsals and the fault drill. Then P8/P9 (raffle and spoken trigger), then P10 manual FaceTime.

## Owner actions pending

- **Record two Minecraft 1v1 takes**, one won by each player. Cues are in D19 and the earlier HANDOFF: an opening line, ≥90 s of setup, "3, 2, 1, fight!", the death message visible, and a spoken winner.
- **Set the OBS keyframe interval to 2 s**, and add the clock overlay `spikes/p0-media/obs_clock.html` for delay measurement.
- **Later:** the 4242 test checkout; rehearsals; the manual FaceTime call.

## Do not repeat / known failures

- **Capture:**
  - Never use a GAP/STALE threshold of 6 s or less: Twitch delivers media in bursts about 6 s apart.
  - Never use the WAL journal mode (D23).
  - Never pass `--twitch-disable-ads`.
  - Never run `cpu_threads=4` on the Pi alongside other load.
- **ASR:**
  - Never use decoder prompts or hotwords: they hallucinated "FaZeGavin" and "1v1".
  - Never commit third-party media or any transcripts.
- **Process checks:** `pgrep -f` in a shell one-liner matches its own command line. Use a script file, or the `[x]` bracket trick.
- **Origins:** never use wildcard extension origins.
- **Vultr:** never create a resource without `check-create` and the `fazetime` tag.
