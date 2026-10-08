-- 0444 · a coach is asked to listen again, blind (founder 2026-10-06, QG12a A
-- and P26b A, decisions log N53.4; the three signed lines P26c, N54.1; Q-B8
-- A, N62; build plan D-CP-10)
--
-- WHY. QG12a A: "If the machine says 'reached' but the speaker says No or
-- Not sure, the coach gets the moment as 'they disagree'." P26b A: the coach
-- is asked to listen again "in the coach's usual work list"; P26c: the words
-- on that moment "don't say why, or what the speaker answered, so the
-- coach's second answer stays blind." Today the disagreement between the
-- speaker's one answer and the machine's read is already the follow-up
-- matrix's ambiguity (services/judgement_follow_up.py: the request's kind
-- or answer_kind becomes 'ambiguity'), and a coach who has already judged
-- the moment never hears of it: their queue shows the moment as answered.
--
-- WHAT. One table and two writers, nothing else:
--
--   coach_listen_again_requests   one row per time a coach is asked to
--                                 listen to a moment again: the Take, the
--                                 moment, the coach, WHICH of the three
--                                 signed lines the list shows (its key), when
--                                 it was asked and when the coach's new blind
--                                 answer landed (heard_at). No reason column,
--                                 no answer column, no read column: the row
--                                 cannot carry why, by its shape. At most one
--                                 open row per moment and coach; closed rows
--                                 stay as history.
--   request_coach_listen_again_v1 called when the disagreement flag fires:
--                                 one open row for every coach with a blind
--                                 judgment of record on the clip (lane
--                                 'coach', not a self-report, not an
--                                 Audio-unclear abstention, blind), none for a coach
--                                 who has not judged it yet (the moment is
--                                 still in their queue to judge blind), none
--                                 twice while one is open (ON CONFLICT on
--                                 the one-open index). The line key rotates
--                                 per coach (the line after the coach's
--                                 latest, under a per-coach advisory lock),
--                                 never the same twice in a row. The moment
--                                 is stored in canonical uuid text. Returns how many
--                                 rows it wrote: a routing count for the
--                                 server's log, never a user payload.
--   mark_coach_listen_again_heard_v1   stamps heard_at on the coach's open
--                                 row when their new blind answer is saved
--                                 (the rating route's reconsideration, 0427).
--
-- THE APP'S SIDE. While a coach has an open row on a moment, the server
-- treats that coach as not having rated it: their own earlier answer is
-- masked in every read that the blind gate keys on, so the moment read, the
-- drafts, the named errors and the speaker's answer answer 409 again until
-- the new blind answer lands (BLIND COACH); the queue lists the moment as
-- `listen_again` with the line key and nothing else, not even the kind it
-- rose under. Nothing here reaches a speaker; nothing is a score (AC-9);
-- the flag is a side write that never blocks the speaker's answer (LIVE
-- LOOP). The speaker's answer is read by the matrix, never copied here (L3).
--
-- WHAT DOES NOT CHANGE. confidence_labels is read, never altered; no
-- trigger on it (a busy production table takes no lock). exercise_coach_
-- requests is untouched. The older User Yes / Coach No re-review record
-- (confidence_rereview_queue, 0278, the Voice Album's leg) keeps its own
-- life.
--
-- Idempotent: IF NOT EXISTS, CREATE OR REPLACE; applied twice it changes
-- nothing. Writes no row on its own. Locks: only the new table (and, at run
-- time, a per-coach transaction advisory lock inside the request function).
--
-- Rollback (a new forward migration): DROP FUNCTION
-- public.request_coach_listen_again_v1(text, text); DROP FUNCTION
-- public.mark_coach_listen_again_heard_v1(text, text); DROP TABLE
-- public.coach_listen_again_requests. Nothing else depends on them.

BEGIN;

CREATE TABLE IF NOT EXISTS public.coach_listen_again_requests (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    take_session_id text        NOT NULL,
    snippet_id      text        NOT NULL,
    coach_id        text        NOT NULL,
    line_key        text        NOT NULL,
    requested_at    timestamptz NOT NULL DEFAULT now(),
    heard_at        timestamptz NULL,
    CONSTRAINT coach_listen_again_line_key_check CHECK (
        line_key IN ('P26c-A', 'P26c-B', 'P26c-C')),
    CONSTRAINT coach_listen_again_ids_check CHECK (
        length(btrim(take_session_id)) > 0 AND length(btrim(snippet_id)) > 0
        AND length(btrim(coach_id)) > 0),
    CONSTRAINT coach_listen_again_heard_after_asked CHECK (
        heard_at IS NULL OR heard_at >= requested_at)
);

-- One open ask per moment and coach; the coach's open list is the read.
CREATE UNIQUE INDEX IF NOT EXISTS coach_listen_again_one_open
    ON public.coach_listen_again_requests (snippet_id, coach_id)
    WHERE heard_at IS NULL;
CREATE INDEX IF NOT EXISTS coach_listen_again_open_by_coach
    ON public.coach_listen_again_requests (coach_id, take_session_id)
    WHERE heard_at IS NULL;
CREATE INDEX IF NOT EXISTS coach_listen_again_take_idx
    ON public.coach_listen_again_requests (take_session_id);

ALTER TABLE public.coach_listen_again_requests ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE public.coach_listen_again_requests IS
    'A coach asked to listen to a moment again, blind (0444; QG12a A, P26b A, '
    'N53.4; P26c, N54.1). One row per ask: the Take, the moment, the coach, '
    'the key of the signed line the list shows, when asked, when the new '
    'blind answer landed. By its shape the row carries no reason and no '
    'answer: the coach never learns why. Written only by '
    'request_coach_listen_again_v1 and mark_coach_listen_again_heard_v1; '
    'purged with the Take and with the coach.';

CREATE OR REPLACE FUNCTION public.request_coach_listen_again_v1(
    p_take_session_id text,
    p_snippet_id text
) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    v_snippet  uuid;
    v_key      text;
    v_coach    text;
    v_written  integer := 0;
    v_inserted integer;
    v_last     text;
    v_line     text;
BEGIN
    IF COALESCE(btrim(p_take_session_id), '') = ''
       OR COALESCE(btrim(p_snippet_id), '') = '' THEN
        RAISE EXCEPTION 'COACH_LISTEN_AGAIN_INPUT_INVALID';
    END IF;
    BEGIN
        v_snippet := p_snippet_id::uuid;
    EXCEPTION WHEN invalid_text_representation THEN
        RAISE EXCEPTION 'COACH_LISTEN_AGAIN_INPUT_INVALID';
    END;
    -- The moment is stored in the uuid's canonical text form, whatever case
    -- or braces the caller sent, so one moment is one key everywhere.
    v_key := v_snippet::text;

    -- Every coach with a blind judgment of record on this clip: the
    -- ledger's coach lane, no self-report, no abstention, blind (0411: a
    -- rating made after the coach saw the clip's non-blind side is not a
    -- judgment of record) -- the same rows the quorum counts as a coach's
    -- vote. A coach who has not judged it yet still has it in their queue
    -- to judge blind: nothing to add.
    FOR v_coach IN
        SELECT DISTINCT label.rater_id::text
          FROM public.confidence_labels label
         WHERE label.snippet_id = v_snippet
           AND COALESCE(label.state_id, 'confidence') = 'confidence'
           AND label.lane = 'coach'
           AND COALESCE(label.self_report, false) = false
           AND COALESCE(label.unrateable, false) = false
           AND label.blind IS NOT FALSE
           AND label.value IN ('yes', 'in_between', 'no', 'not_sure')
           AND label.rater_id IS NOT NULL
         ORDER BY 1
    LOOP
        -- One rotation per coach at a time: two flags firing together for
        -- the same coach pick their lines one after the other.
        PERFORM pg_advisory_xact_lock(hashtext('coach_listen_again:' || v_coach));
        -- The three signed lines rotate per coach: the line after the one
        -- the coach was asked with last (A, B, C, A ...), never the same
        -- twice in a row (N52.6, N54.1). Read from the latest row, not a
        -- count, so a purge of older rows cannot make a line repeat.
        SELECT line_key INTO v_last FROM public.coach_listen_again_requests
         WHERE coach_id = v_coach
         ORDER BY requested_at DESC, id DESC
         LIMIT 1;
        v_line := CASE v_last
                      WHEN 'P26c-A' THEN 'P26c-B'
                      WHEN 'P26c-B' THEN 'P26c-C'
                      ELSE 'P26c-A'
                  END;
        -- None twice while one is open: the partial unique index decides,
        -- so a concurrent flag on the same moment writes nothing either.
        INSERT INTO public.coach_listen_again_requests (
            take_session_id, snippet_id, coach_id, line_key, requested_at
        ) VALUES (
            p_take_session_id, v_key, v_coach, v_line, clock_timestamp()
        )
        ON CONFLICT (snippet_id, coach_id) WHERE heard_at IS NULL DO NOTHING;
        GET DIAGNOSTICS v_inserted = ROW_COUNT;
        v_written := v_written + v_inserted;
    END LOOP;
    RETURN v_written;
