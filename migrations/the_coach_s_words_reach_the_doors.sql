-- 0459 · The coach's own words reach doors 2, 3 and 4, closed (founder
-- 2026-10-08, Privacy/Terms 3.5, decisions log N68; legal/phase1-2026.1/
-- 22-privacy-terms-3.5-all-learning-SIGNED-2026-10-08.md, E2; C5-a).
--
-- WHY. The coach's own words, the personal line on a moment
-- (`coach_moment_line`) and the word for a Take (`coach_take_word`), are
-- recorded as (draft, final) pairs in `feedback_pairs` (0411) but stood
-- outside every learning door until counsel answered. Privacy/Terms 3.5,
-- signed by the founder 2026-10-08, covers them as training data under the
-- SPEAKER's training yes, and the coach agreement covers the coach's side.
-- The code now lets doors 2 (release), 3 (training) and 4 (promotion)
-- accept them exactly like the three answer surfaces; this file lets the
-- database hold what those doors write. It opens nothing: each door still
-- opens for a surface only when its code switch is on AND the founder names
-- the surface in that door's config set (PAIR_RELEASE_SURFACES,
-- TRAINING_SURFACES, PROMOTION_SURFACES, config.py; all three name neither
-- coach-word surface today), and every pair of either surface leaves only
-- with its speaker's yes in force (the weekly refresh's p_required_surfaces
-- and the release-time decision both name all five surfaces).
--
-- WHAT.
--   1. The surface CHECK on the four door tables, `pair_releases` (0405),
--      `fine_tune_runs`, `evaluation_reports` and `model_promotions`
--      (0406), widens from the three answer surfaces to all five pair
--      surfaces. `feedback_pairs` already holds all five (0411).
--   2. `promote_runtime_surface_model_v1` (0352, widened in 0406), the one
--      writer of a promoted model, gains the two coach-word keys
--      (`openai_surface_model_coach_moment_line`,
--      `openai_surface_model_coach_take_word`); services/runtime_model_gate.py
--      MODEL_CONFIG_KEYS already lists them. Same body as 0406, the IN-list
--      widened by those two lines and nothing else. The BEFORE trigger on
--      runtime_config already covers the keys by prefix.
--   3. `ml_learning_surface_aliases` gains the two aliases
--      services/mlc2_foundation.py LEARNING_SURFACE_ALIASES already maps
--      (both to `coach_comment_generation`), as 0406 seeded the three.
--   4. `draft_prompt jsonb NULL` on `exercise_coach_requests` (the moment
--      line's draft row) and `coach_take_words` (the Take word's): what the
--      coach-word drafter's prompt was given ({passage_text, prompt_context:
--      {prompt: "coach_word_drafts", coach_text}}), written with the draft
--      (services/coach_word_pairs.py) and copied onto the pair, so a
--      training example and a golden evaluation rebuild the serving prompt
--      verbatim. A coach-word pair without it carries no passage and is
--      never released, judged or trained on (fail closed). Coach-only
--      columns, never in any speaker payload (take_word_payload and the
--      request payloads name their fields); a row's erasure takes them with
--      it (data_purge_registry: exercise_coach_requests and coach_take_words
--      by take).
--
-- Idempotent: DROP CONSTRAINT IF EXISTS then ADD CONSTRAINT, CREATE OR
-- REPLACE, ON CONFLICT DO NOTHING, ADD COLUMN IF NOT EXISTS; applied twice
-- it changes nothing. Writes no row except the two alias rows. Locks: each
-- of the four door tables briefly ACCESS EXCLUSIVE for the constraint swap
-- and one validating scan (each holds a few rows a week at most); the two
-- ADD COLUMNs are catalog-only (nullable, no default, no rewrite). Reads no
-- environment variable. Every existing row satisfies the wider CHECKs.
--
-- Rollback (a new forward migration): narrow the four CHECKs back to the
-- three answer surfaces (refused while a row of a coach-word surface
-- exists, which is the point), restore 0406's promote body, delete the two
-- alias rows, and leave the two nullable columns (dropping them is a
-- separate, previewed retention operation).

BEGIN;

