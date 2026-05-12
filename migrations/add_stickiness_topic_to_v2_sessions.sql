-- Phase 11: per-session "stickiness-topic" metric.
--
-- Measures how much a user fixates on a single topic across the
-- answers in one session. Computed alongside the existing KPI when
-- the admin clicks "Compute Metrics":
--
--   1. The LLM extracts a 1-2-word topic per snippet (one batch call).
--   2. We count topic frequencies, case-folded.
--   3. stickiness_top_topic    = the most-recurring topic.
--      stickiness_score        = top_topic_count / topical_snippets
--                                (0.0 = broad coverage, 1.0 = total fixation).
--      stickiness_topic_distribution = {topic_lower: count, ...} JSONB
--                                for debugging + future drill-downs.
--
-- Why a session column (not a join table)
-- ---------------------------------------
-- We never query "which sessions mention topic X" — the metric is
-- always read in the context of the session itself. Per-row JSONB
-- is the right granularity; a join table would add cost with no
-- query benefit. If we ever want cross-session topic search,
-- coaching_attempts.entities (Phase 4) already covers the user-
-- level question.
--
-- Idempotent.

ALTER TABLE v2_sessions
    ADD COLUMN IF NOT EXISTS stickiness_top_topic TEXT,
    ADD COLUMN IF NOT EXISTS stickiness_score NUMERIC(5, 4),
    ADD COLUMN IF NOT EXISTS stickiness_topic_distribution JSONB,
    ADD COLUMN IF NOT EXISTS stickiness_computed_at TIMESTAMPTZ;

COMMENT ON COLUMN v2_sessions.stickiness_top_topic IS
    'Phase 11 — the topic the user returned to most often across this '
    'session''s answers. Surface-form of the most common topic; '
    'case-folded for counting but display preserves capitalisation. '
    'NULL when no topics could be extracted (sparse / unanswered).';
COMMENT ON COLUMN v2_sessions.stickiness_score IS
    'Phase 11 — fraction in [0, 1] of session snippets that mapped to '
    'stickiness_top_topic. 1.0 means every answer was about that '
    'topic; 0.0 means every answer was about something different.';
COMMENT ON COLUMN v2_sessions.stickiness_topic_distribution IS
    'Phase 11 — {topic_lower: count, ...} JSONB. Debug + future '
    'drill-down. Distinct keys reflect the LLM''s per-snippet topic '
    'choices after case-folding.';
COMMENT ON COLUMN v2_sessions.stickiness_computed_at IS
    'When the stickiness metric was last computed for this session.';

NOTIFY pgrst, 'reload schema';
