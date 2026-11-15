-- FaZeTime API schema v1 (CONTRACTS §9.11/§9.13, ECONOMICS §2-4, D23/D26/D28).
-- Applied once by fazetime_api.db.migrate() inside BEGIN IMMEDIATE; never edit after it ships.
--
-- Conventions
--   * STRICT tables: SQLite refuses type coercion, so money columns can only hold INTEGER minor units.
--   * Times are TEXT 'YYYY-MM-DDTHH:MM:SS.mmmZ' (UTC, exactly three fractional digits), so
--     lexical comparison equals chronological comparison.
--   * Ledger, operations, events and audit rows are append-only (triggers reject UPDATE/DELETE).
--   * No phone fields anywhere (D16). No card data anywhere (AGENTS fixed constraint).

CREATE TABLE users (
    user_id              TEXT PRIMARY KEY CHECK (length(user_id) = 36 AND substr(user_id, 1, 4) = 'usr_'),
    display_name         TEXT NOT NULL CHECK (length(display_name) BETWEEN 1 AND 32),
    claimed_twitch_login TEXT CHECK (claimed_twitch_login IS NULL OR length(claimed_twitch_login) BETWEEN 1 AND 25),
    role                 TEXT NOT NULL CHECK (role IN ('VIEWER', 'OPERATOR', 'MEDIA_WORKER', 'CALL_WORKER')),
    is_bot               INTEGER NOT NULL CHECK (is_bot IN (0, 1)),
    created_at_utc       TEXT NOT NULL,
    CHECK (NOT (is_bot = 1 AND role <> 'VIEWER'))
) STRICT;

CREATE TRIGGER users_identity_immutable BEFORE UPDATE ON users
WHEN NEW.user_id IS NOT OLD.user_id OR NEW.role IS NOT OLD.role OR NEW.is_bot IS NOT OLD.is_bot
BEGIN SELECT RAISE(ABORT, 'user id, role and bot flag are immutable'); END;

CREATE TRIGGER users_no_delete BEFORE DELETE ON users
BEGIN SELECT RAISE(ABORT, 'users are never deleted'); END;

-- Invite codes: 12 Crockford base32 chars, stored only as SHA-256 of the normalized code.
-- Role and bot flag are bound here on the server; the enroll body cannot set them (§9.8).
CREATE TABLE invite_codes (
    invite_id          TEXT PRIMARY KEY CHECK (length(invite_id) = 36 AND substr(invite_id, 1, 4) = 'inv_'),
    code_hash          TEXT NOT NULL UNIQUE CHECK (length(code_hash) = 64),
    role               TEXT NOT NULL CHECK (role IN ('VIEWER', 'OPERATOR')),
    is_bot             INTEGER NOT NULL CHECK (is_bot IN (0, 1)),
    bind_user_id       TEXT REFERENCES users(user_id),
    created_by_user_id TEXT REFERENCES users(user_id),
    created_at_utc     TEXT NOT NULL,
    expires_at_utc     TEXT NOT NULL,
    used_at_utc        TEXT,
    used_by_user_id    TEXT REFERENCES users(user_id),
    CHECK ((used_at_utc IS NULL) = (used_by_user_id IS NULL)),
    CHECK (NOT (role = 'OPERATOR' AND is_bot = 1)),
    CHECK (expires_at_utc > created_at_utc)
) STRICT;

-- Single use: the only permitted update is the one conditional NULL -> used transition.
CREATE TRIGGER invite_codes_single_use BEFORE UPDATE ON invite_codes
WHEN OLD.used_at_utc IS NOT NULL
  OR NEW.used_at_utc IS NULL
  OR NEW.invite_id IS NOT OLD.invite_id OR NEW.code_hash IS NOT OLD.code_hash
  OR NEW.role IS NOT OLD.role OR NEW.is_bot IS NOT OLD.is_bot
  OR NEW.bind_user_id IS NOT OLD.bind_user_id OR NEW.created_by_user_id IS NOT OLD.created_by_user_id
  OR NEW.created_at_utc IS NOT OLD.created_at_utc OR NEW.expires_at_utc IS NOT OLD.expires_at_utc
