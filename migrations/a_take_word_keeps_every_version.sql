-- a_take_word_keeps_every_version (0478; founder 2026-10-19, decisions log N79)
--
-- WHY. There is one coach_take_words row per (Take, coach) (0403). Each save
-- replaced the word and its video, each re-draft replaced the draft and its
-- prompt (0411, 0459), and nothing kept what was there before. The founder's
-- rule is that every old version stays in the history; for a coach's Take
-- word, no version did.
--
-- WHAT. coach_take_word_versions holds the row as it was whenever a write
-- replaces a word, a video, a draft or a transcript. Only the trigger
-- writes it, so no writer (upsert_coach_take_word, set_coach_take_word_draft,
-- set_coach_take_word_transcript, or a hand UPDATE) can skip it. A NULL
-- being filled in loses nothing and keeps no version. A transcript belongs
-- to its video: a new or removed video clears the transcript on the live
-- row (the app does too since #1131), and the old video with its words
-- stays here. Never shown to a speaker; not training data by itself (the
-- pairs are, under the speaker's yes, and only the latest version teaches,
-- 0477). Purged with the Take; a coach's words stay with the speaker (N79).
--
-- Additive and idempotent: CREATE TABLE / INDEX IF NOT EXISTS, CREATE OR
-- REPLACE, DROP TRIGGER IF EXISTS + CREATE. Nothing dropped, no row
-- written, no env var. CREATE TRIGGER takes a brief SHARE ROW EXCLUSIVE lock
-- on coach_take_words, a small table, with no rewrite or scan. The trigger
-- fails closed: if it errors, the coach's save fails, as the 0446 resolver
-- does, so the history is never silently incomplete. That is the coach's
-- path, never the speaker's record, process, Ideal Text loop.
--
-- Deploy with services/data_purge_registry.py's coach_take_word_versions
-- entry in the same PR: an unregistered table with take_session_id stops a
-- purge for review. Merge when no deletion is mid-run.
-- Released rehearsal lane only: it copies coach_take_words.draft_prompt (0459).

BEGIN;

CREATE TABLE IF NOT EXISTS public.coach_take_word_versions (
    id                  uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    take_word_id        uuid        NOT NULL
                        REFERENCES public.coach_take_words (id) ON DELETE CASCADE,
    take_session_id     text        NOT NULL,
    coach_id            text        NOT NULL,
    version             integer     NOT NULL,
    replaced            text        NOT NULL,
    text                text        NULL,
    video_ref           text        NULL,
    shared_at           timestamptz NULL,
    updated_at          timestamptz NOT NULL,
    draft_text          text        NULL,
    draft_model_version text        NULL,
    draft_prompt        jsonb       NULL,
    drafted_at          timestamptz NULL,
    transcript          text        NULL,
    transcribed_at      timestamptz NULL,
    superseded_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT coach_take_word_versions_once UNIQUE (take_word_id, version),
    CONSTRAINT coach_take_word_versions_positive CHECK (version >= 1),
    CONSTRAINT coach_take_word_versions_replaced
        CHECK (replaced IN ('word', 'draft', 'transcript'))
);
CREATE INDEX IF NOT EXISTS coach_take_word_versions_take_idx
    ON public.coach_take_word_versions (take_session_id);
ALTER TABLE public.coach_take_word_versions ENABLE ROW LEVEL SECURITY;
COMMENT ON TABLE public.coach_take_word_versions IS
    'Every Take word, video, draft and transcript a coach_take_words row had and '
    'no longer has (0478; founder 2026-10-19, N79). Written only by the trigger '
    'coach_take_word_keeps_its_versions; the live row is the current version. '
    'Never shown to a speaker; not training data by itself. Purged with the Take.';

CREATE OR REPLACE FUNCTION public.coach_take_word_keeps_its_versions_v1()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_word  boolean;
    v_draft boolean;
    v_heard boolean;
    v_next  integer;
BEGIN
    -- Only what would be lost counts: a NULL being filled in loses nothing.
    v_word := (OLD.text IS NOT NULL AND OLD.text IS DISTINCT FROM NEW.text)
           OR (OLD.video_ref IS NOT NULL AND OLD.video_ref IS DISTINCT FROM NEW.video_ref);
    v_draft := (OLD.draft_text IS NOT NULL AND OLD.draft_text IS DISTINCT FROM NEW.draft_text)
            OR (OLD.draft_prompt IS NOT NULL AND OLD.draft_prompt IS DISTINCT FROM NEW.draft_prompt)
            OR (OLD.draft_model_version IS NOT NULL
                AND OLD.draft_model_version IS DISTINCT FROM NEW.draft_model_version);
    -- A transcript belongs to the video it was made from.
    IF NEW.video_ref IS DISTINCT FROM OLD.video_ref THEN
        NEW.transcript := NULL;
        NEW.transcribed_at := NULL;
    END IF;
    v_heard := OLD.transcript IS NOT NULL AND OLD.transcript IS DISTINCT FROM NEW.transcript;
    IF v_word OR v_draft OR v_heard THEN
        -- The UPDATE holds this word's row lock, so versions are numbered in turn.
        SELECT COALESCE(max(version), 0) + 1 INTO v_next
          FROM public.coach_take_word_versions WHERE take_word_id = OLD.id;
        INSERT INTO public.coach_take_word_versions (
            take_word_id, take_session_id, coach_id, version, replaced,
            text, video_ref, shared_at, updated_at,
            draft_text, draft_model_version, draft_prompt, drafted_at,
            transcript, transcribed_at)
        VALUES (
            OLD.id, OLD.take_session_id, OLD.coach_id, v_next,
            CASE WHEN v_word THEN 'word' WHEN v_draft THEN 'draft' ELSE 'transcript' END,
            OLD.text, OLD.video_ref, OLD.shared_at, OLD.updated_at,
            OLD.draft_text, OLD.draft_model_version, OLD.draft_prompt, OLD.drafted_at,
            OLD.transcript, OLD.transcribed_at);
    END IF;
    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.coach_take_word_keeps_its_versions_v1() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.coach_take_word_keeps_its_versions_v1() FROM anon, authenticated;

DROP TRIGGER IF EXISTS coach_take_word_keeps_its_versions ON public.coach_take_words;
CREATE TRIGGER coach_take_word_keeps_its_versions
    BEFORE UPDATE ON public.coach_take_words
    FOR EACH ROW EXECUTE FUNCTION public.coach_take_word_keeps_its_versions_v1();

-- Only the trigger writes the history. The app may read it; the purge deletes it.
REVOKE ALL ON TABLE public.coach_take_word_versions FROM PUBLIC;
REVOKE ALL ON TABLE public.coach_take_word_versions FROM anon, authenticated, service_role;
GRANT SELECT, DELETE ON TABLE public.coach_take_word_versions TO service_role;

COMMIT;
