# Demo operations and rehearsal

Status: preparation plan, not a completed rehearsal. `PROJECT_PLAN.md` owns phase acceptance and scope. This runbook covers operation of the resulting single-stream Python/TypeScript demo. Final ingestion must use Twitch; a local recording is permitted as broadcast source and test fixture, never as a substitute inference feed. Calls are flexible; unreliable calls must not break the core demo.

## P0 decisions and owners

Record the actual remaining deadline, chosen game/challenge, machine specifications/operating systems, and network arrangement before assigning runtime processes. Do not guess GPU availability or Pi performance. Assign four practical responsibilities; one person may cover multiple roles: presenter, OBS/media operator, backend/ledger operator, and phone/call operator.

Select a prerecorded challenge with a clear announcement, substantial setup, distinct start cue, objectively visible result, and result hold. Rehearse spoken names against ASR. Resolve exactly what counts as yes/no before recording. Include a separate longer scene for the inactive-user bookie call; ringing, answering, understanding, confirming, and placing a bet require more time than clicking the browser UI.

Prepare two or three demo accounts with fictional names and test balances. Calls use only consenting team phones. Seeded pool activity must be labeled demo activity and pass through the same wager APIs as visible users. No-fee pool payouts follow the canonical ledger rules. Raffle weights come from cumulative nonvoid settled stakes, not deposits, current wallet balances, unresolved bets, refunds, or manually inflated fake odds.

## Networking: choose one topology and prove it

| Topology | Appropriate use | Required checks |
|---|---|---|
| Backend on presenting laptop; extension talks through its service worker to loopback | Fast initial local development and a one-laptop core demo | Exact host permissions, validated message bridge, reachable API, websocket reconnect; localhost on another machine is a different machine. |
| Backend on Pi; all laptops use a verified private network | Multi-client rehearsal when venue routing permits | Pi address, firewall, browser permission behavior, Wi-Fi client isolation, stable power, clock synchronization. |
| Backend reached through an HTTPS/WSS public endpoint/tunnel | Hosted panel, cross-device demo, public webhook callbacks | Working TLS, exact origins, authentication, callback URLs, tunnel reconnect, unchanged hostname during rehearsal, no public admin/OBS access. |

These are deployment choices, not interchangeable URL substitutions. Extension content scripts remain subject to page-origin network restrictions; an extension service worker can make appropriately permissioned requests. Use a narrow validated message bridge rather than granting arbitrary URLs. Do not assume that successful command-line access proves a browser request will work. [N1]

A hosted panel should use HTTPS/WSS for its own API. An iframe on Twitch introduces embedding policy, origin, session, and messaging requirements; check CSP `frame-ancestors`, permitted parent origins, and exact `postMessage` origins. Do not plan to disable browser protections. Local-network behavior varies with Chrome version and permission state; test the actual installed version rather than claiming every HTTP loopback/private-network request is always allowed or always blocked. [N2]

For a tunnel, expose only the application and necessary authenticated webhook routes. Keep database, OBS WebSocket, SSH, and operator reset actions private or separately protected. A URL is not authorization. Campus networks may block peer-to-peer access or outbound tunnel connectivity even when ordinary websites work. Verify from each participating laptop and phone at the venue.

Cloudflare Quick Tunnels are a possible zero-cost development option, not an uptime promise. Their documentation specifies temporary URLs, a limit of 200 in-flight requests, and no SSE support. If choosing one, verify WSS end-to-end and use WebSocket push plus HTTP snapshot/poll fallback; do not quietly deploy SSE through an unsupported path. Polling must preserve server deadline checks and idempotency, not invent local event state. A hostname change requires rechecking extension host permissions/CSP, panel configuration, callbacks, and allowed origins. Re-register or update the Stripe webhook endpoint and use that endpoint's correct signing secret; a secret from another endpoint or CLI forwarding session is not interchangeable. Keep application authentication and provider signature checks. Do not enable an interactive email gate such as `--allowed-mail` on a path that noninteractive workers or provider webhooks must access. A named tunnel or sponsor hosting can be considered only after actual access and zero-cost limits are verified. [N3]

