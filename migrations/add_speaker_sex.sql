-- willab — self-declared SPEAKER SEX on user_settings.
--
-- WHY IT EXISTS (this is not a demographics field). The voice-confidence
-- composite (services/voice_confidence.py, the DELIVERY term of the L2
-- ranking blend) reads seven acoustic cues from Jiang & Pell 2017. One of
-- them REVERSES DIRECTION by speaker sex:
--
--     pitch variability (f0_sd):  wide range = CONFIDENT in women
--                                 wide range = UNCONFIDENT in men
--
-- Within-speaker z-scoring does NOT absorb that — it is a direction flip,
-- not a scale offset — so a single sex-blind weight actively mis-scores one
-- sex. Two more cues keep their direction but change strength (loudness
-- range matters more in women; pausing and loudness matter more in men).
-- Hence an explicit term, sourced from the speaker rather than guessed.
--
-- VALUES
--   'female' | 'male'         — routes the sex-specific cue weights.
--   'prefer_not_to_say'       — the user was asked and declined. DISTINCT
--                               from NULL, and load-bearing: the composite
--                               treats it as a hard opt-out and will NOT
--                               fall back to inferring sex from the pitch
--                               baseline. Sex-blind weights (the shipped
--                               v1 behaviour) are used instead.
--   NULL                      — never asked (every pre-existing user, and
--                               anyone who signed up before the field went
--                               live). Composite may route on the acoustic
--                               fallback; sex-blind if that is ambiguous.
--
-- NOT SURFACED. This value never appears in a coach packet, never enters a
-- score shown to a user (AC-9), and never becomes a badge. It selects a
-- weight vector, full stop.
--
-- RLS: user_settings already carries its own row-level policies (one row per
-- user, user_id is the PK) — an added column inherits them. No new table, so
-- nothing new to enable.
--
-- Run in the Supabase SQL Editor. Idempotent; safe to re-run.

ALTER TABLE user_settings
    ADD COLUMN IF NOT EXISTS profile_sex TEXT;

-- Enum guard (idempotent via pg_constraint probe). NULL always allowed —
-- the CHECK only constrains non-null values.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'user_settings_profile_sex_check'
    ) THEN
        ALTER TABLE user_settings
            ADD CONSTRAINT user_settings_profile_sex_check
            CHECK (
                profile_sex IS NULL OR profile_sex IN (
                    'female', 'male', 'prefer_not_to_say'
                )
            );
    END IF;
END$$;

COMMENT ON COLUMN user_settings.profile_sex IS
    'Self-declared speaker sex — an ACOUSTIC ROUTING key, not a '
    'demographic. Selects the cue weights of the voice-confidence '
    'composite (services/voice_confidence.py); one cue, pitch '
    'variability, reverses direction by sex (Jiang & Pell 2017). '
    'female|male route the sex-specific weights; prefer_not_to_say is a '
    'hard opt-out that also suppresses the acoustic fallback; NULL means '
    'never asked. Never surfaced to a user or on a coach packet (AC-9).';

NOTIFY pgrst, 'reload schema';
