-- P4/P5 AI proposals, operator approval and resolutions (CONTRACTS §9.17, D32). Applied once; never edit after it ships.
-- Model output is untrusted data. These rows record what a model proposed and what the backend decided.
-- They never move money: opening, settling and voiding go through the domain functions (BEGIN IMMEDIATE),
-- exactly like operator fixture markets. No prompts, keys or other secrets are stored anywhere here.

-- AI market terms, frozen at OPEN (criteria are side-keyed, §9.3). NULL for fixture markets.
ALTER TABLE markets ADD COLUMN candidate_cnd_id TEXT;          -- cnd_ of the AI candidate that opened the market
ALTER TABLE markets ADD COLUMN criteria_json TEXT;             -- {"YES": predicate, "NO": predicate}
ALTER TABLE markets ADD COLUMN cancellation_json TEXT;         -- cancellation conditions (JSON list of strings)
ALTER TABLE markets ADD COLUMN opening_evidence_json TEXT;     -- resolved evidence refs cited by the candidate
-- Resolution applied with the terminal transition (AI resolution approval or AUTOMATIC mode). NULL otherwise.
ALTER TABLE markets ADD COLUMN resolution_rsl_id TEXT;
ALTER TABLE markets ADD COLUMN resolution_evidence_json TEXT;
ALTER TABLE markets ADD COLUMN resolution_mode TEXT
    CHECK (resolution_mode IS NULL OR resolution_mode IN ('AUTOMATIC', 'OPERATOR_APPROVED'));
ALTER TABLE markets ADD COLUMN resolution_reason TEXT
    CHECK (resolution_reason IS NULL OR length(resolution_reason) <= 300);

CREATE TRIGGER markets_ai_terms_frozen BEFORE UPDATE ON markets
WHEN OLD.state <> 'DRAFT' AND (
       NEW.candidate_cnd_id IS NOT OLD.candidate_cnd_id OR NEW.criteria_json IS NOT OLD.criteria_json
    OR NEW.cancellation_json IS NOT OLD.cancellation_json OR NEW.opening_evidence_json IS NOT OLD.opening_evidence_json)
BEGIN SELECT RAISE(ABORT, 'AI market terms are frozen after OPEN'); END;

CREATE TRIGGER markets_resolution_with_terminal BEFORE UPDATE ON markets
WHEN (NEW.resolution_rsl_id IS NOT OLD.resolution_rsl_id OR NEW.resolution_mode IS NOT OLD.resolution_mode
      OR NEW.resolution_reason IS NOT OLD.resolution_reason
      OR NEW.resolution_evidence_json IS NOT OLD.resolution_evidence_json)
  AND NEW.state NOT IN ('SETTLED', 'VOID')
BEGIN SELECT RAISE(ABORT, 'resolution fields are written only with the terminal transition'); END;

CREATE UNIQUE INDEX markets_one_per_candidate ON markets(candidate_cnd_id) WHERE candidate_cnd_id IS NOT NULL;

