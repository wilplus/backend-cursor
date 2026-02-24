-- Seed default exercise "0-intro" for step 0 when no exercise is assigned.
-- Backend uses this by title when assigned_next_exercise_id/last_assigned_exercise_id are not set.
-- So the step 0 screen shows a video (not just "0-intro" text), do one of:
--   1. Set video_url and description in Admin → Exercises (edit "0-intro"), or
--   2. Set INTRO_0_VIDEO_URL and optionally INTRO_0_DESCRIPTION in .env (used when DB has NULL).
-- Idempotent: only inserts if no row with title '0-intro' exists.

INSERT INTO v2_exercises (title, video_url, description, is_active)
SELECT '0-intro', NULL, NULL, true
WHERE NOT EXISTS (SELECT 1 FROM v2_exercises WHERE title ILIKE '0-intro');
