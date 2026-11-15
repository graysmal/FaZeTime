# FaZeTime API (phase 2)

**TEST MONEY ONLY.** Demo credits in integer minor units (100 = one demo dollar). There are no real payments, no card data and no phone fields. `payment_mode` is `UNAVAILABLE` unless Stripe test keys load (P6). A new stream starts with `ai_mode` `OFF` (`FAZETIME_AI_MODE_DEFAULT`); the operator sets it with `POST /v1/operator/ai-mode`. Fixture markets are labelled `OPERATOR_FIXTURE`; AI markets `AI_APPROVED` / `AI_AUTOMATIC`.

Source health is derived from media-worker heartbeats (§9.16). It is `STOPPED` with null fields until a worker registers an epoch.

The API is one FastAPI process with one SQLite file, using stdlib `sqlite3`, explicit SQL and numbered migrations (D13, D23, D28). Contract: `docs/CONTRACTS.md` §9 (v1). Money rules: `docs/ECONOMICS.md` §2–4.

## Versions (resolved in `uv.lock`)

- Python 3.12 via uv. Measured on `latpop`: CPython 3.12.3 with SQLite 3.45.1.
- Runtime: fastapi 0.163.0, starlette 1.10.0, pydantic 2.14.3, uvicorn 0.54.0, websockets 17.4, python-multipart 0.0.33. python-multipart is pure Python and is needed for the §9.16 multipart frame upload.
- Measured on the Pi `fazetime`: aarch64, Debian 13, uv-managed CPython 3.12.16, which bundles **SQLite 3.53.1**.
- Dev: pytest 9.2.0, httpx2 2.16.0 (used by the Starlette test client).
- FastAPI's built-in OpenTelemetry hooks are disabled in `create_app`.

## Commands (run from `services/api/`; the tree digest above is sha256 over all files except README.md, .venv, __pycache__ and var)

```bash
uv sync --frozen                                  # install exactly what uv.lock pins
uv run --frozen pytest                            # full suite (real SQLite files in tmp dirs)
uv run --frozen python -m fazetime_api bootstrap-operator   # prints ONE operator invite to this terminal only
uv run --frozen python -m fazetime_api issue-worker-token --label pi-capture  # prints ONE fzk_ MEDIA_WORKER token
uv run --frozen python -m fazetime_api revoke-worker-tokens                   # revokes every worker token
uv run --frozen python -m fazetime_api serve      # uvicorn, 1 process, FAZETIME_HOST:FAZETIME_PORT (127.0.0.1:8000)
uv run --frozen python -m fazetime_api reconcile  # ledger reconciliation JSON (exit 1 if not ok)
uv run --frozen python -m fazetime_api backup /path/backup.db   # online copy via sqlite3 backup API
```

You can also run `uv run --frozen uvicorn fazetime_api.main:create_app --factory --host 127.0.0.1 --port 8000`. Never use `--workers` greater than 1: WebSocket fanout and rate limits are in-process.

Migrations (`0001_initial`, `0002_presence`, `0003_media_worker`, `0004_ai`, `0005_topups`) apply at startup and from every CLI command. An applied migration whose file has changed is refused (sha256 check). The data dir defaults to `var/`, holding `var/fazetime.db` and `var/evidence/`. It is gitignored along with `*.db-journal`.

