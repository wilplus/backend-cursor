-- the_ai_clip_can_practise_fillers (0475)
--
-- WHY. The AI clip (0462) practises one problem per sentence: pace, pause
-- or stress. The founder (2026-10-18, Linear "Evaluate retaining filler
-- words in transcripts") added a fourth: fillers. The transcript stays
-- clean (the smoothing fence of 2026-07-20 keeps removing "um" and "uh"
-- silently); the speaker learns about their fillers in the clip, which says
-- the sentence without them, with one signed sentence under the player.
--
-- WHAT. The CHECK on ai_voice_cycles.exercise admits 'fillers'. Nothing is
-- dropped but the old constraint, which is put back wider in the same
-- statement list. Idempotent: the constraint on the column is found by its
-- column, whatever its name, and the new one is added by name.

DO $$
DECLARE
    c RECORD;
BEGIN
    FOR c IN
        SELECT conname
          FROM pg_constraint
         WHERE conrelid = 'public.ai_voice_cycles'::regclass
           AND contype = 'c'
           AND conkey = ARRAY[(SELECT attnum FROM pg_attribute
                                WHERE attrelid = 'public.ai_voice_cycles'::regclass
                                  AND attname = 'exercise')]
    LOOP
        EXECUTE format('ALTER TABLE public.ai_voice_cycles DROP CONSTRAINT %I', c.conname);
    END LOOP;
END $$;

ALTER TABLE public.ai_voice_cycles
    ADD CONSTRAINT ai_voice_cycles_exercise_check
    CHECK (exercise IN ('pace', 'pause', 'stress', 'fillers'));

COMMENT ON COLUMN public.ai_voice_cycles.exercise IS
    'The one problem the clip practises: pace, pause, stress or fillers (0475).';
