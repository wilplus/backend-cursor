-- A Take names its recording as `recording_id` (founder 2026-09-26).
--
-- WHY. v2_sessions stores the Take's recording as `recording_1_id`, a name
-- left over from the three-recording homework flow. Code that asked the row
-- for `recording_id` got nothing back and no error: the Ideal Text retry
-- resolved no recording and, under PLF1 enforce, failed every Take with
-- PROCESSING_PRINCIPAL_UNRESOLVED ("Try creating it again" never worked).
--
-- STEP 1 OF 3 — THE SAFE RENAME. A direct RENAME COLUMN would break every
-- process still running the old code during a deploy (web and worker roll
-- separately), so this file only ADDS:
--
--   1. `recording_id`, the same type as `recording_1_id` (see below on keys);
--   2. a backfill copying every existing `recording_1_id` into it;
--   3. a trigger that keeps the two equal whichever one a writer sets, so
--      old code (writes `recording_1_id`) and new code (writes
--      `recording_id`) both leave a consistent row.
--
-- Step 2 moves the readers and writers to `recording_id`. Step 3 — removing
-- `recording_1_id` — is a separately authorized retention change, never a
-- side effect of a later migration.
--
-- ADDITIVE AND IDEMPOTENT: re-running it changes nothing. The only rows it
-- writes are the backfill, and only where `recording_id` is still NULL. The
-- existing v2_sessions trigger (ready_take_advances_...) fires on
-- `analysis_state` only, so the backfill does not wake it.

BEGIN;

-- NO FOREIGN KEY, deliberately. The new column is a MIRROR and must accept
-- exactly what recording_1_id accepts; a stricter constraint here would turn
-- the mirror trigger into a new way for a Take insert to fail (the rehearsal
-- tier's fixtures write recording_1_id values with no recordings row, and
-- production's own constraint on that column is not ours to assume). Where
-- recording_1_id does carry ON DELETE SET NULL, the trigger carries the NULL
-- across, so both names still clear together.
ALTER TABLE public.v2_sessions
    ADD COLUMN IF NOT EXISTS recording_id UUID NULL;

COMMENT ON COLUMN public.v2_sessions.recording_id IS
    'The Take''s recording (recordings.id). Kept equal to the legacy '
    'recording_1_id by v2_sessions_mirror_recording_id until that column is '
    'retired.';

CREATE OR REPLACE FUNCTION public.v2_sessions_mirror_recording_id_v1()
RETURNS trigger LANGUAGE plpgsql SET search_path=public AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NEW.recording_id IS NULL THEN
      NEW.recording_id := NEW.recording_1_id;
    ELSIF NEW.recording_1_id IS NULL THEN
      NEW.recording_1_id := NEW.recording_id;
    END IF;
    RETURN NEW;
  END IF;
  -- UPDATE: whichever column the statement changed wins. A statement that
  -- sets both is left exactly as written.
  IF NEW.recording_1_id IS DISTINCT FROM OLD.recording_1_id
     AND NEW.recording_id IS NOT DISTINCT FROM OLD.recording_id THEN
    NEW.recording_id := NEW.recording_1_id;
  ELSIF NEW.recording_id IS DISTINCT FROM OLD.recording_id
     AND NEW.recording_1_id IS NOT DISTINCT FROM OLD.recording_1_id THEN
    NEW.recording_1_id := NEW.recording_id;
  END IF;
  RETURN NEW;
END $$;

REVOKE ALL ON FUNCTION public.v2_sessions_mirror_recording_id_v1()
  FROM PUBLIC, anon, authenticated;

UPDATE public.v2_sessions
   SET recording_id = recording_1_id
 WHERE recording_id IS NULL
   AND recording_1_id IS NOT NULL;

DROP TRIGGER IF EXISTS v2_sessions_mirror_recording_id ON public.v2_sessions;
CREATE TRIGGER v2_sessions_mirror_recording_id
BEFORE INSERT OR UPDATE OF recording_id, recording_1_id ON public.v2_sessions
FOR EACH ROW EXECUTE FUNCTION public.v2_sessions_mirror_recording_id_v1();

COMMIT;
