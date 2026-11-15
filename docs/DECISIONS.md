# Decision register

Status meanings:
- OWNER_CONFIRMED: the owner chose it.
- DESIGN_DEFAULT: a reviewable engineering choice.
- OPEN: not yet decided.
- DEFERRED: postponed.

The phase plan owns execution order. This register owns decisions and their provenance. When the owner makes a later decision, it supersedes the older text explicitly.

| ID | Status | Decision and consequence |
|---|---|---|
| D01 | OWNER_CONFIRMED | Hackathon demo only. Stripe test mode. No real money and no public launch. |
| D02 | OWNER_CONFIRMED | Python backend; TypeScript extension and dashboard. This supersedes an earlier Rust API preference. |
| D03 | OWNER_CONFIRMED | $0 external spend unless absolutely necessary and discussed separately. Use existing machines and verified sponsor allocations first. |
| D04 | OWNER_CONFIRMED | The team's prerecorded video broadcasts through OBS to Twitch. Final ingestion must consume what Twitch delivers. |
| D05 | OWNER_CONFIRMED | A manual FaceTime fallback is acceptable. Falling back from Twitch to a local file is not. |
| D06 | OWNER_CONFIRMED | Binary pari-mutuel pool payouts with zero fee. Show estimates before lock. |
| D07 | OWNER_CONFIRMED | A user's raffle odds follow the cumulative amount they wagered in the stream. No ticket purchases or multipliers. |
| D08 | OWNER_CONFIRMED | Proposals and results should be automatic where quality allows; the operator approval mode stays available. |
| D09 | OWNER_CONFIRMED | Chert provides 24 hours of free sponsor usage. See D18 for the confirmed limits. |
| D10 | OWNER_CONFIRMED | **Deadline:** submission cutoff 12:00 Sun 2026-11-15. America/Chicago is assumed from the venue and laptop. **Machine roles:** see D22. **Challenge:** see D19. The number of human builders is not stated; plan for one owner plus agents. |
| D11 | OWNER_CONFIRMED | A user's raffle weight is their accepted stake in settled, non-void markets in the current stream run, win or lose. Deposits, refunds, redemption spend and bots do not count. The draw snapshot waits only for markets still unfinished when the cue fires. See D27 for the draw boundary. |
| D12 | OWNER_CONFIRMED | A market with an empty or one-sided pool **must** become VOID at lock, with every stake refunded. Voids earn no raffle weight and carry no fee. |
| D13 | DESIGN_DEFAULT | One FastAPI process plus SQLite on one host (D22). Sponsor PostgreSQL only if an actual need outweighs the time cost. |
| D14 | OWNER_CONFIRMED | "Whatever works." The **bundled** WXT/React ShadowRoot panel is the primary path. The hosted-URL iframe is dropped from P1 because of the deadline and may only be revisited after the core gate. There is no arbitrary URL relay. |
| D15 | OWNER_CONFIRMED | Identity is invite-only demo sessions using one-time enrollment codes. Test payments use Stripe-hosted Checkout outside the panel. Phone is not an identity factor. |
| D16 | OWNER_CONFIRMED | The owner said phone opt-in adds unnecessary complexity, so there is no viewer-facing phone opt-in or verification flow, and no phone field in P1. Calls go only to the team's own demo devices, listed in local operator configuration that is never committed. Any bet made in a call needs a fresh, explicit confirmation. Insufficient funds lead to test Checkout plus a new confirmation, never an automatic saved-card charge. |
| D17 | OWNER_CONFIRMED | Prioritise the viewer's experience, and do the simplest thing that works. If time forces a choice, P10 (raffle winner call, with the accepted manual FaceTime fallback) comes before P11, which is the first expansion to cut. Phase specifications are kept, not deleted. |
| D18 | OWNER_CONFIRMED | The 24-hour Chert grant is usable through judging, but only **50 free FaceTime minutes** are available. A second Chert account is possible but must not be relied on. Group video and identity exposure are still unverified (P0-E). A team member plays the creator. |
| D19 | OWNER_CONFIRMED | **Challenge:** a prerecorded Minecraft 1v1, FaZeGavin vs FaZeNeville. Opening line: "Hi it's FaZeGavin and we'll be 1v1ing my friend FaZeNeville!" **Cues:** the start and outcome cues are coordinator proposals awaiting the recording (see HANDOFF). The minimum lead-in comes from measurements. |
| D20 | OWNER_CONFIRMED | The Gemini key is in `.env.local` and valid: `models.list` returned HTTP 200 at 2026-11-14 20:40 CT, and `gemini-3.5-flash-lite` is listed. On 2026-11-14 ~21:10 CT the owner confirmed the key's project is on the **free tier with no billing linked**. Free-tier content may be reviewed by humans, so send demo media only. Numeric RPM/TPM/RPD limits are visible only in AI Studio and are still to be recorded. Never link billing or switch to a paid key automatically. |
| D21 | DEFERRED | Real-money operation, store distribution, withdrawal, live card charging, public recruitment, multi-stream scaling, chat choice highlighting, referrals, watch-time streaks, nostalgic email outreach, and the hosted-URL iframe panel (D14). |
| D22 | OWNER_CONFIRMED | **Machine roles:** Raspberry Pi 5 `fazetime` (16 GB) runs the API, SQLite, Twitch capture and speech-to-text, subject to the P0-D benchmark on the Pi. OBS runs on the laptop `latpop` (recommended), or on the Pi if needed. Viewer browsers are laptops. If the Pi fails its benchmark, the fallback (DESIGN_DEFAULT) is to move API and ASR together to `latpop`. |
| D23 | DESIGN_DEFAULT | SQLite runs with `journal_mode=DELETE`, `synchronous=FULL`, `foreign_keys=ON` and `busy_timeout=5000`. Every money or state mutation uses `BEGIN IMMEDIATE`. Reason: sqlite.org's WAL-reset bug affects 3.7.0–3.51.2, which includes the laptop's 3.45.1 and the Pi's 3.46.1. |
| D24 | DESIGN_DEFAULT | Toolchain: Python 3.12 (uv-managed) on all hosts for the API and worker; Node 24 LTS for the extension tooling (Node 25 reached end of life on 2026-06-01). Versions are pinned to what passes measurement. |
| D25 | DESIGN_DEFAULT | Network: browsers and workers reach the API over the team tailnet (MagicDNS `fazetime`). No public tunnel unless P0-F shows a need. Stripe test webhooks arrive via `stripe listen` forwarding on the API host. |
| D26 | DESIGN_DEFAULT | Contract v1 freeze is in CONTRACTS §9. It splits `rules_version` from `aggregate_version`, binds labels to their sides, and scopes idempotency to the actor. Wallets are per (user, run), seeded fresh each run. A user may bet only one side per market. "Unresolved" means a VOID with refund. A durable sweeper performs lock, void and timeout. |
| D27 | DESIGN_DEFAULT | Raffle draw boundary (P8/P9): an armed cue blocks new markets only and never closes an open market early. The snapshot is taken once the market open at trigger time ends. In the demo script the cue follows the settled 1v1, so there is no wait. |
| D28 | DESIGN_DEFAULT | Persistence uses stdlib `sqlite3` with explicit parameterized SQL, explicit `BEGIN IMMEDIATE`, and numbered SQL migration files applied at startup. There is no ORM. This settles D13's "pick once". Reason: explicit transaction control and fewer moving parts before the deadline. |
| D29 | DESIGN_DEFAULT | Source-health thresholds: LIVE ≤12 s, STALE 12–30 s, STOPPED >30 s (CONTRACTS §9.4). The spike measured 6 s media bursts. P0-B and P3 may test Streamlink's generic `--hls-playlist-reload-time segment` to shorten the cadence. That option is not an ad bypass. |

