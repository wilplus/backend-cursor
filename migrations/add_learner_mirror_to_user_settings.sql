-- Phase 6 of the snippet-CTA learning loop: on-demand learner mirror.
--
-- The "mirror" is an LLM-generated narrative reflection on a user's
-- recent coaching attempts — headline + 2-3 paragraph reflection
-- + a short list of factual observations grounded in their actual
-- profile data (specificity trend, recurring entities, self-rating
-- gap). It's what they see when they tap "Show me what you're
-- noticing about me" on the /results screen.
--
-- Cadence: on-demand only. v1 has no scheduler and no auto-
-- regenerate — the user (or an admin, later) explicitly triggers
-- generation. So we store ONE current mirror per user; the
-- generated_at timestamp + the source data hash live alongside it
-- so the frontend can tell "this was generated 6 days ago, want a
-- fresh one?".
--
-- Why JSONB on user_settings (not a history table)
-- ------------------------------------------------
-- v1 only ever shows the latest mirror — there's no UI yet for "see
-- past reflections". Storing a single JSONB per user is the cheapest
-- right thing. When the journal-history feature lands, that gets a
-- separate `learner_mirrors` table and this column becomes a fast-
-- path cache pointing at the latest row.
--
-- Idempotent.

ALTER TABLE user_settings
    ADD COLUMN IF NOT EXISTS current_learner_mirror JSONB,
    ADD COLUMN IF NOT EXISTS current_learner_mirror_generated_at TIMESTAMPTZ;

COMMENT ON COLUMN user_settings.current_learner_mirror IS
    'On-demand LLM-generated narrative reflection. Shape: '
    '{version, generated_at, model, based_on_attempts, headline, '
    'narrative, observations[]}. NULL until the user explicitly '
    'generates one. Replaced (not appended) on each regenerate.';
COMMENT ON COLUMN user_settings.current_learner_mirror_generated_at IS
    'Timestamp of the latest mirror generation. Lets the frontend '
    'render a "freshness" indicator and is the input to any future '
    'cooldown logic.';