| Env var | Default | Meaning |
|---|---|---|
| `FAZETIME_DATA_DIR` | `var` | Holds `fazetime.db` and `evidence/`. On the Pi: `~/fazetime-data` |
| `FAZETIME_DB_PATH` / `FAZETIME_EVIDENCE_DIR` | `<data dir>/fazetime.db` / `<data dir>/evidence` | Explicit overrides |
| `FAZETIME_EVIDENCE_KEEP_FRAMES` / `FAZETIME_EVIDENCE_KEEP_S` | `600` / `1800` | Evidence bounds (see below) |
| `FAZETIME_HEALTH_LIVE_MAX_S` / `FAZETIME_HEALTH_STALE_MAX_S` / `FAZETIME_HEALTH_BACKLOG_MAX_MS` | `12` / `30` / `12000` | Health thresholds (§9.4, §9.16 item 5) |
| `FAZETIME_HOST` / `FAZETIME_PORT` | `127.0.0.1` / `8000` | Bind address. `serve` refuses `0.0.0.0` unless `--allow-all-interfaces` |
| `FAZETIME_ALLOWED_ORIGINS` | `https://www.twitch.tv` | Comma-separated **exact** origins for the WebSocket Origin check. Wildcards are refused at startup (review M2). Add the pinned `chrome-extension://<id>` reported by the extension worker. An unpinned extension ID gets 4403 |
| `FAZETIME_CORS_ORIGINS` | the `chrome-extension://` entries of the list above | Exact CORS origins. twitch.tv is CORS-allowed only if listed here, because API calls come from the extension background (L7) |
| `FAZETIME_SEED_GRANT_MINOR` | `2000` | SEED_GRANT per user per run |
| `FAZETIME_MIN_LEAD_MS` | `30000` | Minimum `close_at_utc − now` at OPEN. A fixture market's `close_in_s` must be at least this |
| `FAZETIME_SWEEPER_ENABLED` / `FAZETIME_SWEEPER_INTERVAL_S` | `1` / `1.0` | Durable sweeper |
| `FAZETIME_LOG_LEVEL` | `INFO` | Tokens, tickets and invite codes are never logged |
| `FAZETIME_OPERATOR_DIST` | unset | Path to an `apps/operator` build (`dist/` with `index.html`), served same-origin at `/operator/` |
| `FAZETIME_ALLOW_AUTOMATIC` | `false` | D32 server flag. Without it `POST /v1/operator/ai-mode {mode: AUTOMATIC}` is `403 FORBIDDEN`, and a stored AUTOMATIC acts as APPROVAL. Set only after the P4/P5 quality gate is recorded |
| `FAZETIME_AI_MODE_DEFAULT` | `OFF` | AI mode of a brand-new stream's first run (`OFF`/`SHADOW`/`APPROVAL`/`AUTOMATIC`). D32 names APPROVAL as the default: set `APPROVAL` on the demo host. A reset keeps the previous run's mode |
| `FAZETIME_CANDIDATE_EXPIRY_S` | `60` | A PENDING AI candidate becomes EXPIRED this long after receipt |
| `FAZETIME_EVIDENCE_FRESH_S` | `90` | Evidence cited by a proposal must have been received within this window (rechecked at approval) |
| (code defaults) | `45`–`600` / `60`–`900` | AI `close_in_s` / `resolve_in_s` bounds (`Settings.ai_close_*`, `ai_resolve_*`): close below 45 s is `INSUFFICIENT_LEAD`, above 600 is clamped; resolve is clamped |

## Routes

**Viewer** (Bearer `fzs_…` session):
- `POST /v1/enroll`: no auth, 10 per 10 min per client.
- `GET /v1/me`.
- `GET /v1/streams/{stream_id}/snapshot`.
- `POST /v1/wagers`: 201 the first time, 200 with `replayed: true`.
- `GET /v1/operations/{operation_id}`.
- `POST /v1/ws-ticket`.
- `WS /v1/ws`.
- `POST /v1/presence`.
- `POST /v1/topups`, `GET /v1/topups/{id}`, `POST /v1/redemptions` and `GET /v1/raffle` return `503 CAPABILITY_UNAVAILABLE`.

Liveness: `GET /healthz`, unauthenticated, with no internals. OpenAPI: `/openapi.json` and `/docs`.

**Operator** (operator session; every mutation takes an `operation_id`, is idempotent per operator and writes an `audit_log` row):

