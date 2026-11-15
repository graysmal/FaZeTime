---
paths:
  - "apps/extension/**"
  - "apps/operator/**"
---

# Extension and operator UI constraints

- Root `PROJECT_PLAN.md` defines phase scope; API contracts define behavior.
- Use TypeScript/React. WXT and Manifest V3 apply to apps/extension; apps/operator is an ordinary React/Vite web app. Bundle extension executable code; do not eval remote output.
- Keep host permissions narrow. Extension permissions do not remove content-script CORS restrictions.
- Prove actual Twitch embedding/CSP/auth behavior. Do not assume iframe authentication works with third-party cookies blocked.
- Allowlist the hosted app origin; validate message schema, exact origin, and source window. Do not send secrets with wildcard postMessage targets.
- Provider secret keys and raw card data must never enter extension storage or bundles.
- Backend state is authoritative for identity, balances, accepted wagers, deadlines, outcomes, and raffle weights.
- Treat service-worker globals as disposable; fetch current snapshots on reconnect.
- Clean up mounts, observers, timers, and listeners during Twitch navigation and extension reload.
- Render transcript/model text as text. Test unusual long content and invalid/expired events.
- Confirm real-browser behavior; mark unavailable checks as unperformed.
- Preserve the demo-only label and the plan's exact user experience. No store-eligibility claim based on a URL-embedding workaround.