-- ── 1. The door tables hold all five pair surfaces ───────────────────────
ALTER TABLE public.pair_releases DROP CONSTRAINT IF EXISTS pair_releases_surface_check;
ALTER TABLE public.pair_releases ADD CONSTRAINT pair_releases_surface_check
    CHECK (surface IN ('praise_line', 'clearer_version', 'exercise_script',
                       'coach_moment_line', 'coach_take_word'));

ALTER TABLE public.fine_tune_runs DROP CONSTRAINT IF EXISTS fine_tune_runs_surface_check;
ALTER TABLE public.fine_tune_runs ADD CONSTRAINT fine_tune_runs_surface_check
    CHECK (surface IN ('praise_line', 'clearer_version', 'exercise_script',
                       'coach_moment_line', 'coach_take_word'));

ALTER TABLE public.evaluation_reports DROP CONSTRAINT IF EXISTS evaluation_reports_surface_check;
ALTER TABLE public.evaluation_reports ADD CONSTRAINT evaluation_reports_surface_check
    CHECK (surface IN ('praise_line', 'clearer_version', 'exercise_script',
                       'coach_moment_line', 'coach_take_word'));

ALTER TABLE public.model_promotions DROP CONSTRAINT IF EXISTS model_promotions_surface_check;
ALTER TABLE public.model_promotions ADD CONSTRAINT model_promotions_surface_check
    CHECK (surface IN ('praise_line', 'clearer_version', 'exercise_script',
                       'coach_moment_line', 'coach_take_word'));

-- ── 2. The promote RPC's allowlist gains the two coach-word keys ─────────
-- Same body as 0406 (a_model_learns_only_from_the_yes.sql); guarded the
-- same way: a database without runtime_config gets a notice, not an error.
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
        'openai_surface_model_coach_moment_line',
        'openai_surface_model_coach_take_word',
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
    -- CREATE OR REPLACE keeps 0352's grants; restated so the file holds
    -- them itself (Supabase grants the browser roles on public functions
    -- directly, and a REVOKE from PUBLIC alone leaves those grants).
    EXECUTE 'REVOKE ALL ON FUNCTION public.promote_runtime_surface_model_v1(TEXT, TEXT, TEXT, JSONB) FROM PUBLIC';
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        EXECUTE 'REVOKE ALL ON FUNCTION public.promote_runtime_surface_model_v1(TEXT, TEXT, TEXT, JSONB) FROM anon';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        EXECUTE 'REVOKE ALL ON FUNCTION public.promote_runtime_surface_model_v1(TEXT, TEXT, TEXT, JSONB) FROM authenticated';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        EXECUTE 'GRANT EXECUTE ON FUNCTION public.promote_runtime_surface_model_v1(TEXT, TEXT, TEXT, JSONB) TO service_role';
    END IF;
END;
$guard$;

-- ── 3. The two coach-word surfaces join the alias registry ───────────────
-- Matches services.mlc2_foundation.LEARNING_SURFACE_ALIASES.
INSERT INTO public.ml_learning_surface_aliases (
    alias, learning_surface_id, canonical_writes_allowed, reason
) VALUES
    ('coach_moment_line', 'coach_comment_generation', true,
     'Explicit product/runtime alias only (the coach''s own words, 3.5 N68, 0459)'),
    ('coach_take_word', 'coach_comment_generation', true,
     'Explicit product/runtime alias only (the coach''s own words, 3.5 N68, 0459)')
ON CONFLICT (alias) DO NOTHING;

-- ── 4. A coach-word draft keeps what its prompt was given ────────────────
ALTER TABLE public.exercise_coach_requests
    ADD COLUMN IF NOT EXISTS draft_prompt jsonb NULL;
ALTER TABLE public.coach_take_words
    ADD COLUMN IF NOT EXISTS draft_prompt jsonb NULL;
COMMENT ON COLUMN public.exercise_coach_requests.draft_prompt IS
    'What the coach-word drafter''s prompt was given ({passage_text, prompt_context}), '
    'coach-only; copied onto the coach_moment_line pair (0459). NULL for any other draft.';
COMMENT ON COLUMN public.coach_take_words.draft_prompt IS
    'What the coach-word drafter''s prompt was given ({passage_text, prompt_context}), '
    'coach-only; copied onto the coach_take_word pair (0459).';

COMMIT;
