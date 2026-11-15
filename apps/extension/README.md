# FaZeTime extension

Chrome MV3 extension built with WXT, React and TypeScript, using a **bundled ShadowRoot panel**. Per D14 there is no hosted iframe, no URL entry and no remote code. It has two build modes:

| Mode | Data | Funds | Mounts on |
|---|---|---|---|
| `mock` (P1) | Local fixtures in the background (`MockBackend`) | MOCK top-up and redeem | every `twitch.tv/<channel>` page |
| `live` (P2) | Real API through the background (`LiveBackend`) | **Unavailable until P6** (honest message) | only `twitch.tv/fazegavin1234` |

Test money only. No card fields, no phone fields, no real payments.

**Pinned extension ID:** `hodaaffdhncidmaccebmionoljljfefe`, so the extension origin is `chrome-extension://hodaaffdhncidmaccebmionoljljfefe`.
- `manifest-key.json` holds the PUBLIC key only. The key pair was generated in memory; the private key was never exported or written to disk.
- The backend must allowlist exactly this origin for CORS and the WebSocket (`FAZETIME_ALLOWED_ORIGINS`).

## Versions (installed and run on `latpop`, 2026-11-14)

| Tool | Version |
|---|---|
| Node / npm | 24.22.2 (nvm) / 11.19.1 |
| WXT / @wxt-dev/module-react | 0.21.5 / 1.2.2 |
| Vite / @vitejs/plugin-react | 8.3.8 / 6.3.0 (transitive) |
| React / react-dom | 19.3.1 |
| TypeScript | 6.0.3 |
| Vitest / happy-dom | 4.1.12 / 20.14.6 |
| Playwright (smoke and e2e) | 1.65.1, bundled Chromium build 1255 |
| Backend for e2e | `services/api` via `uv run --frozen` (read-only) |

## Build configuration

These are build-time environment variables, injected by `wxt.config.ts` through `define`. None of them is a secret.

| Variable | Default | Notes |
|---|---|---|
| `WXT_FAZETIME_MODE` | `mock` | `mock` or `live` |
| `WXT_FAZETIME_API_BASE` | `http://127.0.0.1:8000` | Must be a bare origin. It becomes the ONLY `host_permissions` entry (live builds only). The Pi build uses `http://fazetime:8000` |
| `WXT_FAZETIME_CHANNEL` | `fazegavin1234` | Live mount target. Override it **only for tests**; a non-default value builds into `chrome-mv3-live…-test-<channel>` |

Output folders:

| Folder | Build |
|---|---|
| `.output/chrome-mv3` | mock |
| `.output/chrome-mv3-live` | live, local API |
| `.output/chrome-mv3-live-fazetime` | live, Pi API |

## Commands (exactly as run)

```bash
source ~/.nvm/nvm.sh && nvm use 24

# Contracts: packages/contracts
cd packages/contracts
npm install --no-audit --no-fund
node scripts/generate-fixtures.mjs   # regenerate fixtures/v1 (deterministic; run after the 9.15 rulings)
npx tsc --noEmit
npx vitest run                       # 190 tests

# Extension: apps/extension
cd ../../apps/extension
npm install --no-audit --no-fund --ignore-scripts && npx wxt prepare
npx tsc --noEmit
npx vitest run                       # 94 tests
npm run build:mock                   # -> .output/chrome-mv3
npm run build:live                   # -> .output/chrome-mv3-live            (API http://127.0.0.1:8000)
npm run build:live:pi                # -> .output/chrome-mv3-live-fazetime   (API http://fazetime:8000)
node scripts/copy-to-documents.mjs                                                       # mock -> ~/Documents/fazetime-extension
node scripts/copy-to-documents.mjs chrome-mv3-live fazetime-extension-live               # -> ~/Documents/fazetime-extension-live
node scripts/copy-to-documents.mjs chrome-mv3-live-fazetime fazetime-extension-live-pi   # -> ~/Documents/fazetime-extension-live-pi

# Real-browser checks (Playwright bundled Chromium; downloaded once)
npx playwright install --no-shell chromium
node scripts/smoke.mjs               # mock build on live twitch.tv: 25/25 (incl. theater, chat collapse/expand, full-screen)
node scripts/e2e-live.mjs            # two-browser test against the real API: 31/31 (see below)
```

The copy script overwrites files in place and never deletes anything. Stale chunk files from older builds are harmless.

## Load unpacked

Chrome on this laptop is a Flatpak and can only read folders such as `~/Documents`.

1. Open `chrome://extensions`, turn on **Developer mode**, click **Load unpacked**, and choose one of:
   - `~/Documents/fazetime-extension` (mock);
   - `~/Documents/fazetime-extension-live` (live, local API);
   - `~/Documents/fazetime-extension-live-pi` (live, Pi API).
2. Check that the card shows the ID `hodaaffdhncidmaccebmionoljljfefe`.
3. **Live builds (D35 open access):** click the toolbar icon and press **Join**. "Your name" and the Twitch name are optional; an empty name becomes "Viewer 1234".
   - The popup sends these to the background, which calls `POST /v1/enroll` name-only (no `invite_code` field) and keeps the session token in background storage.
   - Only if the server refuses name-only enroll (401, invite-only; or an older API that requires `invite_code`) does the popup show an "Invite code" field and retry with it.
   - The popup, content scripts and the page never receive the token, and it is never logged.
   - A 401 or an expired session triggers one silent name-only re-join with the stored name (single-flight, at most one attempt per 10 s), then the request is retried once. Only if that fails do the panel and popup ask you to join again. An explicit Sign out forgets the name, so nothing re-joins.
