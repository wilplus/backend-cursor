-- Cleanup migration after backend/frontend use v2_sessions.score everywhere.
-- Safe to run multiple times.

ALTER TABLE IF EXISTS v2_sessions
  DROP COLUMN IF EXISTS performance_score_1,
  DROP COLUMN IF EXISTS performance_score_2,
  DROP COLUMN IF EXISTS performance_score_end;
