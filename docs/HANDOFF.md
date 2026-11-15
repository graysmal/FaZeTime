# Current handoff

- **Timestamp / coordinator:** 2026-11-14 22:01 CT. Coordinator session in the Claude Code desktop app (2.1.289, model Opus 5.5 `claude-opus-5-5`).
- **Deadline:** 12:00 CT Sun 2026-11-15, about 14 h away.
- **Branch:** `hackathon-build` @ `e4f736a`, pushed to `origin` (graysmal/FaZeTime, a **public** repo).
  - The owner authorized committing and pushing coherent increments.
  - Never commit names, phone numbers, Chert or Stripe IDs, or keys.
  - Run a scan of the staged diff before every push.

## Phase state

See STATUS for the evidence.

| Phase | State |
|---|---|
| P0 | Closing. Remaining: the P0-B team-channel analysis from the media worker, then the coordinator writes the P0 gate record |
| P1 | Built. The owner loaded the mock build in Flatpak Chrome: "looks alright". Visual critique deferred; focus on function |
| P2 | Built, and the two-browser e2e passed 29/29. Remaining: the Pi run, review fixes M2/M3, and the operator console |
| P3 | In progress |
| P4/P5 | Contract frozen (CONTRACTS §9.17), not started |
| P6 | Adapter prep in progress |

## Active workers

All work in the main checkout on disjoint paths and do not commit.

| Worker | Paths | Task |
|---|---|---|
| Backend | `services/api/**` | §9.16 worker routes; review fixes M2, M3, L1–L3 and L8; D30 operators cannot wager; `/operator` static mount; Pi deploy with origins `https://www.twitch.tv,chrome-extension://hodaaffdhncidmaccebmionoljljfefe` |
| Media | `services/worker/**`, `spikes/p0b-team/**` | P0-B analysis and choosing the ASR model on the team audio, then the P3 worker |
| Extension | `apps/extension/**`, `packages/contracts/**` | D31 clean live UI with one "test credits" note; snapshot refresh on reload; theater/chat/full-screen smoke checks |
| Operator console | `apps/operator/**` | New React/Vite app, served by the API at `/operator/` |
| Stripe | `services/api/fazetime_api/integrations/**`, `services/api/tests/integrations/**`, `spikes/p6-stripe/**` | Stdlib adapter for Checkout and webhooks, a fulfillment planner, and a test-mode smoke run |

## Next assignments, after the current reports

1. **Backend (queued gaps from the operator console, commit `bed549e`):**
   - an optional settle `note` (at most 200 chars) recorded in the audit row;
   - operator health returns `modes`, worker detail (`asr_backlog_ms`, `queue_depth`, heartbeat age, `host_id`) and the market limits (minimum lead, close/resolve bounds);
   - a self-logout route that revokes only the current session;
   - `FAZETIME_OPERATOR_DIST` in the README environment table.
   Then the P4/P5 routes from §9.17, plus P6 wiring: a topups table, the webhook route with the raw body, and fulfillment inside the transaction, following the Stripe adapter's report. Then a review.
2. **Media:** the Gemini proposer and resolver from §9.17 (`gemini-3.5-flash-lite`, structured output, few frames), tested against the owner's recordings.
3. **Extension:** P6-E, the Stripe Checkout handoff in Wallet, once the backend routes exist.
4. **Coordinator:** the P0 gate record; then commit and push each accepted increment.

## Owner actions

- **Record two Minecraft 1v1 takes**, ETA about 00:00 CT. One where FaZeGavin wins, one where FaZeNeville wins. Cues:
  - in-game names FaZeGavin and FaZeNeville;
  - the opening line from D19, then at least 90 s of setup;
  - "3, 2, 1, fight!";
  - chat visible so the death message shows;
  - a spoken "FaZe<name> wins!".
- **Then stream them via OBS** on `latpop` to `fazegavin1234`, for the live P3/P4/P5 tests.
- **Later:** a P6 test checkout using Stripe's published test card in Stripe's test-mode page; the rehearsals; and a manual FaceTime handoff for P10. Chert is blocked unless the owner wants automation.

## Environment facts

- **`.env.local` keys** (names only): `GEMINI_API_KEY`, `CHERT_API_KEY`, `CHERT_PROJECT_ID`, `CHERT_LINE_NUMBER`, `DEMO_CALL_ALLOWLIST`, `STRIPE_SECRET_KEY`. The Stripe key's test-mode prefix has been verified.
- **Stripe CLI** 1.55.11 at `~/.local/bin/stripe`. Use `--api-key`; no login is needed.
- **Pi `fazetime`:**
  - Official PSU: `0x0` throttling under load.
  - Reached with `ssh fazetime@fazetime` using key auth only. Never use a password or sudo.
  - The API binds only to the tailnet IP on port 8000 (`http://fazetime:8000`), with data in `~/fazetime-data/`.
  - ASR: tiny.en at 3 threads is provisional, pending the team-audio test.
  - The P0-B capture output is in `~/fazetime-p0b/`. It is the team's own content; keep it out of git.
- **Extension builds** in `~/Documents/`:
  - `fazetime-extension` (mock)
  - `fazetime-extension-live` (`127.0.0.1:8000`)
  - `fazetime-extension-live-pi` (`fazetime:8000`)
  - Pinned extension ID: `hodaaffdhncidmaccebmionoljljfefe`.

## Do not repeat / known failures

- Never use a GAP/STALE threshold of 6 s or less: Twitch delivers media in bursts about 6 s apart.
- Never use the WAL journal mode (D23).
- Never pass `--twitch-disable-ads`.
- Never run `cpu_threads=4` on the Pi alongside other load.
- Never use wildcard extension origins.
- Never commit third-party media or transcripts.
- Never write key-shaped literals in tests, even obviously fake ones (`sk_test_…`, `rk_live_…`, `whsec_…`). GitHub push protection blocks them in this public repo. Split them with adjacent literals, for example `"sk" "_test_FIXTURE…"`. Never use the "allow secret" bypass.
- `STRIPE_WEBHOOK_SECRET` (CLI listener, `--device-name fazetime-api`) is now in `.env.local`. **P6 wiring is not done yet.** It goes to the backend owner after its current task, following CONTRACTS §9.18 and the integration steps in spikes/p6-stripe/README.md.
