# Capability record: Chert FaceTime (P0-E)

- **Capability / owning phase:** outbound FaceTime for the bookie (P11, prioritized) and the raffle winner (P10, deferred per D41).
- **Provider:** Chert managed FaceTime API (`facetime.trychert.com/api/v1`).
  - CLI `@trychert/facetime`: npm latest is 0.1.0-beta.21 (2026-11-14), while the docs pin beta.19.
  - JS SDK 0.3.0; PyPI `chert-sdk` 0.2.3.
- **Account alias:** the owner's Chert project. `CHERT_API_KEY` in `.env.local` has the documented `ftk_` prefix, meaning a FaceTime project API key. Its value is not recorded, and its validity is untested.
- **Checked at:** 2026-11-14 ~21:10 CT. Read-only documentation research. **Zero requests were sent to the Chert API**, the key was never transmitted, and no call minutes were used.

**Facts**

| Fact | Finding | Label |
|---|---|---|
| Project UUID | Required as `X-Chert-Project-Id` on every line, worker and call read. It is not in `.env.local`, and an `ftk_` key cannot list projects. Get it from dashboard → Developer → Project API keys, or `chert whoami --json` after browser login | Owner action |
| Minutes, grant `valid_until`, recipient verification | Not readable with an `ftk_` key; dashboard billing only | Owner action |
| Owner-reported allowance | 24-hour grant, usable through judging; only **50 FaceTime minutes** (D18) | USER_CONFIRMED |
| Per-call / daily limits | Generic public plan: 5 min per call, 50 min/day, 1 active call per line, 100 contacts per project | VERIFIED_DOC; our grant UNVERIFIED |
| Group calls | Rolling out per line. Group video is enabled separately. On Free/Shared lines every recipient must be phone-verified, and one lapsed verification rejects the whole group. One mixed audio track; no participant count | VERIFIED_DOC |
| Webhooks | Optional and off by default. `X-Chert-Signature: sha256=<hex>` over the raw body. At-least-once delivery; deduplicate on `event_id` | VERIFIED_DOC |
| LiveKit / model | Chert provides LiveKit keys only to paid Shared projects. The workshop guide expects a team-owned LiveKit project and "a funded model API account", which conflicts with the $0 rule (D03) | VERIFIED_DOC |
| SDK env naming | The SDK reads `CHERT_API_KEY` as an iMessage key. A FaceTime token should be supplied as `CHERT_FACETIME_TOKEN` when the integration is built | VERIFIED_DOC |

**MEASURED 2026-11-14 21:02 CT.** The coordinator ran read-only GETs with the project ID the owner supplied (`GET /lines`, `/workers`, `/integrations`, `/calls?limit=20`), all HTTP 200. No call minutes were used.
- **One line:** `shared_line: true`, masked identity ***7200. The owner confirmed this is the Chert line number, not a recipient. `supports_audio` and `supports_video` are both true.
- **Worker capabilities:**
  - outbound audio protocol 1, outbound video protocol 1
  - FaceTime group protocol 1, so group calling is available on this worker
  - FaceTime link protocol 0, so link joining is not available
- **Readiness:** FaceTime signed in, `video_ready` true. `audio_ready` was false and `production_media_ready` false. The system-audio check runs "at_call_start".
- **Line status:** `busy` / `operational_status: busy`, with reservation and media-cleanup holds. Because the line is shared, other teams may be using it, which is a real scheduling risk.
- **Account state:** no integrations, so no webhooks are configured. `/calls` total is 0, so nothing has been used yet.
- **Still unknown:** minutes remaining, grant `valid_until`, and group video enablement. They are shown only in the dashboard.

**Demo recipients:** the owner named one teammate's phone. It is stored only in `.env.local` as `DEMO_CALL_ALLOWLIST` (E.164) and is never committed or logged; reference it as ***9335. Every live call still needs the owner's go-ahead.

**Status:** BLOCKED, with the accepted fallback recorded. P0's exit gate allows Chert to stay blocked. P10 is deferred (D41); if it resumes, it uses the manual FaceTime handoff (D05). P11 (now prioritized) needs Chert outbound calling, which requires all of the following before about 09:00 CT:
1. The owner adds `CHERT_PROJECT_ID` to `.env.local`.
2. Read-only GETs to `/lines`, `/workers` and `/integrations` show outbound calling, plus group video if needed.
3. A $0 LiveKit path is confirmed.

**Minute budget, if automation is attempted:**
- About 10 min of tests: audio, second-call cleanup, group/video.
- One rehearsal.
- At least 15 min reserved for judging.
- Log every call locally, because the key cannot read remaining minutes.

**Unanswered sponsor questions:** all 11 in P0-docs-verification.md remain open.
