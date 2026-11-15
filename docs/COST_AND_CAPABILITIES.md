# Cost and capability decisions

Research checked 2026-11-14. Account permissions, quotas, hardware performance and sponsor entitlements have not been tested. `PROJECT_PLAN.md` phase 0 is the source of truth for resolving them; this document is the comparison and verification checklist, not authorization to incur charges.

## Budget policy

Default external spend is $0. The owner will consider a budget only when necessary. Use the Pi and laptops where practical, and verified sponsor benefits where they reduce integration risk. Do not purchase credits, enable paid billing, enable auto-reload or switch to a paid model automatically. If a zero-cost critical path fails, report its measured failure, a concrete alternative and the smallest proposed cap for the owner to decide.

The user confirmed Chert usage for 24 hours. Its activation time, expiration, concurrency and available FaceTime capabilities still need confirmation. Schedule that window around integration and judging. TigerData or another sponsor is optional until actual access and expiration are recorded; 'sponsor exists' is not a usable service entitlement. The ceremony's ElevenLabs prize is not proof of current API credits.

## Event-specific cloud alternatives

Visual review of the ceremony's image-only slides found explicit TigerData (page 55), Vultr (page 59), Google AI Studio (page 51), and Chert (page 18) resources. These provide more concrete alternatives than assuming generic student credits.

