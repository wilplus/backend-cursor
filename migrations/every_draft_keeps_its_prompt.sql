-- every_draft_keeps_its_prompt (0479; founder 2026-10-19, decisions log N79)
--
-- WHY. A model draft shown to a coach lived only on the row it was shown
-- from: draft_text on the moment's request (0402) or on the coach's Take
-- word (0411). A re-draft replaced it, so a draft the coach kept as it was
-- (never a pair: a pair needs the final to differ) and every superseded
-- draft were gone. For the three answer surfaces (praise_line,
-- clearer_version, exercise_script) the row kept nothing of the prompt
-- either: draft_prompt was written NULL, so the coach's notes and the
-- spotted labels the model was sent were lost, and no row anywhere said
-- which version of the drafter's prompt wrote a draft.
--
-- WHAT. coach_draft_history keeps every draft shown to a coach on the
-- answer surfaces and the coach-word surfaces (coach_moment_line,
-- coach_take_word), one row per draft, with:
--   * what the prompt was given (prompt_inputs: the passage as sent, and
--     the kind, the spotted labels and tag ids and the coach's notes for an
--     answer; the coach's notes for a coach word);
--   * prompt_sha256: sha256 of the exact (system, user) text sent, as the
--     UTF-8 of the JSON array [system, user] with no spaces and no ASCII
--     escaping (services.coach_draft_history.prompt_sha256);
--   * prompt_lock_sha256: the surface's locked prompt hash when it was
--     drafted, the value fine_tune_runs, evaluation_reports and promotions
--     record (ml_surface_contracts.locked_prompt_hash); NULL if unreadable;
--   * settled_at / final_unchanged, set when the coach saves an answer
--     while this draft is the row's current one: whether the saved words
--     are the draft as written. A later save of the same draft sets them
--     again (the latest version counts, N79).
-- The app writes the row once and may only set the two settle columns
-- afterwards (column grant below).
--
-- The request's and the Take word's own draft_prompt (0459) now also name
-- the draft (draft_id, beside the snapshot, which the pair copies without
-- it), and the answer surfaces write theirs too, as {passage_text,
-- prompt_context: {prompt: 'coach_answer_drafts', kind, spotted,
-- spotted_tags, notes}, draft_id}; the two column comments say so.
--
-- Capture only: no training, release, golden or promotion reader reads
-- this table or the answer surfaces' draft_prompt, and neither is in a
-- speaker's or coach's payload. Every row belongs to a speaker's Take and
-- is purged with it (services/data_purge_registry.py, coach_draft_history,
-- order 57, before the word and request rows whose cascades are only the
-- backstop). No by-coach entry: a coach's words stay with the speaker's
-- Take (N79).
--
-- Additive and idempotent: CREATE TABLE / INDEX IF NOT EXISTS, REVOKE and
-- GRANT, COMMENT. Nothing dropped, no row written, no env var. Creating the
-- table's two foreign keys takes a brief SHARE ROW EXCLUSIVE lock on
-- exercise_coach_requests and coach_take_words, with no scan (the new table
-- is empty); the two comments take SHARE UPDATE EXCLUSIVE, which blocks no
-- read or write. Deploy with the registry entry in the same PR: an unregistered
-- table with take_session_id stops a purge for review. Merge when no
-- deletion is mid-run. Released rehearsal lane only: its column comments
-- are on draft_prompt (0459, released lane).

BEGIN;

CREATE TABLE IF NOT EXISTS public.coach_draft_history (
    id                 uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    surface            text        NOT NULL,
    coach_id           text        NOT NULL,
    owner_user_id      text        NULL,
    take_session_id    text        NOT NULL,
    snippet_id         text        NULL,
    request_id         uuid        NULL
                       REFERENCES public.exercise_coach_requests (id) ON DELETE CASCADE,
    take_word_id       uuid        NULL
                       REFERENCES public.coach_take_words (id) ON DELETE CASCADE,
    draft_text         text        NOT NULL,
    model_version      text        NULL,
    prompt_family      text        NOT NULL,
    prompt_lock_sha256 text        NULL,
    prompt_sha256      text        NOT NULL,
    prompt_inputs      jsonb       NOT NULL,
    drafted_at         timestamptz NOT NULL DEFAULT now(),
    settled_at         timestamptz NULL,
    final_unchanged    boolean     NULL,
    CONSTRAINT coach_draft_history_surface CHECK (surface IN (
        'praise_line', 'clearer_version', 'exercise_script',
        'coach_moment_line', 'coach_take_word')),
    CONSTRAINT coach_draft_history_family CHECK (
        (prompt_family = 'coach_word_drafts'
         AND surface IN ('coach_moment_line', 'coach_take_word'))
        OR (prompt_family = 'coach_answer_drafts'
            AND surface IN ('praise_line', 'clearer_version', 'exercise_script'))),
    -- A Take word's draft hangs on the Take; every other draft on its moment's request.
    CONSTRAINT coach_draft_history_one_home CHECK (
        (surface = 'coach_take_word' AND request_id IS NULL)
        OR (surface <> 'coach_take_word' AND request_id IS NOT NULL
            AND take_word_id IS NULL)),
    CONSTRAINT coach_draft_history_coach CHECK (length(btrim(coach_id)) > 0),
    CONSTRAINT coach_draft_history_take CHECK (length(btrim(take_session_id)) > 0),
    CONSTRAINT coach_draft_history_text CHECK (length(btrim(draft_text)) > 0),
    CONSTRAINT coach_draft_history_prompt_sha CHECK (prompt_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT coach_draft_history_lock_sha CHECK (
        prompt_lock_sha256 IS NULL OR prompt_lock_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT coach_draft_history_inputs CHECK (jsonb_typeof(prompt_inputs) = 'object'),
    CONSTRAINT coach_draft_history_settled CHECK (
        (settled_at IS NULL) = (final_unchanged IS NULL))
);
CREATE INDEX IF NOT EXISTS coach_draft_history_take_idx
    ON public.coach_draft_history (take_session_id);
CREATE INDEX IF NOT EXISTS coach_draft_history_request_idx
    ON public.coach_draft_history (request_id) WHERE request_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS coach_draft_history_take_word_idx
    ON public.coach_draft_history (take_word_id) WHERE take_word_id IS NOT NULL;
ALTER TABLE public.coach_draft_history ENABLE ROW LEVEL SECURITY;
COMMENT ON TABLE public.coach_draft_history IS
    'Every model draft shown to a coach on the answer and coach-word surfaces '
    '(0479; founder 2026-10-19, N79), with what its prompt was given, the sha256 '
    'of the exact system and user text sent and the surface''s prompt lock hash. '
    'Written once; only settled_at and final_unchanged are set later, when the '
    'coach saves an answer. Capture only: read by no training, release, golden or '
    'promotion reader, in no payload. Purged with the Take.';

-- The app inserts a draft, settles it, and the purge deletes it. Nothing
-- else: no role may rewrite what was drafted or what the prompt was sent.
REVOKE ALL ON TABLE public.coach_draft_history FROM PUBLIC;
REVOKE ALL ON TABLE public.coach_draft_history FROM anon, authenticated, service_role;
GRANT SELECT, INSERT, DELETE ON TABLE public.coach_draft_history TO service_role;
GRANT UPDATE (settled_at, final_unchanged) ON TABLE public.coach_draft_history TO service_role;

COMMENT ON COLUMN public.exercise_coach_requests.draft_prompt IS
    'What the current draft''s prompt was given ({passage_text, prompt_context}, '
    'and since 0479 draft_id, its coach_draft_history row), coach-only. A coach-word '
    'draft''s is copied onto the coach_moment_line pair without draft_id (0459); an '
    'answer draft''s (prompt coach_answer_drafts, 0479) is capture only.';
COMMENT ON COLUMN public.coach_take_words.draft_prompt IS
    'What the coach-word drafter''s prompt was given ({passage_text, prompt_context}, '
    'and since 0479 draft_id, its coach_draft_history row), coach-only; copied onto '
    'the coach_take_word pair without draft_id (0459).';

COMMIT;