BEGIN SELECT RAISE(ABORT, 'invite codes are single use and otherwise immutable'); END;

CREATE TRIGGER invite_codes_no_delete BEFORE DELETE ON invite_codes
BEGIN SELECT RAISE(ABORT, 'invite codes are never deleted'); END;

-- Sessions: opaque fzs_ token, stored as SHA-256 only; 72 h absolute expiry; revocable.
CREATE TABLE sessions (
    session_id     TEXT PRIMARY KEY CHECK (length(session_id) = 36 AND substr(session_id, 1, 4) = 'ses_'),
    token_hash     TEXT NOT NULL UNIQUE CHECK (length(token_hash) = 64),
    user_id        TEXT NOT NULL REFERENCES users(user_id),
    invite_id      TEXT NOT NULL UNIQUE REFERENCES invite_codes(invite_id),
    device_id      TEXT,
    created_at_utc TEXT NOT NULL,
    expires_at_utc TEXT NOT NULL,
    revoked_at_utc TEXT,
    CHECK (expires_at_utc > created_at_utc)
) STRICT;
CREATE INDEX sessions_user ON sessions(user_id);

CREATE TRIGGER sessions_only_revocation BEFORE UPDATE ON sessions
WHEN OLD.revoked_at_utc IS NOT NULL
  OR NEW.session_id IS NOT OLD.session_id OR NEW.token_hash IS NOT OLD.token_hash
  OR NEW.user_id IS NOT OLD.user_id OR NEW.invite_id IS NOT OLD.invite_id
  OR NEW.expires_at_utc IS NOT OLD.expires_at_utc OR NEW.created_at_utc IS NOT OLD.created_at_utc
BEGIN SELECT RAISE(ABORT, 'sessions can only be revoked once'); END;

-- One Twitch channel per stream row (application enforces a single stream in v1).
CREATE TABLE streams (
    stream_id            TEXT PRIMARY KEY CHECK (length(stream_id) = 36 AND substr(stream_id, 1, 4) = 'str_'),
    twitch_channel_login TEXT NOT NULL UNIQUE CHECK (length(twitch_channel_login) BETWEEN 1 AND 25),
    aggregate_version    INTEGER NOT NULL CHECK (aggregate_version >= 1),
    created_at_utc       TEXT NOT NULL
) STRICT;

CREATE TRIGGER streams_version_monotonic BEFORE UPDATE ON streams
WHEN NEW.aggregate_version <= OLD.aggregate_version OR NEW.stream_id IS NOT OLD.stream_id
BEGIN SELECT RAISE(ABORT, 'stream aggregate_version must increase'); END;

-- Runs (stream_session_id). Exactly one ACTIVE run per stream; ARCHIVED runs stay inspectable.
CREATE TABLE runs (
    run_id           TEXT PRIMARY KEY CHECK (length(run_id) = 36 AND substr(run_id, 1, 4) = 'run_'),
    stream_id        TEXT NOT NULL REFERENCES streams(stream_id),
    state            TEXT NOT NULL CHECK (state IN ('ACTIVE', 'ARCHIVED')),
    ai_mode          TEXT NOT NULL CHECK (ai_mode IN ('OFF', 'SHADOW', 'APPROVAL', 'AUTOMATIC', 'FIXTURE')),
    seed_grant_minor INTEGER NOT NULL CHECK (seed_grant_minor >= 0),
    created_at_utc   TEXT NOT NULL,
    archived_at_utc  TEXT,
    CHECK ((state = 'ARCHIVED') = (archived_at_utc IS NOT NULL))
) STRICT;
CREATE UNIQUE INDEX runs_one_active_per_stream ON runs(stream_id) WHERE state = 'ACTIVE';

