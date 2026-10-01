-- a_model_learns_only_from_the_yes (founder 2026-09-30, L6 to L9; counsel
-- 2026-10-01; build plan ML-10, ML-11, ML-12, ML-14).
--
-- Doors 3 and 4, built with both doors closed. What a training run and a
-- promotion leave behind so that a withdrawal can reach every copy:
--
--   * feedback_pairs remembers the passage it was drafted from (the prompt a
--     training example needs) and the run that trained on it (a pair trains
--     once; a withdrawal reaches the run by its owners);
--   * fine_tune_runs: one row per OpenAI fine-tuning job — the file it
--     uploaded (deleted at the provider when the job ends or an owner
--     withdraws), the job, the candidate it produced; fine_tune_run_owners
--     says whose passages it learned from;
--   * evaluation_reports: candidate vs baseline on the sealed golden set,
--     with the regurgitation check counsel asked for;
--   * model_promotions: the history door 4 writes (runtime_config holds only
--     the present), with the kill that returns a surface to the stock model;
--   * golden_judgements learns to hold a text moment (the passage and the
--     coach's final the founder confirmed), so a pair surface can have a
--     golden set; its owner is named so erasure reaches it;
--   * the promote RPC's allowlist gains the three coach-answer surfaces;
--   * two acoustic shadow cues (low_volume, flat_pitch) join the speaking
--     error library in the shadow stage: logged, routing nothing (E10).
--
-- Nothing here opens a door: MLC2_TRAINING_ENABLED and
-- MLC2_PROMOTION_ENABLED stay False in code. Idempotent, additive, no env
-- var. RLS on every new table; no browser role reaches any of it.

BEGIN;

-- ── The pair remembers its prompt and its run ────────────────────────────
ALTER TABLE public.feedback_pairs
    ADD COLUMN IF NOT EXISTS passage_text   text  NULL,
    ADD COLUMN IF NOT EXISTS prompt_context jsonb NULL,
    ADD COLUMN IF NOT EXISTS trained_run_id uuid  NULL;

CREATE INDEX IF NOT EXISTS idx_feedback_pairs_trainable
    ON public.feedback_pairs (surface, created_at)
    WHERE trained_run_id IS NULL AND release_id IS NOT NULL;

-- Backfill the passage from the clip the pair names, where the clip still
-- exists (a purged Take leaves the pair without one, and such a pair is
-- never a training example).
DO $$
BEGIN
    IF to_regclass('public.charisma_snippets') IS NOT NULL THEN
        UPDATE public.feedback_pairs fp
           SET passage_text = NULLIF(btrim(s.transcript), '')
          FROM public.charisma_snippets s
         WHERE fp.passage_text IS NULL
           AND fp.snippet_id IS NOT NULL
           AND s.id::text = fp.snippet_id;
    END IF;
END $$;

-- ── Fine-tune runs ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.fine_tune_runs (
    id                 uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    run_version        text        NOT NULL,
    surface            text        NOT NULL
        CHECK (surface IN ('praise_line', 'clearer_version', 'exercise_script')),
    base_model         text        NOT NULL CHECK (length(btrim(base_model)) > 0),
    status             text        NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'succeeded', 'failed', 'cancelled', 'withdrawn')),
    item_count         integer     NOT NULL CHECK (item_count > 0),
    train_count        integer     NOT NULL CHECK (train_count >= 0),
    validation_count   integer     NOT NULL CHECK (validation_count >= 0),
    file_sha256        text        NOT NULL CHECK (file_sha256 ~ '^[0-9a-f]{64}$'),
    owners_sha256      text        NOT NULL CHECK (owners_sha256 ~ '^[0-9a-f]{64}$'),
    prompt_lock_sha256 text        NULL,
    openai_file_id     text        NULL,
    openai_validation_file_id text NULL,
    openai_job_id      text        NULL,
    candidate_model    text        NULL,
    failure            text        NULL,
    started_at         timestamptz NOT NULL DEFAULT now(),
    finished_at        timestamptz NULL,
    files_deleted_at   timestamptz NULL,
    withdrawn_at       timestamptz NULL,
    withdrawn_reason   text        NULL
);
CREATE INDEX IF NOT EXISTS idx_fine_tune_runs_surface
    ON public.fine_tune_runs (surface, started_at DESC);

CREATE TABLE IF NOT EXISTS public.fine_tune_run_owners (
    run_id             uuid NOT NULL REFERENCES public.fine_tune_runs(id) ON DELETE CASCADE,
    owner_principal_id uuid NOT NULL,
    PRIMARY KEY (run_id, owner_principal_id)
);
CREATE INDEX IF NOT EXISTS idx_fine_tune_run_owners_owner
    ON public.fine_tune_run_owners (owner_principal_id);