## Change log

To record a change, append:
- ID and date
- owner or source
- the previous choice it supersedes
- the new choice
- the reason
- affected phases and contracts
- migration required
- evidence

Do not keep two active, contradictory decisions.

- **2026-11-14 ~20:35 CT, owner chat answers to the phase-0 questions (1–6).**
  - D10, D11, D12, D14, D15, D16, D17, D18, D19 and D22 moved to OWNER_CONFIRMED.
  - D16 changed: the viewer-facing phone opt-in was removed, and the restriction to approved devices was kept (AGENTS fixed constraint).
  - D14 changed: the bundled panel replaces the hosted-URL iframe for P1, because the owner said "whatever works".
  - The owner asked whether raffle weight follows deposits. The coordinator clarified that weight is wagered stake (D07, AGENTS constraint). The owner did not change D07.
  - Affected: P1 (no phone field, bundled panel), P8–P11.
  - Migration: none, since no code exists.
- **2026-11-14 21:25 CT, coordinator: D22 primary restored.**
  - The owner installed the official 27 W supply. The re-run then showed `0x0` throttling under about 20 min of load (spikes/p0-pi/README.md).
  - The Pi again hosts the API, capture and ASR, as the owner chose. Provisional ASR: tiny.en, int8, `cpu_threads=3`, VAD on.
  - base.en only after a bounded-decoding test passes: `temperature=0`, capped tokens, a per-chunk deadline.
  - `cpu_threads=4` is never used while other work needs a core.
  - The laptop stays the measured fallback, about 3.5× faster.
- **2026-11-14 20:56 CT, coordinator: D22 fallback activated.**
  - Evidence (spikes/p0-pi/README.md): the Pi ASR benchmark was stopped by under-voltage. There is no USB-PD contract, so the board negotiates 900 mA instead of 5 A.
  - Until the owner installs the official 27 W supply and a re-run passes, the API, capture and ASR run on `latpop`. The owner's Pi preference stays recorded, and moving back to the Pi is a host move with the same code.
  - What did work on the Pi: Streamlink audio plus PyAV decode without the ffmpeg CLI, and tailnet HTTP/WS.
  - Affected: P2 deployment, P3, P7.
- **2026-11-14, coordinator.**
  - D20 updated from the `models.list` check.
  - D23–D27 added from the P0-G planner proposal and reviewer findings (docs/evidence/p0/P0-G-contract-review.md).
  - Affected: CONTRACTS v1, P2 schema, P8.