CREATE TRIGGER runs_archive_only BEFORE UPDATE ON runs
WHEN OLD.state = 'ARCHIVED'
  OR NEW.run_id IS NOT OLD.run_id OR NEW.stream_id IS NOT OLD.stream_id
  OR NEW.seed_grant_minor IS NOT OLD.seed_grant_minor OR NEW.created_at_utc IS NOT OLD.created_at_utc
BEGIN SELECT RAISE(ABORT, 'archived runs are immutable'); END;

CREATE TRIGGER runs_no_delete BEFORE DELETE ON runs
BEGIN SELECT RAISE(ABORT, 'runs are never deleted'); END;

-- Markets. State machine and frozen terms are enforced by triggers below (CONTRACTS §9.3).
CREATE TABLE markets (
    market_id            TEXT PRIMARY KEY CHECK (length(market_id) = 36 AND substr(market_id, 1, 4) = 'mkt_'),
    run_id               TEXT NOT NULL REFERENCES runs(run_id),
    origin               TEXT NOT NULL CHECK (origin IN ('OPERATOR_FIXTURE', 'CANNED_FIXTURE', 'AI_APPROVED', 'AI_AUTOMATIC')),
    state                TEXT NOT NULL CHECK (state IN ('DRAFT', 'OPEN', 'LOCKED', 'EVALUATING', 'SETTLED', 'VOID')),
    question             TEXT NOT NULL CHECK (length(question) BETWEEN 1 AND 200),
    yes_label            TEXT NOT NULL CHECK (length(yes_label) BETWEEN 1 AND 40),
    no_label             TEXT NOT NULL CHECK (length(no_label) BETWEEN 1 AND 40),
    rules_version        INTEGER NOT NULL CHECK (rules_version >= 1),
    aggregate_version    INTEGER NOT NULL CHECK (aggregate_version >= 1),
    close_in_ms          INTEGER NOT NULL CHECK (close_in_ms > 0),
    resolve_in_ms        INTEGER NOT NULL CHECK (resolve_in_ms > 0),
    created_by_user_id   TEXT REFERENCES users(user_id),
    created_at_utc       TEXT NOT NULL,
    opened_at_utc        TEXT,
    close_at_utc         TEXT,
    resolve_by_utc       TEXT,
    locked_at_utc        TEXT,
    lock_source_epoch    TEXT,
    lock_media_ms        INTEGER,
    terminal_at_utc      TEXT,
    winning_side         TEXT CHECK (winning_side IN ('YES', 'NO')),
    void_reason          TEXT CHECK (void_reason IN ('EMPTY_POOL', 'ONE_SIDED_POOL', 'UNRESOLVABLE',
                                                     'RESOLUTION_TIMEOUT', 'SOURCE_GAP', 'RUN_RESET',
                                                     'OPERATOR_CANCELLED')),
    settlement_algorithm TEXT,
    yes_minor            INTEGER NOT NULL DEFAULT 0 CHECK (yes_minor >= 0),
    no_minor             INTEGER NOT NULL DEFAULT 0 CHECK (no_minor >= 0),
    simulated_minor      INTEGER NOT NULL DEFAULT 0 CHECK (simulated_minor >= 0),
    wager_count          INTEGER NOT NULL DEFAULT 0 CHECK (wager_count >= 0),
    CHECK ((state = 'SETTLED') = (winning_side IS NOT NULL)),
    CHECK ((state = 'SETTLED') = (settlement_algorithm IS NOT NULL)),
    CHECK ((state = 'VOID') = (void_reason IS NOT NULL)),
    CHECK ((state IN ('SETTLED', 'VOID')) = (terminal_at_utc IS NOT NULL)),
    CHECK (state = 'DRAFT' OR (opened_at_utc IS NOT NULL AND close_at_utc IS NOT NULL AND resolve_by_utc IS NOT NULL)),
    CHECK (state <> 'DRAFT' OR (opened_at_utc IS NULL AND wager_count = 0 AND yes_minor = 0 AND no_minor = 0)),
    CHECK (state NOT IN ('LOCKED', 'EVALUATING', 'SETTLED') OR locked_at_utc IS NOT NULL),
    CHECK (close_at_utc IS NULL OR close_at_utc > opened_at_utc),
    CHECK (resolve_by_utc IS NULL OR resolve_by_utc > close_at_utc),
    CHECK (simulated_minor <= yes_minor + no_minor),
    CHECK (state <> 'SETTLED' OR (yes_minor > 0 AND no_minor > 0))
) STRICT;