-- A pair trains once, under one run, and only while releasable: the run
-- reads releasability at its start (a queued run never learns from a pair
-- whose owner withdrew in the meantime).
CREATE OR REPLACE FUNCTION public.mark_feedback_pairs_trained_v1(
    p_run_id uuid, p_pair_ids uuid[]
) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    marked integer;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.fine_tune_runs WHERE id = p_run_id) THEN
        RAISE EXCEPTION 'FINE_TUNE_RUN_UNKNOWN';
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.feedback_pairs
         WHERE id = ANY(p_pair_ids)
           AND (releasable IS DISTINCT FROM true OR trained_run_id IS NOT NULL
                OR release_id IS NULL)
    ) THEN
        RAISE EXCEPTION 'FINE_TUNE_PAIRS_NOT_TRAINABLE';
    END IF;
    UPDATE public.feedback_pairs
       SET trained_run_id = p_run_id
     WHERE id = ANY(p_pair_ids);
    GET DIAGNOSTICS marked = ROW_COUNT;
    RETURN marked;
END;
$$;
REVOKE ALL ON FUNCTION public.mark_feedback_pairs_trained_v1(uuid, uuid[])
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.mark_feedback_pairs_trained_v1(uuid, uuid[])
    TO service_role;

-- Runs whose owner withdrew: the sweep deletes their files at the provider
-- and cancels a job still running. Read through the same active-grants view
-- the pair refresh uses (0405).
CREATE OR REPLACE VIEW public.fine_tune_runs_with_withdrawn_owner AS
SELECT DISTINCT r.id AS run_id, r.surface, r.status, r.openai_job_id,
       r.openai_file_id, r.openai_validation_file_id, r.files_deleted_at,
       r.withdrawn_at, r.candidate_model
  FROM public.fine_tune_runs r
  JOIN public.fine_tune_run_owners o ON o.run_id = r.id
 WHERE NOT EXISTS (
        SELECT 1 FROM public.training_consent_active_grants g
         WHERE g.acquisition_principal_id = o.owner_principal_id);

