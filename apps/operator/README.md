# FaZeTime operator console (P2-E)

A minimal, authenticated operator web app for the demo. **Test money only.** It uses React 19, Vite 8 and TypeScript 6 as a plain Vite app (WXT and MV3 apply only to the extension).

The API serves the built app **same-origin at `/operator/`** when `FAZETIME_OPERATOR_DIST` points at `dist/`, so there is no CORS. API calls are relative (`/v1/...`), and the Vite `base` is `/operator/`.

Pinned versions: react/react-dom 19.3.1, typescript 6.0.3, vite 8.3.8, @vitejs/plugin-react 6.3.0, vitest 4.1.12, happy-dom 20.14.6, playwright 1.65.1, @types/react(-dom) 19.3.0, @types/node 24.19.2. Shared types are imported read-only from `packages/contracts/src` through an alias.

## Commands (run from `apps/operator/`, with Node 24)

```bash
source ~/.nvm/nvm.sh && nvm use 24
npm ci                 # installs exactly what package-lock.json pins
npx tsc --noEmit       # type-check
npx vitest run         # unit and component tests (happy-dom)
npm run build          # tsc + vite build -> dist/ (base /operator/; a CSP meta tag is added at build time)
```

## Serving it

```bash
# Like production: the API serves dist/ at /operator/
cd services/api
FAZETIME_OPERATOR_DIST="$PWD/../../apps/operator/dist" uv run --frozen python -m fazetime_api serve
# then open http://127.0.0.1:8000/operator/

# Development: Vite proxies /v1, /openapi.json and /healthz to FAZETIME_API_PROXY (default http://127.0.0.1:8000)
npm run dev        # http://127.0.0.1:5174/operator/
npm run preview    # serves the built dist/ with the same proxy: http://127.0.0.1:4174/operator/
```

**Two views.** `/operator/` is the minimal **demo view**: one stream pill (LIVE / Connecting… / OFFLINE from source health) and one big card that follows the state (idle with a "test bet" form that creates and opens a fixture market, AI candidate with Approve / Reject, market open with pools and a countdown, betting closed, AI result suggestion with Approve result / Void & refund, fixture winner buttons, last result), plus "Reset for next take" (one confirm). `/operator/#advanced` is the full console below (IDs, modes, evidence, invites, sign-out). Both use the same client, polling (2 s) and fresh-`operation_id`-per-click rules; the demo view shows errors as one sentence and offers "Try again" (same operation) only for an unknown outcome.

**Open access (D35).** With `FAZETIME_OPEN_ACCESS=1` on the API, the console signs itself in through `POST /v1/open/operator-session {device_id}` on load and again after ANY 401 (single flight, then the failed request is retried once with the same body and operation_id). The device_id is kept in `localStorage`; the session stays in `sessionStorage`. Only a 404 from that route (invite mode) shows the sign-in form. Sign-out (Advanced only) clears just the session.

**Sign-in** (invite mode) needs an **OPERATOR** invite. Get one from `python -m fazetime_api bootstrap-operator` on the API host; it is printed once, to that terminal only. The page refuses viewer sessions and never stores their token.

## End-to-end run against a real local API (Playwright)

This uses a throwaway data directory and port, and does not touch the services/api tree or its `.venv`. The script calls the API CLI for the operator invite and for a MEDIA_WORKER token, so it needs the same `FAZETIME_DATA_DIR` and `UV_PROJECT_ENVIRONMENT` as the server.

```bash
S=$(mktemp -d)
cd services/api
UV_PROJECT_ENVIRONMENT=$S/venv uv sync --frozen
UV_PROJECT_ENVIRONMENT=$S/venv FAZETIME_DATA_DIR=$S/data FAZETIME_HOST=127.0.0.1 FAZETIME_PORT=18741 \
  FAZETIME_MIN_LEAD_MS=10000 FAZETIME_OPERATOR_DIST="$PWD/../../apps/operator/dist" \
  uv run --frozen python -m fazetime_api serve &
cd ../../apps/operator && npm run build
UV_PROJECT_ENVIRONMENT=$S/venv FAZETIME_DATA_DIR=$S/data FAZETIME_E2E_BASE=http://127.0.0.1:18741 npm run e2e
```

- `FAZETIME_MIN_LEAD_MS=10000` only shortens the test. The fixture market closes 15 s after opening; the default minimum lead is 30 s.
- The script uses Playwright's installed Chromium (`channel: 'chromium'`, revision 1255 for 1.65.1). If it is missing, run `npx playwright install chromium`.

