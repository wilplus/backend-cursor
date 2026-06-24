-- willab monetization re-lock (2026) — charge 5 credits ON COACH-FEEDBACK
-- DELIVERY (publish), idempotently, once per session.
--
-- Every user starts with 15 credits (v2_ensure_credits_initialized, grant=15)
-- = 3 free coach feedbacks at 5 each. The charge moves OFF send (the old
-- lab_credits_charged_at / 1-per-send path) ONTO publish: when the coach's
-- insights are delivered to the user, db.v2_charge_feedback_credits_once stamps
-- this column when NULL, then deducts 5 (soft — floors at 0, never withholds
-- the coach's work). A re-publish / re-view never re-charges.
--
-- Nullable + additive; the charge degrades to a no-op if this column is missing
-- (recording/publish never blocked). Idempotent — safe to re-run.

ALTER TABLE public.v2_sessions
    ADD COLUMN IF NOT EXISTS feedback_credits_charged_at TIMESTAMPTZ NULL;

-- Rollback (manual):
--   ALTER TABLE public.v2_sessions DROP COLUMN IF EXISTS feedback_credits_charged_at;
