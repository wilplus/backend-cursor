-- a_coach_video_belongs_to_its_speaker (0477)
--
-- WHY. A coach's exercise video was filed into the one shared library
-- (diagnostic_exercise has no owner), so a video a coach recorded for one
-- speaker's moment was served by itself to any speaker whose clip showed the
-- same error, from their first Take, at a public link. Coach praise lines
-- went the same way into feedback_catalogue. The founder (Claude Code
-- session, 18 October 2026; decisions log N77): a coach video belongs to the
-- speaker it was made for; the app matches only inside that speaker's own
-- set; the shared library holds only what the founder makes or approves;
-- coach praise lines follow the same rule.
--
-- Revised 19 October (decisions log N78): two kinds of coach video. An
-- exercise video goes to the speaker it was made for at once, and to every
-- speaker whose recording fits it once the founder approves it. A direct
-- message (an answer on a moment, the word for a Take) is never shared.
--
-- WHAT.
--   1. diagnostic_exercise.owner_user_id. NULL is the shared library; set,
--      the row is a coach video for that one speaker and no other speaker,
--      coach list or library page sees it. review_decision / reviewed_at /
--      reviewed_by: the founder's review of a coach's exercise video,
--      'approved' for everyone (the owner is cleared in the same write) or
--      'kept' for its speaker.
--   2. diagnostic_exercise_version.owner_user_id, copied from the live row
--      when the version is written (the live row is upserted first), so a
--      speaker's versions go with their account. The immutability guard
--      admits one more transition: owner NULL -> a speaker, nothing else
--      changed (the founder-approved backfill of the rows filed before this).
--   3. speaker_exercise_set: the exercises the app may serve ONE speaker by
--      itself after a Take -- their own coach videos, and library exercises
--      a coach picked for one of their moments.
--   4. feedback_catalogue.owner_user_id and request_id: a coach's praise
--      line serves the speaker it was written for, and no one else.
--
-- Additive and idempotent: ADD COLUMN IF NOT EXISTS, CREATE ... IF NOT
-- EXISTS, CREATE OR REPLACE. Nothing dropped, nothing deleted. No env var.
-- Every existing row keeps owner NULL until the backfill (step 2), which
-- the founder approves before it runs. The rehearsal database has no
-- diagnostic_exercise, so parts 1 and 2 run only where the tables exist.

-- 1 · the owner on the live exercise, and the founder's approval ----------
-- 19 October (N78): an exercise video a coach made for one speaker is
-- shared with every speaker whose recording fits it once the founder
-- approves it. The founder's review is recorded here: 'approved' (the
-- owner is cleared in the same write, so the row is the library's and
-- stays when that speaker leaves) or 'kept' (it stays with its speaker and
-- leaves the review list); who, and when.
ALTER TABLE IF EXISTS public.diagnostic_exercise
    ADD COLUMN IF NOT EXISTS owner_user_id TEXT NULL
        CHECK (owner_user_id IS NULL OR length(owner_user_id) > 0),
    ADD COLUMN IF NOT EXISTS review_decision TEXT NULL
        CHECK (review_decision IS NULL OR review_decision IN ('approved', 'kept')),
    ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS reviewed_by TEXT NULL;

DO $$
BEGIN
    IF to_regclass('public.diagnostic_exercise') IS NOT NULL THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_diagnostic_exercise_owner '
             || 'ON public.diagnostic_exercise (owner_user_id) '
             || 'WHERE owner_user_id IS NOT NULL';
        EXECUTE 'COMMENT ON COLUMN public.diagnostic_exercise.owner_user_id IS '
             || quote_literal('NULL: the founder''s shared library. Set: a '
             || 'coach video for this one speaker, served to no one else (0477).');
    END IF;
END $$;

-- 2 · the owner on each version --------------------------------------------
ALTER TABLE IF EXISTS public.diagnostic_exercise_version
    ADD COLUMN IF NOT EXISTS owner_user_id TEXT NULL
        CHECK (owner_user_id IS NULL OR length(owner_user_id) > 0);

-- The version row takes the live row's owner as it is written.
CREATE OR REPLACE FUNCTION public.exercise_version_takes_its_owner_v1()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = public
AS $$
BEGIN
    -- The library may be absent (the rehearsal database): no owner then.
    IF NEW.owner_user_id IS NULL
       AND to_regclass('public.diagnostic_exercise') IS NOT NULL THEN
        EXECUTE 'SELECT owner_user_id FROM public.diagnostic_exercise '
             || 'WHERE exercise_id = $1'
           INTO NEW.owner_user_id USING NEW.exercise_id;
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION public.exercise_version_takes_its_owner_v1()
    FROM PUBLIC, anon, authenticated;

