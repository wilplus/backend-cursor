-- Phase 16: pre-baked baseline summary from the EBCP turns 1-4.
--
-- The first 4 interview turns are a structured EBCP Baseline Mapping
-- (math, math-under-pressure, charismatic leader, fictional
-- character). The LLM at turn 5 used to do both extraction +
-- generation in one shot — given 4 raw transcripts in conversation
-- history, "now write turn 5". That's a lot of cognitive load for
-- one model call, and is exactly where shallow openers leak in.
--
-- Phase 16 splits the work: when the user first reaches turn 5, a
-- dedicated LLM call digests the 4 baseline answers into a
-- structured summary (headline, themes, aspirational archetype,
-- productive tension, ONE coaching handle). That JSONB lands on
-- user_settings and is injected into every subsequent turn-5+
-- prompt — and every future contextual /chat prompt for this user
-- — so the model doesn't have to re-derive who-this-user-is from
-- raw transcripts on every call.
--
-- One LLM extra call per user, exactly once at baseline graduation
-- (and again if admin resets baseline). Pays for itself the moment
-- the second turn is generated.
--
-- Idempotent.

ALTER TABLE user_settings
    ADD COLUMN IF NOT EXISTS baseline_summary JSONB,
    ADD COLUMN IF NOT EXISTS baseline_summary_computed_at TIMESTAMPTZ;

COMMENT ON COLUMN user_settings.baseline_summary IS
    'Phase 16 — structured digest of the user''s EBCP turns 1-4 '
    '(headline, themes, aspirational_archetype, tension, '
    'coaching_handle). Computed once at baseline graduation; read '
    'by the turn-5+ interview-question generator and the contextual '
    '/chat first-question generator. NULL until the user finishes '
    'their first EBCP run.';
COMMENT ON COLUMN user_settings.baseline_summary_computed_at IS
    'When baseline_summary was last computed. Cleared whenever '
    'reset_baseline_established is called so the next session '
    're-bakes the digest.';

NOTIFY pgrst, 'reload schema';