END;
$$;

CREATE OR REPLACE FUNCTION public.mark_coach_listen_again_heard_v1(
    p_snippet_id text,
    p_coach_id text
) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    v_key    text;
    v_closed integer;
BEGIN
    IF COALESCE(btrim(p_snippet_id), '') = '' OR COALESCE(btrim(p_coach_id), '') = '' THEN
        RAISE EXCEPTION 'COACH_LISTEN_AGAIN_INPUT_INVALID';
    END IF;
    -- The same canonical form the ask was stored under.
    BEGIN
        v_key := p_snippet_id::uuid::text;
    EXCEPTION WHEN invalid_text_representation THEN
        RAISE EXCEPTION 'COACH_LISTEN_AGAIN_INPUT_INVALID';
    END;
    UPDATE public.coach_listen_again_requests
       SET heard_at = GREATEST(clock_timestamp(), requested_at)
     WHERE snippet_id = v_key AND coach_id = p_coach_id AND heard_at IS NULL;
    GET DIAGNOSTICS v_closed = ROW_COUNT;
    RETURN v_closed;
END;
$$;

COMMENT ON FUNCTION public.request_coach_listen_again_v1(text, text) IS
    'The disagreement flag (QG12a A; 0444): one open blind ask per coach with '
    'a judgment of record on the clip; the signed line key rotates per coach. '
    'Returns rows written. service_role only.';
