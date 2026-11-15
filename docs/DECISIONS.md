# Decision register

Status meanings: OWNER_CONFIRMED; DESIGN_DEFAULT (reviewable engineering choice); OPEN; DEFERRED.
The phase plan owns execution order. This register owns decisions and their provenance. Later owner decisions supersede older text explicitly.

| ID | Status | Decision and consequence |
|---|---|---|
| D01 | OWNER_CONFIRMED | Hackathon demo only. Stripe test mode, no real money or public launch scope. |
| D02 | OWNER_CONFIRMED | Python backend; TypeScript extension/dashboard. Supersedes intermediate Rust API preference. |
| D03 | OWNER_CONFIRMED | $0 external spend unless absolutely necessary and separately discussed. Existing machines and verified sponsor allocations first. |
| D04 | OWNER_CONFIRMED | Prerecorded team video broadcasts through OBS to Twitch. Final ingestion must consume Twitch delivery. |
| D05 | OWNER_CONFIRMED | Manual FaceTime fallback acceptable; Twitch fallback to local file is not accepted. |
| D06 | OWNER_CONFIRMED | Binary pari-mutuel pool payouts; zero fee. Display estimates before lock. |
| D07 | OWNER_CONFIRMED | Raffle odds use cumulative amount each user wagered in the stream, keeping it simple. No ticket purchases or extra multiplier system. |
| D08 | OWNER_CONFIRMED | Prefer automatic proposal/result actions, subject to observed quality; may switch to operator approval. |
| D09 | OWNER_CONFIRMED | Chert provides 24-hour free sponsor usage. Exact boundaries, capacity, model/LiveKit inclusion remain unverified. |
| D10 | OWNER_CONFIRMED | Deadline, laptop hardware, and recorded game/challenge are to be decided in phase 0. |
| D11 | DESIGN_DEFAULT | Eligible raffle amount means accepted stakes from settled nonvoid markets in this stream run, regardless of win/loss; no deposits, refunds, redemption spend, or bots. Draw waits for markets to become terminal. Confirm this interpretation at P0. |
| D12 | DESIGN_DEFAULT | Empty/one-sided pools void and refund, preventing undefined winner payout. No fee and no raffle weight for voids. |
| D13 | DESIGN_DEFAULT | Single FastAPI process + SQLite on one host; local ASR worker on best measured laptop. Sponsor PostgreSQL only if actual need/available setup wins the time tradeoff. |
| D14 | DESIGN_DEFAULT | Hosted fixed-origin iframe is a P1 spike; bundled Shadow DOM panel is a proposed fallback requiring owner acknowledgment if it changes the PDF's embed interaction. No arbitrary URL relay. |
| D15 | DESIGN_DEFAULT | Stripe-hosted test Checkout outside the embedded panel; phone is a profile field, not authentication. Invite-only demo sessions before public OAuth. |
| D16 | DESIGN_DEFAULT | Bookie calls only opted-in, verified team recipients; fresh explicit bet confirmation; insufficient funds lead to test Checkout and new confirmation, not an automatic saved-card charge. |
| D17 | OPEN | Exact deadline and how much P8–P11 to prioritize if the core overruns. Preserve their specs; no silent deletion. |
| D18 | OPEN | Actual Chert grant expiry/group video/identity exposure; whether creator participation is represented by a teammate or actual invited creator. Use team devices until established. |
| D19 | OPEN | Recorded challenge and objective result cues; minimum lead-in derived from measurements. |
| D20 | OPEN | Account's Gemini free-tier quotas/credit redemption and any unavoidable prepayment. No cash authorization exists. |
| D21 | DEFERRED | Real-money operation, store distribution, withdrawal, live card charging, public recruitment, multi-stream scaling, chat choice highlighting, referrals, watch-time streaks, nostalgic email outreach. |

For changes append: ID, date, owner/source, previous choice superseded, new choice, reason, affected phases/contracts, migration required, evidence. Do not keep two active contradictory decisions.

