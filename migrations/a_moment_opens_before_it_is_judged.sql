-- 0408 · a moment opens before it is judged (founder 2026-10-01, F1; Phase 2
-- of the after-practice paths)
--
-- WHY. "Opening a bookmark never asks for a judgment first. The machine's
-- read chooses the feedback. The speaker judges themselves after it: on a
-- confident moment right after the praise, on a moment that needed work
-- after each practice attempt." (F1, signed 1 Oct 2026.) The moment's coach
-- request therefore rises when the moment OPENS, tagged with the machine's
-- kind (praise, error, rewrite), and the speaker's later judgement is kept
-- beside it as `answer_kind` (the follow-up matrix's kind; an ambiguity where
-- the speaker and the machine disagree). Opens and skips are recorded once
-- each, so the coach can see them on a requested moment after their blind
-- rating, and the coach-load report can count requests per opened moment
-- before and after the switch.
--
-- WHAT. Three columns on exercise_coach_requests (two nullable, one with a
-- default), one append-only table moment_events, one RPC (v3) that records
-- where the request rose. Additive; idempotent; no env var. Dark:
-- Config.JUDGEMENT_AFTER_FEEDBACK_ENABLED is False, so no request takes a
-- value other than the defaults until a reviewed change flips it;
-- moment_events is written under either flow (a receipt, like the exercise
-- render), which is what makes the before/after report possible.
--
-- Rollback (a new forward migration): drop request_exercise_from_coach_v3,
-- drop the three columns, drop moment_events.

BEGIN;

ALTER TABLE public.exercise_coach_requests
    ADD COLUMN IF NOT EXISTS answer_kind TEXT NULL;
ALTER TABLE public.exercise_coach_requests
    ADD COLUMN IF NOT EXISTS answered_at TIMESTAMPTZ NULL;
ALTER TABLE public.exercise_coach_requests
    ADD COLUMN IF NOT EXISTS raised_on TEXT NOT NULL DEFAULT 'judgement';

ALTER TABLE public.exercise_coach_requests
    DROP CONSTRAINT IF EXISTS exercise_coach_request_answer_kind_check;
ALTER TABLE public.exercise_coach_requests
    ADD CONSTRAINT exercise_coach_request_answer_kind_check
    CHECK (answer_kind IS NULL
           OR answer_kind IN ('error', 'praise', 'rewrite', 'ambiguity'));

ALTER TABLE public.exercise_coach_requests
    DROP CONSTRAINT IF EXISTS exercise_coach_request_raised_on_check;
ALTER TABLE public.exercise_coach_requests
    ADD CONSTRAINT exercise_coach_request_raised_on_check
    CHECK (raised_on IN ('judgement', 'open'));

COMMENT ON COLUMN public.exercise_coach_requests.answer_kind IS
    'The follow-up matrix''s kind once the speaker judged the moment '
    '(0408): error, praise, rewrite, or ambiguity where the speaker and the '
    'machine disagree. NULL until the judgement. The coach acts on this when '
    'set, else on kind.';
COMMENT ON COLUMN public.exercise_coach_requests.answered_at IS
    'When the speaker''s judgement set answer_kind (0408).';
COMMENT ON COLUMN public.exercise_coach_requests.raised_on IS
    'Where the request rose (0408): ''judgement'' (the answer saved; the flow '
    'before F1) or ''open'' (the moment opened; F1). For the coach-load '
    'report before and after the switch.';

CREATE TABLE IF NOT EXISTS public.moment_events (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_user_id   text        NOT NULL,
    take_session_id text        NOT NULL,
    snippet_id      text        NOT NULL,
    event           text        NOT NULL,
    co_exposed      jsonb       NOT NULL DEFAULT '{}'::jsonb,
    created_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT moment_events_event_check CHECK (event IN ('opened', 'skipped')),
    CONSTRAINT moment_events_once UNIQUE (take_session_id, snippet_id, event)
);

CREATE INDEX IF NOT EXISTS moment_events_created_idx
    ON public.moment_events (created_at);
CREATE INDEX IF NOT EXISTS moment_events_take_idx
    ON public.moment_events (take_session_id);

ALTER TABLE public.moment_events ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE public.moment_events IS
    'The speaker opened or skipped a bookmark (0408; founder 2026-10-01, F1). '
    'Append-only, once per (Take, moment, event). co_exposed names what the '
    'sheet showed at the open. Never a label; purged with the Take.';

-- Insert-once, as v2; the raised_on is the difference.
CREATE OR REPLACE FUNCTION public.request_exercise_from_coach_v3(
    p_owner_user_id TEXT,
    p_take_session_id TEXT,
    p_snippet_id TEXT,
    p_reason TEXT,
    p_kind TEXT,
    p_raised_on TEXT,
    p_pattern TEXT,
    p_observed_tags TEXT[],
    p_request_trace JSONB
) RETURNS public.exercise_coach_requests
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    found_row public.exercise_coach_requests;
BEGIN
    IF COALESCE(btrim(p_owner_user_id), '') = ''
       OR COALESCE(btrim(p_take_session_id), '') = ''
       OR COALESCE(btrim(p_snippet_id), '') = ''
       OR p_reason IS NULL
       OR p_reason NOT IN ('nothing_spotted', 'nothing_targets_it', 'library_matched')
       OR p_kind IS NULL OR p_kind NOT IN ('error', 'praise', 'rewrite', 'ambiguity')
       OR p_raised_on IS NULL OR p_raised_on NOT IN ('judgement', 'open')
       OR p_request_trace IS NULL OR jsonb_typeof(p_request_trace) <> 'object'
    THEN
        RAISE EXCEPTION 'EXERCISE_COACH_REQUEST_INPUT_INVALID';
    END IF;
    INSERT INTO public.exercise_coach_requests (
        owner_user_id, take_session_id, snippet_id, reason, kind, raised_on,
        pattern, observed_tags, request_trace
    ) VALUES (
        p_owner_user_id, p_take_session_id, p_snippet_id, p_reason, p_kind,
        p_raised_on, p_pattern, COALESCE(p_observed_tags, '{}'::TEXT[]),
        p_request_trace
    )
    ON CONFLICT (take_session_id, snippet_id) DO NOTHING;
    SELECT * INTO found_row FROM public.exercise_coach_requests
     WHERE take_session_id = p_take_session_id AND snippet_id = p_snippet_id;
    RETURN found_row;
END;
$$;

REVOKE ALL ON FUNCTION public.request_exercise_from_coach_v3(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT[], JSONB)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.request_exercise_from_coach_v3(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT[], JSONB) TO service_role;

COMMIT;