COMMENT ON FUNCTION public.mark_coach_listen_again_heard_v1(text, text) IS
    'The coach''s new blind answer landed (0444): closes their open ask on the '
    'moment. Returns rows closed. service_role only.';

-- ── The door ───────────────────────────────────────────────────────────────
-- Browser roles and PUBLIC get nothing on the table or the functions,
-- whatever default privileges the schema carries (Supabase grants
-- anon/authenticated on public by default; PostgREST publishes every public
-- function). The app reads the table and calls the two functions with the
-- service key, and the purge deletes rows with the Take and the coach; the
-- table is written only through the functions. Roles are guarded: they exist
-- on Supabase, not on a bare Postgres.
REVOKE ALL ON TABLE public.coach_listen_again_requests FROM PUBLIC;
REVOKE ALL ON FUNCTION public.request_coach_listen_again_v1(text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.mark_coach_listen_again_heard_v1(text, text) FROM PUBLIC;
DO $$
DECLARE
    v_role text;
BEGIN
    FOREACH v_role IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
            EXECUTE format('REVOKE ALL ON TABLE public.coach_listen_again_requests FROM %I', v_role);
            EXECUTE format('REVOKE ALL ON FUNCTION public.request_coach_listen_again_v1(text, text) FROM %I', v_role);
            EXECUTE format('REVOKE ALL ON FUNCTION public.mark_coach_listen_again_heard_v1(text, text) FROM %I', v_role);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        REVOKE ALL ON TABLE public.coach_listen_again_requests FROM service_role;
        GRANT SELECT, DELETE ON TABLE public.coach_listen_again_requests TO service_role;
        GRANT EXECUTE ON FUNCTION public.request_coach_listen_again_v1(text, text) TO service_role;
        GRANT EXECUTE ON FUNCTION public.mark_coach_listen_again_heard_v1(text, text) TO service_role;
    END IF;
END $$;

COMMIT;
