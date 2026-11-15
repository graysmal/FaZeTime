# Source map and requirement traceability

Research date: November 14, 2026, America/Chicago. Sources were researched for planning; no authenticated provider tests were performed. Links are living documentation and may change. Recheck the exact capability/version during P0. The intermediate research drafts are intentionally not included because they contain recommendations superseded by later owner choices.

## User-provided documents

| Source | Relevant content | Planning use |
|---|---|---|
| `FaZeTime.pdf`, 6 pages | Pages 1–3 product and extension experience; pages 3–4 phases 1–11; pages 4–5 demo/resources and sponsor goals | Product basis and original phase order. Latest owner answers supersede ambiguous or earlier details. |
| `HackUTA FaZe Clan Hacker Challenge.pdf`, 4 pages | Page 2 challenge, deliverable and five judging criteria; page 1 suggested tools; page 3 brand history | MVP recommendation, resource discipline, audience/engagement story. Brand history is supplied brief context, not independently verified corporate history. |
| `HackUTA 2026_compressed.pdf`, 80 pages | Text plus visual inspection of image-only slides: Chert p18, AI Studio p51, TigerData p55, Vultr p59; ceremony schedule, general judging and ElevenLabs prize | Logistics reminder and sponsor context, not guaranteed credits, precise current cutoff, or account entitlements. |

Original attachments are not copied into this repo kit. Keep them privately available to the coordinator if needed. Their contents were read directly. Do not treat `agents.md` hyperlinks inside the PDF as an external specification.

## Trace from original phases

| Original | Canonical plan | Main supporting docs |
|---|---|---|
| 1 extension mocks | P1 | ARCHITECTURE, CONTRACTS |
| 2 server/users/presence | P2 | ARCHITECTURE, CONTRACTS, ECONOMICS |
| 3 transcription/vision | P3 | INGESTION, AI_PIPELINE |
| 4 proposals | P4 | AI_PIPELINE, CONTRACTS |
| 5 results | P5 | AI_PIPELINE, ECONOMICS |
| 6 Stripe/test betting | P6 | INTEGRATIONS, ECONOMICS |
| 7 connect flow | P7 | TEST_STRATEGY, DEMO_RUNBOOK |
| 8 raffle odds | P8 | ECONOMICS |
| 9 spoken Raffle | P9 | INGESTION, ECONOMICS |
| 10 creator/winner calls | P10 | INTEGRATIONS |
| 11 absent-user bookie | P11 | INTEGRATIONS, CONTRACTS |

P0 adds bounded early feasibility checks. It does not reorder the product or count a capability spike as a completed feature.

## Material clarifications and corrections

- The owner selected demo only, default $0, mandatory Twitch input, flexible call fallback, Python backend, no pool fee, stake-volume raffle odds, and quality-dependent automatic AI.
- Raw stored credit-card data is replaced by Stripe-hosted test payment entry and provider IDs. This preserves the desired top-up demonstration without adding an unnecessary card-data system.
- “Odds” on the panel are pool shares/estimated payout, not an AI's predictive confidence. Raffle probability is a separate denominator.
- No-fee pools do not generate direct fee revenue. The demo can motivate commerce/sponsorship revenue, but cannot claim a fee it does not charge.
- The branded FaceTime reward is demonstrated using approved team devices unless a real creator explicitly participates. The sponsor's general openness is not a credential, calling entitlement, or platform approval.
- Chat choice highlighting, existing email lists, referrals, streaks, public user acquisition, store launch and multi-stream support remain outside P1–P11 implementation.

## Primary research routes

### Twitch, OBS, Chrome

