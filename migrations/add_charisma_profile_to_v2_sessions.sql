-- Store the Charisma Awareness Dashboard payload as a single
-- JSONB blob on the session row. Computed once during
-- session-publish + admin compute-metrics, read straight
-- off the row by the BFF /results endpoints. NULL until
-- the session has been finalized — the frontend treats
-- NULL as "hide the dashboard section entirely."
--
-- Why one column, not a sibling table:
--   - The blob is always written/read together (atomic update
--     during finalize; one column read in the BFF).
--   - No join needed; no per-block invalidation; no per-block
--     indexing requirement.
--   - Schema lives in services/charisma_profile.py — Postgres
--     just holds the bytes.
--
-- Run in Supabase SQL Editor. Idempotent.

DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'v2_sessions'
      AND column_name = 'charisma_profile'
  ) THEN
    ALTER TABLE v2_sessions
      ADD COLUMN charisma_profile JSONB DEFAULT NULL;
  END IF;
END $$;

COMMENT ON COLUMN v2_sessions.charisma_profile IS
  'Charisma Awareness Dashboard payload for the /results page. '
  'Shape: { archetype, narrative, acoustics{}, trinity{}, triggers{}, recommendation{} }. '
  'See services/charisma_profile.py for the contract. '
  'Written by compute_and_persist_charisma_profile() at session-publish + admin compute-metrics. '
  'NULL until first compute — frontend hides the dashboard when NULL.';