-- At most one OPEN/LOCKED/EVALUATING market per run (§9.3, §9.11).
CREATE UNIQUE INDEX markets_one_nonterminal_per_run ON markets(run_id)
    WHERE state IN ('OPEN', 'LOCKED', 'EVALUATING');
CREATE INDEX markets_run_state ON markets(run_id, state);

CREATE TRIGGER markets_transition_guard BEFORE UPDATE OF state ON markets
WHEN NEW.state IS NOT OLD.state AND NOT (
       (OLD.state = 'DRAFT'      AND NEW.state = 'OPEN')
    OR (OLD.state = 'OPEN'       AND NEW.state IN ('LOCKED', 'VOID'))
    OR (OLD.state = 'LOCKED'     AND NEW.state IN ('EVALUATING', 'VOID'))
    OR (OLD.state = 'EVALUATING' AND NEW.state IN ('SETTLED', 'VOID')))
BEGIN SELECT RAISE(ABORT, 'illegal market state transition'); END;

CREATE TRIGGER markets_terminal_immutable BEFORE UPDATE ON markets
WHEN OLD.state IN ('SETTLED', 'VOID')
BEGIN SELECT RAISE(ABORT, 'terminal markets are immutable'); END;

CREATE TRIGGER markets_terms_frozen BEFORE UPDATE ON markets
WHEN OLD.state <> 'DRAFT' AND (
       NEW.question IS NOT OLD.question OR NEW.yes_label IS NOT OLD.yes_label OR NEW.no_label IS NOT OLD.no_label
    OR NEW.rules_version IS NOT OLD.rules_version OR NEW.origin IS NOT OLD.origin OR NEW.run_id IS NOT OLD.run_id
    OR NEW.opened_at_utc IS NOT OLD.opened_at_utc OR NEW.close_at_utc IS NOT OLD.close_at_utc
    OR NEW.resolve_by_utc IS NOT OLD.resolve_by_utc OR NEW.market_id IS NOT OLD.market_id)
BEGIN SELECT RAISE(ABORT, 'market terms are frozen after OPEN'); END;

CREATE TRIGGER markets_version_monotonic BEFORE UPDATE ON markets
WHEN NEW.aggregate_version <= OLD.aggregate_version
BEGIN SELECT RAISE(ABORT, 'market aggregate_version must increase on every change'); END;

CREATE TRIGGER markets_pool_grows_only_while_open BEFORE UPDATE ON markets
WHEN (OLD.state <> 'OPEN' AND (NEW.yes_minor IS NOT OLD.yes_minor OR NEW.no_minor IS NOT OLD.no_minor
                               OR NEW.simulated_minor IS NOT OLD.simulated_minor
                               OR NEW.wager_count IS NOT OLD.wager_count))
  OR NEW.yes_minor < OLD.yes_minor OR NEW.no_minor < OLD.no_minor
  OR NEW.simulated_minor < OLD.simulated_minor OR NEW.wager_count < OLD.wager_count
BEGIN SELECT RAISE(ABORT, 'pool totals only grow, and only while OPEN'); END;

CREATE TRIGGER markets_no_delete BEFORE DELETE ON markets
BEGIN SELECT RAISE(ABORT, 'markets are never deleted'); END;