-- Immutable, except the one transcript transition (0399) and, from 0477,
-- the one owner transition: NULL to a speaker with nothing else changed.
CREATE OR REPLACE FUNCTION public.guard_exercise_version_update_v1()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = public
AS $$
BEGIN
    IF NEW.owner_user_id IS DISTINCT FROM OLD.owner_user_id THEN
        IF OLD.owner_user_id IS NULL
           AND (to_jsonb(NEW) - 'owner_user_id')
               = (to_jsonb(OLD) - 'owner_user_id')
        THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'EXERCISE_VERSION_IMMUTABLE';
    END IF;
    IF OLD.transcript_status <> 'pending'
       OR NEW.transcript_status NOT IN ('done', 'failed', 'coach_authorization_missing')
       OR NEW.id IS DISTINCT FROM OLD.id
       OR NEW.exercise_id IS DISTINCT FROM OLD.exercise_id
       OR NEW.version IS DISTINCT FROM OLD.version
       OR NEW.title IS DISTINCT FROM OLD.title
       OR NEW.instruction IS DISTINCT FROM OLD.instruction
       OR NEW.introduction_copy IS DISTINCT FROM OLD.introduction_copy
       OR NEW.confident_introduction_copy IS DISTINCT FROM OLD.confident_introduction_copy
       OR NEW.acoustic_problem_tags IS DISTINCT FROM OLD.acoustic_problem_tags
       OR NEW.supported_confidence_patterns IS DISTINCT FROM OLD.supported_confidence_patterns
       OR NEW.matching_criteria IS DISTINCT FROM OLD.matching_criteria
       OR NEW.ai_draft_text IS DISTINCT FROM OLD.ai_draft_text
       OR NEW.ai_draft_model_version IS DISTINCT FROM OLD.ai_draft_model_version
       OR NEW.explanation_video_url IS DISTINCT FROM OLD.explanation_video_url
       OR NEW.video_sha256 IS DISTINCT FROM OLD.video_sha256
       OR NEW.video_bytes IS DISTINCT FROM OLD.video_bytes
       OR NEW.source IS DISTINCT FROM OLD.source
       OR NEW.created_by IS DISTINCT FROM OLD.created_by
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
    THEN
        RAISE EXCEPTION 'EXERCISE_VERSION_IMMUTABLE';
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION public.guard_exercise_version_update_v1()
    FROM PUBLIC, anon, authenticated;

DO $$
BEGIN
    IF to_regclass('public.diagnostic_exercise_version') IS NOT NULL THEN
        EXECUTE 'DROP TRIGGER IF EXISTS diagnostic_exercise_version_owner '
             || 'ON public.diagnostic_exercise_version';
        EXECUTE 'CREATE TRIGGER diagnostic_exercise_version_owner '
             || 'BEFORE INSERT ON public.diagnostic_exercise_version '
             || 'FOR EACH ROW EXECUTE FUNCTION public.exercise_version_takes_its_owner_v1()';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_diagnostic_exercise_version_owner '
             || 'ON public.diagnostic_exercise_version (owner_user_id) '
             || 'WHERE owner_user_id IS NOT NULL';
    END IF;
END $$;

-- 3 · each speaker's own set -----------------------------------------------
-- No foreign key to diagnostic_exercise: the reader keeps only rows that are
-- live (active, with a video), so a retired exercise simply stops serving,
-- and the table stands where the library does not (the rehearsal database).
CREATE TABLE IF NOT EXISTS public.speaker_exercise_set (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_user_id TEXT        NOT NULL CHECK (length(owner_user_id) > 0),
    exercise_id   TEXT        NOT NULL CHECK (length(exercise_id) > 0),
    source        TEXT        NOT NULL CHECK (source IN ('coach_made', 'coach_pick')),
    source_id     TEXT        NULL,
    added_by      TEXT        NOT NULL DEFAULT '',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT speaker_exercise_set_once UNIQUE (owner_user_id, exercise_id)
);

COMMENT ON TABLE public.speaker_exercise_set IS
    'The exercises the app may serve one speaker by itself after a Take: '
    'their own coach videos and library exercises a coach picked for them '
    '(0477, decisions log N77). Goes with the speaker''s account.';

ALTER TABLE public.speaker_exercise_set ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.speaker_exercise_set FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, DELETE ON public.speaker_exercise_set TO service_role;

-- 4 · the owner on a coach's praise line -------------------------------------
ALTER TABLE IF EXISTS public.feedback_catalogue
    ADD COLUMN IF NOT EXISTS owner_user_id TEXT NULL
        CHECK (owner_user_id IS NULL OR length(owner_user_id) > 0),
    ADD COLUMN IF NOT EXISTS request_id UUID NULL;

DO $$
BEGIN
    IF to_regclass('public.feedback_catalogue') IS NOT NULL THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_feedback_catalogue_owner '
             || 'ON public.feedback_catalogue (owner_user_id) '
             || 'WHERE owner_user_id IS NOT NULL';
    END IF;
END $$;
