-- Per-take coach "Save" checkpoint (founder 2026-07-15) — the coach saves
-- each recording's corrections and moves to the next; NOTHING is delivered
-- until the single "Save and Publish full analysis". The publish requires
-- all 3 spoken takes saved. Idempotent.

ALTER TABLE public.v2_sessions
    ADD COLUMN IF NOT EXISTS coach_feedback_saved_at TIMESTAMPTZ;
