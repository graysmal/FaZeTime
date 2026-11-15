# Risks, early signals, and bounded responses

This register supports [PROJECT_PLAN](../PROJECT_PLAN.md); phase gates remain authoritative. Ratings are engineering judgments about this demo, not measured probabilities. Resolve only risks relevant to the current phase; do not turn this into a production compliance project.

| Risk | Severity | Early evidence / response | Stop or fallback |
|---|---|---|---|
| Actual deadline unknown | Critical | P0 confirm cutoff, judging, remaining builders | Cannot promise P11 delivery without time; prioritize with owner |
| Twitch reader blocked or codec fails | Critical | P0 actual channel/network 10–15-min capture | Timebox Streamlink, try authorized Twitch tab capture; if both fail core blocked |
| Stream delay makes market retrospective | Critical | Measure source cue through UI, compare action boundary | Record longer setup, reject late proposal; do not use spontaneous 1v3 first |
| AI invents event/outcome | Critical | Negative fixtures, evidence citations, held-out result | Abstain/void; approval mode if owner accepts; no confidence threshold shortcut |
| Missing media interpreted as loss | Critical | Gap/staleness signal and result interval | Lock/void affected unresolved market; never infer NO from silence |
| Duplicate debit/credit/draw/call | Critical | Concurrent retries and restart tests | Unique operations + transaction/outbox; freeze release until corrected |
| Gemini free quota absent/exhausted | High | Real account smoke test and request budget | Local STT; fewer bounded model calls; stop proposals. No paid auto-fallback |
| Student credits need cash activation | High | Check actual entitlement and prepay plan | Stay on working free tier; ask owner about concrete minimum if essential |
| Chert trial expires before judging | High | Record exact grant start/end including time zone | Schedule spike/rehearsal wisely; ask sponsor extension or use accepted manual call |
| Chert transport free but AI/LiveKit not | High | Verify each separate project's quotas | Tested free path only; do not assume all bundled |
| Group video not enabled | High | P0 sponsor confirmation and two-phone test | Manual FaceTime accepted; single call is only partial integration |
| Calling takes longer than market | High | Measure ring/answer/confirmation distribution | Dedicated long-window bookie scene; late refusal is correct |
| Pi too slow / ARM dependency unavailable | High | Benchmark actual OS, wheels, sustained STT | Move inference to laptop; API can remain Pi |
| Venue client isolation/NAT | High | Test browser/worker connectivity before coding topology | Colocate or verified HTTPS tunnel; no unapproved cloud spend |
| Hosted iframe/auth blocked | High | P0/P1 exact origin and cookie tests | Owner-approved bundled panel; no CSP stripping |
| Quick Tunnel changes hostname / drops socket | Medium | Restart route and test reconnect | Update allowlists/callback config; polling; stable existing domain if available |
| SSE chosen for Quick Tunnel | High | Official docs exclude SSE | Use WebSocket + HTTP snapshots/polling |
| Browser worker terminates | Medium | Stop service worker/popup during test | Keep authority backend and media in offscreen document where applicable |
| SQLite contention or bad backup | High | Real-engine concurrent tests, version check | Short write transactions; supported backup; do not share file over network |
| Phone identity privacy promise false | Medium | Inspect both iPhones during real group call | Use team devices and remove claim until verified |
| Simulated bot wins raffle | High | Flags and denominator tests | Bots count for pool only, excluded from raffle/calls |
| Call model mistakes speaker/user | High | Bound single-user call; mixed group audio test | No financial tools in group calls; explicit scoped confirmation |
| Context rot or parallel schema drift | High | Contradictory status/contracts, worker wrong base | Coordinator-only canonical files; bounded task packets; reread after compaction |
| Sponsor research/example becomes stale | Medium | Pin tested docs/version and account result | Reverify narrow capability; no wholesale stack churn |
| No-fee demo claims direct wagering revenue | Medium | Review pitch against implemented economics | Explain potential sponsored challenges/commerce; label projections, no earned-revenue claim |

## Irreducible uncertainties

No documentation can guarantee unblocked Twitch playback, machine throughput, the team's Google entitlement, Chert group enablement or actual AI quality. Phase-0 records and later live gates are how the implementation reduces those uncertainties. Do not hide them behind a detailed architecture diagram.

## Demo integrity controls

Keep three independent labels: media source (`TWITCH_*` or test fixture), model mode (automatic/approval/fixture), and payment funding (Stripe test/seed/mock). A single vague “demo” badge cannot explain which pieces are real. The full final mode uses Twitch delivery, live model inference and server transactions; staged source content is disclosed, while future answers remain unavailable to inference.

Provider rules are operational blockers, not a debate about the product idea. Stripe's live gambling restriction and Chrome store distribution policy mean this specific demo cannot be described as ready to launch by changing keys or disguising an embed. No legal or public-launch work is included; a future request would need its own provider and distribution decisions.

