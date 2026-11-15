# Current execution status

Updated: 2026-11-15 ~02:50 CT. Plan version: 1.0 + contract v1 (CONTRACTS §9, items 9.15–9.18). State: CORE BUILT AND DEPLOYED; real-world gates P3–P6 pending; P7–P10 not started. **D37 (game-agnostic AI markets) is integrated and deployed on the Pi (worker profile `generic`); the Twitch gate is pending.** See HANDOFF for the runbook.

**Deadline:** submission cutoff 12:00 CT Sun 2026-11-15 (D10). About 15 h were left at 21:00.

**Time allocation (15/45/20/20):**

| Block | Ends (CT) |
|---|---|
| P0 | ~23:15 |
| Core P1–P7 | ~06:00 |
| P8–P11 expansion | ~09:00 |
| Feature freeze | 09:00 |
| Rehearsal and buffer | 09:00–12:00 |

| Phase | State | Evidence |
|---|---|---|
| P0 Capability and contract gates | **COMPLETE_WITH_ACCEPTED_FALLBACK** | Twitch proven on the team channel (`docs/evidence/p0/P0-B-twitch.md`); Gemini proven (`P0-C-gemini.md`); STT proven on the Pi with team audio (tiny.en, duty 0.34); network over the tailnet; contract v1 frozen. Chert PARTIAL, with the manual FaceTime fallback (D05). Open, non-blocking: free-tier quota figures (AI Studio) and the glass-to-capture delay, which moves to P4 |
| P1 Extension mocks | **COMPLETE** (mock gate) | Coordinator re-ran 94/94 extension and 190/190 contracts. Playwright on live Twitch passed 25/25: install, mount once, SPA remount, close/reopen, resize, no focus trap, mock wager, insufficient funds → "FaZe Up!", all terminal banners, theater mode, chat collapse/expand, full-screen hides the pill. The owner loaded the mock build in Flatpak Chrome: "looks alright". MOCK is shown in mock builds. Live builds follow D31 |
| P2 Server/users/presence/ledger foundation | BUILT, gate PARTIAL (checkpoint commit on `hackathon-build`) | pytest 167 passed, 2 skipped (coordinator re-run). Review: **accept with limitations**, no Critical/High (`docs/evidence/p2/P2-review.md`), bound to `6930352`. Fixes M2 (pinned origin) and M3 (constraint tests) are in progress. **Two-browser e2e PASSED 31/31** (with D31 clean UI; bet sync 118 ms): two Chromium processes against the real API with the pinned origin; the pool update reached the other viewer in 310 ms; WS-drop → polling → reconnect; correct settlement banners and balances; ledger reconciled. **Still pending:** the Pi run, the M2/M3 fixes, and the operator console (P2-E, in progress) **Still pending:** the two-browser live test (extension live adapter, in progress) and the run on the Pi (in progress) |
| P3 Twitch perception | BUILT, gate pending a live run | Worker deployed on the Pi (env ready; `check` reports no problems), with remote ASR (Vultr distil-small.en) and local tiny.en fallback. The gate needs a live team-channel run through the Pi API |
| P4 AI proposals | BUILT (H2H), gate pending Twitch evidence; **D37 generic: fixture prototype** | Backend §9.17 (502 tests) and the worker proposer (101 tests; synthetic live smoke correct) are deployed. The supervised-AI console is live on the Pi (AI e2e 10/10). APPROVAL mode. The gate needs the owner's recording through Twitch. **D37:** the game-agnostic observer, reducer and template proposer in `spikes/p4-generic/` were replayed on two owner Peggle recordings (LOCAL FIXTURE). Pass 3: 4 markets, 2 correct, 2 correct voids, 0 wrong. A bet is published 2–5 s after its trigger (`docs/evidence/p4/P4-generic-fixture-replay.md`). **Integrated** (`761616a`, `5df12ac`, `a2d272e`):
  - API `GENERIC_BINARY_V1` with a 35 s floor (552 tests); console (73 tests); worker generic profile (151 tests).
  - LOCAL end-to-end on real code: run 4 proposed, approved with 35 s from approval, staked both sides, then settled a correct YES.
  - Deployed to the Pi at ~02:38 CT, with migration 0006 applied.
  - The gate still needs a Twitch run |
