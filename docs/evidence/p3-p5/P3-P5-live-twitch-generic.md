# P3–P5 live Twitch evidence: generic AI profile (D37) on a public channel (D40)

**REAL TWITCH INGESTION, through Streamlink on the Pi.** The source was a public third-party channel, not the team channel. This was the owner's choice (D40), so it does not replace the team-channel gate. Timings and outcomes only: no transcripts, frames or quotes.

- **Date:** 2026-11-15, 02:44–02:51 CT.
- **Code:** `a2d272e` (worker generic profile) on the Pi, with the API at `5df12ac`. Approval mode.
- **Channel:** Counter-Strike, about 30 viewers.
- **Operator:** the coordinator clicked in the console at the owner's request ("approve the next bet").
- **Stakes:** two labelled TEST viewers, created through open access (D35) with test credits, staked one side each so the pool was not empty (D12).

## Timeline (stream media time)

| Media time | Event |
|---|---|
| 2 s | Observer sees gameplay. The game is read as Counter-Strike 2, with the unit "round" |
| 20–28 s, 62–148 s | Rounds detected; a result screen ends each one. 3 proposals rejected by code as `INSUFFICIENT_LEAD`, because each came too late in its round |
| 184 s | New round starts |
| 202 s | **Proposed: "Will the streamer win this round?"** (EPISODE_OUTCOME). Approved in the console with about 57 s left on the approval countdown. Betting window 35 s from approval. YES $1.00 / NO $1.00 |
| 264 s | Lock (`lock_media_ms` 264 020) |
| 292 s | Last frame classified as gameplay |
| 300 s | Observer: post-round menu, round ended. Episode ended |
| 02:50:31 CT | Resolver: **both reads "ROUND LOST", so NO**. Reader B fell back from 3.1 to 3.5 Flash-Lite. Posted to the API as PENDING_APPROVAL |
| shortly after | Operator checked the evidence frame on the result card (the red-tinted post-death screen), then approved. **"No won. Winners paid."** |

**Fairness:** the round ended between media 292 s and 300 s. That is 28–36 s after lock, outside the 20 s margin plus 15 s slack (`300 − 264 = 36`).

**Latency:** the owner saw the result about 30–40 s after seeing the round end on Twitch. The contributors:
- Twitch HLS delay of about 6–10 s;
- the observer's 8 s cadence;
- slow or failing 3.1 Flash-Lite calls, including one cooldown skip;
- the 4 s post-end wait;
- reader fallback.

## Follow-ups from this take
- Worker env tuning was applied after it: the observer chain is now 3.5 first, every 6 s, with per-model spacing of 4.2 s. The timeout is 10 s, because **8 s gave HTTP 400 on every call**, which is the API's minimum-deadline rule.
- The tuned setup has not been re-measured on a live bet yet.
- Still pending:
  - a **positive** outcome (YES) on Twitch;
  - the team-channel take that the P3–P5 gates require.
- Minecraft survival (no rounds) produced one bet that could not be resolved ("…when this game ends?"), left unapproved. **Gap:** add fixed-window templates for streams with no detected round ends.
