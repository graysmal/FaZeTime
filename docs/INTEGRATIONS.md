# Sponsor, payment, and voice integration contracts

This is a planning document. [PROJECT_PLAN.md](../PROJECT_PLAN.md) owns phase order, status, acceptance gates, and scope changes. Read this file for phases 6 and 8–11; read [ECONOMICS.md](ECONOMICS.md) for wallet, payout, and raffle invariants. Python owns backend/domain logic; TypeScript owns the extension/frontend. A sponsor-provided Node CLI may run as an external tool without creating a second business backend.

Research checked: 2026-11-14. No account was authenticated, call placed, or payment attempted during planning. Provider documentation establishes documented behavior; the assigned account and live rehearsal establish actual availability.

## 1. Phase 6: Stripe test API integration

Phase 1's wallet dialog is a local mock. Phase 6 replaces its payment adapter with an actual Stripe sandbox integration. Both remain fake-money demonstrations, but they are different capabilities and must be labeled accurately in operator status.

Use server-created Stripe Checkout Sessions in test mode, opening hosted Checkout in a separate browser tab. This minimizes payment form work and avoids building third-party payment UI inside Twitch's DOM or a nested iframe. Keep the extension's “FaZe Up!” button as the checkout-launch action; after return, refresh wallet state from the backend. Stripe currently recommends Checkout Sessions for ordinary payment collection. Inline Payment Element is an optional later UI refinement, not a prerequisite. [S1, S2]

The backend validates an allowed positive top-up amount, resolves the authenticated user, creates an internal top-up record, and creates or reuses its Checkout Session with a stable idempotency key. Request test card payment methods only for the narrow demo, without subscriptions, bank accounts, Connect payouts, saved-card charging, or cash withdrawals. Do not let the client choose arbitrary currency, price, user, or credit multiplier.

Use the documented test Visa `4242 4242 4242 4242`, any valid future expiry, and suitable test CVC in Stripe's hosted UI. Automated provider tests should use documented test PaymentMethods rather than raw card numbers. Test transactions do not move actual money. Reject live-mode payment events and do not accept live secret keys as a configuration shortcut. [S1]

### Fulfillment and reconciliation

The webhook is the durable completion path. Verify its signature using the raw request bytes; compare the associated payment/session to the server's top-up record, expected amount, currency, paid status, and user. In one transaction, record provider-event processing and grant demo credit once. Uniqueness on the underlying paid object prevents two different event IDs from crediting the same top-up. Return success after durable acceptance/processing; avoid expensive downstream calls inside the webhook. [S3]

A checkout return URL cannot grant credits by itself. The buyer may never return, or may replay the URL. Server-side return-page reconciliation may fetch the provider object and invoke the same idempotent fulfillment routine, but never trust browser claims of success. If payment status remains pending, the UI says pending and continues reading backend state. [S4]

Provider request idempotency and application ledger idempotency solve separate problems. Preserve creation keys across network retries; preserve database uniqueness across restarts and beyond provider retention. Do not change the amount under the same idempotency key. [S5]

For local development, Stripe CLI webhook forwarding avoids requiring a public payment endpoint. If the final rehearsal uses an HTTPS endpoint instead, configure and verify that endpoint separately. A CLI listener's signing secret differs from the dashboard webhook secret; record which path is active. Keep the listener running during demonstrations. [S3]

### Data correction from the source PDF

The original proposal suggested storing credit cards in the user table. This plan deliberately replaces that with provider object references. Application storage may contain user ID, Stripe test customer/session/payment IDs, amount, status, and nonsecret display metadata if needed. It must not contain PAN, CVC, raw card form values, or private payment secrets. Logs and AI prompts must not contain them either.

The original phase-11 idea also suggested automatically debiting a saved card when voice wagering exceeds the wallet. This is deferred: the demo uses hosted test top-up, followed by a fresh quote and explicit wager reconfirmation. Implementing saved-card off-session test flows would require a separate owner decision and handling authentication-required failures. No agent should silently add that branch.

