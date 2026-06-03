-- willab beta — one-time user PROFILE (design §2 / contract §1/§3.1).
--
-- The intake captures the user's self-declared {domain, goal}. This is
-- the SOURCE that the derived fields already on user_settings
-- (inferred_learner_profile, baseline_summary) build on — so it lives
-- here, co-located with its lineage, rather than on v2_speaker_profiles
-- (which is the ADMIN-authored coach-notes table: main_goal/coach_notes
-- are the coach's words about the student, a different axis from the
-- user's own intake). One row per user — user_settings.user_id is the PK.
--
--   profile_domain  TEXT  — one of the five intake domains (design §2).
--                           CHECK enum; NULL until intake submitted.
--   profile_goal    TEXT  — the user's goal in their own words (the one
--                           genuine free-text turn of intake). NULL
--                           until submitted; the Lab shows it read-only.
--
-- Distinct from v2_speaker_profiles.main_goal (admin-authored) by design
-- — do not merge the two; the split-sink spirit (user-declared vs
-- admin-authored) applies here too.
--
-- Idempotent. Safe to re-run.

ALTER TABLE user_settings
    ADD COLUMN IF NOT EXISTS profile_domain TEXT,
    ADD COLUMN IF NOT EXISTS profile_goal TEXT;

-- Enum guard (idempotent via pg_constraint probe). NULL allowed
-- (pre-intake); the CHECK only constrains non-null values.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'user_settings_profile_domain_check'
    ) THEN
        ALTER TABLE user_settings
            ADD CONSTRAINT user_settings_profile_domain_check
            CHECK (
                profile_domain IS NULL OR profile_domain IN (
                    'public_speaking', 'sales', 'executive_presence',
                    'customer_service', 'interview_prep'
                )
            );
    END IF;
END$$;

COMMENT ON COLUMN user_settings.profile_domain IS
    'willab beta §2 — user-self-declared intake domain (one of five). '
    'Metadata, never a flow fork. NULL pre-intake. Distinct from '
    'v2_speaker_profiles (admin coach-notes).';

COMMENT ON COLUMN user_settings.profile_goal IS
    'willab beta §2 — user-self-declared goal in their own words '
    '(intake free-text turn). Feeds inferred_learner_profile / '
    'baseline_summary. NULL pre-intake.';

NOTIFY pgrst, 'reload schema';