| Route | Body |
|---|---|
| `POST /v1/operator/invites` | `{operation_id, role: VIEWER\|OPERATOR, is_bot, bind_user_id?}`. The code is returned once and never stored or replayed. `bind_user_id` makes a recovery invite for an existing user |
| `POST /v1/operator/streams` | `{operation_id, twitch_channel_login}`. Creates the single stream and its first run if absent, and seeds every user |
| `POST /v1/operator/runs/reset` | `{operation_id, stream_id}`. VOIDs the open market with RUN_RESET (refunded), archives the run, then creates and seeds a new run |
| `POST /v1/operator/credits` | `{operation_id, user_id, amount_minor 1..100000, memo?}`. FIXTURE_CREDIT, capped at 1,000,000 available |
| `POST /v1/operator/markets` | `{operation_id, question, yes_label="Yes", no_label="No", close_in_s, resolve_in_s}`. Creates a DRAFT with origin OPERATOR_FIXTURE. At OPEN, `close_at = open + close_in_s` and `resolve_by = close_at + resolve_in_s` |
| `POST /v1/operator/markets/{id}/open` | `{operation_id}`. DRAFT→OPEN |
| `POST /v1/operator/markets/{id}/settle` | `{operation_id, winning_side, note?}` (`note` at most 200 chars, kept in the audit row). Fixture markets only: EVALUATING, and only before `resolve_by_utc`. AI markets settle by approving a resolution |
| `POST /v1/operator/markets/{id}/void` | `{operation_id, note?}`. VOID with OPERATOR_CANCELLED and refunds |
| `POST /v1/operator/sessions/revoke` | `{operation_id, user_id}` |
| `GET /v1/operator/health` | Service pragmas and migrations, sweeper, WebSocket, run, markets including DRAFT, wallets, funding, reconciliation, recent events and audit, presence |
| `GET /v1/operator/ledger?run_id=` | Transactions with entries, plus reconciliation |

## Media-worker routes (§9.16)

Issue a token on the API host with `python -m fazetime_api issue-worker-token`. Set it on the worker host as `FAZETIME_WORKER_TOKEN` and send it as `Authorization: Bearer fzk_…`. Only its hash is stored.

- Viewer and operator sessions get `403 FORBIDDEN` on `/v1/worker/*`, and a worker token gets `401` on viewer and operator routes.
- JSON bodies are limited to 256 KB, and frames to 300 KB JPEG (SOI/EOI checked; sha256 must match).
- Data for an epoch that is not current gets `409 STALE_EPOCH`, with `details.current_source_epoch`.
- Worker data can change source health. It has no route to balances, wagers or settlement.

| Route | Behaviour |
|---|---|
| `POST /v1/worker/epochs` | `{schema_version, stream_id, source_epoch, source_kind, reason, variant, host_id, started_at_utc}`. Returns 201 if created, 200 on an identical retry. Re-registering a superseded epoch gets `STALE_EPOCH`. A new epoch becomes current, and a nonterminal **Twitch-origin** market is voided with `SOURCE_GAP` (fixture markets are exempt) |
| `POST /v1/worker/heartbeat` | Every 5 s. Returns `{server_time_utc, stream_session_id, current_source_epoch}`. `last_media_end_ms` only moves forward. `worker_state=GAP` marks the epoch as having a gap |
| `POST /v1/worker/evidence` | Multipart parts `meta` (JSON) and `file` (JPEG). Returns `{evidence_id, deduped}`: 201 if new, 200 if deduped on (`source_epoch`, `sequence`). Same key with a different sha256 is `IDEMPOTENCY_CONFLICT` |
| `POST /v1/worker/observations` | `{schema_version, stream_id, source_epoch, items[1..50]}`. Returns `{accepted, duplicates, rejected:[{sequence, code}]}`. The server stamps `received_at_utc`. A FRAME needs an `evidence_id` from this epoch; a GAP item marks a gap. Transcript text is stored verbatim as untrusted data |
| `POST /v1/worker/proposals`, `/resolutions` | §9.17, see "AI proposals and resolutions" below |
| `GET /v1/operator/evidence?since=<utc>&limit=` | Operator only. Recent observations (flagged `untrusted: true`), frame metadata and current health |
| `GET /v1/operator/evidence/{evidence_id}` | Operator only. Returns the JPEG, or 404 if unknown or pruned |

**Health is LIVE** when, for the current epoch, a heartbeat arrived no more than 12 s ago, it reported `LIVE`, `last_media_end_ms` advanced within the last 12 s, and `asr_backlog_ms` is at most 12,000. Otherwise:

| State | When |
|---|---|
| GAP | A gap was reported in this epoch |
| STOPPED | The heartbeat and epoch registration are more than 30 s old, or media is more than 30 s old, or the worker says STOPPED |
| CONNECTING | A new epoch with no media yet |
| STALE | Anything in between |

Health is computed on read, so wagers and snapshots never use a stale cache. The sweeper publishes one `source.health` event per state or epoch change (aggregate `SOURCE` with `aggregate_id = stream_id`).

