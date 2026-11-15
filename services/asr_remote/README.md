# Remote speech-to-text service (D34)

faster-whisper int8 on the CPU of the Vultr VM `fazetime-asr`, reachable only over the tailnet. The Pi worker
calls it through `services/worker/fazetime_worker/asr_remote.py` and falls back to its local tiny.en engine
whenever the service is slow, failing or unreachable.

## Deployed instance

- Endpoint: `http://100.91.148.70:8090` (MagicDNS `fazetime-asr`). It is reachable only over the tailnet; plain HTTP runs inside WireGuard.
- Model: `distil-small.en`, which is the HF repo `Systran/faster-distil-whisper-small.en`, snapshot `ef77d905`.
  - Settings: int8, `ASR_THREADS=8`, concurrency 1, CTranslate2 4.9.0 with the default ISA (AVX2 kernels plus oneDNN int8 GEMM), faster-whisper 1.2.1.
  - Why this model: it was the most accurate model whose VM p95 per 4 s window stayed at or below 1.0 s (0.97 s). The bench is in the D34 handoff.
- The Pi reaches the VM over a Tailscale DERP relay (`dfw`); no direct path is established. Each 4 s chunk adds about 165 ms of network and HTTP time at p50 and 307 ms at p95.
- systemd unit: `fazetime-asr.service`, with `Restart=on-failure` and logs in journald.

### Worker (client) environment

| Variable | Default | Meaning |
|---|---|---|
| `ASR_REMOTE_URL` | unset, which means local ASR only | `http://100.91.148.70:8090` |
| `ASR_REMOTE_TOKEN` | – | The bearer token, a secret. It lives in `.env.local` on the laptop and in `~/fazetime-data/worker.env` (mode 0600) on the Pi. Never put it in a URL or a log |
| `ASR_REMOTE_TIMEOUT_S` / `ASR_REMOTE_CONNECT_S` | 2.5 / 1.0 | Read and connect timeouts. The client asks the server for a deadline 200 ms shorter |
| `ASR_REMOTE_SLOW_MS` | 1800 | A slower round trip counts as a breaker strike; its result is still used |
| `ASR_REMOTE_FAILURES` / `ASR_REMOTE_OPEN_S` | 3 / 30 | Consecutive strikes that open the circuit, and how long it stays open |

### Operate (on the VM as root)

```
systemctl is-active fazetime-asr
systemctl status fazetime-asr
journalctl -u fazetime-asr -n 50 --no-pager
systemctl restart fazetime-asr
systemctl stop fazetime-asr
ss -ltnp | grep 8090        # must show 100.91.148.70:8090 only
```

To change the model, pre-download it first with `bash deploy/install.sh MODEL`. Then edit `ASR_MODEL` in `/etc/systemd/system/fazetime-asr.service`, run `systemctl daemon-reload` and restart the service.

## API

- `POST /v1/transcribe`
  - Body: raw 16 kHz mono s16le PCM, 1 to 320,000 bytes (at most 10 s). Requests that use `Transfer-Encoding` are refused.
  - `Authorization: Bearer <ASR_REMOTE_TOKEN>` is required. The token is compared in constant time.
  - Optional correlation metadata, as a header or a query parameter. The server validates these and echoes them back in `request`:
    - `X-Source-Epoch` / `source_epoch`
    - `X-Sequence` / `sequence`
    - `X-Media-Start-Ms` / `media_start_ms`
  - Optional `X-Deadline-Ms`. It is clamped to `ASR_DEADLINE_MS`.
  - A 200 response contains `{text, segments:[{start_ms,end_ms,text,avg_logprob,no_speech_prob,compression_ratio}], model, compute_ms, queue_ms, total_ms, audio_ms, filtered_repetitive, request, server_received_at, server_sent_at}`.
    - `text` leaves out segments whose compression ratio is above 2.4.
    - `segments` contains every decoded segment, so the worker can apply its own filter.
  - Errors:
    - 401: token missing or wrong.
    - 400, 411 or 413: bad body or bad metadata.
    - 503 `queue_full` or `deadline_exceeded`.
    - 500 `engine_failure`.
- `GET /healthz` needs no token. It returns `{status, model, concurrency, in_flight, waiting, uptime_s}`.

Decoding is identical to the Pi worker (`engine.DECODE_KW`): `language=en`, `beam_size=5`, `vad_filter=True`, `temperature=0.0` with no fallback ladder, `max_new_tokens=64` and `condition_on_previous_text=False`. **No `initial_prompt` and no `hotwords`**: on the team audio they fabricated names and "1v1" loops (spikes/p0b-team).

## Safety limits

- **Binding.** The server binds only to the IPv4 address of `tailscale0`, which must be in 100.64.0.0/10. With any other address it refuses to start, including `0.0.0.0`, the public IP, loopback and hostnames.
- **Load limits:**
  - concurrency of 1 to 2 (semaphore);
  - a wait queue capped by `ASR_QUEUE_CAP`;
  - a per-request deadline that returns 503;
  - at most 8 connections;
  - a 15 s socket timeout.
- **Logging.** The server never logs the token or transcript text. Each request produces one journald line with the status, epoch, sequence and timings.

## Configuration (systemd `Environment=` lines; the secret lives in `/etc/fazetime-asr.env`, root 0600)

| Variable | Default | Meaning |
|---|---|---|
| `ASR_REMOTE_TOKEN` | (required, ≥32 chars) | bearer token; only in `/etc/fazetime-asr.env` |
| `ASR_BIND_HOST` / `ASR_BIND_IFACE` / `ASR_PORT` | – / `tailscale0` / 8090 | must be the tailnet IPv4 of the interface |
| `ASR_MODEL` | `small.en` (the unit sets `distil-small.en`) | faster-whisper model name, pre-downloaded |
| `ASR_THREADS` / `ASR_CONCURRENCY` | 8 / 1 | CTranslate2 intra-op threads / parallel decodes |
| `ASR_QUEUE_CAP` / `ASR_DEADLINE_MS` | 2 / 2500 | waiting requests / per-request deadline |
| `ASR_MODELS_DIR` | – | HF cache dir; loaded with `local_files_only=True` |

## Deploy (on the VM as root, from a copy of this directory)

```
bash deploy/install.sh distil-small.en     # user, /opt/fazetime-asr, uv sync --frozen, model, unit, restart
systemctl status fazetime-asr; journalctl -u fazetime-asr -n 50
```

Install the token from the laptop without printing it:
`grep '^ASR_REMOTE_TOKEN=' .env.local | ssh root@fazetime-asr 'umask 077; cat > /etc/fazetime-asr.env'`.

## Tests and bench

- `uv run --frozen pytest` runs the server tests offline with a stub engine on loopback.
- `bench/vm_bench.py` is the VM benchmark (streaming windows of 4 s with a 3 s hop, the same policy as the server).
- `bench/rtt_probe.py` measures the Pi-to-VM round trip. It reads the token from stdin.
- Bench transcripts are team content. They stay on the VM and are deleted after a run; never commit them.
