# FaZeTime API (phase 2)

**TEST MONEY ONLY.** Demo credits in integer minor units (100 = one demo dollar). There are no real payments, no card data and no phone fields. `payment_mode` is `UNAVAILABLE` and `ai_mode` is `OFF`. Source health is `STOPPED` until P3. Fixture markets are labelled `OPERATOR_FIXTURE`.

The API is one FastAPI process with one SQLite file, using stdlib `sqlite3`, explicit SQL and numbered migrations (D13, D23, D28). Contract: `docs/CONTRACTS.md` §9 (v1). Money rules: `docs/ECONOMICS.md` §2–4.

## Versions (resolved in `uv.lock`)

- Python 3.12 via uv. Measured on `latpop`: CPython 3.12.3 with SQLite 3.45.1.
- Runtime: fastapi 0.163.0, starlette 1.10.0, pydantic 2.14.3, uvicorn 0.54.0, websockets 17.4.
- Dev: pytest 9.2.0, httpx2 2.16.0 (used by the Starlette test client).
- FastAPI's built-in OpenTelemetry hooks are disabled in `create_app`.

## Commands (run from `services/api/`)

```bash
uv sync --frozen                                  # install exactly what uv.lock pins
uv run --frozen pytest                            # full suite (real SQLite files in tmp dirs)
uv run --frozen python -m fazetime_api bootstrap-operator   # prints ONE operator invite to this terminal only
uv run --frozen python -m fazetime_api serve      # uvicorn, 1 process, FAZETIME_HOST:FAZETIME_PORT (127.0.0.1:8000)
uv run --frozen python -m fazetime_api reconcile  # ledger reconciliation JSON (exit 1 if not ok)
uv run --frozen python -m fazetime_api backup /path/backup.db   # online copy via sqlite3 backup API
```

You can also run `uv run --frozen uvicorn fazetime_api.main:create_app --factory --host 127.0.0.1 --port 8000`. Never use `--workers` greater than 1: WebSocket fanout and rate limits are in-process.

Migrations apply at startup and from every CLI command. An applied migration whose file has changed is refused (sha256 check). The database is `var/fazetime.db` by default, which is gitignored along with `*.db-journal`.

| Env var | Default | Meaning |
|---|---|---|
| `FAZETIME_DB_PATH` | `var/fazetime.db` | SQLite file on local persistent disk |
| `FAZETIME_HOST` / `FAZETIME_PORT` | `127.0.0.1` / `8000` | Bind address. `serve` refuses `0.0.0.0` unless `--allow-all-interfaces` |
| `FAZETIME_ALLOWED_ORIGINS` | `https://www.twitch.tv,chrome-extension://*` | CORS and WebSocket Origin allowlist (exact origins or `scheme://*`) |
| `FAZETIME_SEED_GRANT_MINOR` | `2000` | SEED_GRANT per user per run |
| `FAZETIME_MIN_LEAD_MS` | `30000` | Minimum `close_at_utc − now` at OPEN. A fixture market's `close_in_s` must be at least this |
| `FAZETIME_SWEEPER_ENABLED` / `FAZETIME_SWEEPER_INTERVAL_S` | `1` / `1.0` | Durable sweeper |
| `FAZETIME_LOG_LEVEL` | `INFO` | Tokens, tickets and invite codes are never logged |

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
| `POST /v1/operator/markets/{id}/settle` | `{operation_id, winning_side}`. Fixture markets only: EVALUATING, and only before `resolve_by_utc` |
| `POST /v1/operator/markets/{id}/void` | `{operation_id, note?}`. VOID with OPERATOR_CANCELLED and refunds |
| `POST /v1/operator/sessions/revoke` | `{operation_id, user_id}` |
| `GET /v1/operator/health` | Service pragmas and migrations, sweeper, WebSocket, run, markets including DRAFT, wallets, funding, reconciliation, recent events and audit, presence |
| `GET /v1/operator/ledger?run_id=` | Transactions with entries, plus reconciliation |

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

