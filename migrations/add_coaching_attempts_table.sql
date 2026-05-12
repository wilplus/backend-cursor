-- Phase 2 of the snippet-CTA learning loop: 1:N coaching attempts history.
--
-- Why a new table (vs. continuing to mutate charisma_snippets.follow_up_outcome)
-- ---------------------------------------------------------------------------
-- The JSONB column on charisma_snippets is a single row per snippet — every
-- new contextual-chat attempt OVERWRITES the prior outcome (latest-wins).
-- That kills two things the system needs:
--   1. Per-snippet progress signal — "did the user improve over attempts?"
--      can't be answered when only the latest blob survives.
--   2. Few-shot pool depth — the retrieval layer (Phase 1) can only pick
--      ONE exemplar per snippet today; with N attempts persisted we can
--      pick the BEST attempt per snippet and grow the pool meaningfully.
--
-- Rollout
-- -------
-- Dual-write phase (COACHING_ATTEMPTS_DUAL_WRITE=true, the default):
--   - Every outcome lands in BOTH coaching_attempts (canonical) AND
--     charisma_snippets.follow_up_outcome (legacy, latest-wins).
--   - get_top_followup_examples reads coaching_attempts.
--   - Admin UI still reads charisma_snippets.follow_up_outcome until the
--     strip is re-pointed at coaching_attempts.
-- Once the admin strip migrates, flip the flag off and stop writing the
-- legacy column. Drop the column in a later cleanup migration.
--
-- Idempotency
-- -----------
-- This migration is safe to re-run: the IF NOT EXISTS guards on table,
-- indexes, and the backfill UPSERT (DO NOTHING on the unique attempt_number
-- conflict) all handle re-execution. Backfill seeds attempt_number=1 from
-- any existing follow_up_outcome JSONBs so historical data is preserved.

CREATE TABLE IF NOT EXISTS coaching_attempts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snippet_id UUID NOT NULL REFERENCES charisma_snippets(id) ON DELETE CASCADE,
    user_id UUID NOT NULL,
    attempt_number INT NOT NULL,

    -- 'post_turn_1_evaluation' (live) or 'backfill' (one-shot seed from the
    -- legacy follow_up_outcome JSONB). Keep as text — values are stable
    -- enough that an enum would just create migration friction.
    source TEXT NOT NULL DEFAULT 'post_turn_1_evaluation',

    -- Headline composite score in [0, 1]. Mirrors evaluator.score from the
    -- old JSONB and is the column the few-shot retrieval orders by.
    score NUMERIC(5, 4),

    -- Per-component sub-scores: specificity, emotional_movement, engagement.
    -- JSONB rather than three columns because the component set is expected
    -- to evolve and we'd rather not run an ALTER for each tweak.
    components JSONB,

    -- Optional acoustic telemetry (Phase 4 territory but reserved now so we
    -- don't migrate twice). Today: nothing writes it; Phase 4 will fill it.
    acoustic_features JSONB,

    question_text TEXT,
    user_answer_text TEXT,
    user_answer_duration_ms INT,
    user_answer_word_count INT,

    rationale TEXT,
    -- Phase 5 fact-check verdict mirrored at row level so the few-shot
    -- retrieval can filter without a JSONB poke. Default TRUE for backfilled
    -- rows so legacy outcomes don't disappear from the pool.
    is_eligible_for_few_shot BOOLEAN NOT NULL DEFAULT TRUE,
    -- Full fact-check block kept for admin audit / debugging.
    fact_check JSONB,

    evaluator_model TEXT,
    raw_outcome JSONB,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Per-snippet attempt counter must be unique; doubles as the race-safety
    -- net for the read-then-insert pattern in services/db.py.
    UNIQUE (snippet_id, attempt_number)
);

CREATE INDEX IF NOT EXISTS idx_coaching_attempts_snippet
    ON coaching_attempts (snippet_id, attempt_number);

CREATE INDEX IF NOT EXISTS idx_coaching_attempts_user
    ON coaching_attempts (user_id, created_at DESC);

-- Powers get_top_followup_examples: filter by eligibility, order by score.
CREATE INDEX IF NOT EXISTS idx_coaching_attempts_eligible_score
    ON coaching_attempts (is_eligible_for_few_shot, score DESC);

COMMENT ON TABLE coaching_attempts IS
    'One row per contextual /chat turn-1 evaluation. 1:N to charisma_snippets. '
    'Replaces the latest-wins charisma_snippets.follow_up_outcome JSONB so the '
    'system can read per-snippet progress + serve best-attempt few-shot exemplars. '
    'Dual-write coexists with the legacy column behind COACHING_ATTEMPTS_DUAL_WRITE.';

-- One-shot backfill: seed attempt_number=1 from any existing
-- follow_up_outcome JSONB on charisma_snippets. Idempotent — re-running
-- skips snippets that already have a row (ON CONFLICT DO NOTHING on the
-- snippet_id+attempt_number unique constraint).
INSERT INTO coaching_attempts (
    snippet_id, user_id, attempt_number, source, score, components,
    question_text, user_answer_text, user_answer_duration_ms,
    user_answer_word_count, rationale,
    is_eligible_for_few_shot, fact_check, evaluator_model, raw_outcome,
    created_at
)
SELECT
    s.id,
    s.user_id,
    1,
    'backfill',
    NULLIF((s.follow_up_outcome->>'score'), '')::NUMERIC,
    s.follow_up_outcome->'evaluator'->'components',
    NULLIF(s.follow_up_outcome->>'question_text', ''),
    NULLIF(s.follow_up_outcome->'user_answer'->>'text', ''),
    NULLIF((s.follow_up_outcome->'user_answer'->>'duration_ms'), '')::INT,
    NULLIF((s.follow_up_outcome->'user_answer'->>'word_count'), '')::INT,
    NULLIF(s.follow_up_outcome->'evaluator'->>'rationale', ''),
    -- Legacy outcomes written before Phase 5 don't carry the flag —
    -- default to TRUE so backfilled rows participate in the few-shot pool.
    COALESCE((s.follow_up_outcome->>'eligible_for_few_shot')::BOOLEAN, TRUE),
    s.follow_up_outcome->'fact_check',
    NULLIF(s.follow_up_outcome->'evaluator'->>'model', ''),
    s.follow_up_outcome,
    COALESCE(
        NULLIF(s.follow_up_outcome->>'captured_at', '')::TIMESTAMPTZ,
        s.updated_at,
        s.created_at,
        now()
    )
FROM charisma_snippets s
WHERE s.follow_up_outcome IS NOT NULL
  AND s.user_id IS NOT NULL
ON CONFLICT (snippet_id, attempt_number) DO NOTHING;
