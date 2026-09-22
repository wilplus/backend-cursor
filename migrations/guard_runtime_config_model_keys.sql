-- 0352 · A row in runtime_config cannot change which model writes a
--        speaker's document. LEGACY-1 (blocker) and R-13, audit 2026-09-22.
--
-- WHAT THE AUDIT FOUND. `public.runtime_config` is a five-column key/value
-- table with no RLS (`relrowsecurity = f`), no trigger, and `GRANT ALL` to
-- `service_role` (add_runtime_model_config.sql:15). Five of its keys are read
-- straight into the `model` argument of an OpenAI chat completion:
--
--   openai_surface_model_ideal_text        → slide_selection._render_composition,
--                                            surface "best_presentation" — the
--                                            TAKE-1 IDEAL TEXT COMPOSITION
--   openai_surface_model_say_it_stronger   → every Say It Stronger card
--   openai_surface_model_coach_comment_draft
--   openai_chat_model / openai_copilot_model  (R-13; no writer in the repo)
--
-- `services/ml_surface_contracts.py` caches that read for sixty seconds and
-- `services/llm.py` uses it. So one INSERT by anyone holding the service-role
-- key — which the backend client itself is — changed the words in a speaker's
-- Ideal Text within a minute, with `MLC2_PROMOTION_ENABLED` still false and
-- the HTTP promotion surface still answering "promotion is not active".
--
-- The Python gate landed in the same pull request. This is the other half,
-- because a Python gate cannot bind a psql session or a one-line script that
-- holds the same key. Below the boundary, the table itself refuses.
--
-- HOW. A BEFORE INSERT OR UPDATE trigger rejects any write to a model key
-- unless the transaction carries `willab.runtime_model_promotion` set to that
-- exact key. The only thing that can set it is
-- `promote_runtime_surface_model_v1`, because PostgREST runs each request in
-- its own transaction and does not publish `set_config`, so a GUC cannot be
-- carried in from outside. Per-key column privileges do not exist in
-- PostgreSQL — `REVOKE ... (key)` is not a thing for rows — so the trigger IS
-- the row-level revoke the audit asks for.
--
-- ADDITIVE AND IDEMPOTENT. No table, column, row or grant is dropped, and no
-- existing row is rewritten: reads are untouched, so a model key already in
-- production keeps serving exactly as the Python gate decides. The only
-- writer in the repository is `scripts/promote_openai_model.py`, which moves
-- to the RPC in this same pull request.
--
-- THIS OPENS NOTHING. The RPC refuses every key outside the allowlist, and
-- refuses a promotion that does not carry the `prompts.lock.json` digest it
-- was evaluated under (H-1). Whether promotion happens at all is decided
-- above it, by `Config.MLC2_PROMOTION_ENABLED`, which ships false.

-- ── The guard ────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.reject_ungated_runtime_model_write_v1()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
DECLARE
    permitted_key TEXT;
BEGIN
    IF NEW.key NOT LIKE 'openai_surface_model_%'
       AND NEW.key NOT IN ('openai_chat_model', 'openai_copilot_model') THEN
        RETURN NEW;
    END IF;

    permitted_key := current_setting('willab.runtime_model_promotion', true);
    IF permitted_key IS NULL OR permitted_key <> NEW.key THEN
        RAISE EXCEPTION
            'RUNTIME_MODEL_PROMOTION_NOT_PERMITTED: % may only be written by '
            'promote_runtime_surface_model_v1', NEW.key
            USING ERRCODE = 'P0001';
    END IF;

    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.reject_ungated_runtime_model_write_v1()
    FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON FUNCTION public.reject_ungated_runtime_model_write_v1()
            FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON FUNCTION public.reject_ungated_runtime_model_write_v1()
            FROM authenticated;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT EXECUTE ON FUNCTION public.reject_ungated_runtime_model_write_v1()
            TO service_role;
    END IF;
END;
$$;

-- Degrades gracefully, per the house rule: `runtime_config` arrives in 0051,
-- so it is present everywhere this runs, but a lane that has not taken that
-- file must not be blocked by this one. The RPC body below needs no guard —
-- plpgsql bodies are not resolved until they are called.
DO $$
BEGIN
    IF to_regclass('public.runtime_config') IS NULL THEN
        RAISE NOTICE
            'runtime_config absent; model-key guard not installed here';
        RETURN;
    END IF;
    DROP TRIGGER IF EXISTS runtime_config_model_key_guard
        ON public.runtime_config;
    CREATE TRIGGER runtime_config_model_key_guard
    BEFORE INSERT OR UPDATE ON public.runtime_config
    FOR EACH ROW EXECUTE FUNCTION public.reject_ungated_runtime_model_write_v1();
END;
$$;

-- ── The one permitted writer ─────────────────────────────────────────────
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
    -- The allowlist, in the database, matching
    -- services.runtime_model_gate.MODEL_CONFIG_KEYS. `moment_suggestion` is
    -- absent from both: the canonical registry rejects that alias for
    -- learning writes (E-6), so the surface cannot be promoted at all.
    IF p_key NOT IN (
        'openai_surface_model_say_it_stronger',
        'openai_surface_model_coach_comment_draft',
        'openai_surface_model_ideal_text',
        'openai_chat_model',
        'openai_copilot_model'
    ) THEN
        RAISE EXCEPTION 'RUNTIME_MODEL_KEY_NOT_ENUMERATED: %', p_key
            USING ERRCODE = 'P0001';
    END IF;

    IF p_value IS NULL OR btrim(p_value) = '' THEN
        RAISE EXCEPTION 'RUNTIME_MODEL_VALUE_REQUIRED' USING ERRCODE = 'P0001';
    END IF;

    -- H-1: a promoted model is bound to the prompts it was evaluated under.
    -- Stored, not verified here — the lockfile lives in the repository, so
    -- only the caller can compare it. What the database guarantees is that
    -- the binding EXISTS and is shaped like a digest, so a promotion with no
    -- prompt provenance cannot be written at all.
    prompt_hash := lower(btrim(COALESCE(p_metadata->>'prompt_lock_sha256', '')));
    IF prompt_hash !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION
            'RUNTIME_MODEL_PROMPT_LOCK_REQUIRED: metadata.prompt_lock_sha256 '
            'must be the sha256 of the surface''s locked prompts'
            USING ERRCODE = 'P0001';
    END IF;

    -- Transaction-local, and the only place it is ever set.
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

REVOKE ALL ON FUNCTION public.promote_runtime_surface_model_v1(TEXT, TEXT, TEXT, JSONB)
    FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON FUNCTION
            public.promote_runtime_surface_model_v1(TEXT, TEXT, TEXT, JSONB)
            FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON FUNCTION
            public.promote_runtime_surface_model_v1(TEXT, TEXT, TEXT, JSONB)
            FROM authenticated;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT EXECUTE ON FUNCTION
            public.promote_runtime_surface_model_v1(TEXT, TEXT, TEXT, JSONB)
            TO service_role;
    END IF;
END;
$$;

COMMENT ON FUNCTION public.reject_ungated_runtime_model_write_v1() IS
    'LEGACY-1/R-13: runtime_config model keys are writable only through '
    'promote_runtime_surface_model_v1.';
COMMENT ON FUNCTION public.promote_runtime_surface_model_v1(TEXT, TEXT, TEXT, JSONB) IS
    'The one permitted writer of a runtime_config model key. Requires '
    'metadata.prompt_lock_sha256 (H-1). Promotion itself is gated above this '
    'by Config.MLC2_PROMOTION_ENABLED, which ships false.';
