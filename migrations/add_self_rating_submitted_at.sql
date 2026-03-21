-- Marks that the user submitted self-rating (rating or skip), so completion
-- can continue in background when recording_1 processing finishes.
ALTER TABLE v2_sessions
  ADD COLUMN IF NOT EXISTS self_rating_submitted_at TIMESTAMPTZ;

COMMENT ON COLUMN v2_sessions.self_rating_submitted_at IS
  'Timestamp when POST self-rating was submitted (rating or skip). Used for background completion.';
