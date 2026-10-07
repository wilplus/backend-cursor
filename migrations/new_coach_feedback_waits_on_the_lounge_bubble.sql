-- 0439 · new coach feedback waits on the Lounge bubble until the walk
-- shows it (build plan D-FW-5; founder lock 2026-10-06, the Feedback walk,
-- flow 1 and "Amendments: Lounge").
--
-- WHY. The walk lock: "When new feedback from the coach arrives, the Ideal
-- Text bubble in the Lounge gets the orange outline and a 'new' tag." The
-- Lounge needs one yes/no per project (never a count, AC-9): is there a
-- coach word or a coach answer, published to the speaker, that the walk has
-- not shown them yet? Machine-only feedback never lights it.
--
-- WHAT.
--   * coach_feedback_seen: per speaker, per Take, per item, when the walk
--     last showed it. An item is the Take's coach note ('take_word') or one
--     moment (its snippet id). Written by mark_coach_feedback_seen_v1 when
--     the walk shows the coach's note or that moment; a later show moves
--     seen_at forward.
--   * new_coach_feedback_by_project_v1(p_owner): every project of that
--     speaker with one boolean: true while any published coach item of
--     one of its Takes is newer than when the walk last showed it.
--     Published means coach_take_words.shared_at is set (its time is the
--     later of shared_at and updated_at, so a word edited after sharing is
--     new again) or exercise_coach_requests.shared_at is set for this
--     speaker (its time is the latest of shared_at, answered_at and
--     resolved_at). Nothing else counts: no machine row is read.
--   * mark_coach_feedback_seen_v1(p_owner, p_take, p_item): refuses a Take
--     that is not the speaker's (COACH_FEEDBACK_TAKE_NOT_OWNED), otherwise
--     records the show and returns seen_at.
-- Both functions read v2_sessions, coach_take_words and
-- exercise_coach_requests at call time (plpgsql), so a database without
-- one of them still takes this file.
--
-- PRIVATE. RLS on with no policy; the browser roles hold nothing on the
-- table or the functions; the app calls them with the service key. Purged
-- with the Take and with the speaker (services/data_purge_registry.py).
--
-- Additive; idempotent; no env var; no lock on an existing table.
-- Rollback (a new forward migration): drop the two functions and the table.

BEGIN;

CREATE TABLE IF NOT EXISTS public.coach_feedback_seen (
    owner_user_id   text        NOT NULL,
    take_session_id text        NOT NULL,
    item            text        NOT NULL,
    seen_at         timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT coach_feedback_seen_pkey PRIMARY KEY (owner_user_id, take_session_id, item),
    CONSTRAINT coach_feedback_seen_item_shape CHECK (
        char_length(item) BETWEEN 1 AND 128)
);
CREATE INDEX IF NOT EXISTS coach_feedback_seen_take_idx
    ON public.coach_feedback_seen (take_session_id);
ALTER TABLE public.coach_feedback_seen ENABLE ROW LEVEL SECURITY;
COMMENT ON TABLE public.coach_feedback_seen IS
    'When the Feedback walk last showed a speaker a coach item (0439, '
    'D-FW-5): the Take''s coach note (item take_word) or one moment (item = '
    'its snippet id). The Lounge bubble''s "new" is true while a published '
    'coach item is newer than this. A yes/no, never a count. Purged with the '
    'Take and with the speaker.';

CREATE OR REPLACE FUNCTION public.new_coach_feedback_by_project_v1(p_owner text)
RETURNS TABLE (arc_id text, has_new boolean)
LANGUAGE plpgsql STABLE
SET search_path = public, pg_temp
AS $$
DECLARE
    v_owner uuid;