## 2. Chert: responsibilities and capability gates

Chert's managed Bring Your Own Room service connects a provisioned FaceTime line to an application-owned LiveKit room. The application supplies the agent runtime and model; Chert supplies the FaceTime endpoint/bridge. Chert and LiveKit projects are separate. The team does not need to modify or deploy Chert's open-source browser connector to use its managed sponsor service. [C1]

The owner has confirmed a 24-hour Chert sponsor grant. Obtain its exact start/end timestamps and verify it covers Sunday judging. Current public pricing advertises 50 FaceTime minutes/day, a five-minute per-call limit, one concurrent call per shared line, and restrictions on proactive iMessage. These are generic terms, not a guarantee of this sponsor allocation; cached public text has differed. Record the assigned grant's actual quota before committing to the demo sequence. Own LiveKit and model usage remain separate. [C2]

### Required sponsor answers

Record nonsecret answers in the project's environment/capability notes:

- Assigned Chert project UUID, line ID, actual FaceTime handle, owner/admin access, and supported backend credential path.
- Reservation window, whether another team shares the line, and recovery contact for busy/offline/uncleaned state.
- Outbound audio, outbound video, agent video, caller capture, and two-recipient group video availability, independently.
- Phone verification requirements for both iPhones and permitted outbound-message behavior.
- Exact trial expiry, minutes, per-call duration, contact count, and concurrency.
- Supported CLI/API/SDK version and whether the chosen endpoints are deployed on this allocation.
- Whether a dynamic market/receipt card satisfies the sponsor's “show what you need” visual criterion.
- What phone numbers/emails each participant sees in group FaceTime; do not promise anonymity without this test.

These are technical capability questions. Keep credentials out of documentation, screenshots, model context, and committed environment files.

### Early proof before phases 10–11

During initial setup, prove a basic call before building the full bookie. Start the agent, connect the assigned line, exchange actual speech, interrupt once, hang up, observe resource release, and make a second clean call. Then test outbound calling and video separately. A health check, room membership, HTTP 201, or SDK import does not establish working audio/video.

The managed CLI currently documents macOS/Linux support and a pinned beta version, with slightly different supported runtimes for its starter. Pin the combination that the team actually tests. Public SDK package notes explicitly identify some APIs as undeployed previews; do not build from a method name without checking live endpoint support. [C3, C4]

## 3. Phase 10: raffle winner and creator FaceTime (DEFERRED, D41)

Deferred by the owner on 2026-11-15; kept for reference. P11 (§4) takes priority.

The preferred automated option is one outbound group call inviting the winning user and the team member acting as streamer. Group calling is documented but enabled per line. It uses one call ID and one line slot rather than two independent calls. Free/shared recipients require current phone verification. Group video has a separate capability gate. [C5]

The documented group request uses `recipients`, not the single-recipient `destination` fields. Prepare the room, one eligible agent audio publisher, and a call-scoped bridge token before creating the call. Persist a call-job ID and stable provider idempotency key. The agent gives a brief introduction only after media readiness, then stays quiet while the people talk.

The API does not provide a trusted participant count or per-person moderation. Group audio reaches the agent as one mixed track with no verified speaker identity. Do not enable balance access or wagering tools in the group call. Partial joins are possible; an operator must observe that both intended phones connected. Preserve the winner if one person does not answer. [C5]

The plan does not guarantee that one participant's phone number or email remains hidden from the other. Verify both phones' incoming-call and in-call screens. A provider's backend indirection does not imply FaceTime UI anonymity.

If the allocated line cannot support the required group video, use the owner-approved manual FaceTime fallback between the two team phones. The application still performs the actual draw and displays the selected winner; the operator places the call manually. Label telephony orchestration as manual. This is a permitted demo fallback, not an implemented automatic bridge. Do not build an unplanned two-line mixer or disguise a manual call as a successful API integration.

