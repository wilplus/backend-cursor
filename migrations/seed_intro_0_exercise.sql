-- Seed default exercise "intro-0" for step 0 when no exercise is assigned.
-- Backend uses this by title when assigned_next_exercise_id/last_assigned_exercise_id are not set.
-- So the step 0 screen shows a video (not just "intro-0" text), do one of:
--   1. Set video_url and description in Admin → Exercises (edit "intro-0"), or
--   2. Set INTRO_0_VIDEO_URL and optionally INTRO_0_DESCRIPTION in .env (used when DB has NULL).
-- Idempotent: only inserts if no row with title 'intro-0' exists.

INSERT INTO v2_exercises (title, video_url, description, is_active)
SELECT 'intro-0', NULL, NULL, true
WHERE NOT EXISTS (SELECT 1 FROM v2_exercises WHERE title ILIKE 'intro-0');
