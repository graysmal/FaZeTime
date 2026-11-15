# Current execution status

Updated: 2026-11-14 ~21:05 CT. Plan version: 1.0 + contract v1 freeze. State: P0_IN_PROGRESS. P1 and P2 started early, because their only dependencies were the UI decisions and the contract freeze.

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
| P0 Capability and contract gates | IN_PROGRESS | `docs/evidence/p0/` (inventory, docs verification, contract review), `spikes/p0-media/README.md`. Contract v1 frozen in CONTRACTS §9 |
| P1 Extension mocks | BUILT, gate PARTIAL (checkpoint commit on `hackathon-build`) | Coordinator re-ran contracts 190/190, extension 77/77, tsc and the build. Playwright on live Twitch passed 19/19 (mount once, SPA remount, mock wager, insufficient funds → "FaZe Up!", banners, resize, no focus trap). **Still pending:** a manual Flatpak Chrome pass (theater mode, full-screen, chat collapse, popup, Load unpacked) |
| P2 Server/users/presence/ledger foundation | BUILT, gate PARTIAL (checkpoint commit on `hackathon-build`) | pytest 167 passed, 2 skipped (coordinator re-run). Independent review in progress. **Still pending:** the two-browser live test (extension live adapter, in progress) and the run on the Pi (in progress) |
| P3 Twitch perception | IN_PROGRESS | Worker contract frozen (CONTRACTS §9.16). The worker is choosing the ASR model on the team audio and building `services/worker`. The backend is adding the worker routes |
| P4 AI proposals | NOT_STARTED | None |
| P5 AI outcomes | NOT_STARTED | None |
| P6 Test payments and wagering | NOT_STARTED | None |
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

- **Critical unknowns:** the team Twitch channel/OBS capture through Twitch; whether the Gemini project is on the free tier; Pi ASR throughput; Chert line capabilities; Pi power supply.
- **Approved cuts:** manual FaceTime handoff (D05); bundled panel instead of the hosted iframe (D14); P11 is the first expansion to cut (D17).
- **Not approved:** replacing Twitch with local playback for final acceptance.

Keep this file to current facts. Link detailed evidence rather than pasting logs. Only the coordinator updates overall phase state.