## 4. Phase 11: individual AI bookie

Use one bound user, one market, one call, and one clear confirmation. The eligibility query selects the highest cumulative qualifying demo-spend real user who has no fresh stream heartbeat, opted into the demonstration, has an approved destination, and is outside a cooldown. Bots never qualify. Stale presence is only an estimate of absence; cancel a pending outreach when the user returns if no call has yet been placed.

Persist one logical outreach job uniquely keyed by stream_session_id, market_id, user_id and job kind. Store attempt count as mutable retry metadata, not part of a new job identity; uncertain submission retries preserve the same provider idempotency key. A deliberate redial after a confirmed terminal failure requires the recorded operator retry policy. Before dialing, compare remaining market-open time to the rehearsed call duration budget: room startup, ringing, greeting, explanation, answer, and confirmation. If insufficient, skip the call. For the prerecorded Twitch demo, arrange a long pre-event setup window so the wager can be understood and accepted before the action begins. Never extend a locked deadline simply to finish the demo.

Bind the call to the backend's user/destination mapping. A caller saying another name cannot change that identity. The AI receives only this call's market ID/version, options, deadline, current wallet, pool snapshot, and bounded recent context. It does not receive a user table, raw payment data, unrestricted database connection, or general administrative tools.

Expose a small tool contract:

- Read this market's current state and server time.
- Read the bound caller's available demo balance.
- Quote a valid side and integer stake, returning a quote ID, deadline, and estimated gross payout.
- Confirm that quote after the agent reads back amount/side and obtains explicit approval; backend rechecks balance, market version, and deadline using the normal wager transaction.
- Initiate the approved hosted test top-up handoff when needed.
- End this call.

An utterance such as “yeah” is only confirmation when it answers a current, unambiguous readback. Negation, interruption, side corrections, and changed amounts invalidate the earlier quote. A tool's persisted wager receipt is the sole evidence of acceptance. The agent must not say “placed” while an operation is still pending or after backend rejection.

For insufficient balance, inform the user and open/send the approved hosted test checkout handoff through an available channel. After webhook credit, fetch the market again and ask for new confirmation. If it closed, leave the top-up available for another event and explain the wager was not placed. Do not queue a financial promise that silently executes later.

After a successful wager, speak and display the backend receipt. If proactive iMessage is not included in the sponsor grant, use the extension and FaceTime video for notifications. A sent API response is not a delivery guarantee, and permission to place FaceTime calls does not automatically authorize outbound texts. Call only the agreed demonstration devices.

## 5. Media, speech, and the $0 target

A simple dynamic video card is preferable to an avatar dependency: render market question, options, server-derived countdown, demo balance, and receipt into the agent's video track. The participant publishing video should be the same one providing the eligible agent audio. Caller-camera capture is distinct from sending agent video, and unused for this core workflow. [C6]

Use a verified free LiveKit Cloud Build project for reachable media, while running the Python agent locally. Published pricing has separate transport, agent-session, and inference allowances. The public page currently lists $0 with no card required, included WebRTC usage, and a small inference credit allotment; verify the dashboard before testing and stop when the free quota is exhausted. Do not assume local execution makes cloud transport or inference unlimited. [C7]

The official LiveKit Google plugin supports Python and Node and can use direct Gemini API credentials or Vertex AI credentials. A working native-audio Gemini Live model can provide speech understanding and generated audio, avoiding a separate STT/TTS service for calls. Model availability, quota, and plugin compatibility must be checked against the team's actual account. A student consumer subscription does not establish API credit. [C8]

If native-audio access is unavailable, evaluate a bounded STT → text model → TTS pipeline using already verified free/sponsor allocations. Do not add ElevenLabs, OpenAI Realtime, or a paid avatar just because a Chert starter imports it. The sponsor's free FaceTime grant does not pay those model bills. A pre-recorded audio/card response can demonstrate media transport as a visibly scripted fallback, but cannot be called a functioning conversational bookie.

