-- P11 inbound-call bookie (CONTRACTS §9.21, D43). Applied once by fazetime_api.db.migrate(); never edit after it ships.
-- Money never moves here. A confirmed intent commits through domain.place_wager as the bound user, so the wager,
-- its WAGER_STAKE ledger transaction (source_key 'stake:<user>:<operation_id>', UNIQUE) and the operations row are
-- exactly those of a viewer wager. These rows only record who is bound to the line and what was quoted.
-- No caller identity from audio, names or caller ID is stored; no contact details of any kind.

-- The operator-bound demo line (created only by the CLI on the API host). At most one ACTIVE job.
CREATE TABLE call_jobs (
    call_job_id    TEXT PRIMARY KEY CHECK (length(call_job_id) = 36 AND substr(call_job_id, 1, 4) = 'cjb_'),
    user_id        TEXT NOT NULL REFERENCES users(user_id),
    run_id         TEXT NOT NULL REFERENCES runs(run_id),
    kind           TEXT NOT NULL CHECK (kind = 'BOUND_LINE'),
    state          TEXT NOT NULL CHECK (state IN ('ACTIVE', 'ENDED')),
    created_by     TEXT NOT NULL CHECK (created_by = 'CLI'),
    created_at_utc TEXT NOT NULL,
    ended_at_utc   TEXT,
    CHECK ((state = 'ENDED') = (ended_at_utc IS NOT NULL))
) STRICT;
CREATE UNIQUE INDEX call_jobs_one_active ON call_jobs(state) WHERE state = 'ACTIVE';

-- Only the bound user must be a non-bot VIEWER (D30): checked at insert, and users.role/is_bot are immutable.
CREATE TRIGGER call_jobs_bound_user_is_viewer BEFORE INSERT ON call_jobs
WHEN NOT EXISTS (SELECT 1 FROM users u WHERE u.user_id = NEW.user_id AND u.role = 'VIEWER' AND u.is_bot = 0)
BEGIN SELECT RAISE(ABORT, 'a call job binds one non-bot VIEWER'); END;

-- Forward-only: identity never changes; ACTIVE -> ENDED once; ENDED is final.
CREATE TRIGGER call_jobs_forward_only BEFORE UPDATE ON call_jobs
WHEN OLD.state = 'ENDED'
  OR NEW.call_job_id IS NOT OLD.call_job_id OR NEW.user_id IS NOT OLD.user_id OR NEW.run_id IS NOT OLD.run_id
  OR NEW.kind IS NOT OLD.kind OR NEW.created_by IS NOT OLD.created_by OR NEW.created_at_utc IS NOT OLD.created_at_utc
BEGIN SELECT RAISE(ABORT, 'call jobs only move ACTIVE -> ENDED; identity is immutable'); END;

CREATE TRIGGER call_jobs_no_delete BEFORE DELETE ON call_jobs
BEGIN SELECT RAISE(ABORT, 'call jobs are never deleted'); END;

-- Wager intents (POST /v1/call/intents). Idempotent on (call_job_id, client_request_id) with a request hash.
-- operation_id is a fresh server UUID and becomes the wager's operation_id on confirm. Only the SHA-256 of the
-- one-time nonce is stored. quote_json is the original prepare response without the nonce (replayed verbatim
-- with nonce null and the current status).
CREATE TABLE wager_intents (
    intent_id              TEXT PRIMARY KEY CHECK (length(intent_id) = 36 AND substr(intent_id, 1, 4) = 'wit_'),
    call_job_id            TEXT NOT NULL REFERENCES call_jobs(call_job_id),
    client_request_id      TEXT NOT NULL CHECK (length(client_request_id) = 36),
    request_hash           TEXT NOT NULL CHECK (length(request_hash) = 64),
    user_id                TEXT NOT NULL REFERENCES users(user_id),
    run_id                 TEXT NOT NULL REFERENCES runs(run_id),
    market_id              TEXT NOT NULL REFERENCES markets(market_id),
    rules_version          INTEGER NOT NULL CHECK (rules_version >= 1),
    side                   TEXT NOT NULL CHECK (side IN ('YES', 'NO')),
    amount_minor           INTEGER NOT NULL CHECK (amount_minor > 0),
    operation_id           TEXT NOT NULL UNIQUE CHECK (length(operation_id) = 36),
    nonce_hash             TEXT NOT NULL UNIQUE CHECK (length(nonce_hash) = 64),
    quoted_aggregate_version INTEGER NOT NULL CHECK (quoted_aggregate_version >= 1),
    est_gross_return_minor INTEGER NOT NULL CHECK (est_gross_return_minor >= amount_minor),
    quote_json             TEXT NOT NULL CHECK (json_valid(quote_json)),
    status                 TEXT NOT NULL CHECK (status IN ('PENDING', 'CONFIRMED', 'CANCELLED', 'EXPIRED')),
    wager_id               TEXT UNIQUE REFERENCES wagers(wager_id),
    created_at_utc         TEXT NOT NULL,
    expires_at_utc         TEXT NOT NULL,
    terminal_at_utc        TEXT,
    UNIQUE (call_job_id, client_request_id),
    CHECK ((status = 'CONFIRMED') = (wager_id IS NOT NULL)),
    CHECK ((status = 'PENDING') = (terminal_at_utc IS NULL)),
    CHECK (expires_at_utc > created_at_utc)
) STRICT;
CREATE UNIQUE INDEX wager_intents_one_pending_per_job ON wager_intents(call_job_id) WHERE status = 'PENDING';
CREATE INDEX wager_intents_job ON wager_intents(call_job_id, created_at_utc);

