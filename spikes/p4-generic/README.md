# Game-agnostic proposer and resolver spike (D37)

LOCAL FIXTURE replay only. It is never the Twitch gate and is not wired to the API. The design comes from `reports/Game agnostic stream prop bets.md`. Results are in `docs/evidence/p4/P4-generic-fixture-replay.md`.

The fixture media, transcripts, labels and run outputs live in `~/fazetime-data/fixtures/`. Never commit them.

```bash
# 1. prepare a recording (local faster-whisper small.en plus 1 fps 480p frames)
services/worker/.venv/bin/python -I spikes/p4-generic/prep_fixture.py VIDEO.mp4 ~/fazetime-data/fixtures/peggle/NAME
# 2. causal replay (real Gemini calls; key read from .env.local; counted per model per Pacific day)
services/worker/.venv/bin/python -I spikes/p4-generic/replay.py ~/fazetime-data/fixtures/peggle/NAME RUN_DIR/NAME
# 3. grade against ~/fazetime-data/fixtures/peggle/ground_truth.json
python3 -I spikes/p4-generic/grade.py RUN_DIR
```

| File | Role |
|---|---|
| `fixture.py` | Causal slicer: words released 1.5 s after they end, frames after their media second |
| `generic.py` | Observer prompt and schema; the reducer (episode state machine, number histories, score-reset boundaries); the four templates with rules rendered by code; the validators; extract-then-decide resolution; D39 timing constants |
| `replay.py` | The loop: observe → reduce → resolve → propose. Observer `--observer flash` (default) or `gemma-first` |
| `llm.py` | The worker's `GeminiClient` with one gate per model; a TPM governor for Gemma |
| `grade.py` | Labels → expected answers, fairness and latency checks |
| `probe_models.py` | One-request capability probe (image, system instruction, JSON schema) |

Request use per full pass of both recordings (about 8 minutes of media): about 80 `gemini-3.1-flash-lite` observer calls, plus about 10 `gemini-3.5-flash-lite` and `gemini-3.1-flash-lite` proposer and resolver calls. The free tier allows 500 a day for each Flash-Lite model.
