# FaZeTime extension (P1: local MOCK interactions)

Chrome MV3 extension built with WXT + React + TypeScript. The P1 build is a **bundled ShadowRoot
panel** (D14: no hosted iframe, no URL entry, no remote code) with **local MOCK/FIXTURE data only**.
It makes no backend calls, has no OAuth, no Stripe, no capture and no calls. Demo funds are not money.

## Versions (as installed and run on `latpop`, 2026-11-14)

| Tool | Version |
|---|---|
| Node / npm | 24.22.2 (nvm) / 11.19.1 |
| WXT / @wxt-dev/module-react | 0.21.5 / 1.2.2 |
| Vite / @vitejs/plugin-react | 8.3.8 / 6.3.0 (transitive) |
| React / react-dom | 19.3.1 |
| TypeScript | 6.0.3 |
| Vitest / happy-dom | 4.1.12 / 20.14.6 |
| Playwright (smoke only) | 1.65.1, bundled Chromium build 1255 |

Versions are pinned exactly in `package.json`, with a local `package-lock.json`. WXT 0.21.5 itself is
developed against Vite 8, TypeScript 6 and Vitest 4, which is why those majors were chosen.

## Commands (exactly as run)

```bash
source ~/.nvm/nvm.sh && nvm use 24

# Contracts (types, validators, fixtures): packages/contracts
cd packages/contracts
npm install --no-audit --no-fund
npx tsc --noEmit
npx vitest run                     # 190 tests
node scripts/generate-fixtures.mjs # only to regenerate fixtures/v1 (deterministic)

# Extension: apps/extension
cd ../../apps/extension
npm install --no-audit --no-fund --ignore-scripts   # first install, before entrypoints existed
npx wxt prepare                                     # generates .wxt/ (the postinstall script does this now)
npx tsc --noEmit
npx vitest run                                      # 77 tests
npx wxt build                                       # -> .output/chrome-mv3
node scripts/copy-to-documents.mjs                  # -> ~/Documents/fazetime-extension (copies, never deletes)

# Optional real-browser smoke test on live twitch.tv (logged out), screenshots in artifacts/
npx playwright install --no-shell chromium
node scripts/smoke.mjs                              # 19/19 checks passed on 2026-11-14
```

## Load unpacked

Chrome on this laptop is a Flatpak and can only read folders such as `~/Documents`.

1. Open `chrome://extensions` and turn on **Developer mode**.
2. Click **Load unpacked** and choose `~/Documents/fazetime-extension`.
3. Open any `https://www.twitch.tv/<channel>` page. The panel appears between the chat header and the
   chat messages, and a small `MOCK` pill appears at the top centre of the video.
4. Optional: click the toolbar icon to set a display name and an optional Twitch login. The login is a
   label and is marked "not verified". There is no phone field and there are no card fields.

After rebuilding, run `node scripts/copy-to-documents.mjs` again, then click reload on the extension card
and refresh the Twitch tab.

## Gate walkthrough (dev "Fixture" menu)

The panel header has a **Fixture ▾** menu. It exists only with the MOCK adapter and is labelled
"dev · MOCK only".
- Pick any of the 18 snapshot fixtures from CONTRACTS §9.14. Times are shifted so the fixed fixture time
  becomes "now".
- "Next bet/top-up fails with …" injects any of the 15 typed errors once.
- "Simulate timeout on next bet" commits the bet but reports an unknown outcome. The panel shows
  "Outcome unknown", retries with the **same** `operation_id`, and then shows the replayed receipt
  ("charged once").
- "Restart clock" reloads the current fixture with a fresh countdown.

Suggested order:
1. `open_no_position`: pick a side, then **Place Bet**.
2. `open_low_balance`: **Top up to bet** opens the MOCK dialog. Press **FaZe Up!**.
3. Terminal states: `settled_win`, `settled_loss` ("Ooohhh, so close!!"), `void_one_sided`,
   `void_resolution_timeout`, `void_unresolvable` and `settled_no_position`.
4. `run_reset` shows the new-run notice.

## Architecture

- `entrypoints/background.ts` owns the backend adapter (P1: `src/mock/backend.ts`) behind
  `src/api/router.ts`.
  - The adapter state persists in `storage.session`, so a service-worker restart keeps it.
  - P2 swaps in a live adapter here. The session token must stay in background-only storage.
- `entrypoints/twitch.content/` runs the mount/lifecycle shell (`src/content/mount.ts`).
  - It talks to the background only through `src/api/client.ts` over one runtime Port (`fazetime/v1`).
  - It never calls an API.
- `src/state/controller.ts` is the view store, and `src/state/betFlow.ts` is the pure bet state machine.
  - Success is shown only after a receipt.
  - An unknown outcome retries the same key.
  - Each click creates a new key.
- UI lives in `src/ui/`: `Panel.tsx` (tabs, wallet, redeem, top-up, fixture menu, resize),
  `MarketCard.tsx` and `Overlay.tsx` (over-video dropdown).
- Contract types and fixtures come from `packages/contracts` through the `@fazetime/contracts` alias.

## Known limitations and gaps

- **MOCK only.** Balances live in the background mock and reset when the browser restarts.
  - Nothing is authoritative until P2.
  - The mock has no sweeper: at 0:00 the card shows "Betting closed (waiting for the server to lock)"
    and the mock rejects with `MARKET_CLOSED`.
  - Use the Fixture menu to move between states.
- **Browser checks not performed:**
  - theater mode;
  - real full-screen (the dropdown hides itself on `fullscreenchange`; the panel is outside the
    full-screen element);
  - chat collapse/expand;
  - extension reload while a tab is open;
  - a logged-in Twitch session;
  - a manual load in Flatpak Google Chrome. The smoke test used Playwright's bundled Chromium.
- **Accessibility:** after SPA navigation, Twitch set `aria-hidden="true"` on an ancestor DIV of the
  panel host (observed in the smoke test). Screen readers may then skip the panel. Mouse and keyboard
  use still work.
- **Anchors:** the panel anchors on `.stream-chat-header`, falling back to
  `section[data-test-selector="chat-room-component-layout"]`. The video anchor is
  `[data-a-target="video-player"]`.
  - These were verified only on logged-out pages on 2026-11-14.
  - If chat is missing for 10 s, a floating panel appears with a Retry button.
  - If Twitch removes the host more than 5 times a minute, re-insertion stops and a recoverable notice
    is shown.
- The panel mounts on every `twitch.tv/<channel>` page. P2 should restrict it to the configured stream.
- Twitch hotkeys are suppressed only while focus is inside the panel.
