# P0 documentation verification (planner subagent)

- Phase / task / base / date: P0-A, C, E, F documentation check / `6c05030` / 2026-11-14
- Mode: primary-source documentation only. The best label any fact here can earn is VERIFIED_DOC (VD). Nothing here is MEASURED or verified against our accounts. Other labels: UV = UNVERIFIED, CX = CONTRADICTORY, NC = NOT CHECKED
- One Google docs page that was fetched contained text addressed to AI agents. The planner ignored it, and nothing was acted on

## Gemini (P0-C)

- **Docs moved** (VD): `ai.google.dev/gemini-api/docs/*` now returns a 301 redirect to `aistudio.google.com/docs/*`.
- **Candidate model `gemini-3.5-flash-lite`** (VD; /docs/models, /docs/deprecations):
  - Stable, with no shutdown date.
  - Input: text, image, video, audio and PDF. Output: text.
  - Supports structured output. No Live API.
  - Token limits: 1,048,576 in, 65,536 out.
- **Alternatives:**
  - `gemini-4-hydrogen`: Stable, released 2026-11-12, "recommended for new projects". Paid tier costs $1.50 input / $7.50 output per 1M tokens, so treat it as a measured alternative only.
  - `gemini-3.1-flash-lite`: CX. The deprecations page gives a 2027-05-07 shutdown, but its model page lists none.
  - `gemini-2.5-flash-lite`.
- **Avoid:** `gemini-2.5-flash` (deprecated; reroutes automatically on 2026-12-01) and any `*-preview` model.
- **Free tier** (/docs/pricing; /docs/rate-limits):
  - VD: all four models are listed "Free of charge". Limits apply per project, not per key. RPD resets at midnight Pacific. Some projects need verification.
  - UV: the numeric free RPM/TPM/RPD figures are no longer public. They are visible only in the owner's AI Studio. COST_AND_CAPABILITIES quota maths stays blocked until P0-C reads them.
- **Billing** (VD; /docs/billing):
  - The tier is set per billing account, and linked projects and their keys inherit it.
  - Unlinking a project returns it to the free tier.
  - Prepay requires a $5 minimum.
  - Treat any request from a billing-linked project as billable.
- **Where the owner checks** (aistudio.google.com): `/projects` "Billing Tier" column, `/usage`, `/rate-limit`.
- **SDK** (VD):
  - `google-genai` 3.3.0, released 2026-11-12, needs Python ≥3.11.
  - `GOOGLE_API_KEY` takes precedence over `GEMINI_API_KEY` when both are set.
  - `generateContent` is labelled "legacy" but is still fully supported.
  - The Interactions API is now recommended, but it stores requests by default (`store=false` disables this). Decide which API to use before P4.
- **Images and structured output** (VD):
  - Inline images: 20 MB maximum.
  - An image of 384 px or less costs 258 tokens. Larger images are tiled at 768 px, 258 tokens per tile.
  - Structured output ignores length and uniqueness keywords but enforces `minItems`/`maxItems`.
- **Terms** (VD; /docs/terms, effective 2026-03-23):
  - Free-tier content may be used to improve products and may be read by human reviewers.
  - Do not send sensitive or personal data.
  - Account holders must be 18 or older.
  - So send approved demo media only.

## Streamlink (P0-B)

- **Version** (VD; PyPI, changelog): 8.6.3, released 2026-10-29, needs Python ≥3.10. Version 8.6.0 contained security fixes.
- **Ads** (VD): ads have always been filtered since 7.5.0. Output pauses during an ad, and a discontinuity on resume is expected. `--twitch-disable-ads` is deprecated; do not pass it. Pauses must show up as GAP/STALE or as a new epoch.
- **Client integrity:**
  - VD: a client-integrity token is "sometimes required". It is obtained through a Chromium-based browser using the `--webbrowser-*` options.
  - UV risk: Streamlink may not be able to find the Flatpak Chrome.
- **Output and retries** (VD): `-O`/`--stdout`. Retry options: `--retry-streams`, `--retry-max`, `--retry-open`, `--stream-segment-timeout`.

## ASR (P0-D)

- **faster-whisper 1.2.1** (2025-10-31) (VD):
  - Dependencies: ctranslate2 4.9.0; onnxruntime 1.32.0 (released 2026-11-13, so prefer a version that has been measured); av 19.0.2 (needs Python ≥3.12).
  - The wheels are manylinux_2_28 for x86_64 and aarch64. The Pi therefore needs a 64-bit OS with glibc ≥2.28; the Pi itself is NC.
- **whisper.cpp v1.9.5** (2026-10-06): source build only. Its docs say the Pi is supported but give no performance figures. Community reports (UV): a Pi 4 handles tiny.en, and on a Pi 5 base.en saturates the CPU.

## WXT and Node (P1)

- **WXT** (VD): wxt 0.21.5 needs Node ≥22 and works with any package manager.
- **Node versions** (VD):
  - Node 25 has been end-of-life since 2026-06-01.
  - Node 24 is in Maintenance LTS until 2028-04-30.
  - Node 26 has been Active LTS since 2026-10-28.
  - The Chert starter needs Node 22.23.2 or 24.x. Proposal: Node 24.x everywhere. This laptop already has v24.22.2.

## Hosted iframe (P0-F; owner question 5)