-- ── Evaluation reports ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.evaluation_reports (
    id                 uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    report_version     text        NOT NULL,
    surface            text        NOT NULL
        CHECK (surface IN ('praise_line', 'clearer_version', 'exercise_script')),
    run_id             uuid        NULL REFERENCES public.fine_tune_runs(id) ON DELETE SET NULL,
    candidate_model    text        NOT NULL CHECK (length(btrim(candidate_model)) > 0),
    baseline_model     text        NOT NULL CHECK (length(btrim(baseline_model)) > 0),
    golden_sha256      text        NOT NULL CHECK (golden_sha256 ~ '^[0-9a-f]{64}$'),
    golden_count       integer     NOT NULL CHECK (golden_count > 0),
    prompt_lock_sha256 text        NULL,
    report             jsonb       NOT NULL CHECK (jsonb_typeof(report) = 'object'),
    passed             boolean     NOT NULL,
    created_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_evaluation_reports_surface
    ON public.evaluation_reports (surface, created_at DESC);

-- ── Promotions, the history ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.model_promotions (
    id                   uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    surface              text        NOT NULL
        CHECK (surface IN ('praise_line', 'clearer_version', 'exercise_script')),
    candidate_model      text        NOT NULL CHECK (length(btrim(candidate_model)) > 0),
    previous_model       text        NULL,
    run_id               uuid        NULL REFERENCES public.fine_tune_runs(id) ON DELETE SET NULL,
    evaluation_report_id uuid        NULL REFERENCES public.evaluation_reports(id) ON DELETE SET NULL,
    promoted_by          text        NOT NULL CHECK (length(btrim(promoted_by)) > 0),
    promoted_at          timestamptz NOT NULL DEFAULT now(),
    killed_at            timestamptz NULL,
    killed_by            text        NULL,
    kill_reason          text        NULL
);
CREATE INDEX IF NOT EXISTS idx_model_promotions_surface
    ON public.model_promotions (surface, promoted_at DESC);

-- ── The golden set can hold a text moment ────────────────────────────────
ALTER TABLE public.golden_judgements
    ADD COLUMN IF NOT EXISTS passage            text NULL,
    ADD COLUMN IF NOT EXISTS reference          text NULL,
    ADD COLUMN IF NOT EXISTS prompt_context     jsonb NULL,
    ADD COLUMN IF NOT EXISTS owner_principal_id uuid NULL;
CREATE INDEX IF NOT EXISTS idx_golden_judgements_owner
    ON public.golden_judgements (owner_principal_id)
    WHERE owner_principal_id IS NOT NULL;

-- ── RLS, grants ──────────────────────────────────────────────────────────
ALTER TABLE public.fine_tune_runs        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.fine_tune_run_owners  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.evaluation_reports    ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.model_promotions      ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.fine_tune_runs, public.fine_tune_run_owners,
              public.evaluation_reports, public.model_promotions
    FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.fine_tune_runs,
      public.fine_tune_run_owners, public.evaluation_reports,
      public.model_promotions TO service_role;
REVOKE ALL ON public.fine_tune_runs_with_withdrawn_owner FROM PUBLIC, anon, authenticated;
GRANT SELECT ON public.fine_tune_runs_with_withdrawn_owner TO service_role;

-- ── The promote RPC's allowlist gains the three coach-answer surfaces ─────
-- Same body as migrations/guard_runtime_config_model_keys.sql, the IN-list
-- widened; the BEFORE trigger already covers the keys by prefix.
-- Guarded like guard_runtime_config_model_keys.sql: a database without
-- runtime_config (a narrow rehearsal lane) gets a notice, not an error.
DO $guard$
BEGIN
    IF to_regclass('public.runtime_config') IS NULL THEN
        RAISE NOTICE 'runtime_config absent; promote allowlist not widened here';
        RETURN;
    END IF;
    EXECUTE $fn$
CREATE OR REPLACE FUNCTION public.promote_runtime_surface_model_v1(
    p_key TEXT,
    p_value TEXT,
    p_updated_by TEXT,
    p_metadata JSONB
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
DECLARE
    prompt_hash TEXT;
    stored public.runtime_config%ROWTYPE;
BEGIN
    IF p_key NOT IN (
        'openai_surface_model_say_it_stronger',
        'openai_surface_model_coach_comment_draft',
        'openai_surface_model_ideal_text',
        'openai_surface_model_praise_line',
        'openai_surface_model_clearer_version',
        'openai_surface_model_exercise_script',
        'openai_chat_model',
        'openai_copilot_model'
    ) THEN
        RAISE EXCEPTION 'RUNTIME_MODEL_KEY_NOT_ENUMERATED: %', p_key
            USING ERRCODE = 'P0001';
    END IF;

    IF p_value IS NULL OR btrim(p_value) = '' THEN
        RAISE EXCEPTION 'RUNTIME_MODEL_VALUE_REQUIRED' USING ERRCODE = 'P0001';
    END IF;

    prompt_hash := lower(btrim(COALESCE(p_metadata->>'prompt_lock_sha256', '')));
    IF prompt_hash !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION
            'RUNTIME_MODEL_PROMPT_LOCK_REQUIRED: metadata.prompt_lock_sha256 '
            'must be the sha256 of the surface''s locked prompts'
            USING ERRCODE = 'P0001';
    END IF;

    PERFORM set_config('willab.runtime_model_promotion', p_key, true);

    INSERT INTO public.runtime_config (key, value, updated_at, updated_by, metadata)
    VALUES (p_key, btrim(p_value), now(), NULLIF(btrim(COALESCE(p_updated_by, '')), ''),
            COALESCE(p_metadata, '{}'::jsonb))
    ON CONFLICT (key) DO UPDATE
        SET value = EXCLUDED.value,
            updated_at = EXCLUDED.updated_at,
            updated_by = EXCLUDED.updated_by,
            metadata = EXCLUDED.metadata
    RETURNING * INTO stored;

    RETURN jsonb_build_object(
        'key', stored.key,
        'value', stored.value,
        'updated_at', stored.updated_at,
        'updated_by', stored.updated_by,
        'metadata', stored.metadata
    );
END;
$$;
    $fn$;
END;
$guard$;


-- ── The three answer surfaces join the alias registry ────────────────────
-- Same shape as add_mlc2_foundation.sql; matches
-- services.mlc2_foundation.LEARNING_SURFACE_ALIASES.
INSERT INTO public.ml_learning_surface_aliases (
    alias, learning_surface_id, canonical_writes_allowed, reason
) VALUES
    ('praise_line', 'praise_generation', true,
     'Explicit product/runtime alias only (coach answer surface, 0406)'),
    ('clearer_version', 'correction_generation', true,
     'Explicit product/runtime alias only (coach answer surface, 0406)'),
    ('exercise_script', 'coach_comment_generation', true,
     'Explicit product/runtime alias only (coach answer surface, 0406)')
ON CONFLICT (alias) DO NOTHING;

-- ── Two acoustic cues in the shadow stage (E10) ──────────────────────────
INSERT INTO public.speaking_error (
    error_id, label, definition, asks, status, detector_ref
) VALUES
(
    'low_volume',
    'Low volume',
    'The voice barely rises above the room. Measured on the clip''s own '
    'frames (services/acoustic_cues.py, acoustic-cues-v1): the speaking '
    'frames (90th percentile of frame loudness) stand under 12 dB above the '
    'quietest frames (10th percentile), on a clip with at least 20 frames. '
    'Relative to the recording itself, never an absolute level, because '
    'microphones differ.',
    'Did the voice carry above the room in this passage?',
    'shadow',
    'acoustic_cues:low_volume'
),
(
    'flat_pitch',
    'Flat pitch',
    'The voice stays on one note. Measured on the clip''s pitch track '
    '(services/acoustic_cues.py, acoustic-cues-v1): the standard deviation '
    'of the fundamental frequency is under 6% of its mean, on at least 30 '
    'confident pitch frames. A ratio, so a low voice and a high voice are '
    'read alike.',
    'Did the voice move in pitch during this passage?',
    'shadow',
    'acoustic_cues:flat_pitch'
)
ON CONFLICT (error_id) DO NOTHING;

COMMIT;