## Manual smoke (2026-11-15 03:24 UTC, latpop, 127.0.0.1)

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
open market                                  HTTP 200  {'state': 'OPEN', 'close_at_utc': '2026-11-15T03:25:09.755Z'}
Alice wagers YES 500                         HTTP 201  {'status': 'ACCEPTED', 'available_after': 1500}
Alice replays same operation_id              HTTP 200  {'replayed': True, 'same_wager': True}
Bob wagers NO 700                            HTTP 201  {'status': 'ACCEPTED', 'available_after': 1300}
Bob tries other side                         HTTP 409  SIDE_CONFLICT
waiting 32.5s for close_at + sweeper ...
late wager after close                       HTTP 409  ('MARKET_CLOSED', 'STATE')
snapshot after lock                          HTTP 200  {'state': 'EVALUATING', 'pool': {'yes_minor': 500, 'no_minor': 700, 'total_minor': 1200, 'simulated_minor': 0, 'wager_count': 2}}
settle YES                                   HTTP 200  {'state': 'SETTLED', 'winning_side': 'YES'}
snapshot Alice                               HTTP 200  {'result': 'WON', 'payout_total_minor': 1200, 'available_minor': 2700, 'in_play_minor': 0, 'event_hwm': 18}
snapshot Bob                                 HTTP 200  {'result': 'LOST', 'payout_total_minor': 0, 'available_minor': 1300, 'in_play_minor': 0, 'event_hwm': 18}
operator health reconciliation               HTTP 200  {'ok': True, 'accounts_checked': 5, 'transactions_checked': 6, 'markets_checked': 1, 'problems': []}
operator health service                      HTTP 200  {'sqlite': '3.45.1', 'pragmas': {'journal_mode': 'delete', 'synchronous': 2, 'foreign_keys': 1, 'busy_timeout': 5000}, 'sweeper_runs>0': True}
ledger transactions (reason, entries sum)    HTTP 200  [('SEED_GRANT', 0), ('SEED_GRANT', 0), ('SEED_GRANT', 0), ('WAGER_STAKE', 0), ('WAGER_STAKE', 0), ('PAYOUT', 0)]
viewer calls operator route                  HTTP 403  FORBIDDEN
Alice WS frames: [('ready', 4), ('market.opened', 2), ('pool.updated', 3), ('wager.updated', 1), ('wallet.changed', 2), ('pool.updated', 4), ('market.locked', 5), ('market.evaluating', 6), ('market.settled', 7), ('wager.updated', 2), ('wallet.changed', 3)]
```

The money adds up. The pool was 1,200, and the sole winner (Alice, 500 YES) received the gross 1,200, so her net is +700. Bob lost 700. Total demo money is still 3 × 2,000 seeds = 6,000 (2,700 + 1,300 + 2,000).

**Rerun on final code.** A fresh DB had migrations 0001 and 0002 applied at startup. The results were identical: Alice WON with 2,700, Bob LOST with 1,300, reconciliation ok, and the same 11 WS frames. The server log had 0 tracebacks.

**Restart check.** I stopped the server and started it again on the same DB. Afterwards reconciliation was ok, the market was still `SETTLED/YES`, the wallets were unchanged (Alice 2,700, Bob 1,300) and the event history was intact. A WS client that dropped TCP abruptly left 0 tracebacks in the server log.

**Secret scan.** `grep -cE "fzs_|fzw_|XXXX-XXXX-XXXX"` over both server logs found 0 matches.

## Raspberry Pi 5 (aarch64, Debian/Raspberry Pi OS 64-bit)

The coordinator verified that uv-managed CPython 3.12.16 on the Pi installs aarch64 wheels. pydantic-core, uvicorn and websockets publish manylinux aarch64 wheels; the rest is pure Python. Nothing here compiles from source.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh        # if uv is missing
cd ~/FaZeTime/services/api
uv python install 3.12                                  # uv-managed CPython 3.12.x (aarch64)
uv sync --frozen                                        # same lock as the laptop
uv run --frozen pytest -q                               # run the suite ON THE PI before the demo
uv run --frozen python -c "import sqlite3; print(sqlite3.sqlite_version)"   # record it; WAL stays off regardless
FAZETIME_DB_PATH=$HOME/fazetime-data/fazetime.db FAZETIME_HOST=<pi-tailnet-ip> \
  uv run --frozen python -m fazetime_api serve
```

- Bind to the Pi's Tailscale IP (100.x), or 127.0.0.1 behind a local proxy. Never 0.0.0.0 on venue Wi-Fi.
- Put the DB on local persistent storage, not tmpfs or a network share. Back it up with `python -m fazetime_api backup`.
- uv-managed CPython bundles its own SQLite. It may differ from the system's 3.46.1; `GET /v1/operator/health` reports the version in use.
- If the extension calls the API from a `https://www.twitch.tv` content script, CORS allows that origin, and Private Network Access preflights are answered. Mixed content (an http API from an https page) is a P0-F network question that this service does not solve.

## Notes for the P1 adapter

- WALLET events use `aggregate_id = user_id` (matching the fixture). `balance_version` restarts at 1 in each run, so key versions by `(stream_session_id, aggregate_id)` and refetch on `stream.updated` with a new run.
- `balance_version` also advances when `in_play_minor` changes without a ledger movement (a losing stake). Use the version, not balance equality, for ordering.
- Market `aggregate_version` is 1 at DRAFT, so a viewer's first event is `market.opened` with version 2. Never assume versions start at 1.
- WS: send `{"type":"auth","ticket"}` within 5 s. You get `ready` (with `event_hwm`, `stream_id`, `server_time_utc`), then events. Send `{"type":"ping"}` to get `{"type":"pong"}`; the server sends `{"type":"ping"}` every 25 s. `{"type":"resync"}` means refetch the snapshot. Closes: 4401 for auth (including a revoked session), 4403 for origin or role.
- `wagering_paused` is true only when the current OPEN market is Twitch-origin and the source is not LIVE. Fixture markets are never paused by source health.
- Validation errors use `details.fields[].loc` with the `"body"` prefix, for example `["body","user_id"]`.
- Error envelopes also carry `schema_version: 1`, which is additive. An unknown HTTP method returns 405 with code `NOT_FOUND`.