**Evidence bounds.** The API keeps a frame only while it is among the newest 600 and younger than 30 minutes. Frames pinned by a market (`pinned_by_market_id`, set by P4/P5) are always kept. Pruning runs on upload and in the sweeper. File paths are built from server-validated IDs only.

Worker smoke with curl (token in a variable, never on the command line of a shared shell):

```bash
H="Authorization: Bearer $FAZETIME_WORKER_TOKEN"; API=http://fazetime:8000; SID=<stream_id>; EP=ep_$(python3 -c 'import uuid;print(uuid.uuid4().hex)')
curl -s -H "$H" -H 'Content-Type: application/json' $API/v1/worker/epochs -d "{\"stream_id\":\"$SID\",\"source_epoch\":\"$EP\",\"source_kind\":\"TWITCH_STREAMLINK\",\"reason\":\"PROCESS_START\",\"variant\":null,\"host_id\":\"pi\",\"started_at_utc\":\"$(date -u +%FT%T.000Z)\"}"
curl -s -H "$H" -F "meta={\"source_epoch\":\"$EP\",\"sequence\":1,\"kind\":\"FRAME\",\"media_ms\":0,\"width\":640,\"height\":360,\"sha256\":\"$(sha256sum f.jpg|cut -c1-64)\"}" -F file=@f.jpg $API/v1/worker/evidence
```

## AI proposals and resolutions (§9.17, P4/P5)

