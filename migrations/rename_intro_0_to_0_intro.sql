-- Rename existing exercise title from 'intro-0' to '0-intro' so it matches backend/config.
-- Run once if you previously ran seed_intro_0_exercise.sql with the old title. Idempotent.

UPDATE v2_exercises
SET title = '0-intro'
WHERE title ILIKE 'intro-0'
  AND (SELECT COUNT(*) FROM v2_exercises WHERE title ILIKE '0-intro') = 0;
