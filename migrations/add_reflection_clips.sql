-- Reflection Game (F2 handoff §1, 2026-08-03).
-- One row per clip offered to a user: a shadow-flagged "possibly
-- confident" moment OR a duration-matched decoy (machine_flagged FALSE)
-- from the same user's takes. machine_flagged is SERVER-SIDE ONLY —
-- no route may ever serialize it or any model confidence (the
-- no-decoy-leak fence). user_vote ('best'|'not_this') and the blind
-- coach_verdict ('confident'|'not_confident') complete the three-way
-- agreement matrix, logged off-surface. coach_verdict='confident' rows
-- ARE the cross-project Confident Voices library (decoys eligible).
-- Idempotent; degrades gracefully — the game endpoints serve empty
-- until this runs.

CREATE TABLE IF NOT EXISTS reflection_clips (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  snippet_id UUID NOT NULL,
  take_session_id UUID,
  arc_id UUID,
  machine_flagged BOOLEAN NOT NULL DEFAULT FALSE,
  recording_kind TEXT,
  named_emotion TEXT,
  topic TEXT,
  start_offset_ms INT,
  duration_ms INT,
  transcript TEXT,
  served_at TIMESTAMPTZ,
  user_vote TEXT CHECK (user_vote IN ('best', 'not_this')),
  voted_at TIMESTAMPTZ,
  coach_verdict TEXT CHECK (coach_verdict IN ('confident', 'not_confident')),
  verified_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, snippet_id)
);

CREATE INDEX IF NOT EXISTS idx_reflection_clips_user
  ON reflection_clips (user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_reflection_clips_coach_pending
  ON reflection_clips (voted_at)
  WHERE user_vote IS NOT NULL AND coach_verdict IS NULL;
CREATE INDEX IF NOT EXISTS idx_reflection_clips_library
  ON reflection_clips (user_id, verified_at)
  WHERE coach_verdict = 'confident';

ALTER TABLE reflection_clips ENABLE ROW LEVEL SECURITY;
GRANT ALL ON reflection_clips TO service_role;
