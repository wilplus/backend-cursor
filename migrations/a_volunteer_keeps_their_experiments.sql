-- a_volunteer_keeps_their_experiments
--
-- A private experiments area for one volunteer at a time. The auth user id
-- lives only on experiment_volunteer_keys, so a deletion can find the row
-- and so a direct PostgREST read (auth.uid()) can see only that volunteer's
-- id. Sessions, takes, prompts and interventions store the opaque
-- volunteer_id and no auth id. The Flask service also filters every read
-- by that id. The service role bypasses these policies; the policies are
-- the door if a grant is ever added for a signed-in key.
--
--   experiment_volunteer_keys   user_id, volunteer_id, researcher_consent
--   experiment_sessions         one sitting, its consent, an optional file
--   experiment_takes            the recording's words and where the audio is
--   experiment_prompts          the volunteer's own prompt library
--   experiment_interventions    a grid pattern, a threshold and a rule
--
-- Audio and the optional file go in the private bucket
-- experiment-recordings. DELETE /v2/experiments/me removes those objects.
-- Dropping the key row cascades the other rows. No environment variable is
-- required for the migration. The volunteer id's pepper is
-- EXPERIMENTS_VOLUNTEER_PEPPER, read by the service, never stored here.
--
-- Idempotent and additive. Nothing is dropped and no row is written except
-- the bucket's own row (ON CONFLICT DO NOTHING). One transaction.
--
-- Rollback (a new forward migration): leave the tables. Removing them is a
-- separate, previewed retention operation.

BEGIN;

SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS public.experiment_volunteer_keys (
    user_id              UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    volunteer_id         TEXT NOT NULL UNIQUE,
    researcher_consent   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT experiment_volunteer_keys_id_hex
        CHECK (volunteer_id ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS public.experiment_sessions (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    volunteer_id          TEXT NOT NULL REFERENCES public.experiment_volunteer_keys(volunteer_id) ON DELETE CASCADE,
    consent               JSONB NOT NULL,
    business_case_path    TEXT,
    business_case_name    TEXT,
    business_case_type    TEXT,
    business_case_text    TEXT NOT NULL DEFAULT '',
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT experiment_sessions_volunteer_hex
        CHECK (volunteer_id ~ '^[0-9a-f]{64}$'),
    CONSTRAINT experiment_sessions_consent_object
        CHECK (jsonb_typeof(consent) = 'object'),
    CONSTRAINT experiment_sessions_case_name
        CHECK (business_case_name IS NULL OR char_length(business_case_name) BETWEEN 1 AND 200)
);

CREATE INDEX IF NOT EXISTS experiment_sessions_volunteer_idx
    ON public.experiment_sessions (volunteer_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.experiment_takes (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_session_id   UUID NOT NULL REFERENCES public.experiment_sessions(id) ON DELETE CASCADE,
    volunteer_id            TEXT NOT NULL REFERENCES public.experiment_volunteer_keys(volunteer_id) ON DELETE CASCADE,
    prompt_id               TEXT NOT NULL,
    tag                     TEXT NOT NULL,
    self_rating             JSONB NOT NULL,
    transcript              TEXT NOT NULL DEFAULT '',
    words                   JSONB NOT NULL DEFAULT '[]'::jsonb,
    audio_path              TEXT,
    audio_type              TEXT,
    seconds                 DOUBLE PRECISION NOT NULL DEFAULT 0,
    features                JSONB,
    analysis                JSONB,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT experiment_takes_volunteer_hex
        CHECK (volunteer_id ~ '^[0-9a-f]{64}$'),
    CONSTRAINT experiment_takes_tag_len
        CHECK (char_length(tag) BETWEEN 1 AND 40),
    CONSTRAINT experiment_takes_prompt_len
        CHECK (char_length(prompt_id) BETWEEN 1 AND 80),
    CONSTRAINT experiment_takes_rating_object
        CHECK (jsonb_typeof(self_rating) = 'object'),
    CONSTRAINT experiment_takes_words_list
        CHECK (jsonb_typeof(words) = 'array'),
    CONSTRAINT experiment_takes_features_object
        CHECK (features IS NULL OR jsonb_typeof(features) = 'object'),
    CONSTRAINT experiment_takes_analysis_object
        CHECK (analysis IS NULL OR jsonb_typeof(analysis) = 'object')
);

CREATE INDEX IF NOT EXISTS experiment_takes_volunteer_idx
    ON public.experiment_takes (volunteer_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.experiment_prompts (
    volunteer_id   TEXT NOT NULL REFERENCES public.experiment_volunteer_keys(volunteer_id) ON DELETE CASCADE,
    prompt_id      TEXT NOT NULL,
    tag            TEXT NOT NULL,
    text           TEXT NOT NULL,
    reference      TEXT,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (volunteer_id, prompt_id),
    CONSTRAINT experiment_prompts_volunteer_hex
        CHECK (volunteer_id ~ '^[0-9a-f]{64}$'),
    CONSTRAINT experiment_prompts_tag_len
        CHECK (char_length(tag) BETWEEN 1 AND 40),
    CONSTRAINT experiment_prompts_text_len
        CHECK (char_length(text) BETWEEN 1 AND 4000),
    CONSTRAINT experiment_prompts_reference
        CHECK (reference IS NULL OR reference = 'business_case')
);

CREATE TABLE IF NOT EXISTS public.experiment_interventions (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    volunteer_id   TEXT NOT NULL REFERENCES public.experiment_volunteer_keys(volunteer_id) ON DELETE CASCADE,
    grid           JSONB NOT NULL,
    threshold      DOUBLE PRECISION NOT NULL,
    rule           JSONB NOT NULL,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT experiment_interventions_volunteer_hex
        CHECK (volunteer_id ~ '^[0-9a-f]{64}$'),
    CONSTRAINT experiment_interventions_grid_object
        CHECK (jsonb_typeof(grid) = 'object'),
    CONSTRAINT experiment_interventions_rule_object
        CHECK (jsonb_typeof(rule) = 'object'),
    CONSTRAINT experiment_interventions_threshold
        CHECK (threshold >= 0 AND threshold <= 2)
);

CREATE INDEX IF NOT EXISTS experiment_interventions_volunteer_idx
    ON public.experiment_interventions (volunteer_id, created_at);

ALTER TABLE public.experiment_volunteer_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.experiment_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.experiment_takes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.experiment_prompts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.experiment_interventions ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.experiment_volunteer_keys FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.experiment_sessions FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.experiment_takes FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.experiment_prompts FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.experiment_interventions FROM PUBLIC, anon, authenticated;

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.experiment_volunteer_keys TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.experiment_sessions TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.experiment_takes TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.experiment_prompts TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.experiment_interventions TO service_role;

-- Own rows only. The key matches auth.uid(); the other tables match the
-- volunteer id that key holds. service_role bypasses this. The backend
-- filters by volunteer_id as well.
DO $policies$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND policyname = 'experiment_keys_own'
    ) THEN
        CREATE POLICY experiment_keys_own ON public.experiment_volunteer_keys
            FOR ALL
            USING (user_id = auth.uid())
            WITH CHECK (user_id = auth.uid());
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND policyname = 'experiment_sessions_own'
    ) THEN
        CREATE POLICY experiment_sessions_own ON public.experiment_sessions
            FOR ALL
            USING (volunteer_id IN (
                SELECT k.volunteer_id FROM public.experiment_volunteer_keys k
                WHERE k.user_id = auth.uid()))
            WITH CHECK (volunteer_id IN (
                SELECT k.volunteer_id FROM public.experiment_volunteer_keys k
                WHERE k.user_id = auth.uid()));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND policyname = 'experiment_takes_own'
    ) THEN
        CREATE POLICY experiment_takes_own ON public.experiment_takes
            FOR ALL
            USING (volunteer_id IN (
                SELECT k.volunteer_id FROM public.experiment_volunteer_keys k
                WHERE k.user_id = auth.uid()))
            WITH CHECK (volunteer_id IN (
                SELECT k.volunteer_id FROM public.experiment_volunteer_keys k
                WHERE k.user_id = auth.uid()));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND policyname = 'experiment_prompts_own'
    ) THEN
        CREATE POLICY experiment_prompts_own ON public.experiment_prompts
            FOR ALL
            USING (volunteer_id IN (
                SELECT k.volunteer_id FROM public.experiment_volunteer_keys k
                WHERE k.user_id = auth.uid()))
            WITH CHECK (volunteer_id IN (
                SELECT k.volunteer_id FROM public.experiment_volunteer_keys k
                WHERE k.user_id = auth.uid()));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND policyname = 'experiment_interventions_own'
    ) THEN
        CREATE POLICY experiment_interventions_own ON public.experiment_interventions
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

INSERT INTO storage.buckets (id, name, public)
VALUES ('experiment-recordings', 'experiment-recordings', false)
ON CONFLICT (id) DO NOTHING;

NOTIFY pgrst, 'reload schema';

COMMIT;
