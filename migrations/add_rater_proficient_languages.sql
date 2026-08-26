-- One explicit language-eligibility profile for blind confidence raters.
-- This routes queues only. It never changes a rating, user feedback, model
-- score, styling decision, or Voice Album eligibility.

ALTER TABLE public.user_settings
    ADD COLUMN IF NOT EXISTS profile_proficient_languages TEXT[];

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'user_settings_proficient_languages_check'
    ) THEN
        ALTER TABLE public.user_settings
            ADD CONSTRAINT user_settings_proficient_languages_check
            CHECK (
                profile_proficient_languages IS NULL
                OR (
                    cardinality(profile_proficient_languages) BETWEEN 1 AND 20
                    AND array_to_string(profile_proficient_languages, ',')
                        ~ '^[a-z]{2}(,[a-z]{2})*$'
                )
            );
    END IF;
END$$;

COMMENT ON COLUMN public.user_settings.profile_proficient_languages IS
    'Self-declared ISO-639-1 languages the rater understands well enough to '
    'judge vocal confidence. Queue-routing only; never a label or score.';

NOTIFY pgrst, 'reload schema';