4. Open `https://www.twitch.tv/fazegavin1234` (live) or any channel page (mock).

## Live adapter behaviour (CONTRACTS 9.9, 9.15)

- **The background owns all API calls.** The content script uses one runtime Port and never calls the API.
- **WebSocket:**
  - It uses `POST /v1/ws-ticket`, then `ws://…/v1/ws`.
  - The ticket goes only in the first frame `{"type":"auth","ticket"}`, never in the URL.
  - The client pings every 25 s, answers the server's pings, and reconnects with exponential backoff (1 s up to 15 s, plus jitter).
  - A 4403 close is reported as an origin rejection and is not retried in a loop.
- **Events:**
  - Events carry full state. Any higher `aggregate_version` per (run, aggregate) is applied, and jumps are normal (9.15(14)).
  - `my_position` is derived from `wager.updated` receipts. A state is pushed to tabs only once it is consistent, for example after settled + wager.updated + wallet.changed.
- **Snapshot refetch:** only on (re)connect, a run change or a server `resync`. A 5-second safety net resyncs once if event-derived state stays inconsistent.
- **Polling fallback:** while the socket is down, every 2 s if a market is OPEN, else every 10 s.
- **Presence:** while the panel is mounted, the content script reports `page_visibility` and `player_state` every 15 s and on visibility change. The background adds the device ID and session and calls `POST /v1/presence`.
- **Top-up and redeem:** the background returns `CAPABILITY_UNAVAILABLE` without making a network call. The UI says "unavailable until phase 6".
- **Labels (D31):**
  - Live builds are named plain "FaZeTime".
  - The panel, over-video pill and popup carry no MOCK/DEMO badge, no mode chips and no Fixture menu. Fixture-origin markets show no origin label; AI-origin markets read "AI suggested".
  - Exactly one small grey note, "Balances are test credits.", appears in the Wallet tab and in the top-up dialog.
  - Mock builds keep their MOCK badge and Media/Model/Funds/Data chips (dev only). The operator console carries the mode labels.
- **Reload:** a newly connected tab gets the cached snapshot immediately, and the background then refreshes once from the server.
- **Chat collapse** is not "chat missing": it never spawns the floating panel and does not use the re-attach budget. Expanding chat restores the panel above chat.

## Two-browser evidence (`scripts/e2e-live.mjs`, 2026-11-14 ~21:52 CT)

**Setup:**
- The real API from `services/api` ran via `uv run --frozen python -m fazetime_api serve` on `127.0.0.1:8765`, with a temp DB under `/tmp/ft-e2e-*`.
- `FAZETIME_ALLOWED_ORIGINS=https://www.twitch.tv,chrome-extension://hodaaffdhncidmaccebmionoljljfefe`.
- The operator was created with `bootstrap-operator`, and two VIEWER invites were made through `/v1/operator/invites`.
- Viewers A and B ran as two separate Chromium processes, each with its own profile, using the live build. Each enrolled through the popup.

**Mount target:** this is a test-only override. `WXT_FAZETIME_CHANNEL=<a currently live channel>` was set because `fazegavin1234` may be offline. The run used `theburntpeanut`.

**Result: 29/29.**
- Both sockets reached LIVE through the exact pinned origin.
- `market.opened` reached A and B within 74 ms and 173 ms.
- **B saw A's YES bet 310 ms after A's receipt.** The target was 2 s or less.
- After its socket was killed, B dropped to POLLING, caught up 1.2 s after A's next bet, then reconnected.
- The sweeper locked the market 41 s after it opened, and the operator settled YES.
- A saw "You won!" and "Paid $13.00 incl. $6.00 stake". B saw "Ooohhh, so close!!".
- Wallets showed A at $27.00 and B at $13.00, with $0.00 in play. Server reconciliation was OK.
- After a reload, B still showed $13.00 and the loss banner.
- The live labels were correct and the Fixture menu was absent.
- Snapshot HTTP fetches over the whole run: A 3, B 6.
- Presence reached the server for 2 users.
- The server log contained no tokens or tickets.

Screenshots and `summary.json` are in `artifacts/live/`, which is gitignored.

## Known limitations and gaps

- **Not verified in a real browser:**
  - theater mode;
  - real full-screen (the dropdown hides on `fullscreenchange`);
  - chat collapse;
  - extension reload with a tab open;
  - a logged-in Twitch session;
  - Flatpak Google Chrome (all automated runs used Playwright's Chromium);
  - the Pi build against the Pi;
  - the actual `fazegavin1234` page.
- **Accessibility:** after SPA navigation, Twitch set `aria-hidden="true"` on an ancestor of the panel host. Screen readers may then skip the panel.
- **Tab reload while the socket is live:** the tab gets the background's event-maintained cache, which is authoritative-derived. It does not trigger an HTTP refetch (9.15(14)).
- **Mock mode** has no sweeper and no settlement. Use the dev Fixture menu (MOCK builds only).
- **Panel anchors** were verified only on logged-out pages on 2026-11-14:
  - the panel uses `.stream-chat-header`, falling back to `section[data-test-selector="chat-room-component-layout"]`;
  - the video anchor is `[data-a-target="video-player"]`;
  - if chat is not found within 10 s, a floating panel appears;
  - if Twitch removes the host more than 5 times a minute, re-insertion stops and a recoverable notice is shown.
