-- willab — coach-time-per-audit baseline (readiness rig #3).
--
-- First-touch stamp of when the coach OPENED a session for review (GET
-- /v2/coach/sessions/<id>). Coach active time ≈ results_published_at -
-- review_opened_at — the ROI baseline the AI draft must later BEAT before it's
-- shown to coaches (D18). Set-once (never overwritten). Additive; idempotent.
ALTER TABLE public.v2_sessions
    ADD COLUMN IF NOT EXISTS review_opened_at TIMESTAMPTZ NULL;

-- Rollback (manual):
--   ALTER TABLE public.v2_sessions DROP COLUMN IF EXISTS review_opened_at;
