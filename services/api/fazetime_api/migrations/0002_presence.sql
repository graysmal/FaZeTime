-- P2-C presence (PROJECT_PLAN P2, CONTRACTS §9.13 I). One row per (user, device, stream); tabs on the
-- same device update the same row. Presence is "the extension reports the channel open", not attention,
-- and it never affects balances or raffle weight. last_seen_utc is stamped by the server only.
CREATE TABLE presence (
    user_id                TEXT NOT NULL REFERENCES users(user_id),
    device_id              TEXT NOT NULL CHECK (length(device_id) = 36),
    stream_id              TEXT NOT NULL REFERENCES streams(stream_id),
    session_id             TEXT NOT NULL REFERENCES sessions(session_id),
    run_id                 TEXT NOT NULL REFERENCES runs(run_id),
    tab_instance_id        TEXT NOT NULL CHECK (length(tab_instance_id) = 36),
    observed_channel_login TEXT,
    page_visibility        TEXT NOT NULL CHECK (page_visibility IN ('VISIBLE', 'HIDDEN', 'UNKNOWN')),
    player_state           TEXT NOT NULL CHECK (player_state IN ('PLAYING', 'PAUSED', 'BUFFERING', 'UNKNOWN')),
    extension_version      TEXT NOT NULL CHECK (length(extension_version) BETWEEN 1 AND 32),
    first_seen_utc         TEXT NOT NULL,
    last_seen_utc          TEXT NOT NULL,
    heartbeat_count        INTEGER NOT NULL CHECK (heartbeat_count >= 1),
    PRIMARY KEY (user_id, device_id, stream_id)
) STRICT;
CREATE INDEX presence_stream_seen ON presence(stream_id, last_seen_utc);