-- Ledger (ECONOMICS §2). Every movement is a balanced transaction of signed entries.
-- Materialized balances are a cache of entries; reconciliation proves they agree.
CREATE TABLE ledger_accounts (
    account_id     INTEGER PRIMARY KEY,
    kind           TEXT NOT NULL CHECK (kind IN ('USER_AVAILABLE', 'MARKET_ESCROW', 'FUNDING_SOURCE', 'REDEMPTION_SINK')),
    run_id         TEXT NOT NULL REFERENCES runs(run_id),
    user_id        TEXT REFERENCES users(user_id),
    market_id      TEXT REFERENCES markets(market_id),
    is_simulated   INTEGER NOT NULL DEFAULT 0 CHECK (is_simulated IN (0, 1)),
    balance_minor  INTEGER NOT NULL DEFAULT 0,
    version        INTEGER NOT NULL DEFAULT 0 CHECK (version >= 0),
    created_at_utc TEXT NOT NULL,
    -- available_minor >= 0 and escrow >= 0; only the demo funding source may go negative.
    CHECK (kind = 'FUNDING_SOURCE' OR balance_minor >= 0),
    CHECK ((kind = 'USER_AVAILABLE') = (user_id IS NOT NULL)),
    CHECK ((kind = 'MARKET_ESCROW') = (market_id IS NOT NULL))
) STRICT;
CREATE UNIQUE INDEX ledger_accounts_wallet  ON ledger_accounts(run_id, user_id) WHERE kind = 'USER_AVAILABLE';
CREATE UNIQUE INDEX ledger_accounts_escrow  ON ledger_accounts(market_id)       WHERE kind = 'MARKET_ESCROW';
CREATE UNIQUE INDEX ledger_accounts_funding ON ledger_accounts(run_id)          WHERE kind = 'FUNDING_SOURCE';
CREATE UNIQUE INDEX ledger_accounts_sink    ON ledger_accounts(run_id)          WHERE kind = 'REDEMPTION_SINK';

CREATE TRIGGER ledger_accounts_guard BEFORE UPDATE ON ledger_accounts
WHEN NEW.account_id IS NOT OLD.account_id OR NEW.kind IS NOT OLD.kind OR NEW.run_id IS NOT OLD.run_id
  OR NEW.user_id IS NOT OLD.user_id OR NEW.market_id IS NOT OLD.market_id
  OR NEW.is_simulated IS NOT OLD.is_simulated OR NEW.created_at_utc IS NOT OLD.created_at_utc
  OR NEW.version <> OLD.version + 1
BEGIN SELECT RAISE(ABORT, 'account identity is immutable and version increments by exactly one'); END;

CREATE TRIGGER ledger_accounts_no_delete BEFORE DELETE ON ledger_accounts
BEGIN SELECT RAISE(ABORT, 'ledger accounts are never deleted'); END;

CREATE VIEW wallets AS
    SELECT run_id, user_id, balance_minor AS available_minor, version AS balance_version, is_simulated
    FROM ledger_accounts WHERE kind = 'USER_AVAILABLE';

CREATE TABLE ledger_transactions (
    txn_id         TEXT PRIMARY KEY CHECK (length(txn_id) = 36 AND substr(txn_id, 1, 4) = 'txn_'),
    run_id         TEXT NOT NULL REFERENCES runs(run_id),
    reason         TEXT NOT NULL CHECK (reason IN ('SEED_GRANT', 'FIXTURE_CREDIT', 'WAGER_STAKE', 'PAYOUT',
                                                   'REFUND', 'STRIPE_TEST_TOPUP', 'REDEMPTION')),
    -- Stable economic source identity, e.g. 'seed:<run>:<user>', 'stake:<wager>', 'payout:<wager>'.
    -- UNIQUE makes a repeated economic effect impossible even if idempotency logic were bypassed.
    source_key     TEXT NOT NULL UNIQUE,
    market_id      TEXT REFERENCES markets(market_id),
    actor_user_id  TEXT REFERENCES users(user_id),
    operation_id   TEXT,
    is_simulated   INTEGER NOT NULL DEFAULT 0 CHECK (is_simulated IN (0, 1)),
    created_at_utc TEXT NOT NULL
) STRICT;
CREATE INDEX ledger_transactions_run ON ledger_transactions(run_id);

