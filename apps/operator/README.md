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

**Sign-in** needs an **OPERATOR** invite. Get one from `python -m fazetime_api bootstrap-operator` on the API host; it is printed once, to that terminal only. The page refuses viewer sessions and never stores their token.

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

Screenshots and `e2e-summary.json` go to `artifacts/`, which is gitignored. Invite codes and tokens stay in memory, and anything printed is redacted.

## Behaviour that matters

- **Session.** The `fzs_` token is kept in `sessionStorage` only, for this tab. It is sent only as `Authorization: Bearer`, never in a URL or a log. Any 401 clears it and returns to sign-in, and a 403 on an operator route does the same. Sign-out forgets the token locally; the server has no self-logout route.
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
- **Capability probe.** The app reads `/openapi.json` and shows only features the running API has:
  - the evidence panel (§9.16 item 6);
  - an optional settle reason field (`note` or `reason`);
  - the AI-mode and candidate routes (§9.17). The AI panel is a labelled placeholder until they exist.
- **Evidence.** Transcript and model text is rendered as text. Frames are fetched with the bearer header and shown through `blob:` URLs, which are revoked on unmount.
- **Labels (D31).** The console shows the demo/test-money label, AI mode, funding (payment mode), media source (TEST_FIXTURE is labelled "not Twitch"), market origin, and simulated bot stakes.
