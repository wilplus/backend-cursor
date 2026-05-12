-- Phase 3 of the snippet-CTA learning loop: inferred learner profile.
--
-- After Phase 2/8 every coaching attempt drops a row in
-- coaching_attempts with a score, per-component sub-scores, and an
-- optional 1..10 self-rating. Aggregating those rows by user gives
-- us a deterministic "who is this learner today" snapshot — their
-- average score, weakest component, score trend, self-vs-LLM rating
-- gap, etc. — that we inject into the coaching system prompt so the
-- AI adapts to the specific student instead of coaching everyone
-- the same way.
--
-- Storage shape
-- -------------
-- One JSONB column on user_settings (which already exists per-user).
-- The blob is computed by services/learner_profile.py from the user's
-- most recent N coaching_attempts. Schema is intentionally loose
-- (JSONB rather than columns) because we expect to iterate on the
-- traits during the rollout — adding a new trait is a code change,
-- not a migration.
--
-- Sample shape::
--
--   {
--     "version": "v1",
--     "computed_at": "2026-05-12T18:23:00Z",
--     "attempts_analyzed": 7,
--     "traits": {
--       "score_average": 0.72,
--       "score_per_component": {"specificity": 0.65, ...},
--       "weakest_component": "specificity",
--       "strongest_component": "emotional_movement",
--       "score_trend": "improving",
--       "self_rating_average": 7.2,
--       "self_rating_gap": 0.05
--     }
--   }
--
-- The injection layer (_augment_coaching_system_prompt) treats the
-- whole blob as opt-in: when it's NULL or the analysed sample is too
-- small (< MIN_ATTEMPTS), no profile-derived block is added to the
-- prompt. So a sparse user just sees the existing
-- behavioral_profile + custom_llm_instructions injection.
--
-- Idempotent.

ALTER TABLE user_settings
    ADD COLUMN IF NOT EXISTS inferred_learner_profile JSONB,
    ADD COLUMN IF NOT EXISTS inferred_learner_profile_updated_at TIMESTAMPTZ;

COMMENT ON COLUMN user_settings.inferred_learner_profile IS
    'AI-inferred learner profile derived from coaching_attempts aggregates. '
    'Computed by services/learner_profile.py after each new attempt. '
    'NULL when the user has no analysed attempts yet.';
COMMENT ON COLUMN user_settings.inferred_learner_profile_updated_at IS
    'Timestamp of the most recent successful profile recompute. '
    'Helps debug stale-profile complaints and lets us tell when an '
    'aggregation has fallen behind the latest attempt write.';