CREATE TABLE ledger_entries (
    entry_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    txn_id       TEXT NOT NULL REFERENCES ledger_transactions(txn_id),
    account_id   INTEGER NOT NULL REFERENCES ledger_accounts(account_id),
    amount_minor INTEGER NOT NULL CHECK (amount_minor <> 0)
) STRICT;
CREATE INDEX ledger_entries_txn ON ledger_entries(txn_id);
CREATE INDEX ledger_entries_account ON ledger_entries(account_id);

-- A movement never crosses runs: the entry's account must belong to the transaction's run.
CREATE TRIGGER ledger_entries_same_run BEFORE INSERT ON ledger_entries
WHEN (SELECT run_id FROM ledger_accounts WHERE account_id = NEW.account_id)
     IS NOT (SELECT run_id FROM ledger_transactions WHERE txn_id = NEW.txn_id)
BEGIN SELECT RAISE(ABORT, 'ledger entry account and transaction belong to different runs'); END;

CREATE TRIGGER ledger_transactions_no_update BEFORE UPDATE ON ledger_transactions
BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER ledger_transactions_no_delete BEFORE DELETE ON ledger_transactions
BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER ledger_entries_no_update BEFORE UPDATE ON ledger_entries
BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER ledger_entries_no_delete BEFORE DELETE ON ledger_entries
BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;

-- Wagers. One side per user per market; no edits, cancels or cashouts (§9.6).
CREATE TABLE wagers (
    wager_id                     TEXT PRIMARY KEY CHECK (length(wager_id) = 36 AND substr(wager_id, 1, 4) = 'wgr_'),
    market_id                    TEXT NOT NULL REFERENCES markets(market_id),
    run_id                       TEXT NOT NULL REFERENCES runs(run_id),
    user_id                      TEXT NOT NULL REFERENCES users(user_id),
    operation_id                 TEXT NOT NULL CHECK (length(operation_id) = 36),
    side                         TEXT NOT NULL CHECK (side IN ('YES', 'NO')),
    amount_minor                 INTEGER NOT NULL CHECK (amount_minor > 0),
    is_simulated                 INTEGER NOT NULL CHECK (is_simulated IN (0, 1)),
    rules_version                INTEGER NOT NULL CHECK (rules_version >= 1),
    status                       TEXT NOT NULL CHECK (status IN ('ACCEPTED', 'WON', 'LOST', 'REFUNDED')),
    version                      INTEGER NOT NULL CHECK (version >= 1),
    accepted_at_utc              TEXT NOT NULL,
    stake_txn_id                 TEXT NOT NULL UNIQUE REFERENCES ledger_transactions(txn_id),
    market_aggregate_version     INTEGER NOT NULL CHECK (market_aggregate_version >= 1),
    wallet_after_available_minor INTEGER NOT NULL CHECK (wallet_after_available_minor >= 0),
    wallet_after_in_play_minor   INTEGER NOT NULL CHECK (wallet_after_in_play_minor >= 0),
    wallet_after_balance_version INTEGER NOT NULL CHECK (wallet_after_balance_version >= 0),
    terminal_at_utc              TEXT,
    terminal_txn_id              TEXT UNIQUE REFERENCES ledger_transactions(txn_id),
    payout_minor                 INTEGER CHECK (payout_minor IS NULL OR payout_minor >= 0),
    refund_minor                 INTEGER CHECK (refund_minor IS NULL OR refund_minor >= 0),
    UNIQUE (user_id, operation_id),
    CHECK ((status = 'ACCEPTED') = (terminal_at_utc IS NULL)),
    CHECK (status <> 'ACCEPTED' OR (terminal_txn_id IS NULL AND payout_minor IS NULL AND refund_minor IS NULL)),
    CHECK (status <> 'WON'      OR (payout_minor >= amount_minor AND terminal_txn_id IS NOT NULL AND refund_minor IS NULL)),
    CHECK (status <> 'LOST'     OR (payout_minor = 0 AND terminal_txn_id IS NULL AND refund_minor IS NULL)),
    CHECK (status <> 'REFUNDED' OR (refund_minor = amount_minor AND terminal_txn_id IS NOT NULL AND payout_minor IS NULL))
) STRICT;
CREATE INDEX wagers_market ON wagers(market_id, wager_id);
CREATE INDEX wagers_user_run ON wagers(user_id, run_id, status);