BEGIN
    IF p_owner IS NULL OR btrim(p_owner) = '' THEN
        RAISE EXCEPTION 'COACH_FEEDBACK_OWNER_REQUIRED';
    END IF;
    -- An account id is a uuid (v2_sessions.user_id); anything else owns no
    -- Take, so it has no project and nothing new.
    IF p_owner !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' THEN
        RETURN;
    END IF;
    v_owner := p_owner::uuid;
    RETURN QUERY
    WITH takes AS (
        SELECT s.id::text AS take_id, s.arc_id::text AS arc
          FROM public.v2_sessions s
         WHERE s.user_id = v_owner
           AND s.arc_id IS NOT NULL
    ),
    published AS (
        SELECT t.arc, w.take_session_id, 'take_word'::text AS item,
               max(GREATEST(w.shared_at, w.updated_at)) AS published_at
          FROM public.coach_take_words w
          JOIN takes t ON t.take_id = w.take_session_id
         WHERE w.shared_at IS NOT NULL
         GROUP BY t.arc, w.take_session_id
        UNION ALL
        SELECT t.arc, r.take_session_id, r.snippet_id::text,
               GREATEST(r.shared_at, r.answered_at, r.resolved_at)
          FROM public.exercise_coach_requests r
          JOIN takes t ON t.take_id = r.take_session_id
         WHERE r.shared_at IS NOT NULL
           AND r.snippet_id IS NOT NULL
           AND r.owner_user_id = p_owner
    ),
    unseen AS (
        SELECT p.arc,
               bool_or(seen.seen_at IS NULL OR seen.seen_at < p.published_at) AS fresh
          FROM published p
          LEFT JOIN public.coach_feedback_seen seen
            ON seen.owner_user_id = p_owner
           AND seen.take_session_id = p.take_session_id
           AND seen.item = p.item
         GROUP BY p.arc
    )
    SELECT a.arc, COALESCE(u.fresh, false)
      FROM (SELECT DISTINCT takes.arc FROM takes) a
      LEFT JOIN unseen u ON u.arc = a.arc;
END;
$$;

CREATE OR REPLACE FUNCTION public.mark_coach_feedback_seen_v1(
    p_owner text, p_take text, p_item text
) RETURNS timestamptz
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
    v_seen timestamptz;
BEGIN
    IF p_owner IS NULL OR btrim(p_owner) = ''
       OR p_take IS NULL OR btrim(p_take) = ''
       OR p_item IS NULL OR btrim(p_item) = '' THEN
        RAISE EXCEPTION 'COACH_FEEDBACK_SEEN_INPUT_INVALID';
    END IF;
    IF p_owner !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
       OR p_take !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
       OR NOT EXISTS (
        SELECT 1 FROM public.v2_sessions s
         WHERE s.id = p_take::uuid AND s.user_id = p_owner::uuid
    ) THEN
        RAISE EXCEPTION 'COACH_FEEDBACK_TAKE_NOT_OWNED';
    END IF;
    INSERT INTO public.coach_feedback_seen (owner_user_id, take_session_id, item, seen_at)
    VALUES (p_owner, p_take, p_item, clock_timestamp())
    ON CONFLICT (owner_user_id, take_session_id, item)
    DO UPDATE SET seen_at = GREATEST(public.coach_feedback_seen.seen_at, EXCLUDED.seen_at)
    RETURNING seen_at INTO v_seen;
    RETURN v_seen;
END;
$$;

DO $$
DECLARE
    v_role text;
BEGIN
    REVOKE ALL ON TABLE public.coach_feedback_seen FROM PUBLIC;
    REVOKE ALL ON FUNCTION public.new_coach_feedback_by_project_v1(text) FROM PUBLIC;
    REVOKE ALL ON FUNCTION public.mark_coach_feedback_seen_v1(text, text, text) FROM PUBLIC;
    FOREACH v_role IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
            EXECUTE format('REVOKE ALL ON TABLE public.coach_feedback_seen FROM %I', v_role);
            EXECUTE format('REVOKE ALL ON FUNCTION public.new_coach_feedback_by_project_v1(text) FROM %I', v_role);
            EXECUTE format('REVOKE ALL ON FUNCTION public.mark_coach_feedback_seen_v1(text, text, text) FROM %I', v_role);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT EXECUTE ON FUNCTION public.new_coach_feedback_by_project_v1(text) TO service_role;
        GRANT EXECUTE ON FUNCTION public.mark_coach_feedback_seen_v1(text, text, text) TO service_role;
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.coach_feedback_seen TO service_role;
    END IF;
END $$;

COMMIT;