| Offer documented by organizer/provider | Potential use | Verify before selecting |
|---|---|---|
| [MLH Vultr partner page](https://www.mlh.com/partners/vultr) advertises a $100 gift code with no card required; obtain the code from the MLH coach. [Vultr's own MLH page](https://discover.vultr.com/mlh) describes event cloud/GPU access. | A reachable temporary API host if venue networking fails; potentially ASR compute if the specific grant permits an available GPU. | Actual gift code, account eligibility, redemption, expiration, instance types/region availability, egress/storage costs, quota, and whether GPU is included. A broad GPU marketing statement is not a reserved GPU. |
| [MLH TigerData partner page](https://www.mlh.com/partners/tigerdata) advertises $1,000 new-signup credits valid for 30 days. [TigerData's account docs](https://www.tigerdata.com/docs/deploy/tiger-cloud/tiger-cloud-aws/pricing-and-account-management) describe the no-card trial and possible data removal after expiry. | Managed PostgreSQL if it removes an actual setup burden or the owner chooses that sponsor integration at P0. It does not host arbitrary Python media workers. | New-account eligibility, granted balance, actual service pricing, connection/SSL setup, expiry and export. Do not add a payment method or silently upgrade to preserve data. |
| Ceremony AI Studio shortlink `https://mlh.link/hackuta-aistudio`; Chert event link `https://trychert.com/uta`. | Ask on-site staff for event-specific API/line allocations before considering paid activation. | Shortlinks were not reliably readable through public lookup; no extra Google quota or Chert media allowance is inferred from their existence. |

Default remains existing Pi/laptops. If a sponsor VM is selected, use one small instance, bind only necessary application ports, track consumption and teardown after the demo, export the DB/evidence before trial expiry, and preserve the same service boundaries. Do not add Kubernetes or a GPU just to consume credits. A cloud experiment that requires a card or cash changes the budget decision and must be presented to the owner first. Current offers were checked on 2026-11-14; actual redemption is UNVERIFIED.

## Speech recognition comparison

| Candidate | Evidence and use | Decision gate |
|---|---|---|
| faster-whisper | Python/CTranslate2, CPU INT8, word timestamps and integrated Silero VAD; ordinary calls need an application streaming policy. First laptop candidate. [Official repository](https://github.com/SYSTRAN/faster-whisper) | Benchmark tiny/base/small English models on the actual machine and chosen audio. Verify dependencies and critical-name/negation accuracy. |
| whisper.cpp | CPU and quantized inference, Raspberry Pi support and Apple acceleration. Its stream example is a proof of concept, not a guaranteed live service. [Repository](https://github.com/ggml-org/whisper.cpp), [stream example](https://github.com/ggml-org/whisper.cpp/blob/master/examples/stream/README.md) | Prefer tiny/base for the initial Pi experiment; measure sustained speed and temperature. A 16 GB memory capacity does not imply real-time CPU throughput. |
| CTranslate2 ARM path | Current wheels include Linux AArch64. [Installation](https://opennmt.net/CTranslate2/installation.html) | Verify the exact Pi OS, Python and wheel combination before treating faster-whisper on Pi as available. |
| Gemini audio/transcription | General multimodal requests understand audio; dedicated transcription models are separately listed in current pricing. [Audio guide](https://ai.google.dev/gemini-api/docs/audio), [pricing](https://ai.google.dev/gemini-api/docs/pricing) | Use only if the chosen account/model offers sufficient verified free quota and a representative request succeeds. General audio input is not automatically a continuous realtime STT interface. |
| ElevenLabs Scribe | Recorded and realtime STT; current API pricing advertises Scribe v3 Live at $0.22/hour, with plan-specific allowances and extras. [Capabilities](https://elevenlabs.io/docs/overview/capabilities/speech-to-text), [pricing](https://elevenlabs.io/pricing/api) | Zero-cost sponsor/account allowance must be verified. Pricing alone does not establish that a free account supplies the needed minutes. |
| Google Cloud STT | Separate metered service; V2 standard initial-volume list price is currently $0.016/minute. [Pricing](https://cloud.google.com/speech-to-text/pricing) | Paid fallback or verified applicable credits only. Do not infer entitlement from a Gemini subscription. |

Keep only one working STT backend in the first integration. Preserve an adapter boundary so a measured failure can justify a replacement. Do not implement every candidate in parallel. Benchmark the actual recording plus noisy speech, silence, names, negations and overlapping voices; report real-time factor, segment delay, RAM and critical event errors. Move inference to a stronger laptop before assuming a paid service is necessary.

## What the Google student subscription actually implies

Current official [Google AI Pro benefits](https://support.google.com/googleone/answer/14534406?hl=en) and [Developer Program benefits](https://developers.google.com/profile/help/benefits) list $10/month in eligible Google Cloud developer credits. A linked Developer Program profile and actual entitlement matter. The user's student membership and credit redemption have not been inspected, so this is a potential benefit, not an available balance.

Google's [November 13 announcement](https://blog.google/innovation-and-ai/technology/developers-tools/google-cloud-credits-gdp-ai-studio/) describes claiming credits inside AI Studio. Current [Gemini billing documentation](https://ai.google.dev/gemini-api/docs/billing) says Prepay accounts need a positive prepaid balance before applicable promotional credits can be used, with a minimum $5 purchase. Account billing assignment can differ. This may require out-of-pocket spending even with credits; it cannot be silently treated as the $0 path.

A separate Gemini Developer API free tier remains a candidate. Verify its project and model limits in AI Studio, make a representative multimodal structured request and record success without enabling a paid fallback. Limits apply per project, not per key, and include RPM, TPM and RPD; rotating keys does not create more capacity. See [rate limits](https://ai.google.dev/gemini-api/docs/rate-limits). Do not confuse Gemini app access, developer credits, Developer API quotas and Vertex/Google Cloud billing.

Free-tier pricing indicates content may be used to improve products. Send approved demo media, not phone numbers, card information or account secrets. No provider key belongs in the extension or committed repository.

## Model capability record

A current candidate is `gemini-3.5-flash-lite`. Its [official model page](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite) lists stable status, multimodal input and structured output, but no Live API. Standard [pricing](https://ai.google.dev/gemini-api/docs/pricing) lists a free tier and paid rates of $0.30/million input and $2.50/million output tokens. This is a research candidate, not a pin or proven account permission.

At phase 0 record: exact model ID; project and billing tier without secrets; current quotas; SDK version and endpoint; image/structured-output smoke-test; latency; token usage; pricing URL/check date; deprecation status; allowed role; fallback policy. Recheck [deprecations](https://ai.google.dev/gemini-api/docs/deprecations); older model identifiers can be retired or rerouted. Keep model IDs centralized. Initially use one verified model across observation, proposal and resolution roles.

Sparse images are intentional evidence selection, not comprehensive video understanding. Google's [video guide](https://ai.google.dev/gemini-api/docs/video-understanding) notes that default sampling can miss fast motion. Higher sampling can increase work and cost; evaluate it only if the chosen event needs it.

## Mathematical quota and cost budget

For role j, measure input tokens Ij, output tokens Oj, invocations Nj and its current per-million prices pi/po:

`LLM cost = sum(Nj × (Ij × pi + Oj × po) / 1,000,000) + separately priced features`

Include billable reasoning/output, images/audio, retries and rehearsals according to the actual provider response. Do not assume a fixed image-token count across models. Disable web grounding and unrelated tools for this workload. If STT is billed by duration:

`STT cost = submitted billed minutes × actual plan rate`

Repeated overlap can bill the same audio twice; silence can also count. Local STT has no external per-minute bill but consumes compute.

A fixed invocation every c seconds creates approximately `3600/c` requests/hour before retries: 720/hour at five seconds, 240/hour at fifteen seconds. These are workload calculations, not provider allowances. Let Qday be actual remaining daily quota, Qreserve the judging reserve and Qtest the planned fixture/rehearsal use. Require `Qtest + Qreserve <= Qday`; reduce cadence or test volume if it fails. Also compare burst requests and measured input tokens against RPM/TPM independently.

Use event-triggered calls, a cooldown, one active market, bounded resolution attempts and saved fixtures for development. Reserve judging quota explicitly. Track actual request/token counts centrally, restrict concurrency and output tokens, and provide a stop switch. A quota failure should degrade gracefully; it must never activate billing. A Cloud budget alert is not an application-level hard spending stop.

## Phase-0 capability checklist

- Identify Pi model, OS, architecture, storage, power/cooling and network reachability; identify every laptop CPU/GPU/RAM/OS and which one runs OBS.
- Confirm a Twitch-delivered capture path, media clocks and real end-to-end latency. Local-file tests cannot satisfy final-demo acceptance.
- Choose the demo game/activity, participants, language, event template and clear results evidence before optimizing transcription.
- Verify Google account tier, exact usable model, quotas and whether credits require a payment. Keep all unverified entries marked UNVERIFIED.
- Record sponsor credentials availability, expiry and actual supported operations. Never put credential values in the record.
- Benchmark local STT and one multimodal request on representative content. Select hardware from evidence.
- Allocate request budgets for development, rehearsal and judging. Record the operator responsible for stopping external usage.
- If a paid alternative is necessary, present its measured need and explicit total cap to the owner before activation.