The script covers these steps:
1. Sign in as operator.
2. Create the stream.
3. Evidence: a TEST_FIXTURE epoch with transcripts, frames and a prompt-injection string.
4. Create and open a fixture market.
5. Create three viewer invites; two viewers enroll and wager both sides through the API.
6. Settle YES with a confirm and a reason, then check the payouts.
7. Reset the run with the double confirm.
8. Check that a viewer invite is refused on the operator page.
9. Revoke the operator session and check the page returns to sign-in on 401.
10. Check for CSP violations and console errors.

**Supervised-AI e2e (§9.17):** `npm run e2e:ai`, with the same environment and a fresh DB. It takes about 60 s, because the AI close minimum is 45 s.
1. Set the AI mode to APPROVAL through its confirm, and check AUTOMATIC is shown as unavailable.
2. Register a TEST_FIXTURE worker epoch with LIVE heartbeats every 2 s, plus announcement transcript and frame evidence.
3. Submit a decoy candidate. Check the alert (badges, NEW flash, tab title, countdown), then reject it with a reason.
4. Submit the real candidate and approve it; the market opens as AI_APPROVED.
5. Two viewers wager YES and NO.
6. After lock, read `GET /v1/worker/market` for `lock_media_ms`, post evidence after the lock, and submit a YES resolution. It arrives as `PENDING_APPROVAL`.
7. Approve it through the confirm, then check SETTLED, the payouts and reconciliation.

Screenshots and `e2e-summary.json` / `e2e-ai-summary.json` go to `artifacts/`, which is gitignored. Invite codes and tokens stay in memory, and anything printed is redacted.

## Behaviour that matters

- **Session.** The `fzs_` token is kept in `sessionStorage` only, for this tab. It is sent only as `Authorization: Bearer`, never in a URL or a log. A 401 first tries the silent D35 re-open; only in invite mode does it clear the token and return to sign-in. A 403 on an operator READ does the same; a 403 refusing a mutation (for example approving while the AI mode is OFF) is shown as an error and keeps the session. Sign-out forgets the token locally; the server has no self-logout route.
- **Mutations** follow §9.7 and §9.10:
  - Every click gets a fresh `crypto.randomUUID()` `operation_id`.
  - Success is shown only from a parsed 2xx receipt that echoes that `operation_id`.
  - After a network error, a timeout, a 5xx, an unparseable 2xx or `RATE_LIMITED`, the outcome is shown as **unknown**. "Retry same operation" re-sends the same key and body.
  - Typed errors are shown with their code, HTTP status, `request_id`, details and a hint.
- **Polling:**
  - `GET /v1/operator/health` every 2 s.
  - `GET /v1/streams/{id}/snapshot` every 2 s, for `modes` (payment mode and media source).
  - `GET /v1/operator/evidence` every 3 s, when present.
  - Timers and in-flight requests are cancelled on unmount.
- **Supervised AI panel (§9.17, D32):**
  - **AI mode** (`POST /v1/operator/ai-mode`): OFF, SHADOW, APPROVAL or AUTOMATIC, always behind a confirm. AUTOMATIC is struck through and disabled unless health `ai.allow_automatic` is true.
  - **Candidates** (`GET /v1/operator/candidates`, every 2 s): each shows the question, the side-keyed labels and predicates, the subjects, the VOID conditions and the `rationale` ("Model text, untrusted"). Cited evidence shows transcript snippets plus thumbnails fetched with the bearer header.
  - **Approval countdown:** the time left to approve is the earliest of three deadlines:
    - expiry, 60 s after receipt;
    - evidence freshness, 90 s after the oldest cited evidence;
    - the minimum lead before the receipt-anchored close.
  - **Approve and Reject:** Approve takes an optional `close_in_s` override (45–600, counted from approval). Reject needs a reason. Both are gated on `actionable`, and typed errors show `details.reject_code`.
  - **Resolutions** (`GET /v1/operator/resolutions?market_id=`, every 2 s): shown for the current AI market, with the decision, predicate support, media interval, cited evidence, and the contradictions and reason as untrusted text. Approve goes through a confirm, with a resolve_by countdown.
  - **Alerts:** pending counts from health `ai` appear as pulsing badges and in the tab title. A new candidate flashes and plays a two-tone beep once a click has unlocked audio (toggle "sound alert").
- **Settle note:** the fixture settle always sends `note`, which the server stores in the audit row.
- **Capability probe:** the app reads `/openapi.json` to decide whether to show the evidence panel (§9.16 item 6).
- **Evidence.** Transcript and model text is rendered as text. Frames are fetched with the bearer header and shown through `blob:` URLs, which are revoked on unmount.
- **Labels (D31).** The Advanced console shows the demo/test-money label, AI mode, funding (payment mode), media source (TEST_FIXTURE is labelled "not Twitch"), market origin, and simulated bot stakes.
