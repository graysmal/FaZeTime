# Current handoff

- **Timestamp / coordinator:** 2026-11-14 ~21:05 CT, coordinator session in the Claude Code desktop app (Claude Code 2.1.289, model Opus 5.5 `claude-opus-5-5`).
- **Current phase / task:** P0 exit gate. P1 and P2 are running in parallel.
- **Branch and commit:** `hackathon-build`, pushed to `origin` (graysmal/FaZeTime, a **public** repo) at ~21:50 CT with the owner's authorization.
  - Before the first push, the two local commits were squashed into one checkpoint for phases 0–2, so that a teammate's name and a device name never reached public history.
  - The branch starts from `master` @ `6c05030`.
  - Workers' in-progress edits after the checkpoint stay uncommitted until they are reviewed.
  - Never commit names, phone numbers, IDs or keys: the repo is public.
- **Env keys in `.env.local`** (names only): `GEMINI_API_KEY`, `CHERT_API_KEY`, `CHERT_PROJECT_ID`, `CHERT_LINE_NUMBER`, `DEMO_CALL_ALLOWLIST` (team phone ***9335).
- **Team Twitch channel:** `fazegavin1234`. Not live at 21:01 CT.

**Uncommitted changes and their owners**

| Owner | Paths |
|---|---|
| Coordinator | `.gitignore`, `docs/DECISIONS.md`, `docs/STATUS.md`, `docs/HANDOFF.md`, `docs/CONTRACTS.md` (§9 v1 freeze plus line fixes), `docs/ECONOMICS.md` (4 alignment edits), `PROJECT_PLAN.md` (P5 timeout sentence), `docs/evidence/p0/*` |
| P0 media worker (finished) | `spikes/p0-media/**` |
| Pi worker | `spikes/p0-pi/**` and `~/fazetime-spike/**` on the Pi |
| Chert worker | `spikes/p0-chert/**` |
| P1 worker | `apps/extension/**`, `packages/contracts/**`, `~/Documents/fazetime-extension/` |
| P2 worker | `services/api/**` |

**Decisions changed this session:** D10–D12 and D14–D22 moved to OWNER_CONFIRMED. D23–D29 added as DESIGN_DEFAULT. See the change log in DECISIONS.

**Checks**
- **Passed (MEASURED):**
  - Laptop and Pi inventory.
  - Twitch TOOLCHAIN_SMOKE on a public channel, including the restart → new epoch test.
  - Laptop ASR benchmark.
  - Gemini key validity via `models.list`.
- **Not performed:**
  - Team-channel P0-B.
  - Gemini generation.
  - Pi ASR benchmark (running).
  - Chert probe (reporting).
  - Tailnet WebSocket test (running).
  - Any browser extension check.

**External accounts and devices**
- Pi reachable as `fazetime@fazetime` over Tailscale with key auth. The coordinator never uses or stores a password and never runs sudo on it.
- `.env.local` holds `GEMINI_API_KEY` and `CHERT_API_KEY`. It is gitignored; never print it.

**Active workers**
- Pi ASR/tailnet.
- Chert read-only probe.
- P1 extension.
- P2 backend.
All started from base `6c05030`, all in the main checkout on disjoint paths.

**Blockers and open questions for the owner**
1. Confirm that the Gemini key's project is on the free tier (no billing linked).
2. Create the Twitch channel, then run an OBS test broadcast on `latpop` with the stream key entered by the owner.
3. Run `sudo apt install -y ffmpeg git` on the Pi, and use the official 27 W power supply because of the under-voltage history.
4. Record the Minecraft 1v1 using the proposed cues:
   - The opening line, followed by at least 90 s of setup.
   - A spoken "3, 2, 1, fight".
   - An outcome shown both by the in-game death message and by a spoken "FaZe<name> wins".
5. Authorize commits, preferably on a working branch.

**Next three concrete actions**
1. Review the Pi, Chert, P1 and P2 reports.
2. Run P0-B on the team channel with `spikes/p0-media/capture_spike.py --label P0B_TEAM_CHANNEL --duration-s 900`.
3. Run the P0-C Gemini smoke test (3.3.0 SDK, one request) after free-tier confirmation. Then write the P0 recommendation and gate record.

**Pi notes, updated 21:25 CT**
- The official 27 W supply is installed, and the re-run passed. D22 primary is restored: the Pi hosts the API, capture and ASR. Provisional ASR model: tiny.en at 3 threads.
- The P0-B team-channel capture is running in `~/fazetime-p0b/`, from 21:15:23 to 21:31:23 CT. A scheduled Streamlink kill fires at 21:25:23. The owner stops and restarts the stream at about 21:21.
- The clock is set to America/New_York but NTP is synced; use UTC everywhere.
- The tailnet path is relayed through DERP (Dallas, about 13 ms).
- `~/fazetime-spike/` holds a uv-managed Python 3.12.16 venv, the tiny/base models, and the bench scripts for a re-run.
- The uv installer added `. "$HOME/.local/bin/env"` to `~/.profile` and `~/.bashrc`, and created `~/.config/fish/conf.d/uv.env.fish`. This is a benign PATH line; the revert command is in spikes/p0-pi/README.md.
- The third-party test WAV was deleted from both the laptop and the Pi at 03:22Z, as the Pi worker confirmed.

**Do not repeat / known failed approaches**
- Do not use a GAP/STALE threshold of 6 s or less: Twitch delivers media in 6 s bursts.
- Do not use the WAL journal mode (D23).
- Do not pass `--twitch-disable-ads`.
- After the Pi benchmark, delete the retained third-party WAV at `spikes/p0-media/out/smoke/summit1g/audio.wav` (and its copy on the Pi).