-- Backstops for the transactional checks done in Python (§9.6 check order).
CREATE TRIGGER wagers_require_open_market BEFORE INSERT ON wagers
WHEN (SELECT state FROM markets WHERE market_id = NEW.market_id) IS NOT 'OPEN'
  OR NEW.accepted_at_utc >= (SELECT close_at_utc FROM markets WHERE market_id = NEW.market_id)
  OR NEW.run_id IS NOT (SELECT run_id FROM markets WHERE market_id = NEW.market_id)
  OR NEW.rules_version IS NOT (SELECT rules_version FROM markets WHERE market_id = NEW.market_id)
BEGIN SELECT RAISE(ABORT, 'wager requires an OPEN market of the same run before close_at_utc'); END;

CREATE TRIGGER wagers_one_side_per_user BEFORE INSERT ON wagers
WHEN EXISTS (SELECT 1 FROM wagers WHERE market_id = NEW.market_id AND user_id = NEW.user_id AND side <> NEW.side)
BEGIN SELECT RAISE(ABORT, 'one side per user per market'); END;

CREATE TRIGGER wagers_single_terminal_transition BEFORE UPDATE ON wagers
WHEN OLD.status <> 'ACCEPTED' OR NEW.status = 'ACCEPTED' OR NEW.version <> OLD.version + 1
  OR NEW.wager_id IS NOT OLD.wager_id OR NEW.market_id IS NOT OLD.market_id OR NEW.run_id IS NOT OLD.run_id
  OR NEW.user_id IS NOT OLD.user_id OR NEW.operation_id IS NOT OLD.operation_id OR NEW.side IS NOT OLD.side
  OR NEW.amount_minor IS NOT OLD.amount_minor OR NEW.is_simulated IS NOT OLD.is_simulated
  OR NEW.rules_version IS NOT OLD.rules_version OR NEW.accepted_at_utc IS NOT OLD.accepted_at_utc
  OR NEW.stake_txn_id IS NOT OLD.stake_txn_id OR NEW.market_aggregate_version IS NOT OLD.market_aggregate_version
  OR NEW.wallet_after_available_minor IS NOT OLD.wallet_after_available_minor
  OR NEW.wallet_after_in_play_minor IS NOT OLD.wallet_after_in_play_minor
  OR NEW.wallet_after_balance_version IS NOT OLD.wallet_after_balance_version
BEGIN SELECT RAISE(ABORT, 'wagers are immutable except one terminal transition'); END;

CREATE TRIGGER wagers_no_delete BEFORE DELETE ON wagers
BEGIN SELECT RAISE(ABORT, 'wagers are never deleted'); END;

-- Idempotency records (§9.7): unique per (actor, operation_id); only committed effects are stored.
CREATE TABLE operations (
    actor_user_id  TEXT NOT NULL REFERENCES users(user_id),
    operation_id   TEXT NOT NULL CHECK (length(operation_id) = 36),
    op_type        TEXT NOT NULL,
    request_hash   TEXT NOT NULL CHECK (length(request_hash) = 64),
    http_status    INTEGER NOT NULL,
    resource_type  TEXT,
    resource_id    TEXT,
    response_json  TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    PRIMARY KEY (actor_user_id, operation_id)
) STRICT;