-- Candidates (POST /v1/worker/proposals). Idempotent on the client candidate_id (UUID).
-- Statuses: PENDING (APPROVAL mode), SHADOW (stored, never opened), OPENED, REJECTED (validation reject code, or
-- OPERATOR_REJECTED), EXPIRED (PENDING for more than candidate_expiry_s after receipt).
CREATE TABLE ai_candidates (
    cnd_id                 TEXT PRIMARY KEY CHECK (length(cnd_id) = 36 AND substr(cnd_id, 1, 4) = 'cnd_'),
    candidate_id           TEXT NOT NULL UNIQUE CHECK (length(candidate_id) = 36),
    request_hash           TEXT NOT NULL CHECK (length(request_hash) = 64),
    stream_id              TEXT NOT NULL REFERENCES streams(stream_id),
    run_id                 TEXT NOT NULL REFERENCES runs(run_id),
    source_epoch           TEXT NOT NULL,                 -- as submitted (may be stale: then REJECTED STALE_EPOCH)
    template_id            TEXT NOT NULL,
    episode_fingerprint    TEXT NOT NULL,                 -- canonical: lowercased, h2h subject pair sorted
    raw_fingerprint        TEXT NOT NULL,
    question               TEXT NOT NULL CHECK (length(question) BETWEEN 1 AND 200),
    yes_label              TEXT NOT NULL CHECK (length(yes_label) BETWEEN 1 AND 40),
    yes_predicate          TEXT NOT NULL,
    no_label               TEXT NOT NULL CHECK (length(no_label) BETWEEN 1 AND 40),
    no_predicate           TEXT NOT NULL,
    subjects_json          TEXT NOT NULL,
    evidence_ids_json      TEXT NOT NULL,                 -- refs exactly as submitted
    evidence_json          TEXT NOT NULL DEFAULT '[]',    -- refs resolved at receipt (kind, media positions, receipt)
    announced_at_media_ms  INTEGER NOT NULL CHECK (announced_at_media_ms >= 0),
    suggested_close_in_s   INTEGER NOT NULL,
    suggested_resolve_in_s INTEGER NOT NULL,
    close_in_s             INTEGER,                       -- after clamping; NULL if rejected before clamping
    resolve_in_s           INTEGER,
    cancellation_json      TEXT NOT NULL,
    rationale              TEXT NOT NULL CHECK (length(rationale) <= 300),  -- untrusted, stored verbatim, inert
    model                  TEXT NOT NULL,
    prompt_version         TEXT NOT NULL,
    ai_mode                TEXT NOT NULL,                 -- effective mode when received
    status                 TEXT NOT NULL CHECK (status IN ('PENDING', 'SHADOW', 'OPENED', 'REJECTED', 'EXPIRED')),
    reject_code            TEXT,
    market_id              TEXT REFERENCES markets(market_id),
    received_at_utc        TEXT NOT NULL,
    expires_at_utc         TEXT NOT NULL,
    decided_at_utc         TEXT,
    decided_by_user_id     TEXT REFERENCES users(user_id),
    decision_note          TEXT CHECK (decision_note IS NULL OR length(decision_note) <= 200),
    CHECK ((status = 'REJECTED') = (reject_code IS NOT NULL)),
    CHECK ((status = 'OPENED') = (market_id IS NOT NULL))
) STRICT;
CREATE INDEX ai_candidates_run ON ai_candidates(run_id, received_at_utc);
-- An episode is used once per run: stored/opened/expired candidates and operator rejections burn the fingerprint.
-- Validation rejections (stale epoch, busy market, ...) do not, so a later, valid proposal can still be made.
CREATE UNIQUE INDEX ai_candidates_one_episode ON ai_candidates(run_id, episode_fingerprint)
    WHERE status IN ('PENDING', 'SHADOW', 'OPENED', 'EXPIRED') OR reject_code = 'OPERATOR_REJECTED';
CREATE UNIQUE INDEX ai_candidates_one_market ON ai_candidates(market_id) WHERE market_id IS NOT NULL;

CREATE TRIGGER ai_candidates_transition BEFORE UPDATE ON ai_candidates
WHEN OLD.status <> 'PENDING' OR NEW.status NOT IN ('OPENED', 'REJECTED', 'EXPIRED')
  OR NEW.cnd_id IS NOT OLD.cnd_id OR NEW.candidate_id IS NOT OLD.candidate_id
  OR NEW.request_hash IS NOT OLD.request_hash OR NEW.run_id IS NOT OLD.run_id
  OR NEW.episode_fingerprint IS NOT OLD.episode_fingerprint OR NEW.question IS NOT OLD.question
  OR NEW.yes_label IS NOT OLD.yes_label OR NEW.no_label IS NOT OLD.no_label
  OR NEW.yes_predicate IS NOT OLD.yes_predicate OR NEW.no_predicate IS NOT OLD.no_predicate
  OR NEW.evidence_ids_json IS NOT OLD.evidence_ids_json OR NEW.rationale IS NOT OLD.rationale
  OR NEW.model IS NOT OLD.model OR NEW.prompt_version IS NOT OLD.prompt_version
  OR NEW.received_at_utc IS NOT OLD.received_at_utc OR NEW.expires_at_utc IS NOT OLD.expires_at_utc
BEGIN SELECT RAISE(ABORT, 'AI candidates only move PENDING -> OPENED/REJECTED/EXPIRED; their content is immutable'); END;

CREATE TRIGGER ai_candidates_no_delete BEFORE DELETE ON ai_candidates
BEGIN SELECT RAISE(ABORT, 'AI candidates are never deleted'); END;