Prefer consolidating backend and presentation on one laptop over introducing paid hosting solely to fix LAN routing, provided the measured resource budget passes. Public provider callbacks may still require a tunnel. Record the selected topology, ports, and sanitized endpoint names in the phase handoff; never record secrets.

## OBS control is optional

Manual OBS operation is enough for the initial reliable demo. Only add dashboard control after the core flow works. OBS includes WebSocket control; its protocol exposes media status, cursor, scene controls, and source screenshots. This is not continuous audio transport. [O1, O2]

If automated, allow only named demo actions such as restart media, pause, resume, and standby scene. Keep credentials on the backend/local controller. The prerecorded source cursor helps rehearsal and resets but cannot supply future evidence to the model. Do not silently switch inference to OBS screenshots if Twitch capture breaks.

A dashboard Reset Demo action should require deliberate operator interaction and create a new `stream_session_id`. Close/void active markets and refund reservations through the normal ledger path, end old capture sessions, invalidate stale events, restart the video, wait for the new Twitch-delivered start cue, and refresh every client snapshot. Resetting a demo is not deleting ledger history underneath connected clients. Keep the previous run inspectable.

## Derive the three-minute presentation from measurements

The sponsor materials specify three minutes to present plus two minutes of questions. The timeline below is a presentation budget, not a claim that the pipeline already meets it.

First measure several complete runs. Record: cue reaches Twitch consumer; transcript becomes usable; model proposal validates; panel displays; user confirms bet; server locks; result evidence arrives; settlement commits; client feedback appears. Also measure a phone call from initiation through explicit confirmed wager, if demonstrated. Report sample counts and distinguish median/p95 from a single lucky run.

Let `L` be the measured setup-cue-to-visible-proposal delay, `B` the intended human betting interval, and `M` an explicit jitter margin based on rehearsal. The recorded challenge must not begin before the proposal path has time for `L + B + M`. Record measured values in the rehearsal log. If this does not fit the show budget, simplify the challenge or shorten narration; never shrink safety margins while claiming the same reliability.

| Presentation budget | Intended content | Dependency |
|---|---|---|
| 0:00–0:20 | State audience problem and show the FaZeTime panel on the actual Twitch channel. | Stream already healthy; accounts ready. |
| 0:20–0:55 | Show live transcript/evidence becoming a validated two-outcome market; explain the future challenge. | Measured proposal delay fits the selected scene. |
| 0:55–1:25 | Place a test-currency wager; show current pool estimate and server lock. | One market, funded accounts, enough measured lead-in. |
| 1:25–2:00 | Show the result cue, AI evidence, settled wallet, and outcome feedback. | Clear result and quality-gated automatic settlement. |
| 2:00–2:30 | Show cumulative eligible raffle weights and a deduplicated raffle trigger/draw. | Qualifying settled stakes; no void stakes. |
| 2:30–3:00 | Explain retention/revenue concept and show the absent-viewer bookie call (P11) briefly, or its honest call status/fallback. The winner call (P10) is deferred (D41). | Call capability already rehearsed; no live dependency on an uncertain bridge. |

These windows are targets. Recut and retime the prerecorded video only after measuring the actual feed. Start with OBS already broadcasting and use a recognisable scene cue; do not start a cold stream in the three-minute slot. Pre-warm allowed model resources without precomputing the demonstration answer. If automatic qualification fails, a visible review/manual action is acceptable as a disclosed limitation, not a hidden claim of autonomous success; it does not pass an automatic-mode acceptance gate.

Do not cram the longer bookie conversation into this primary market. Keep a separate measured scene for it (the call demonstration, D41): the person is absent according to presence state, has opted in, receives context, confirms outcome and stake, and the backend revalidates funds and deadline. A missed call, ambiguous reply, or expired market produces no wager. Never charge a saved card merely because the transcript contains an amount.

