-- D37 generic AI market template GENERIC_BINARY_V1 (CONTRACTS §9.19 item 3). Applied once; never edit after it ships.
-- Additive only: H2H_WINNER_V1 rows keep generic_json NULL. No money or market state lives here.
-- generic_json is the validated {spec_version, kind, unit, params, episode_start_media_ms, success_cue, failure_cue}
-- object exactly as accepted at submit. The cues are untrusted model text: stored inert, never sent to viewers.

ALTER TABLE ai_candidates ADD COLUMN generic_json TEXT
    CHECK (generic_json IS NULL OR (json_valid(generic_json) AND length(generic_json) <= 4096));

-- A GENERIC_BINARY_V1 candidate always carries its generic object; every other template never does.
CREATE TRIGGER ai_candidates_generic_matches_template BEFORE INSERT ON ai_candidates
WHEN (NEW.template_id = 'GENERIC_BINARY_V1') <> (NEW.generic_json IS NOT NULL)
BEGIN SELECT RAISE(ABORT, 'generic_json is required for GENERIC_BINARY_V1 and forbidden for other templates'); END;

-- The template and its generic terms are candidate content: immutable, like the columns 0004 already freezes.
CREATE TRIGGER ai_candidates_template_terms_frozen BEFORE UPDATE ON ai_candidates
WHEN NEW.template_id IS NOT OLD.template_id OR NEW.generic_json IS NOT OLD.generic_json
BEGIN SELECT RAISE(ABORT, 'AI candidate template terms are immutable'); END;