Record costs as `transport allowance consumed + voice-model input/output usage + optional STT audio duration + optional TTS text/audio usage`. Keep provider quotas separate. No fixed dollar claim is justified until selected models, account tiers, and a measured rehearsal establish it. Paid fallback requires the owner to authorize the amount first.

## 6. Call lifecycle, recovery, and data boundaries

Outbound creation uses Chert's Calls API with project authorization, selected line, room-scoped token, recipient/media fields, and an idempotency key. HTTP 201 means allocation, not answer. Begin speaking only after `bridge_ready` or the documented corresponding lifecycle event. Reuse the original key after an uncertain response; a fresh key can create a second call. End requests are asynchronous too, so observe terminal cleanup before releasing local resources or reusing the line. [C9]

A group or bookie job must survive backend restart without duplicate dialing. Persist provider call ID and state transitions. Reconcile unknown calls before retrying. One active call per line is a capacity limit; a busy queue may wait longer than the market window, so the bookie should normally fail/skip rather than queue stale outreach. Group raffle calls may wait without changing the winner. [C10]

Keep LiveKit API secrets server-side and issue distinct short-lived room-scoped bridge tokens. Enable and verify webhook signing if using inbound/lifecycle webhooks; do not assume signing is enabled by default. Record sanitized operational IDs, timestamps, and failure codes. Avoid storing full phone numbers in general logs, recording calls unnecessarily, or sending caller video to models that do not need it. [C1]

## 7. Verification and distribution limits

Before final choreography, verify two consecutive clean calls, timeout/no-answer, repeated call request, lost create response reconciliation, line-busy behavior, late voice confirmation rejection, insufficient balance, top-up followed by market closure, call cleanup after process failure, and the manual group-call fallback. Pin all tested versions and record the sponsor expiry in the operator checklist.

Stripe's published prohibited-business list includes gambling and certain prize-bearing activities. This project is a sandbox demonstration, not a plan to switch to production keys. Chrome Web Store policy covers the entire experience; hiding the betting UI behind a user-entered URL does not make a real-money product eligible. Sideload the demo extension, make no real prize fulfillment, and do not claim store or payment-provider approval. [S6, X1]

## Sources

- S1 [Stripe testing](https://docs.stripe.com/testing).
- S2 [Stripe payment integration guidance](https://docs.stripe.com/payments/payment-intents).
- S3 [Stripe webhooks](https://docs.stripe.com/webhooks).
- S4 [Checkout fulfillment](https://docs.stripe.com/checkout/fulfillment.md?ui=full-page).
- S5 [Stripe idempotency](https://docs.stripe.com/api/idempotent_requests).
- S6 [Stripe restricted businesses](https://stripe.com/legal/restricted-businesses).
- C1 [Chert Bring Your Own Room](https://docs.trychert.com/facetime/bring-your-own-room).
- C2 [Chert public pricing](https://www.trychert.com/).
- C3 [Chert setup and testing](https://docs.trychert.com/facetime-cli/quickstart).
- C4 [Chert Python SDK release notes](https://pypi.org/project/chert-sdk/).
- C5 [Chert group calls](https://docs.trychert.com/facetime/group-calls).
- C6 [Chert video and caller vision](https://docs.trychert.com/facetime-cli/video).
- C7 [LiveKit pricing](https://livekit.com/pricing).
- C8 [LiveKit Gemini Live integration](https://docs.livekit.io/agents/models/realtime/gemini/).
- C9 [Chert outbound calls](https://docs.trychert.com/facetime/outbound).
- C10 [Chert capacity and readiness](https://docs.trychert.com/facetime/limits).
- X1 [Chrome Web Store policies](https://developer.chrome.com/docs/webstore/program-policies/policies).