-- Resolutions (POST /v1/worker/resolutions). Idempotent on the client resolution_id (UUID).
-- market_id is stored as submitted without a foreign key: late or unknown-market resolutions are recorded as IGNORED.
CREATE TABLE ai_resolutions (
    rsl_id              TEXT PRIMARY KEY CHECK (length(rsl_id) = 36 AND substr(rsl_id, 1, 4) = 'rsl_'),
    resolution_id       TEXT NOT NULL UNIQUE CHECK (length(resolution_id) = 36),
    request_hash        TEXT NOT NULL CHECK (length(request_hash) = 64),
    stream_id           TEXT NOT NULL REFERENCES streams(stream_id),
    run_id              TEXT REFERENCES runs(run_id),        -- the market's run, when the market is known
    market_id           TEXT NOT NULL,
    rules_version       INTEGER NOT NULL,
    source_epoch        TEXT NOT NULL,
    decision            TEXT NOT NULL CHECK (decision IN ('YES', 'NO', 'WAIT', 'UNRESOLVABLE')),
    evidence_ids_json   TEXT NOT NULL,
    evidence_json       TEXT NOT NULL DEFAULT '[]',
    media_start_ms      INTEGER NOT NULL CHECK (media_start_ms >= 0),
    media_end_ms        INTEGER NOT NULL CHECK (media_end_ms >= media_start_ms),
    support_yes         INTEGER NOT NULL CHECK (support_yes IN (0, 1)),
    support_no          INTEGER NOT NULL CHECK (support_no IN (0, 1)),
    contradictions_json TEXT NOT NULL,
    reason              TEXT NOT NULL CHECK (length(reason) <= 300),  -- untrusted, stored verbatim, inert
    model               TEXT NOT NULL,
    prompt_version      TEXT NOT NULL,
    ai_mode             TEXT NOT NULL,
    status              TEXT NOT NULL CHECK (status IN ('RECORDED', 'SETTLED', 'VOIDED', 'PENDING_APPROVAL', 'IGNORED')),
    status_reason       TEXT,
    received_at_utc     TEXT NOT NULL,
    decided_at_utc      TEXT,
    decided_by_user_id  TEXT REFERENCES users(user_id)
) STRICT;
CREATE INDEX ai_resolutions_market ON ai_resolutions(market_id, received_at_utc);
-- At most one applied (SETTLED/VOIDED) resolution per market.
CREATE UNIQUE INDEX ai_resolutions_one_applied ON ai_resolutions(market_id) WHERE status IN ('SETTLED', 'VOIDED');

CREATE TRIGGER ai_resolutions_transition BEFORE UPDATE ON ai_resolutions
WHEN OLD.status <> 'PENDING_APPROVAL' OR NEW.status NOT IN ('SETTLED', 'VOIDED', 'IGNORED')
  OR NEW.rsl_id IS NOT OLD.rsl_id OR NEW.resolution_id IS NOT OLD.resolution_id
  OR NEW.request_hash IS NOT OLD.request_hash OR NEW.market_id IS NOT OLD.market_id
  OR NEW.decision IS NOT OLD.decision OR NEW.evidence_ids_json IS NOT OLD.evidence_ids_json
  OR NEW.reason IS NOT OLD.reason OR NEW.model IS NOT OLD.model OR NEW.prompt_version IS NOT OLD.prompt_version
  OR NEW.received_at_utc IS NOT OLD.received_at_utc
BEGIN SELECT RAISE(ABORT, 'AI resolutions only move PENDING_APPROVAL -> SETTLED/VOIDED/IGNORED; content is immutable'); END;

CREATE TRIGGER ai_resolutions_no_delete BEFORE DELETE ON ai_resolutions
BEGIN SELECT RAISE(ABORT, 'AI resolutions are never deleted'); END;

-- InferenceTrace (§9.17 item 6): one append-only row per model submission and per operator decision on it.
-- Model, prompt version, evidence refs and the backend's validation result. Never prompts, keys or tokens.
CREATE TABLE inference_traces (
    trace_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind              TEXT NOT NULL CHECK (kind IN ('PROPOSAL', 'PROPOSAL_DECISION', 'RESOLUTION', 'RESOLUTION_DECISION')),
    subject_id        TEXT NOT NULL,                  -- cnd_ or rsl_
    client_id         TEXT NOT NULL,                  -- candidate_id or resolution_id (client UUID)
    stream_id         TEXT NOT NULL REFERENCES streams(stream_id),
    run_id            TEXT REFERENCES runs(run_id),
    market_id         TEXT,
    source_epoch      TEXT NOT NULL,
    model             TEXT NOT NULL,
    prompt_version    TEXT NOT NULL,
    evidence_ids_json TEXT NOT NULL,
    ai_mode           TEXT NOT NULL,
    result            TEXT NOT NULL,                  -- the status the backend assigned
    code              TEXT,                           -- reject code / status reason, if any
    validation_json   TEXT NOT NULL DEFAULT '{}',
    actor_kind        TEXT NOT NULL CHECK (actor_kind IN ('WORKER', 'OPERATOR')),
    actor_ref         TEXT,                           -- worker credential_id or operator user_id
    created_at_utc    TEXT NOT NULL
) STRICT;
CREATE INDEX inference_traces_subject ON inference_traces(subject_id, trace_id);

CREATE TRIGGER inference_traces_no_update BEFORE UPDATE ON inference_traces
BEGIN SELECT RAISE(ABORT, 'inference traces are append-only'); END;
CREATE TRIGGER inference_traces_no_delete BEFORE DELETE ON inference_traces
BEGIN SELECT RAISE(ABORT, 'inference traces are append-only'); END;
