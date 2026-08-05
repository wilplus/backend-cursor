-- willab — SELF-DECLARED NATIVE LANGUAGE (L1) on user_settings.
-- Written 2026-08-05.
-- (SPEC.md v3 D25, Appendix G §G.6/§G.10; backlog process PM-4.)
--
-- WHY IT EXISTS. Differential Item Functioning (Appendix G.6) asks whether a
-- dimension behaves differently for a subgroup AT THE SAME ABILITY — i.e. "is
-- this dimension penalising non-native speakers for something other than the
-- skill it claims to measure?" DIF cannot run without a stored subgroup flag.
-- Speaker sex already exists (user_settings.profile_sex, migration 0223).
-- Nativeness does not. This is that column.
--
-- WHY NOT A BOOLEAN. "Is this speaker native?" HAS NO USER-LEVEL ANSWER.
-- Nativeness is a relation between the speaker and the language of the talk: a
-- native Polish speaker is native when presenting in Polish and non-native when
-- presenting in English. A user-level `is_native` flag would be wrong for one
-- of those two recordings and there is no way to tell which.
--
-- Stored instead: the speaker's L1. Nativeness is DERIVED per recording:
--
--     native  <=>  user_settings.profile_native_language
--                    = recordings.transcription_language
--
-- This is strictly more informative than a boolean — it also permits
-- stratifying by language family later, which is the level at which
-- transfer effects actually operate.
--
-- WHY recordings.transcription_language IS NOT A SUBSTITUTE ON ITS OWN. It is
-- the language the audio was transcribed in, not a property of the speaker. A
-- native Polish speaker presenting in English reads as `en` — identical to a
-- native English speaker. Using it alone as a nativeness proxy would put
-- fluent non-natives and natives in the SAME stratum and hide exactly the DIF
-- the audit exists to find.
--
-- VALUES (mirroring the profile_sex design deliberately — same precedent,
-- same reasoning, so the two subgroup fields behave identically):
--   ISO 639-1 code       'en' | 'pl' | 'es' | 'de' | ... the speaker's L1.
--   'prefer_not_to_say'  the user was asked and declined. DISTINCT from NULL
--                        and load-bearing: DIF must EXCLUDE these rows from
--                        strata entirely, never fold them into either group.
--                        Folding a declining user into a group invents a
--                        subgroup membership they refused to give.
--   NULL                 never asked. Every pre-existing user. Also excluded
--                        from strata, but for a different reason worth keeping
--                        separable: absence of an answer, not refusal of one.
--
-- NOT SURFACED (AC-9). This value never appears in a coach packet, never
-- enters a score shown to a user, and never becomes a badge. It selects a DIF
-- stratum, full stop. Same standing as profile_sex.
--
-- D25 — WHAT THIS FIELD MAY AND MAY NOT DRIVE. It feeds the DIF audit, which
-- REPORTS. It never drives an automatic weight change. A category C finding
-- holds the dimension and raises a PM-2 agenda item for the founder. No
-- automated adjustment on a protected attribute, in either direction, ever.
--
-- Nothing here drops a table or a column (standing constraint).
-- Idempotent; safe to re-run. Run in the Supabase SQL Editor.

ALTER TABLE user_settings
    ADD COLUMN IF NOT EXISTS profile_native_language TEXT;

-- Shape guard. Deliberately NOT an enum of known languages: a closed list
-- would silently reject a speaker whose L1 we had not thought of, which is
-- precisely the population this column exists to protect. Constrain the SHAPE
-- (two lowercase letters) and the one sentinel; leave the set open.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'user_settings_profile_native_language_check'
    ) THEN
        ALTER TABLE user_settings
            ADD CONSTRAINT user_settings_profile_native_language_check
            CHECK (
                profile_native_language IS NULL
                OR profile_native_language = 'prefer_not_to_say'
                OR profile_native_language ~ '^[a-z]{2}$'
            );
    END IF;
END$$;

CREATE INDEX IF NOT EXISTS idx_user_settings_profile_native_language
    ON user_settings (profile_native_language)
    WHERE profile_native_language IS NOT NULL
      AND profile_native_language <> 'prefer_not_to_say';

COMMENT ON COLUMN user_settings.profile_native_language IS
    'Self-declared L1 (ISO 639-1), a DIF STRATIFICATION key, not a '
    'demographic. Nativeness for a recording is derived: profile_native_'
    'language = recordings.transcription_language. A user-level boolean would '
    'be wrong, because nativeness is relative to the language of the talk. '
    'prefer_not_to_say is a refusal and NULL is never-asked; BOTH are excluded '
    'from DIF strata and kept separable. Never surfaced to a user or on a '
    'coach packet (AC-9). Feeds an audit that reports; it never drives an '
    'automatic weight change (SPEC D25).';

NOTIFY pgrst, 'reload schema';

-- down:
--   alter table user_settings drop column if exists profile_native_language;