- **Page CSP:** a Chromium source test (`extension_csp_bypass_browsertest.cc`) shows that an MV3 content script can insert a cross-origin iframe even when the page sets `frame-src 'none'`. `chrome-extension:` URLs bypass page CSP. `frame-ancestors` is not bypassed. This is VD as a source test, not as an API contract.
- **Nested frame:** the extension page must be listed in `web_accessible_resources`. The default extension-page CSP sets no `frame-src`, so nesting an external https frame inside it appears to be allowed (UV). The hosted page must send `frame-ancestors` covering the real ancestor chain and no X-Frame-Options (UV).
- **Third-party cookies:**
  - Chrome kept user choice, and a 2025-12-18 page says they are restricted by default for about 1% of users.
  - The Chrome 157 default is UV.
  - CHIPS (partitioned cookies) still works when third-party cookies are blocked.
- **Storage partitioning:** for the nested chain (twitch.tv, then the extension page, then the hosted page) it is UV.
- **Planned design:** the one-use exchange code over a verified postMessage bridge avoids third-party cookies entirely. It is consistent with the docs, but UV until tested.

## Public HTTPS route (P0-F)

- **Cloudflare Quick Tunnel** (VD, except where marked UV):
  - No account needed. The hostname is random on every run.
  - No SSE. 200 in-flight requests, then 429. No uptime guarantee.
  - WebSockets are supported by Cloudflare Tunnel generally, but the Quick Tunnel page itself is silent (UV).
  - A community report describes idle sockets being dropped after about 100 s (UV).
- **Tailscale Funnel** (VD, except where marked UV):
  - Beta, available on all plans.
  - Requirements: Tailscale ≥1.38.3, MagicDNS, HTTPS certificates, and the `funnel` node attribute (enabling it is a tailnet admin approval, so an owner action).
  - Ports 443, 8443 and 10000 only. Stable `*.ts.net` hostname. Non-configurable bandwidth limits.
  - WebSocket support is undocumented (UV). An open issue reports query parameters being stripped from WebSocket upgrade requests.
- **Planner recommendation:**
  - Use Funnel as the primary route, because its stable hostname keeps allowlists and frame policy valid. Keep Quick Tunnel as the fallback.
  - Send an app-level WebSocket ping every 30 s or less. Authenticate in the first WebSocket message, never in the URL. Keep media off the tunnel.
  - Public hostnames appear in Certificate Transparency logs, so choose a non-identifying machine and tailnet name.

## Chert (P0-E): public docs only, not our grant

- **Bring Your Own Room:**
  - We host the LiveKit room and the agent; Chert is the FaceTime gateway.
  - One active call per line.
  - The bridge token is `wss://`, scoped to one room, and valid for at most 7200 s.
  - Webhook signing is optional and off by default.
- **Outbound calls:**
  - Request: `POST /api/v1/calls` with a Bearer key and `X-Chert-Project-Id`. The key needs the `facetime:write` and `facetime:read` scopes.
  - `Idempotency-Key` is 8–200 characters. Reusing the same key returns the original call; changing fields under the same key returns 409.
  - HTTP 201 means the call was allocated, not answered. Speak only after `bridge_ready` or `call.started`.
  - Ending returns 202; then poll until the call is terminal.
  - An optional busy queue waits up to 2 minutes.
- **Video:** outbound video needs an enabled line. Publish the agent's video before dialing. Caller capture is a separate opt-in.
- **Group calls:**
  - Rolling out per line. 1–31 handles, not guaranteed.
  - On Free and Shared lines every recipient must be phone-verified.
  - The agent receives one mixed audio track, and there is no participant count.
  - Group video needs separate confirmation.
  - What participants see of each other is undocumented.
- **Limits:**
  - 100 contacts per project.
  - The generic Free plan is a 24-hour trial: 50 min/day, 5 min per call, 1 concurrent call per shared line, no agent-initiated outbound messages. Our grant may differ.
- **CLI and SDK:**
  - CLI `@trychert/facetime@0.1.0-beta.19`, macOS and Linux only. It supports Node 22.12+, 24 or 26; the starter needs 22.23.2 or 24.x.
  - `chert doctor --agent` may incur provider usage.
  - Python `chert-sdk` 0.2.3, needs Python ≥3.10.
- **Preview or undeployed:** unified sessions, `create_media_session`, call-video set/get/clear, payments, direct audio, and video composition. P10/P11 must not depend on these. Publish the market card as the agent's own LiveKit video track instead.
- **$0 conflict:** the organizer workshop guide expects each team to bring a LiveKit Cloud project and "a funded model API account". Ask the sponsor about this.
- **Facts to get from the sponsor:**
  - Project UUID and role, line ID, FaceTime address, and line type.
  - Whether the line is shared with other teams, and the test slots.
  - The exact grant start and end, and whether it covers judging.
  - Whether this is the public trial or a separate allocation.
  - Minutes, per-call limit, concurrency and contacts.
  - Which capabilities are enabled: inbound and outbound audio and video, caller capture, group calls, group video, link joining, busy queue.
  - How phone verification works, and whether it expires.
  - What group participants see of each other.
  - The scoped-key path, whether webhook signing is available, and a support contact.
  - Which CLI and SDK versions are supported, and whether the outbound endpoints are deployed for this grant.
  - Whether Chert provides LiveKit keys or a model budget.
  - Whether a dynamic market card meets the sponsor's visual criterion.

## Stripe (P6 prep): NOT CHECKED

Still to verify before P6: the Ubuntu install method for the Stripe CLI, and test-mode `stripe listen --forward-to`.
