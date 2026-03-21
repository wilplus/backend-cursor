-- Admin-only ML review labels for completed sessions.
-- Keeps training labels separate from student-facing coach feedback.

CREATE TABLE IF NOT EXISTS recording_reviews (
  session_id UUID PRIMARY KEY REFERENCES v2_sessions(id) ON DELETE CASCADE,
  recording_id UUID NULL REFERENCES recordings(id) ON DELETE SET NULL,
  overall_quality NUMERIC NULL,
  confidence_score NUMERIC NULL,
  coach_style_score NUMERIC NULL,
  notes TEXT NULL,
  reviewer_id UUID NULL REFERENCES auth.users(id) ON DELETE SET NULL,
  rubric_version TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_recording_reviews_reviewer ON recording_reviews(reviewer_id);
CREATE INDEX IF NOT EXISTS idx_recording_reviews_updated_at ON recording_reviews(updated_at DESC);

COMMENT ON TABLE recording_reviews IS 'Admin-only ML ground-truth labels for a completed session. Separate from student-facing grades and feedback.';
COMMENT ON COLUMN recording_reviews.recording_id IS 'Optional linkage to the reviewed recording inside the session.';
COMMENT ON COLUMN recording_reviews.notes IS 'Internal reviewer notes. Must never be exposed to students.';
COMMENT ON COLUMN recording_reviews.rubric_version IS 'Version of the internal labeling rubric used when saving this review.';

CREATE TABLE IF NOT EXISTS recording_review_annotations (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  session_id UUID NOT NULL REFERENCES v2_sessions(id) ON DELETE CASCADE,
  recording_id UUID NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
  start_ms INTEGER NOT NULL CHECK (start_ms >= 0),
  end_ms INTEGER NOT NULL CHECK (end_ms > start_ms),
  label TEXT NOT NULL,
  notes TEXT NULL,
  reviewer_id UUID NULL REFERENCES auth.users(id) ON DELETE SET NULL,
  rubric_version TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_recording_review_annotations_session ON recording_review_annotations(session_id, recording_id, start_ms);
CREATE INDEX IF NOT EXISTS idx_recording_review_annotations_reviewer ON recording_review_annotations(reviewer_id);

COMMENT ON TABLE recording_review_annotations IS 'Admin-only time-span labels for a session recording. Used for smaller supervised review units before frame-level storage exists.';
COMMENT ON COLUMN recording_review_annotations.label IS 'Short internal label for the annotated span, e.g. pacing_issue or strong_clarity.';
COMMENT ON COLUMN recording_review_annotations.notes IS 'Internal reviewer note for the span. Must never be exposed to students.';
