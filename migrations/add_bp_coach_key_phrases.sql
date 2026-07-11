-- willab — coach-corrected key phrases on the ideal text (Engine 2,
-- founder 2026-07-11). The auto-derived phrases (from the winning pick's
-- Say-It-Stronger upgrades) pre-fill the coach's per-slide editor; the
-- coach's edited set persists here and overrides the auto set on every
-- read once saved. NULL = coach hasn't touched them (auto set serves).
--
-- Shape: JSONB array of short strings (≤5 phrases, ≤60 chars each —
-- validated at the route). Nullable + additive; writers degrade
-- gracefully pre-migration. Idempotent — safe to re-run.

ALTER TABLE coach_best_presentation_edits
    ADD COLUMN IF NOT EXISTS key_phrases JSONB NULL;

-- Rollback (manual):
--   ALTER TABLE coach_best_presentation_edits DROP COLUMN IF EXISTS key_phrases;