| P5 AI outcomes | BUILT (H2H), gate pending Twitch evidence; **D37 generic: fixture prototype** | Resolver plus operator resolution approval (e2e settled exactly once). The gate needs a positive and a negative real outcome. **D37:** two parallel extraction reads (3.5 and 3.1 Flash-Lite), with the decision made in code. Settlement lands 19–20 s after the labelled end in fixtures, and every miss so far was a correct void |
| P6 Test payments and wagering | BUILT, gate pending a 4242 checkout | API top-ups and webhook (§9.18) deployed on the Pi with a laptop `stripe listen` forwarding to it. The extension hands off to Stripe Checkout (117 tests). The gate needs one real 4242 test checkout credited exactly once, plus negative cases |
| P7 Integrated core | NOT_STARTED | None |
| P8 Weighted raffle | NOT_STARTED | None |
| P9 Spoken raffle trigger | NOT_STARTED | None |
| P10 Winner call | NOT_STARTED | None |
| P11 Absent-viewer bookie | NOT_STARTED | First expansion cut (D17) |

## P0 packets

| Packet | State | Result so far |
|---|---|---|
| P0-A inventory | Laptop VERIFIED; Pi inventoried | Pi 5, 16 GB, Debian 13 aarch64; no ffmpeg, git or pip; under-voltage logged since boot |
| P0-B Twitch | TOOLCHAIN_SMOKE passed on a public channel | Anonymous Streamlink 8.6.3 → FFmpeg; kill → new epoch in about 2.4 s; media arrives in 6 s bursts. **Gate blocked** on the team channel and an OBS broadcast |
| P0-C Gemini | **VERIFIED** (free tier, D20) | One request to `gemini-3.5-flash-lite` with image + text + JSON schema: valid output, 2.3 s, 1,161 in / 102 out tokens. One 854×480 frame costs about 1,100 tokens. The free RPM/RPD figures are still unread; see `docs/evidence/p0/P0-C-gemini.md` |
| P0-D ASR | **Pi MEASURED on the official PSU**; laptop measured | Pi, 20 min near-full load: `0x0` throttling, max 60.9 °C. tiny.en int8 at 3 threads keeps up with a large margin (speech-chunk p50 0.93 s, duty 0.16). base.en fits on average but stalls on noise chunks through temperature-fallback retries (one chunk took 45 s), so it needs bounded decoding first. small.en is too slow. Capture at 480p30 costs about 9% of one core. The laptop is about 3.5× faster. Audio was non-representative; ground-truth accuracy is untested. See `spikes/p0-pi/README.md` |
| P0-E Chert | **PARTIAL, with the manual fallback recorded** | Read-only GETs at 21:02 CT showed one shared line (***7200) with audio and video, and a worker reporting group-call support. Line status was busy (shared). 0 calls so far. Minutes, expiry and group video are visible only in the dashboard, and the $0 LiveKit path is unverified. See `docs/evidence/p0/P0-E-chert.md` |
| P0-F network | Tailnet **VERIFIED** (DERP relay) | Laptop → Pi over Tailscale: HTTP 200; WebSocket round-trip p50 13 ms, p95 15.5 ms; survives 120 s idle; reconnects after restart. Bundled panel (D14), so no public route is needed. API calls will run from the extension background, avoiding mixed-content and local-network-access issues |
| P0-G contracts | v1 FROZEN | CONTRACTS §9; decisions D23–D29 |

- **Critical unknowns:** the team Twitch channel/OBS capture through Twitch; Pi ASR throughput; Chert line capabilities; Pi power supply. The Gemini free-tier quotas are now VERIFIED: Flash-Lite 3.5 and 3.1 at 500 RPD each, Gemma 4 at 14.4K RPD (`docs/evidence/p0/P0-C-gemini.md`).
- **Approved cuts:** manual FaceTime handoff (D05); bundled panel instead of the hosted iframe (D14); P11 is the first expansion to cut (D17).
- **Not approved:** replacing Twitch with local playback for final acceptance.

Keep this file to current facts. Link detailed evidence rather than pasting logs. Only the coordinator updates overall phase state.