## Preflight and rehearsal gates

Before judging, confirm the following through behavior, not just green process indicators:

- Twitch is playing on each demo browser; the selected producer yields fresh media and correct source badges.
- The extension is loaded, attached once, and survives Twitch navigation/reload without duplicate UI or subscriptions.
- Accounts, test top-ups, ledger snapshots, pool estimates, and lock rejection work. No real card details appear in app storage or logs.
- Observed media gaps void/refund affected unsettled markets once, and those stakes do not enter the raffle.
- Replayed chunks, duplicated callbacks, and repeated “Raffle” detections cannot duplicate settlements, calls, or draws.
- The selected AI path passes the canonical quality gate on representative positive, negative, ambiguous, and missing-evidence cases.
- Both phones are awake, reachable, and consenting; sponsor access remains inside the actual confirmed free-usage window.
- Every machine has power; sleep/screensaver is controlled; Pi storage and temperature are healthy; clocks are synchronized sufficiently for logs.
- Reset produces a new run and capture session, with no ghost market or queued call from the previous run.

Run the entire presentation at least twice consecutively after the final configuration change. If time allows only one, record that limitation and leave the two-rehearsal P7 gate incomplete until the owner explicitly accepts a partial demonstration. Freeze versions and endpoints after successful rehearsal unless a demonstrated issue justifies changing them.

## Failure playbook

| Failure | Immediate action | Honest demonstration outcome |
|---|---|---|
| Streamlink rejected or unstable | Stop proposals; void/refund compromised unsettled markets; switch to pre-tested operator Twitch tab capture with new session. | Twitch analysis remains valid if fresh captured evidence passes. |
| Both Twitch adapters unavailable | Stop automated markets; show existing UI/test evidence with explicit labels. | Final Twitch acceptance is blocked. Local file analysis is not a substitute. |
| ASR/model quota or timeout | Pause automatic proposal/settlement; preserve evidence; expose unavailable state. | A labeled operator demonstration may continue, but automatic acceptance stays unmet. |
| Media gap during outcome | Void/refund affected unsettled market once. | Show the fault handling; do not guess who won. |
| Client disconnect | Reconnect and fetch authoritative snapshot before enabling actions. | Countdown/wallet do not rely on stale client state. |
| Tunnel hostname or network changes | Pause dependent flow; update exact endpoint configuration and recheck callbacks/origins. | Resume only after the new path is exercised. |
| Chert unanswered, failed, or unsupported bridge | End/mark the attempt; preserve the core flow; use only previously agreed call fallback. | Explain the verified capability and remaining integration limit. |
| Repeated trigger or loop | Deduplicate by run/session/market/raffle identity. | No repeated financial or call side effects. |

The operator may narrate faults rather than hide them. Keep a compact sanitized log of source mode, run/session IDs, market lifecycle, evidence references, ledger transactions, raffle snapshot, and call status. The presenter should distinguish measured behavior from future product claims. No real-money launch or claim of production readiness is part of this demo.

## Sources

- N1: https://developer.chrome.com/docs/extensions/develop/concepts/network-requests — extension and content-script network boundaries.
- N2: https://developer.chrome.com/docs/modern-web-guidance/guides/security/local-network-access — local network permissions and version-dependent browser behavior.
- N3: https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/ and https://developers.cloudflare.com/tunnel/get-started/ — tunnel limits, temporary URLs, network prerequisites.
- O1: https://obsproject.com/kb/remote-control-guide — OBS WebSocket availability.
- O2: https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md?plain=1 — source screenshots and media status/control.
- Presentation timing: supplied `HackUTA 2026_compressed.pdf`, judging slide (three-minute presentation, two-minute Q&A). Use the organizers' current announcements if the schedule changes.
