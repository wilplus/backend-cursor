-- willab — Explore-Session Multi-Take (Prompt A §3). Session-declared arc that
-- links the 3 (optional 4th) takes of the SAME talk so they're comparable.
-- Standalone recordings leave both NULL. Additive + idempotent.
ALTER TABLE v2_sessions
    ADD COLUMN IF NOT EXISTS arc_id UUID,
    ADD COLUMN IF NOT EXISTS take_index INTEGER;

CREATE INDEX IF NOT EXISTS idx_v2_sessions_arc ON v2_sessions (arc_id);
