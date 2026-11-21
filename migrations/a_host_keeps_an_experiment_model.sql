-- a_host_keeps_an_experiment_model
--
-- A host's own experiment model, beside the built-in one that lives in
-- code. The auth user id is not stored: the row names the opaque
-- volunteer id. It goes with that key, so an account purge that deletes
-- the key takes it. DELETE /v2/experiments/me deletes it too.
--
-- experiment_takes.model_id records which catalog id a queued analysis
-- used. No new grant is needed for that column.
--
-- Read and written by the backend (service role) only. RLS scopes a
-- signed-in key to the volunteer id that key holds.
--
-- Idempotent and additive. Nothing is dropped and no row is written.
-- One transaction.
--
-- Rollback (a new forward migration): leave the table and the column.

BEGIN;

SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS public.experiment_models (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    volunteer_id          TEXT NOT NULL
        REFERENCES public.experiment_volunteer_keys (volunteer_id) ON DELETE CASCADE,
    name                  TEXT NOT NULL,
    base_model_id         TEXT NOT NULL,
    measures              TEXT NOT NULL,
    baseline_prompt_ids   JSONB NOT NULL DEFAULT '[]'::jsonb,
    overrides             JSONB,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT experiment_models_volunteer_hex
        CHECK (volunteer_id ~ '^[0-9a-f]{64}$'),
    CONSTRAINT experiment_models_name_len
        CHECK (char_length(name) BETWEEN 1 AND 80),
    CONSTRAINT experiment_models_measures_len
        CHECK (char_length(measures) BETWEEN 1 AND 200),
    CONSTRAINT experiment_models_base_len
        CHECK (char_length(base_model_id) BETWEEN 1 AND 80),
    CONSTRAINT experiment_models_prompts_list
        CHECK (jsonb_typeof(baseline_prompt_ids) = 'array'),
    CONSTRAINT experiment_models_overrides_object
        CHECK (overrides IS NULL OR jsonb_typeof(overrides) = 'object')
);

CREATE INDEX IF NOT EXISTS experiment_models_volunteer_idx
    ON public.experiment_models (volunteer_id, created_at DESC);

ALTER TABLE public.experiment_takes
    ADD COLUMN IF NOT EXISTS model_id TEXT;

ALTER TABLE public.experiment_models ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.experiment_models FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.experiment_models TO service_role;

DO $policies$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND policyname = 'experiment_models_own'
    ) THEN
        CREATE POLICY experiment_models_own ON public.experiment_models
            FOR ALL
            USING (volunteer_id IN (
                SELECT k.volunteer_id FROM public.experiment_volunteer_keys k
                WHERE k.user_id = auth.uid()))
            WITH CHECK (volunteer_id IN (
                SELECT k.volunteer_id FROM public.experiment_volunteer_keys k
                WHERE k.user_id = auth.uid()));
    END IF;
END
$policies$;

NOTIFY pgrst, 'reload schema';

COMMIT;
