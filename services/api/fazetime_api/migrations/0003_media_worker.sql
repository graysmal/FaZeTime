-- P3 media-worker contract (CONTRACTS §9.16). Worker data is untrusted input: it can change source health
-- (and therefore void Twitch-origin markets under §9.4) but it never touches balances or settles anything.

-- fzk_ tokens for MEDIA_WORKER (CALL_WORKER reserved), stored as SHA-256 only. Issued by the CLI.
CREATE TABLE worker_credentials (
    credential_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash     TEXT NOT NULL UNIQUE CHECK (length(token_hash) = 64),
    role           TEXT NOT NULL CHECK (role IN ('MEDIA_WORKER', 'CALL_WORKER')),
    label          TEXT NOT NULL CHECK (length(label) BETWEEN 1 AND 64),
    created_at_utc TEXT NOT NULL,
    revoked_at_utc TEXT
) STRICT;

CREATE TRIGGER worker_credentials_only_revocation BEFORE UPDATE ON worker_credentials
WHEN OLD.revoked_at_utc IS NOT NULL OR NEW.token_hash IS NOT OLD.token_hash OR NEW.role IS NOT OLD.role
  OR NEW.credential_id IS NOT OLD.credential_id
BEGIN SELECT RAISE(ABORT, 'worker credentials can only be revoked once'); END;

-- Source epochs: a new ID on ingest restart, discontinuity recovery or adapter switch.
CREATE TABLE source_epochs (
    source_epoch      TEXT PRIMARY KEY CHECK (length(source_epoch) = 35 AND substr(source_epoch, 1, 3) = 'ep_'),
    stream_id         TEXT NOT NULL REFERENCES streams(stream_id),
    source_kind       TEXT NOT NULL CHECK (source_kind IN ('TWITCH_STREAMLINK', 'TWITCH_TAB_CAPTURE', 'TEST_FIXTURE')),
    reason            TEXT NOT NULL CHECK (reason IN ('PROCESS_START', 'PROCESS_RESTART', 'PTS_DISCONTINUITY',
                                                      'AFTER_GAP', 'ADAPTER_SWITCH')),
    variant           TEXT,
    host_id           TEXT NOT NULL CHECK (length(host_id) BETWEEN 1 AND 64),
    started_at_utc    TEXT NOT NULL,
    registered_at_utc TEXT NOT NULL,
    superseded_at_utc TEXT,
    gap_reported_at_utc TEXT,
    credential_id     INTEGER REFERENCES worker_credentials(credential_id)
) STRICT;
CREATE INDEX source_epochs_stream ON source_epochs(stream_id, registered_at_utc);
CREATE UNIQUE INDEX source_epochs_one_current ON source_epochs(stream_id) WHERE superseded_at_utc IS NULL;

-- Latest worker heartbeat and derived-health bookkeeping, one row per stream.
CREATE TABLE source_state (
    stream_id                  TEXT PRIMARY KEY REFERENCES streams(stream_id),
    current_source_epoch       TEXT REFERENCES source_epochs(source_epoch),
    last_heartbeat_at_utc      TEXT,
    worker_state               TEXT CHECK (worker_state IN ('CONNECTING', 'LIVE', 'GAP', 'STALE', 'STOPPED')),
    heartbeat_epoch            TEXT,
    last_media_end_ms          INTEGER CHECK (last_media_end_ms IS NULL OR last_media_end_ms >= 0),
    last_media_advanced_at_utc TEXT,
    last_transcript_at_utc     TEXT,
    last_input_age_ms          INTEGER,
    asr_backlog_ms             INTEGER,
    queue_depth                INTEGER,
    gap_threshold_ms           INTEGER,
    host_id                    TEXT,
    host_wall_utc              TEXT,
    emitted_state              TEXT,
    emitted_epoch              TEXT,
    health_version             INTEGER NOT NULL DEFAULT 0 CHECK (health_version >= 0),
    state_changed_at_utc       TEXT
) STRICT;

-- Frames. Files live in the bounded evidence directory; paths are derived from server IDs only.
CREATE TABLE evidence (
    evidence_id         TEXT PRIMARY KEY CHECK (length(evidence_id) = 36 AND substr(evidence_id, 1, 4) = 'evd_'),
    stream_id           TEXT NOT NULL REFERENCES streams(stream_id),
    source_epoch        TEXT NOT NULL REFERENCES source_epochs(source_epoch),
    sequence            INTEGER NOT NULL CHECK (sequence >= 1),
    kind                TEXT NOT NULL CHECK (kind = 'FRAME'),
    media_ms            INTEGER NOT NULL CHECK (media_ms >= 0),
    width               INTEGER NOT NULL CHECK (width BETWEEN 1 AND 8192),
    height              INTEGER NOT NULL CHECK (height BETWEEN 1 AND 8192),
    sha256              TEXT NOT NULL CHECK (length(sha256) = 64),
    byte_size           INTEGER NOT NULL CHECK (byte_size BETWEEN 1 AND 307200),
    received_at_utc     TEXT NOT NULL,
    pinned_by_market_id TEXT REFERENCES markets(market_id),
    file_pruned_at_utc  TEXT,
    UNIQUE (source_epoch, sequence)
) STRICT;
CREATE INDEX evidence_received ON evidence(received_at_utc);

-- Observations: dedupe key (source_epoch, sequence). Transcript text is stored verbatim, never interpreted.
CREATE TABLE observations (
    source_epoch         TEXT NOT NULL REFERENCES source_epochs(source_epoch),
    sequence             INTEGER NOT NULL CHECK (sequence >= 1),
    stream_id            TEXT NOT NULL REFERENCES streams(stream_id),
    kind                 TEXT NOT NULL CHECK (kind IN ('TRANSCRIPT', 'FRAME', 'GAP')),
    media_start_ms       INTEGER NOT NULL CHECK (media_start_ms >= 0),
    media_end_ms         INTEGER NOT NULL CHECK (media_end_ms >= media_start_ms),
    captured_at_utc      TEXT NOT NULL,
    received_at_utc      TEXT NOT NULL,
    quality_flags_json   TEXT NOT NULL DEFAULT '[]',
    transcript_json      TEXT,
    evidence_id          TEXT REFERENCES evidence(evidence_id),
    gap_reason           TEXT,
    PRIMARY KEY (source_epoch, sequence),
    CHECK (kind <> 'FRAME' OR (evidence_id IS NOT NULL AND media_start_ms = media_end_ms)),
    CHECK (kind <> 'TRANSCRIPT' OR transcript_json IS NOT NULL),
    CHECK (kind <> 'GAP' OR gap_reason IS NOT NULL)
) STRICT;
CREATE INDEX observations_received ON observations(received_at_utc);

CREATE TRIGGER observations_append_only_u BEFORE UPDATE ON observations
BEGIN SELECT RAISE(ABORT, 'observations are append-only'); END;
