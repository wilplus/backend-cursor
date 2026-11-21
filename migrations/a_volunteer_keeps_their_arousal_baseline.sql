-- a_volunteer_keeps_their_arousal_baseline
--
-- The small baseline JSON that wpl_arousal.build_baseline returns for one
-- anonymous volunteer: per-cue averages and spreads, no audio and no words.
-- The auth user id is not stored. The row goes with the volunteer key, so
-- an account purge that deletes the key takes it. DELETE /v2/experiments/me
-- deletes it too.
--
-- Read and written by the backend (service role) only. RLS scopes a
-- signed-in key to the volunteer id that key holds. The service role
-- bypasses RLS; the Flask code filters by volunteer_id as well.
--
-- Idempotent and additive. Nothing is dropped and no row is written.
-- One transaction.
--
-- Rollback (a new forward migration): leave the table. Removing it is a
-- separate, previewed retention operation.

BEGIN;

SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS public.experiment_volunteer_baselines (
    volunteer_id      TEXT PRIMARY KEY
        REFERENCES public.experiment_volunteer_keys (volunteer_id) ON DELETE CASCADE,
    baseline          JSONB NOT NULL,
    source_take_ids   JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT experiment_volunteer_baselines_id_hex
        CHECK (volunteer_id ~ '^[0-9a-f]{64}$'),
    CONSTRAINT experiment_volunteer_baselines_object
        CHECK (jsonb_typeof(baseline) = 'object'),
    CONSTRAINT experiment_volunteer_baselines_sources
        CHECK (jsonb_typeof(source_take_ids) = 'array')
);

ALTER TABLE public.experiment_takes
    ADD COLUMN IF NOT EXISTS analysis_state TEXT;

ALTER TABLE public.experiment_takes
    ADD COLUMN IF NOT EXISTS analysis_error TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.experiment_takes'::regclass
          AND conname = 'experiment_takes_analysis_state'
    ) THEN
        ALTER TABLE public.experiment_takes
            ADD CONSTRAINT experiment_takes_analysis_state
            CHECK (analysis_state IS NULL OR analysis_state IN
                ('queued', 'running', 'ready', 'failed'));
    END IF;
END
$$;

ALTER TABLE public.experiment_volunteer_baselines ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.experiment_volunteer_baselines FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.experiment_volunteer_baselines TO service_role;

DO $policies$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND policyname = 'experiment_baselines_own'
    ) THEN
        CREATE POLICY experiment_baselines_own ON public.experiment_volunteer_baselines
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