-- An intent is created PENDING on an ACTIVE job, for that job's user and run, on a market of that run.
CREATE TRIGGER wager_intents_match_job BEFORE INSERT ON wager_intents
WHEN NEW.status IS NOT 'PENDING'
  OR NOT EXISTS (SELECT 1 FROM call_jobs j WHERE j.call_job_id = NEW.call_job_id AND j.state = 'ACTIVE'
                 AND j.user_id = NEW.user_id AND j.run_id = NEW.run_id)
  OR NOT EXISTS (SELECT 1 FROM markets m WHERE m.market_id = NEW.market_id AND m.run_id = NEW.run_id)
BEGIN SELECT RAISE(ABORT, 'an intent starts PENDING on an ACTIVE call job, with its user, run and a market of that run'); END;

-- Forward-only: only a PENDING row changes, once, to CONFIRMED / CANCELLED / EXPIRED; the quote is immutable.
CREATE TRIGGER wager_intents_forward_only BEFORE UPDATE ON wager_intents
WHEN OLD.status <> 'PENDING'
  OR NEW.intent_id IS NOT OLD.intent_id OR NEW.call_job_id IS NOT OLD.call_job_id
  OR NEW.client_request_id IS NOT OLD.client_request_id OR NEW.request_hash IS NOT OLD.request_hash
  OR NEW.user_id IS NOT OLD.user_id OR NEW.run_id IS NOT OLD.run_id OR NEW.market_id IS NOT OLD.market_id
  OR NEW.rules_version IS NOT OLD.rules_version OR NEW.side IS NOT OLD.side OR NEW.amount_minor IS NOT OLD.amount_minor
  OR NEW.operation_id IS NOT OLD.operation_id OR NEW.nonce_hash IS NOT OLD.nonce_hash
  OR NEW.quoted_aggregate_version IS NOT OLD.quoted_aggregate_version
  OR NEW.est_gross_return_minor IS NOT OLD.est_gross_return_minor OR NEW.quote_json IS NOT OLD.quote_json
  OR NEW.created_at_utc IS NOT OLD.created_at_utc OR NEW.expires_at_utc IS NOT OLD.expires_at_utc
BEGIN SELECT RAISE(ABORT, 'wager intents only move forward from PENDING; the quote is immutable'); END;

-- CONFIRMED points at exactly this intent's wager: same operation_id, user, run, market, side and stake.
CREATE TRIGGER wager_intents_confirm_matches_wager BEFORE UPDATE ON wager_intents
WHEN NEW.wager_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM wagers w
    WHERE w.wager_id = NEW.wager_id AND w.operation_id = NEW.operation_id AND w.user_id = NEW.user_id
      AND w.run_id = NEW.run_id AND w.market_id = NEW.market_id AND w.side = NEW.side
      AND w.amount_minor = NEW.amount_minor)
BEGIN SELECT RAISE(ABORT, 'a confirmed intent must reference its own wager'); END;

CREATE TRIGGER wager_intents_no_delete BEFORE DELETE ON wager_intents
BEGIN SELECT RAISE(ABORT, 'wager intents are never deleted'); END;
