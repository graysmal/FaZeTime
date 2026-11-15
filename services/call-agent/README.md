# FaZeTime call agent (Chert FaceTime)

Grizz, a sock-puppet bookie with an NYC-cabbie voice, answers the team's Chert FaceTime
line (D42, D43). It talks about the current stream and its open market, quotes the pool's
estimated returns, and takes bets in test credits for the viewer account the operator
bound to the line (CONTRACTS 9.21, P11 scope).

- **Bets:** four tools in `bookie_desk.py`: `get_odds`, `prepare_bet`, `confirm_bet`,
  `cancel_bet`. The backend (`/v1/call/*`, CALL_WORKER token) binds the account, checks
  market, deadline, stake limits, balance and quote, and commits through the normal
  wager path idempotently. Agent code adds the spoken-yes gate: a bet is confirmed only
  after the readback has been spoken and the caller's next final utterance is a clear yes
  (no "no", "wait", "change" or question). The model never sees the nonce. One-to-one
  calls only; a pending bet is cancelled when the call ends. Returns are always called
  estimates; there are no fixed odds.
- **Who bets:** never the voice. On the API host the operator runs
  `python -m fazetime_api list-viewers` and `bind-call-user --user-id usr_...`
  (`end-call-binding` to stop). Anyone the Chert line lets through bets from that account,
  so keep the line's allowed callers to the team's demo phones.
- **Markets:** AI markets close 35 s after opening, too short for a phone bet; the agent
  refuses when under 15 s remain. A longer operator market is needed for in-call bets.
- **Character:** realtime voice `ash` at `VOICE_PITCH=0.92`, NYC-cabbie persona (D43; the
  paid OpenAI Onyx voice was declined).
- **Model:** `openai/gpt-realtime-2.1-mini` through LiveKit Inference. It authenticates
  with the same `LIVEKIT_API_KEY`/`LIVEKIT_API_SECRET`, so there is no model key.
  Override with `REALTIME_MODEL`, `REALTIME_VOICE`, `VOICE_PITCH` (0.6-1.0).
- **Video:** on a FaceTime Video call the caller sees Grizz rising from a puppet booth
  (`puppet.py`, 640x360 at 15 fps): the jaw flaps and the puppet bobs while it speaks, the
  googly eyes jiggle all the time. FaceTime can crop the wide frame to fill an upright phone
  (Chert's per-line Fit/Fill framing, in the dashboard), which keeps only a narrow middle
  column, so the puppet is drawn small and centred (`PUPPET_SCALE`, default 0.5). Frames are
  drawn in a worker thread (~10 ms each) so video never delays the audio. `AGENT_LOOK=face` shows the simpler face (`face.py`) instead. It is a
  camera track from the same participant that speaks, which is the only video the Mac shows.
  FaceTime Audio calls ignore it. If the model session dies mid-call, the agent stops the
  picture and leaves the room rather than showing a live-looking puppet that cannot talk.

## Test without FaceTime

`.venv/bin/python scripts/room_smoke.py` imitates one Chert call in a throwaway room on the
LiveKit project: it dispatches the running agent, sets the `bridge_ready` signal and checks
that the agent stays silent until then, speaks within 9 s and sends one camera track (it
also prints a rough voice-pitch estimate). It uses no FaceTime minutes
(a fraction of a cent of Inference credit). Set `AGENT_NAME=...` in the shell to test a
second copy (for example `AGENT_NAME=fazetime-bookie-test .venv/bin/python agent.py dev`)
without disturbing the one that holds the line.

## Setup (once per machine)

```bash
cd services/call-agent
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env.local && chmod 600 .env.local   # then fill it in privately
.venv/bin/python scripts/check_env.py --inference     # prints no values; see below
scripts/chert.sh login                                # browser approval, lasts 30 days
scripts/chert.sh livekit --env-file "$PWD/.env.local" # Chert's LiveKit, where Chert provides it
scripts/chert.sh setup --env-file "$PWD/.env.local" --project <CHERT_PROJECT_UUID>
```

`chert livekit` fills the three LiveKit values only where Chert provides LiveKit (not on a
trial project; it answers `livekit_not_provisioned`). Otherwise create a free LiveKit Cloud
project (cloud.livekit.io → Settings → API Keys) and put its URL, key and secret in
`.env.local` yourself. `chert livekit` replaces values you entered only with `--force`.

`check_env.py` always checks that the key and secret are accepted by the URL's project
(read-only, free). `--inference` adds one tiny Inference text request (about 20 tokens on
`openai/gpt-oss-120b`, a tiny fraction of a cent) to prove the keys can use Inference.

Bookie access (after the API with CONTRACTS 9.21 is deployed): `scripts/provision_call_token.sh`
mints the CALL_WORKER token on the Pi over SSH and writes `FAZETIME_CALL_WORKER_TOKEN` into
`.env.local` without printing it. `FAZETIME_API_BASE` defaults to `http://fazetime:8000`
(tailnet). Tests: `.venv/bin/python -m pytest -q tests`.

## Every session

Terminal A, the agent:

```bash
services/call-agent/scripts/start_agent.sh
```

Terminal B, Chert:

```bash
services/call-agent/scripts/chert.sh doctor
services/call-agent/scripts/chert.sh dev --agent fazetime-bookie
```

`doctor` warns about a missing `OPENAI_API_KEY`; ignore it, because this agent uses
Inference. Plain `doctor` is read-only; `doctor --agent` dispatches a real test job.
`dev` refuses with `line_offline` (or `worker_unavailable`, `line_paused`) while the Chert
Mac is not accepting calls; only Chert can fix that. Once `dev` prints **Connected to
Chert** and the waiting-room message, call the line with FaceTime Audio.

Stop with Ctrl+C in Terminal B and wait for "Stopped. The line no longer routes to this
agent." before stopping Terminal A. After editing `agent.py`, stop Chert first, restart the
agent, then run `chert dev` again. On a shared line, add `--until HH:MM` for your slot.

## Costs

| Provider | What is used | Cost |
|---|---|---|
| Chert | FaceTime minutes per answered call | Trial: 50 min, 5 min per call |
| LiveKit Cloud | Connection minutes while the agent waits and during calls | Build plan: $0, 5,000 WebRTC min/month, no card |
| LiveKit Inference | gpt-realtime-2.1-mini audio ($10 in / $20 out per 1M audio tokens), only while a caller is connected | About $0.03 per call minute, rising as call context grows, from the Build plan's $2.50/month credit (roughly 50–80 min). On Build the credit is a hard cap: requests fail, possibly mid-call, when it runs out. It is shared across all of the owner's free LiveKit projects and resets on the 1st of each month |

Nothing here is deployed. Deploying the agent (LiveKit Cloud agents or elsewhere) needs a
separate owner OK.