The model only proposes; `fazetime_api/ai.py` validates and decides, and opens, settles or voids only through the
domain functions in one `BEGIN IMMEDIATE` transaction. Model text (question, predicates, rationale, reason,
contradictions) is untrusted: stored verbatim, length-bounded, shown to the operator flagged `*_untrusted`, never
interpreted. Evidence refs (§9.17 item 5c) are `evd_<32 hex>` (a frame) or `<source_epoch>:<sequence>` (an accepted
transcript observation of the request's epoch). Any other reference is unknown: `STALE_EVIDENCE`. Each take reuses
the episode fingerprint, so reset the run between takes (item 5d).

| Route | Behaviour |
|---|---|
| `POST /v1/worker/proposals` | `{schema_version, stream_id, source_epoch, candidate}`. Checks in contract order: `STALE_EPOCH`, `STALE_EVIDENCE` (unknown, other epoch, GAP, pruned, or received more than 90 s ago), `MARKET_BUSY`, `DUPLICATE_EPISODE`, `UNPAIRED_SIDES`, `SOURCE_NOT_LIVE`, then clamping (`INSUFFICIENT_LEAD` below 45 s), then the mode (`AI_OFF` / SHADOW / PENDING / OPENED as `AI_AUTOMATIC`). Response `{candidate_id, id (cnd_), status, reject_code, market_id, close_in_s, resolve_in_s, expires_at_utc, replayed}`: 201 when first recorded (REJECTED included), 200 on a replay of the same `candidate_id` (current status); a different body is `IDEMPOTENCY_CONFLICT`. A schema violation is `422` and is not recorded |
| `GET /v1/operator/candidates?status=&limit=` | Newest first for the active run, with resolved evidence (`frame_url`, transcript text), derived `EXPIRED`, `actionable` |
| `POST /v1/operator/candidates/{id}/approve` | `{operation_id, close_in_s?}`. `id` is the `cnd_` or the client `candidate_id`. Re-runs every check at commit. Close is anchored to receipt (`received + close_in_s`) unless `close_in_s` is given (seconds from approval, same bounds); `close_at − now` must be at least `min_lead_ms`. Errors carry `details.reject_code`: EXPIRED / INSUFFICIENT_LEAD → `409 MARKET_CLOSED` (reason DEADLINE), MARKET_BUSY → `409 STALE_MARKET`, SOURCE_NOT_LIVE → `409 SOURCE_STALE`, STALE_EPOCH → `409 STALE_EPOCH`, UNPAIRED_SIDES → `422`, not PENDING → `409 MARKET_CLOSED` (reason STATE), mode not APPROVAL/AUTOMATIC → `403` |
| `POST /v1/operator/candidates/{id}/reject` | `{operation_id, reason}`. REJECTED with `OPERATOR_REJECTED`; burns the episode |
| `POST /v1/operator/ai-mode` | `{operation_id, mode: OFF\|SHADOW\|APPROVAL\|AUTOMATIC}`. AUTOMATIC needs `FAZETIME_ALLOW_AUTOMATIC`. Emits `stream.updated` (modes) |
| `POST /v1/worker/resolutions` | `{schema_version, stream_id, source_epoch, resolution}`. Always recorded. `IGNORED` with reason `UNKNOWN_MARKET`, `MARKET_TERMINAL`, `NOT_AI_MARKET`, `STALE_MARKET` (not EVALUATING or wrong `rules_version`), `EPOCH_MISMATCH` (not the lock epoch), `NO_LOCK_POSITION`, `STALE_EVIDENCE`, `EVIDENCE_BEFORE_LOCK` (evidence or `media_interval.start_ms` before `lock_media_ms`), `PREDICATE_SUPPORT_MISMATCH`, `DEADLINE`, `DUPLICATE`. WAIT → `RECORDED`. YES/NO/UNRESOLVABLE: AUTOMATIC settles / voids `UNRESOLVABLE` (YES/NO with contradictions → `PENDING_APPROVAL`), APPROVAL → `PENDING_APPROVAL`, SHADOW/OFF → `RECORDED`. 201 first, 200 replay |
| `GET /v1/worker/market?stream_id=` | §9.17 item 5b, MEDIA_WORKER only: `{schema_version, market}` with `market_id, rules_version, state, origin, question, yes_label, no_label, close_at_utc, resolve_by_utc, lock_source_epoch, lock_media_ms` for the run's nonterminal market, else `null`. No balances or user data |
| `GET /v1/operator/resolutions?market_id=` | Stored suggestions with evidence and `actionable` |
| `POST /v1/operator/resolutions/{id}/approve` | `{operation_id}`. Settles or voids exactly as suggested through the fixture settlement path; other pending suggestions become `IGNORED SUPERSEDED`; a second approval is `409 MARKET_CLOSED` |

Every submission and operator decision appends an `inference_traces` row (model, prompt version, evidence refs, AI
mode, result, code). No prompts, keys or tokens are stored.

## Invariants and where they are enforced

- **Integer money:** STRICT tables. Payouts are computed in Python ints (`settlement.py`). Balances use compare-and-set updates with Python-computed values (`ledger.post`).
- **No fee:** the sum of payouts equals escrow (`compute_payouts` asserts it; `reconcile` checks it).
- **Non-negative balances:** `CHECK (kind='FUNDING_SOURCE' OR balance_minor >= 0)` on `ledger_accounts`. The `wallets` view exposes this as `available_minor`.
- **Append-only:** triggers reject UPDATE and DELETE on `ledger_transactions`, `ledger_entries`, `operations`, `events` and `audit_log`.
- **No cross-run movement:** an entry's account must belong to the transaction's run (trigger). `source_key` is UNIQUE, so no economic effect can repeat. Examples: `stake:<user>:<op>`, `payout:<wager>`, `refund:<wager>`, `seed:<run>:<user>`, `fixture_credit:<op_user>:<op>`.
- **Market state machine:**
  - Transition triggers allow only the §9.3 edges.
  - Terms freeze after OPEN, and terminal rows are immutable.
  - `aggregate_version` must increase.
  - The pool only grows, and only while OPEN.
  - A partial unique index allows one OPEN, LOCKED or EVALUATING market per run.
- **Wager backstop triggers:**
  - The market must be OPEN, in the same run, with the same `rules_version`.
  - `accepted_at_utc < close_at_utc`.
  - One side per user per market.
- **Single use:** invite codes and WS tickets are consumed by a conditional UPDATE, backed by a trigger. A session's `invite_id` is UNIQUE.
- **Inside one `BEGIN IMMEDIATE` (`domain.place_wager`):** the wager checks run in the §9.6 order, and the deadline is checked again as the last statement before COMMIT.
- **Before the transaction:** authentication, then rate limit, then validation.
- **Outbox:** events are written in the mutation's transaction, and their payloads are validated before commit. The hub only reads committed rows.

## Manual smoke (2026-11-15 03:53 UTC, latpop, 127.0.0.1, tree sha256 1c0896c4065a4b6a uncommitted on top of 6930352)

The commands are below. `scripts/smoke.py` keeps tokens and invite codes in memory and prints only sanitized fields.

```bash
export FAZETIME_DB_PATH=/tmp/fazetime-smoke.db     # throwaway DB
uv run --frozen python -m fazetime_api serve &      # binds 127.0.0.1:8000
curl -s http://127.0.0.1:8000/healthz
uv run --frozen python scripts/smoke.py
```

Result (verbatim, sanitized by construction):

```text
bootstrap-operator: invite printed to terminal (redacted here)
enroll operator                              HTTP 201  OPERATOR
create stream/run                            HTTP 201  {'created': True, 'run_state': 'ACTIVE'}
invite + enroll Alice                        HTTP 201  {'role': 'VIEWER', 'available_minor': 2000}
invite + enroll Bob                          HTTP 201  {'role': 'VIEWER', 'available_minor': 2000}
create fixture market                        HTTP 201  {'state': 'DRAFT', 'origin': 'OPERATOR_FIXTURE'}
open market                                  HTTP 200  {'state': 'OPEN', 'close_at_utc': '2026-11-15T03:53:18.209Z'}
Alice wagers YES 500                         HTTP 201  {'status': 'ACCEPTED', 'available_after': 1500}
Alice replays same operation_id              HTTP 200  {'replayed': True, 'same_wager': True}
Bob wagers NO 700                            HTTP 201  {'status': 'ACCEPTED', 'available_after': 1300}
Bob tries other side                         HTTP 409  SIDE_CONFLICT
waiting 32.4s for close_at + sweeper ...
late wager after close                       HTTP 409  ('MARKET_CLOSED', 'STATE')
snapshot after lock                          HTTP 200  {'state': 'EVALUATING', 'pool': {'yes_minor': 500, 'no_minor': 700, 'total_minor': 1200, 'simulated_minor': 0, 'wager_count': 2}}
settle YES                                   HTTP 200  {'state': 'SETTLED', 'winning_side': 'YES'}
snapshot Alice                               HTTP 200  {'result': 'WON', 'payout_total_minor': 1200, 'available_minor': 2700, 'in_play_minor': 0, 'event_hwm': 17}
snapshot Bob                                 HTTP 200  {'result': 'LOST', 'payout_total_minor': 0, 'available_minor': 1300, 'in_play_minor': 0, 'event_hwm': 17}
operator health reconciliation               HTTP 200  {'ok': True, 'accounts_checked': 4, 'transactions_checked': 5, 'markets_checked': 1, 'problems': []}
operator health service                      HTTP 200  {'sqlite': '3.45.1', 'pragmas': {'journal_mode': 'delete', 'synchronous': 2, 'foreign_keys': 1, 'busy_timeout': 5000}, 'sweeper_runs>0': True}
ledger transactions (reason, entries sum)    HTTP 200  [('SEED_GRANT', 0), ('SEED_GRANT', 0), ('WAGER_STAKE', 0), ('WAGER_STAKE', 0), ('PAYOUT', 0)]
viewer calls operator route                  HTTP 403  FORBIDDEN
Alice WS frames: [('ready', 3), ('market.opened', 2), ('pool.updated', 3), ('wager.updated', 1), ('wallet.changed', 2), ('pool.updated', 4), ('market.locked', 5), ('market.evaluating', 6), ('market.settled', 7), ('wager.updated', 2), ('wallet.changed', 3)]
```

The money adds up. The pool was 1,200, and the sole winner (Alice, 500 YES) received the gross 1,200, so her net is +700. Bob lost 700. Total demo money is still 2 viewer seeds × 2,000 = 4,000 (2,700 + 1,300). Under D30 the operator holds no wallet.

**Restart check** (earlier P2 tree, committed as 6c14f85). I stopped the server and started it again on the same DB. Afterwards reconciliation was ok, the market was still `SETTLED/YES`, the wallets were unchanged (Alice 2,700, Bob 1,300) and the event history was intact. A WS client that dropped TCP abruptly left 0 tracebacks in the server log.

**Secret scan.** `grep -cE "fzs_|fzw_|XXXX-XXXX-XXXX"` over both server logs found 0 matches.

## Raspberry Pi 5 runbook (host `fazetime`, aarch64, Debian 13)

Use key auth only: `ssh fazetime@fazetime`. No passwords, no sudo. Git isn't guaranteed on the Pi, so copy with tar.

```bash
# laptop: copy the service (no venv, no data)
cd services && tar --exclude=.venv --exclude=__pycache__ --exclude=var -czf - api \
  | ssh fazetime@fazetime 'mkdir -p ~/fazetime/services && tar -C ~/fazetime/services -xzf -'
# Pi: toolchain + deps + tests (uv is at ~/.local/bin/uv)
ssh fazetime@fazetime 'cd ~/fazetime/services/api && ~/.local/bin/uv python install 3.12 && ~/.local/bin/uv sync --frozen \
  && ~/.local/bin/uv run --frozen pytest -o addopts="" -p no:cacheprovider -q'
# Pi: run / inspect / stop (binds ONLY to `tailscale ip -4`, port 8000; data in ~/fazetime-data)
ssh fazetime@fazetime '~/fazetime/services/api/scripts/pi_run.sh start'     # setsid+nohup, log ~/fazetime-data/api.log
ssh fazetime@fazetime '~/fazetime/services/api/scripts/pi_run.sh status'
ssh fazetime@fazetime '~/fazetime/services/api/scripts/pi_run.sh stop'      # TERM to the process group, no SIGKILL
# laptop: reachability over the tailnet
curl -s http://fazetime:8000/healthz
```

- The DB is `~/fazetime-data/fazetime.db`, and frames live in `~/fazetime-data/evidence/`. Back up with `cd ~/fazetime/services/api && FAZETIME_DATA_DIR=~/fazetime-data .venv/bin/python -m fazetime_api backup ~/fazetime-data/backup-$(date +%s).db`.
- **The coordinator bootstraps the production operator invite.** Do it on the Pi itself: `FAZETIME_DATA_DIR=~/fazetime-data .venv/bin/python -m fazetime_api bootstrap-operator`. Mint the worker token the same way with `issue-worker-token`.
- uv-managed CPython bundles SQLite 3.53.1, not the system's 3.46.1. WAL stays off regardless (D23). `GET /v1/operator/health` reports the version in use.
- `pi_run.sh` defaults `FAZETIME_ALLOWED_ORIGINS=https://www.twitch.tv,chrome-extension://hodaaffdhncidmaccebmionoljljfefe`. That is the pinned extension ID, verified by the extension's two-browser e2e. With this setting CORS allows only the extension origin.
- **Operator UI.** If `FAZETIME_OPERATOR_DIST` (default `~/fazetime/apps/operator/dist`) contains an `index.html`, the build is served same-origin at `http://fazetime:8000/operator/`, so no CORS entry is needed. Extension-less client routes fall back to `index.html`; missing assets stay 404. `/v1/*` and `/openapi.json` are unaffected. Copy a build with `tar -C apps/operator -czf - dist | ssh fazetime@fazetime 'mkdir -p ~/fazetime/apps/operator && tar -C ~/fazetime/apps/operator -xzf -'`, then `pi_run.sh restart`.
- `pi_run.sh` refuses to start without a 100.x Tailscale address. Override with `FAZETIME_HOST`; never use 0.0.0.0 on venue Wi-Fi.
- Mixed content (an http API from the https Twitch page) is an extension/P0-F concern. The extension's service worker with host permissions is not subject to page CORS; only its pinned origin needs to be in `FAZETIME_ALLOWED_ORIGINS`.

## Contract rulings

The wire behaviour clients depend on is ruled in **docs/CONTRACTS.md §9.15** (v1 clarifications) and §9.16 (media worker). This README does not restate them. Server-specific defaults not covered there:

- D30: OPERATOR-role users cannot wager (403 FORBIDDEN), receive no seed grant or wallet, and are never raffle-eligible. Viewers and operators enroll with separate invites.
- Live sockets re-check their session on a fixed timer (`ws_session_recheck_s`, 30 s) regardless of traffic, and close with 4401 after revocation or expiry.
- Bodies above the cap (16 KB viewer, 256 KB worker JSON) are rejected from Content-Length, or while streaming, before they are buffered. Any unmapped 4xx returns `VALIDATION_FAILED` 422.
