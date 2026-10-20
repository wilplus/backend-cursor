-- each_answer_keeps_what_the_coach_saw (0482; founder 2026-10-19, decisions log N79)
--
-- WHY. A coach answers a speaker's moment (exercise_coach_requests, 0385+;
-- a changed answer's old one is kept in exercise_coach_request_answer_versions,
-- 0446) or leaves a word on the Take (coach_take_words, 0403; every earlier
-- version in coach_take_word_versions, 0479). What the coach was looking at
-- when they answered was kept nowhere: the words of the clip, the error type
-- they had picked (coach_moment_diagnoses, 0445, which go when the coach's
-- account is purged) and the Ideal Text the Take had. Some of it can be
-- joined back later, but only while nothing is re-cut, replaced or purged.
--
-- WHAT. coach_answer_situations: one row per answer given, frozen when it is
-- given (captured = 'at_answer'). Its columns:
--   * request_id and answered_at = the resolver's resolved_at, for a first
--     answer, each change and each new video on a given answer (0446). This
--     is NOT the request's own answered_at, which is when the SPEAKER judged
--     the moment (0408). A replaced answer finds its history row on
--     (request_id, resolved_at);
--   * or take_word_id and answered_at = the word row's updated_at, one row
--     per save of a Take word. This is NOT an equality key into the 0479
--     history: a re-draft bumps updated_at too. The words a save describes
--     are on the lowest-numbered coach_take_word_versions row of that word
--     whose updated_at >= answered_at, or, when there is none, on the live
--     coach_take_words row;
--   * kind (the request's answer_kind, else its kind; NULL for a Take word),
--     pattern_key (the pattern the coach named on the Home screen, NULL when
--     they named none), passage_text (the clip's transcript, uncut; for a
--     Take word, every clip of the Take and of its mid-take re-reads, joined
--     in the order the coach's packet folds them) and slide_index (the
--     coach's slide correction when there is one, as the document reads it,
--     else the clip's metrics.piece.slide_index);
--   * the coach's current diagnosis, both by id (diagnosis_ids:
--     coach_moment_diagnoses.id, no foreign key) and copied (diagnoses: a
--     JSON array of {diagnosis_id, snippet_id, kind, error_id,
--     named_error_id, label}), so the error type stays with the answer when
--     the coach's account is purged (N79). For a Take word, every moment of
--     the Take and its re-reads this coach diagnosed;
--   * the Ideal Text pinned to the answered Take: the newest
--     ideal_text_document_snapshots row of the Take's arc whose
--     source_take_session_id is the Take (0315), by id and version. A
--     mid-take re-read is never a snapshot's source, so a moment answered on
--     one (take_session_id is the re-read's, as on its request) is pinned to
--     the spoken Take it is folded into. This is never the speaker's current
--     head, which may already belong to a later Take. No foreign key: the
--     snapshot is purged with the person, this row with the Take.
-- Insert-only. A second write of the same answer is ignored (the two UNIQUE
-- keys, used as ON CONFLICT DO NOTHING), and a trigger refuses every UPDATE,
-- whoever asks. 'reconstructed' is reserved for a separately reviewed
-- catch-up of past answers; this file writes no row.
--
-- The app writes a row after each answer and each Take-word save
-- (services/coach_answer_situation.py), never for a coach answering their
-- own Take (L3), best effort, off the coach's request in a daemon thread and
-- never in the coach's way. It copies only what the database already holds
-- and calls no provider.
--
-- CAPTURE ONLY. No training, release, golden or promotion reader, and no
-- speaker or coach payload, reads this table. 0445's rule that a diagnosis
-- is "never a training label" stays in force, as written there, until the
-- founder's single privacy update names this table among the new training
-- uses. Every row belongs to the speaker's Take and is purged with it
-- (services/data_purge_registry.py, coach_answer_situations, order 57,
-- before the request and the Take word, whose cascades are only the
-- backstop). No by-coach entry: a coach's words and the error type they
-- picked stay with the speaker's Take (N79). The table holds no coach id.
--
-- Additive and idempotent: CREATE TABLE / INDEX IF NOT EXISTS, CREATE OR
-- REPLACE FUNCTION, DROP TRIGGER IF EXISTS + CREATE TRIGGER (on the new table
-- only), REVOKE and GRANT, COMMENT. Nothing dropped, no row written, no env
-- var. The two foreign keys take a brief SHARE ROW EXCLUSIVE lock on
-- exercise_coach_requests and coach_take_words, with no scan (the new table
-- is empty). Deploy with the registry entry in the same PR: an unregistered
-- table with take_session_id stops a purge for review. Merge when no
-- deletion is mid-run. Both rehearsal lanes: it needs only 0385 and 0403.

BEGIN;

CREATE TABLE IF NOT EXISTS public.coach_answer_situations (
    id                     uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    take_session_id        text        NOT NULL,
    snippet_id             text        NULL,
    request_id             uuid        NULL
                           REFERENCES public.exercise_coach_requests (id) ON DELETE CASCADE,
    take_word_id           uuid        NULL
                           REFERENCES public.coach_take_words (id) ON DELETE CASCADE,
    answered_at            timestamptz NOT NULL,
    kind                   text        NULL,
    pattern_key            text        NULL,
    passage_text           text        NULL,
    slide_index            integer     NULL,
    diagnosis_ids          uuid[]      NOT NULL DEFAULT '{}'::uuid[],
    diagnoses              jsonb       NOT NULL DEFAULT '[]'::jsonb,
    ideal_text_snapshot_id uuid        NULL,
    ideal_text_version     integer     NULL,
    captured               text        NOT NULL DEFAULT 'at_answer',
    created_at             timestamptz NOT NULL DEFAULT now(),
    -- A moment's answer hangs on its request and moment; a Take word's on the word.
    CONSTRAINT coach_answer_situations_one_answer CHECK (
        (request_id IS NOT NULL AND take_word_id IS NULL AND snippet_id IS NOT NULL)
        OR (take_word_id IS NOT NULL AND request_id IS NULL AND snippet_id IS NULL)),
    CONSTRAINT coach_answer_situations_take CHECK (length(btrim(take_session_id)) > 0),
    CONSTRAINT coach_answer_situations_diagnoses CHECK (jsonb_typeof(diagnoses) = 'array'),
    CONSTRAINT coach_answer_situations_captured CHECK (
        captured IN ('at_answer', 'reconstructed')),
    CONSTRAINT coach_answer_situations_once_per_answer UNIQUE (request_id, answered_at),
    CONSTRAINT coach_answer_situations_once_per_save UNIQUE (take_word_id, answered_at)
);
CREATE INDEX IF NOT EXISTS coach_answer_situations_take_idx
    ON public.coach_answer_situations (take_session_id);
ALTER TABLE public.coach_answer_situations ENABLE ROW LEVEL SECURITY;
COMMENT ON TABLE public.coach_answer_situations IS
    'What the coach saw when they gave an answer (0482; founder 2026-10-19, N79): '
    'the clip''s words (the whole Take''s with its re-reads for a Take word), the '
    'kind, the pattern they named, their diagnosis by id and copied, and the Ideal '
    'Text snapshot made from the answered Take (the spoken Take for a re-read''s '
    'moment). One row per answer given (a first answer, each change, each Take-word '
    'save); a replaced answer joins its history row on (request_id, answered_at = '
    'resolved_at); a Take-word save finds its words as of answered_at (see '
    'answered_at). Insert-only and frozen. Capture '
    'only: read by no training, release, golden or promotion reader, in no '
    'payload; 0445''s "never a training label" stays until the privacy update. '
    'Never for a coach''s own Take. Purged with the Take.';
COMMENT ON COLUMN public.coach_answer_situations.answered_at IS
    'The answer''s own time: the resolver''s resolved_at for a moment''s answer '
    '(not exercise_coach_requests.answered_at, the speaker''s judgement), or '
    'coach_take_words.updated_at for a Take-word save. For a Take word it is no '
    'equality key (a re-draft bumps updated_at too): the words saved are on the '
    'lowest-numbered coach_take_word_versions row of take_word_id with updated_at '
    '>= answered_at, else on the live coach_take_words row.';
COMMENT ON COLUMN public.coach_answer_situations.diagnoses IS
    'The coach''s current diagnoses when they answered, copied: '
    '[{diagnosis_id, snippet_id, kind, error_id, named_error_id, label}]. '
    'Kept after the coach''s account is purged (N79); diagnosis_ids is the same '
    'by reference only.';

-- Frozen: no role, the owner included, rewrites what the coach saw. A
-- DELETE stays open for the purge and the two cascades.
CREATE OR REPLACE FUNCTION public.coach_answer_situation_is_frozen_v1()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
    RAISE EXCEPTION 'COACH_ANSWER_SITUATION_FROZEN';
END;
$$;
REVOKE ALL ON FUNCTION public.coach_answer_situation_is_frozen_v1() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.coach_answer_situation_is_frozen_v1() FROM anon, authenticated;

DROP TRIGGER IF EXISTS coach_answer_situation_is_frozen ON public.coach_answer_situations;
CREATE TRIGGER coach_answer_situation_is_frozen
    BEFORE UPDATE ON public.coach_answer_situations
    FOR EACH ROW EXECUTE FUNCTION public.coach_answer_situation_is_frozen_v1();

-- The app inserts a row and may read it back; the purge deletes it. No role
-- may update it. INSERT ... ON CONFLICT DO NOTHING needs no UPDATE grant.
REVOKE ALL ON TABLE public.coach_answer_situations FROM PUBLIC;
REVOKE ALL ON TABLE public.coach_answer_situations FROM anon, authenticated, service_role;
GRANT SELECT, INSERT, DELETE ON TABLE public.coach_answer_situations TO service_role;

COMMIT;
