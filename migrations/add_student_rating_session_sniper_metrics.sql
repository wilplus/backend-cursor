-- Add student rating (1–10) to session_sniper_metrics for baseline-update logic.
-- Only sessions with student_rating_1_10 >= 8 (or coach grade >= 8) update the Sniper baseline.
-- Run after add_user_sniper_profile.sql (session_sniper_metrics exists).

ALTER TABLE session_sniper_metrics
  ADD COLUMN IF NOT EXISTS student_rating_1_10 SMALLINT NULL
    CHECK (student_rating_1_10 IS NULL OR (student_rating_1_10 >= 1 AND student_rating_1_10 <= 10));

COMMENT ON COLUMN session_sniper_metrics.student_rating_1_10 IS 'Student self-rating 1–10 (how did that feel?). Used to decide if this session updates user_sniper_profile baseline (only when >= 8).';
