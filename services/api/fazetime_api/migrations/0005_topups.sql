-- P6 Stripe TEST-mode top-ups (CONTRACTS §9.18). Applied once by fazetime_api.db.migrate(); never edit after it ships.
-- Only provider object references are stored: no payment-instrument data, no raw webhook bodies (payload hashes only).
-- Money never moves here: a credit is one ledger_transactions row (reason STRIPE_TEST_TOPUP,
-- source_key 'stripe_topup:<topup_id>', already UNIQUE) posted in the top-up's own run.

CREATE TABLE topups (
    topup_id                 TEXT PRIMARY KEY CHECK (length(topup_id) = 36 AND substr(topup_id, 1, 4) = 'top_'),
    user_id                  TEXT NOT NULL REFERENCES users(user_id),
    run_id                   TEXT NOT NULL REFERENCES runs(run_id),
    operation_id             TEXT NOT NULL CHECK (length(operation_id) = 36),
    request_hash             TEXT NOT NULL CHECK (length(request_hash) = 64),
    amount_minor             INTEGER NOT NULL CHECK (amount_minor BETWEEN 500 AND 10000 AND amount_minor % 100 = 0),
    currency                 TEXT NOT NULL CHECK (currency = 'usd'),
    status                   TEXT NOT NULL CHECK (status IN ('CREATED', 'PENDING', 'CREDITED', 'FAILED', 'EXPIRED')),
    stripe_idempotency_key   TEXT NOT NULL UNIQUE CHECK (length(stripe_idempotency_key) BETWEEN 8 AND 255),
    stripe_request_sha256    TEXT NOT NULL CHECK (length(stripe_request_sha256) = 64),
    stripe_session_id        TEXT UNIQUE CHECK (stripe_session_id IS NULL OR substr(stripe_session_id, 1, 8) = 'cs_test_'),
    stripe_payment_intent_id TEXT UNIQUE CHECK (stripe_payment_intent_id IS NULL OR substr(stripe_payment_intent_id, 1, 3) = 'pi_'),
    checkout_url             TEXT CHECK (checkout_url IS NULL OR substr(checkout_url, 1, 8) = 'https://'),
    checkout_expires_at_utc  TEXT,
    credited_txn_id          TEXT UNIQUE REFERENCES ledger_transactions(txn_id),
    review_reason            TEXT,
    created_at_utc           TEXT NOT NULL,
    updated_at_utc           TEXT NOT NULL,
    terminal_at_utc          TEXT,
    UNIQUE (user_id, operation_id),
    CHECK ((status = 'CREDITED') = (credited_txn_id IS NOT NULL)),
    CHECK (status NOT IN ('PENDING', 'CREDITED', 'EXPIRED') OR stripe_session_id IS NOT NULL),
    CHECK ((status IN ('CREDITED', 'FAILED', 'EXPIRED')) = (terminal_at_utc IS NOT NULL))
) STRICT;
CREATE INDEX topups_user_run ON topups(user_id, run_id, status);

-- Forward-only: identity, amount, keys and bound provider references never change; terminal states are final.
CREATE TRIGGER topups_forward_only BEFORE UPDATE ON topups
WHEN NEW.topup_id IS NOT OLD.topup_id OR NEW.user_id IS NOT OLD.user_id OR NEW.run_id IS NOT OLD.run_id
  OR NEW.operation_id IS NOT OLD.operation_id OR NEW.request_hash IS NOT OLD.request_hash
  OR NEW.amount_minor IS NOT OLD.amount_minor OR NEW.currency IS NOT OLD.currency
  OR NEW.stripe_idempotency_key IS NOT OLD.stripe_idempotency_key
  OR NEW.stripe_request_sha256 IS NOT OLD.stripe_request_sha256
  OR NEW.created_at_utc IS NOT OLD.created_at_utc
  OR (OLD.stripe_session_id IS NOT NULL AND NEW.stripe_session_id IS NOT OLD.stripe_session_id)
  OR (OLD.stripe_payment_intent_id IS NOT NULL AND NEW.stripe_payment_intent_id IS NOT OLD.stripe_payment_intent_id)
  OR (OLD.credited_txn_id IS NOT NULL AND NEW.credited_txn_id IS NOT OLD.credited_txn_id)
  OR (OLD.review_reason IS NOT NULL AND NEW.review_reason IS NOT OLD.review_reason)
  OR (OLD.status IN ('CREDITED', 'FAILED', 'EXPIRED') AND NEW.status IS NOT OLD.status)
  OR (OLD.status = 'PENDING' AND NEW.status = 'CREATED')
BEGIN SELECT RAISE(ABORT, 'top-ups only move forward; identity, amount and provider references are immutable'); END;

-- A credit must be this top-up's own STRIPE_TEST_TOPUP transaction, in the top-up's own run (CONTRACTS §9.5).
CREATE TRIGGER topups_credit_matches_ledger BEFORE UPDATE OF credited_txn_id ON topups
WHEN NEW.credited_txn_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM ledger_transactions t
    WHERE t.txn_id = NEW.credited_txn_id AND t.reason = 'STRIPE_TEST_TOPUP'
      AND t.source_key = 'stripe_topup:' || NEW.topup_id AND t.run_id = NEW.run_id)
BEGIN SELECT RAISE(ABORT, 'credited_txn_id must be this top-up''s STRIPE_TEST_TOPUP transaction in its own run'); END;

CREATE TRIGGER topups_no_delete BEFORE DELETE ON topups
BEGIN SELECT RAISE(ABORT, 'top-ups are never deleted'); END;

-- One processing per provider event delivery, across retries and restarts.
CREATE TABLE provider_receipts (
    provider        TEXT NOT NULL CHECK (provider = 'stripe'),
    event_id        TEXT NOT NULL CHECK (length(event_id) BETWEEN 5 AND 255 AND substr(event_id, 1, 4) = 'evt_'),
    event_type      TEXT NOT NULL CHECK (length(event_type) BETWEEN 1 AND 128),
    livemode        INTEGER NOT NULL CHECK (livemode = 0),
    object_id       TEXT,
    topup_id        TEXT REFERENCES topups(topup_id),
    outcome         TEXT NOT NULL CHECK (outcome IN ('CREDIT', 'NOOP_DUPLICATE', 'MISMATCH_REVIEW', 'IGNORE',
                                                     'MARK_FAILED', 'MARK_EXPIRED')),
    reason          TEXT NOT NULL CHECK (length(reason) BETWEEN 1 AND 64),
    payload_sha256  TEXT NOT NULL CHECK (length(payload_sha256) = 64),
    stripe_created  INTEGER NOT NULL CHECK (stripe_created >= 0),
    received_at_utc TEXT NOT NULL,
    PRIMARY KEY (provider, event_id)
) STRICT;
CREATE INDEX provider_receipts_topup ON provider_receipts(topup_id);

CREATE TRIGGER provider_receipts_no_update BEFORE UPDATE ON provider_receipts
BEGIN SELECT RAISE(ABORT, 'provider receipts are append-only'); END;
CREATE TRIGGER provider_receipts_no_delete BEFORE DELETE ON provider_receipts
BEGIN SELECT RAISE(ABORT, 'provider receipts are append-only'); END;