CREATE TRIGGER operations_no_update BEFORE UPDATE ON operations
BEGIN SELECT RAISE(ABORT, 'operation records are kept for the life of the database'); END;
CREATE TRIGGER operations_no_delete BEFORE DELETE ON operations
BEGIN SELECT RAISE(ABORT, 'operation records are kept for the life of the database'); END;

-- Durable domain events / outbox (§9.9). Written in the same transaction as the mutation.
CREATE TABLE events (
    event_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    stream_id         TEXT NOT NULL REFERENCES streams(stream_id),
    run_id            TEXT NOT NULL REFERENCES runs(run_id),
    aggregate_type    TEXT NOT NULL CHECK (aggregate_type IN ('STREAM', 'MARKET', 'WAGER', 'WALLET', 'SOURCE', 'RAFFLE', 'CALL')),
    aggregate_id      TEXT NOT NULL,
    aggregate_version INTEGER NOT NULL CHECK (aggregate_version >= 1),
    event_type        TEXT NOT NULL,
    audience          TEXT NOT NULL CHECK (audience IN ('PUBLIC', 'USER', 'OPERATOR')),
    audience_user_id  TEXT REFERENCES users(user_id),
    occurred_at_utc   TEXT NOT NULL,
    payload_json      TEXT NOT NULL,
    CHECK ((audience = 'USER') = (audience_user_id IS NOT NULL))
) STRICT;
-- Exactly one event per aggregate version within a run: a forgotten version bump fails loudly.
-- (WALLET aggregate_id is the user_id and its balance_version restarts at 1 in each run.)
CREATE UNIQUE INDEX events_one_per_aggregate_version ON events(run_id, aggregate_type, aggregate_id, aggregate_version);

CREATE TRIGGER events_no_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
CREATE TRIGGER events_no_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;

-- WebSocket tickets: fzw_ token stored hashed, 30 s, single use by conditional update.
CREATE TABLE ws_tickets (
    ticket_hash    TEXT PRIMARY KEY CHECK (length(ticket_hash) = 64),
    user_id        TEXT NOT NULL REFERENCES users(user_id),
    session_id     TEXT NOT NULL REFERENCES sessions(session_id),
    stream_id      TEXT NOT NULL REFERENCES streams(stream_id),
    created_at_utc TEXT NOT NULL,
    expires_at_utc TEXT NOT NULL,
    used_at_utc    TEXT
) STRICT;

CREATE TRIGGER ws_tickets_single_use BEFORE UPDATE ON ws_tickets
WHEN OLD.used_at_utc IS NOT NULL OR NEW.used_at_utc IS NULL
  OR NEW.ticket_hash IS NOT OLD.ticket_hash OR NEW.user_id IS NOT OLD.user_id
  OR NEW.session_id IS NOT OLD.session_id OR NEW.stream_id IS NOT OLD.stream_id
  OR NEW.expires_at_utc IS NOT OLD.expires_at_utc
BEGIN SELECT RAISE(ABORT, 'ws tickets are single use'); END;

-- Operator audit trail (§9.8): one row per committed operator mutation or CLI bootstrap.
CREATE TABLE audit_log (
    audit_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_user_id  TEXT REFERENCES users(user_id),
    actor_kind     TEXT NOT NULL CHECK (actor_kind IN ('OPERATOR', 'CLI', 'SYSTEM')),
    action         TEXT NOT NULL,
    operation_id   TEXT,
    target_type    TEXT,
    target_id      TEXT,
    detail_json    TEXT NOT NULL DEFAULT '{}',
    created_at_utc TEXT NOT NULL,
    CHECK ((actor_kind = 'OPERATOR') = (actor_user_id IS NOT NULL))
) STRICT;

CREATE TRIGGER audit_log_no_update BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
CREATE TRIGGER audit_log_no_delete BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