- [Twitch Get Streams](https://dev.twitch.tv/docs/api/reference/streams): metadata, not live media retrieval.
- [Twitch EventSub](https://dev.twitch.tv/docs/eventsub/): status/event delivery, not game outcome truth.
- [Streamlink Twitch](https://streamlink.github.io/cli/plugins/twitch.html): playback/auth caveats and ad gaps.
- [OBS WebSocket protocol](https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md): control and screenshots; not continuous audio output.
- [Chrome tab capture](https://developer.chrome.com/docs/extensions/reference/api/tabCapture/) and [offscreen document](https://developer.chrome.com/docs/extensions/reference/api/offscreen): operator capture candidate and lifecycle limits.
- [WXT content UI](https://wxt.dev/guide/essentials/content-scripts.html): supported mounting/isolation choices.
- [Chrome store policies](https://developer.chrome.com/docs/webstore/program-policies/policies): distribution constraints; no embed loophole assumption.

### AI and costs

- [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [whisper.cpp](https://github.com/ggml-org/whisper.cpp), [CTranslate2 installation](https://opennmt.net/CTranslate2/installation.html): local ASR options and platform dependencies.
- [Gemini structured output](https://ai.google.dev/gemini-api/docs/structured-output), [video](https://ai.google.dev/gemini-api/docs/video-understanding), [audio](https://ai.google.dev/gemini-api/docs/audio): model interface and evidence limits.
- [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing), [rate limits](https://ai.google.dev/gemini-api/docs/rate-limits), [billing](https://ai.google.dev/gemini-api/docs/billing), [deprecations](https://ai.google.dev/gemini-api/docs/deprecations): recheck exact account/model.
- [Google AI Pro benefits](https://support.google.com/googleone/answer/14534406?hl=en), [Developer Program FAQ](https://developers.google.com/profile/help/faq), [Nov 13 credit announcement](https://blog.google/innovation-and-ai/technology/developers-tools/google-cloud-credits-gdp-ai-studio/): possible credits versus verified usable API budget.
- [ElevenLabs API pricing](https://elevenlabs.io/pricing/api), [Google Cloud STT pricing](https://cloud.google.com/speech-to-text/pricing): optional alternatives; not presumed free entitlements.

### Calls, payments, hosting, agents

- [Chert docs](https://docs.trychert.com/), [group calls](https://docs.trychert.com/facetime/group-calls), [managed service](https://www.trychert.com/facetime): sponsor account must verify actual rollout/limits. Chert docs can be unavailable to a public crawler; request the sponsor's current accessible docs instead of inventing an endpoint.
- [Chert open-source connector](https://github.com/cherthq/chert-facetime-opensource): different local-browser path, not proof of managed outbound capability.
- [LiveKit pricing](https://livekit.io/pricing), [Google realtime plugin](https://docs.livekit.io/agents/models/realtime/plugins/gemini/): separate voice/transport costs and compatibility.
- [Stripe testing](https://docs.stripe.com/testing), [fulfillment](https://docs.stripe.com/checkout/fulfillment), [webhooks](https://docs.stripe.com/webhooks), [idempotency](https://docs.stripe.com/api/idempotent_requests): test payment correctness.
- [Stripe restricted businesses](https://stripe.com/legal/restricted-businesses): production-provider boundary, not a production plan.
- [Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/): free development route with material limitations.
- [SQLite WAL](https://www.sqlite.org/wal.html), [transactions](https://www.sqlite.org/lang_transaction.html): local DB concurrency and persistence constraints.
- [Claude memory](https://code.claude.com/docs/en/memory), [subagents](https://code.claude.com/docs/en/sub-agents), [best practices](https://code.claude.com/docs/en/best-practices): persistent context, model inheritance, bounded delegation. Verify installed-client behavior.

Detailed claims and additional links appear beside the relevant decisions in the supporting docs. Local capability records outrank generic documentation for whether this team's setup works.

## Product recommendation and judging story

Audience: existing FaZe fans who want to participate together during a broadcast, and new viewers who need a simple reason to understand and follow a challenge. The first experience is one understandable question and immediate feedback, followed by an attainable creator interaction. Do not rely on unexplained historical lore in the demo.

Demonstrate the loop: watch a challenge announcement, make a prediction with demo credits, see an evidence-supported result, understand the updated raffle share, then experience the call. Returning fans recognize the creator; new fans can understand the event without prior context. Avoid claiming a test user graph measures actual long-term retention.

Potential revenue while preserving the selected zero-fee pool model: sponsor-funded challenge placements, merchant/affiliate commissions on actual future commerce, or an independently designed creator membership. These are business hypotheses, not implemented flows or approved commercial agreements. Show measured engagement instrumentation (market views, accepted wagers, completed challenges, voluntary return to stream), not fabricated revenue or growth statistics. The sponsor requires a clear revenue recommendation; selecting a future monetization model is a pitch decision, not permission to add a hidden fee.

Homer's Odyssey appears in the general ceremony criteria. If useful, describe the audience's shared challenge/journey lightly in the presentation; do not add an unrelated game system solely to satisfy a theme. The sponsor's own criteria emphasize audience/problem, originality, prioritization/resources, technical feasibility, and engagement potential. Align the three-minute story with those facts.

