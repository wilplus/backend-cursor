-- 0446 · a coach may change their answer; every earlier answer stays
-- (founder 2026-10-06, coach panel redesign lock flows 7 and 12, the words
-- CP2 A "Change my answer"; Q-B12 A, N62; Q-B13 A; build plan D-CP-7)
--
-- WHY. The coach panel lock, flow 12: "Summary. An answered moment, reopened
-- from the queue: what happened and 'Your answer'; 'Change my answer'."
-- Q-B12 A: "When a coach changes an answer the speaker already has, the new
-- answer replaces the card; the old one stays in history for audit." Today
-- resolve_exercise_coach_request_v2 (0402, 0403) resolves once: a second
-- answer by the same coach with different words raises
-- EXERCISE_COACH_REQUEST_ALREADY_RESOLVED, and the UPDATE guard (0385)
-- refuses any change to a set resolution or share from anyone.
--
-- WHAT. One history table, a new guard and a new resolver:
--
--   exercise_coach_request_answer_versions   every answer a request has had
--                             and no longer has: the resolution, the
--                             exercise or the words, the video, who gave it,
--                             when, whether it was shared and when it was
--                             replaced. Written only by the resolver, when
--                             an answer is replaced. Insert-only.
--   guard_exercise_coach_request_update_v2   0385's guard, with one door:
--                             the resolver names the request it is changing
--                             in a transaction-local setting
--                             (willab.coach_answer_change); within that
--                             transaction, for that row, the resolution and
--                             the share may change. Every other UPDATE is
--                             refused exactly as before: what was requested
--                             never changes, a resolution is never written
--                             over by hand, a share is never unset by hand.
--   resolve_exercise_coach_request_v3   0403's resolver, with the change.
--                             An unresolved request takes the answer; the
--                             same answer again changes nothing (and may now
--                             carry the share); a DIFFERENT answer by the
--                             coach who gave the current one moves the
--                             current answer into the history, writes the
--                             new one with resolved_at = now(), and sets the
--                             share from this call alone (shared when asked,
--                             else not shared: the old share is withdrawn
--                             with the answer it belonged to); a different
--                             answer by ANOTHER coach is still refused
--                             (ALREADY_RESOLVED): one coach's answer is not
--                             another's to change. The exercise ids, the
--                             words and the video ref on the row at the time
--                             of the change are what the history keeps.
--
-- THE SPEAKER'S CARD (Q-B12 A). The speaker reads the request row and only
-- its shared, current answer (services/confident_voice_practice.py,
-- coach_shared_answer / coach_shared_exercise): a changed, shared answer
-- replaces the card on the next read; a changed, unshared answer takes the
-- card away. The bake's freshness rule reads the row's resolved_at and
-- shared_at (0428), so a change refreshes the stored set. Nothing here is a
-- score (AC-9); the history is the coach's own words, never shown to the
-- speaker; a clearer version still never goes to the library (Q-B13 A: the
-- library filing is the app's and unchanged).
--
-- Idempotent: IF NOT EXISTS, CREATE OR REPLACE, DROP TRIGGER IF EXISTS then
-- CREATE TRIGGER; applied twice it changes nothing. Writes no row. Locks:
-- the new table, and the trigger swap on exercise_coach_requests (a small
-- table written only through its functions: a brief exclusive lock for the
-- catalog change, no rewrite, no scan). v1 and v2 of the resolver stay as
-- they are, unused by the app after this.
--
-- Rollback (a new forward migration): recreate the 0385 trigger on
-- guard_exercise_coach_request_update_v1; DROP FUNCTION
-- public.resolve_exercise_coach_request_v3(uuid, text, text, text, integer,
-- boolean, text); DROP FUNCTION public.guard_exercise_coach_request_update_v2();
-- DROP TABLE public.exercise_coach_request_answer_versions. Rows already
-- changed keep their current answer.

BEGIN;

CREATE TABLE IF NOT EXISTS public.exercise_coach_request_answer_versions (
    id                        uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id                uuid        NOT NULL
                              REFERENCES public.exercise_coach_requests (id) ON DELETE CASCADE,
    take_session_id           text        NOT NULL,
    snippet_id                text        NOT NULL,
    version                   integer     NOT NULL,
    resolution                text        NOT NULL,
    resolved_exercise_id      text        NULL,
    resolved_exercise_version integer     NULL,
    answer_text               text        NULL,
    answer_video_ref          text        NULL,
    resolved_by               text        NOT NULL,
    resolved_at               timestamptz NOT NULL,
    shared_at                 timestamptz NULL,
    superseded_at             timestamptz NOT NULL DEFAULT now(),
    superseded_by             text        NOT NULL,
    CONSTRAINT exercise_coach_request_answer_versions_once UNIQUE (request_id, version),
    CONSTRAINT exercise_coach_request_answer_versions_positive CHECK (version >= 1),
    CONSTRAINT exercise_coach_request_answer_versions_resolution CHECK (resolution IN (
        'exercise_chosen', 'exercise_authored', 'no_safe_match',
        'line_written', 'version_written', 'note_written'))
);
CREATE INDEX IF NOT EXISTS exercise_coach_request_answer_versions_take_idx
    ON public.exercise_coach_request_answer_versions (take_session_id);
ALTER TABLE public.exercise_coach_request_answer_versions ENABLE ROW LEVEL SECURITY;
COMMENT ON TABLE public.exercise_coach_request_answer_versions IS
    'Every answer a coach request had and no longer has (0446; Q-B12 A): the '
    'resolution, the exercise or the words, the video, who gave it and when, '
    'whether it was shared, and when and by whom it was replaced. Written only '
    'by resolve_exercise_coach_request_v3 when the same coach changes their '
    'answer. The current answer is the request row itself. Never shown to the '
    'speaker; purged with the Take and with its request.';

-- ── The guard, with one door ──────────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.guard_exercise_coach_request_update_v2()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = public
AS $$
DECLARE
    changing text := current_setting('willab.coach_answer_change', true);
BEGIN
    -- What was requested never changes, whoever asks.
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.owner_user_id IS DISTINCT FROM OLD.owner_user_id
       OR NEW.take_session_id IS DISTINCT FROM OLD.take_session_id
       OR NEW.snippet_id IS DISTINCT FROM OLD.snippet_id
       OR NEW.reason IS DISTINCT FROM OLD.reason
       OR NEW.pattern IS DISTINCT FROM OLD.pattern
       OR NEW.observed_tags IS DISTINCT FROM OLD.observed_tags
       OR NEW.request_trace IS DISTINCT FROM OLD.request_trace
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
    THEN
        RAISE EXCEPTION 'EXERCISE_COACH_REQUEST_IMMUTABLE';
    END IF;
    -- The resolver, changing this very row in this transaction, may replace
    -- the answer and the share (0446). Nobody else may.
    IF NULLIF(changing, '') IS NOT NULL AND changing = OLD.id::text THEN
        RETURN NEW;
    END IF;
    IF OLD.resolution IS NOT NULL AND (
        NEW.resolution IS DISTINCT FROM OLD.resolution
        OR NEW.resolved_exercise_id IS DISTINCT FROM OLD.resolved_exercise_id
        OR NEW.resolved_exercise_version IS DISTINCT FROM OLD.resolved_exercise_version
        OR NEW.resolved_by IS DISTINCT FROM OLD.resolved_by
        OR NEW.resolved_at IS DISTINCT FROM OLD.resolved_at)
    THEN
        RAISE EXCEPTION 'EXERCISE_COACH_REQUEST_ALREADY_RESOLVED';
    END IF;
    IF OLD.shared_at IS NOT NULL AND NEW.shared_at IS DISTINCT FROM OLD.shared_at THEN
        RAISE EXCEPTION 'EXERCISE_COACH_REQUEST_ALREADY_SHARED';
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION public.guard_exercise_coach_request_update_v2()
    FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS exercise_coach_request_guard
    ON public.exercise_coach_requests;
CREATE TRIGGER exercise_coach_request_guard
    BEFORE UPDATE ON public.exercise_coach_requests
    FOR EACH ROW EXECUTE FUNCTION public.guard_exercise_coach_request_update_v2();

-- ── The resolver, with the change ─────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.resolve_exercise_coach_request_v3(
    p_request_id UUID,
    p_coach_id TEXT,
    p_resolution TEXT,
    p_exercise_id TEXT,
    p_exercise_version INTEGER,
    p_share BOOLEAN,
    p_answer_text TEXT
) RETURNS public.exercise_coach_requests
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    current_row public.exercise_coach_requests;
    in_words BOOLEAN := p_resolution IN ('line_written', 'version_written', 'note_written');
    with_exercise BOOLEAN := p_resolution IN ('exercise_chosen', 'exercise_authored');
    answer TEXT := NULLIF(btrim(p_answer_text), '');
    same_answer BOOLEAN;
    next_version INTEGER;
BEGIN
    IF p_request_id IS NULL OR COALESCE(btrim(p_coach_id), '') = ''
       OR p_resolution IS NULL
       OR p_resolution NOT IN ('exercise_chosen', 'exercise_authored',
                               'no_safe_match', 'line_written', 'version_written',
                               'note_written')
       OR (p_resolution = 'no_safe_match'
           AND (p_exercise_id IS NOT NULL OR p_exercise_version IS NOT NULL
                OR COALESCE(p_share, false) OR answer IS NOT NULL))
       OR (with_exercise
           AND (COALESCE(btrim(p_exercise_id), '') = ''
                OR p_exercise_version IS NULL OR p_exercise_version < 1
                OR answer IS NOT NULL))
       OR (in_words
           AND (p_exercise_id IS NOT NULL OR p_exercise_version IS NOT NULL
                OR answer IS NULL))
    THEN
        RAISE EXCEPTION 'EXERCISE_COACH_REQUEST_INPUT_INVALID';
    END IF;

    SELECT * INTO current_row FROM public.exercise_coach_requests
     WHERE id = p_request_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'EXERCISE_COACH_REQUEST_NOT_FOUND';
    END IF;

    IF current_row.resolution IS NULL THEN
        -- The first answer, as 0403 wrote it.
        UPDATE public.exercise_coach_requests
           SET resolution = p_resolution,
               resolved_exercise_id = p_exercise_id,
               resolved_exercise_version = p_exercise_version,
               answer_text = answer,
               resolved_by = p_coach_id,
               resolved_at = now()
         WHERE id = p_request_id
        RETURNING * INTO current_row;
    ELSE
        same_answer := current_row.resolution IS NOT DISTINCT FROM p_resolution
            AND current_row.resolved_exercise_id IS NOT DISTINCT FROM p_exercise_id
            AND current_row.resolved_exercise_version IS NOT DISTINCT FROM p_exercise_version
            AND current_row.answer_text IS NOT DISTINCT FROM answer;
        IF NOT same_answer THEN
            IF current_row.resolved_by IS DISTINCT FROM p_coach_id THEN
                -- One coach's answer is not another's to change.
                RAISE EXCEPTION 'EXERCISE_COACH_REQUEST_ALREADY_RESOLVED';
            END IF;
            -- Q-B12 A: the old answer goes into the history, whole.
            SELECT COALESCE(max(version), 0) + 1 INTO next_version
              FROM public.exercise_coach_request_answer_versions
             WHERE request_id = p_request_id;
            INSERT INTO public.exercise_coach_request_answer_versions (
                request_id, take_session_id, snippet_id, version, resolution,
                resolved_exercise_id, resolved_exercise_version, answer_text,
                answer_video_ref, resolved_by, resolved_at, shared_at, superseded_by
            ) VALUES (
                current_row.id, current_row.take_session_id, current_row.snippet_id,
                next_version, current_row.resolution,
                current_row.resolved_exercise_id, current_row.resolved_exercise_version,
                current_row.answer_text, current_row.answer_video_ref,
                current_row.resolved_by, current_row.resolved_at, current_row.shared_at,
                p_coach_id
            );
            -- The door in the guard, for this row, in this transaction only.
            PERFORM set_config('willab.coach_answer_change', p_request_id::text, true);
            UPDATE public.exercise_coach_requests
               SET resolution = p_resolution,
                   resolved_exercise_id = p_exercise_id,
                   resolved_exercise_version = p_exercise_version,
                   answer_text = answer,
                   resolved_by = p_coach_id,
                   resolved_at = now(),
                   -- The old share belonged to the old answer: withdrawn with
                   -- it. The new answer is shared only if this call says so.
                   shared_at = CASE WHEN COALESCE(p_share, false) THEN now() END
             WHERE id = p_request_id
            RETURNING * INTO current_row;
            PERFORM set_config('willab.coach_answer_change', '', true);
            RETURN current_row;
        END IF;
    END IF;

    IF COALESCE(p_share, false) AND current_row.shared_at IS NULL THEN
        UPDATE public.exercise_coach_requests
           SET shared_at = now()
         WHERE id = p_request_id
        RETURNING * INTO current_row;
    END IF;
    RETURN current_row;
END;
$$;

COMMENT ON FUNCTION public.resolve_exercise_coach_request_v3(
    UUID, TEXT, TEXT, TEXT, INTEGER, BOOLEAN, TEXT) IS
    'The coach''s answer to a request (0446; Q-B12 A): first answer as 0403; '
    'the same again is a no-op that may add the share; a different answer by '
    'the same coach replaces it and keeps the old one in '
    'exercise_coach_request_answer_versions; another coach''s is refused. '
    'service_role only.';

-- ── The door ───────────────────────────────────────────────────────────────
-- Browser roles and PUBLIC get nothing on the history or the resolver,
-- whatever default privileges the schema carries (Supabase grants
-- anon/authenticated on public by default; PostgREST publishes every public
-- function). The app reads the history and calls the resolver with the
-- service key; the purge deletes history rows with the Take (and the
-- request's cascade does the rest); the history is written only by the
-- resolver. Roles are guarded: they exist on Supabase, not on a bare
-- Postgres.
REVOKE ALL ON TABLE public.exercise_coach_request_answer_versions FROM PUBLIC;
REVOKE ALL ON FUNCTION public.resolve_exercise_coach_request_v3(
    UUID, TEXT, TEXT, TEXT, INTEGER, BOOLEAN, TEXT) FROM PUBLIC;
DO $$
DECLARE
    v_role text;
BEGIN
    FOREACH v_role IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
            EXECUTE format('REVOKE ALL ON TABLE public.exercise_coach_request_answer_versions FROM %I', v_role);
            EXECUTE format('REVOKE ALL ON FUNCTION public.resolve_exercise_coach_request_v3(uuid, text, text, text, integer, boolean, text) FROM %I', v_role);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        REVOKE ALL ON TABLE public.exercise_coach_request_answer_versions FROM service_role;
        GRANT SELECT, DELETE ON TABLE public.exercise_coach_request_answer_versions TO service_role;
        GRANT EXECUTE ON FUNCTION public.resolve_exercise_coach_request_v3(
            uuid, text, text, text, integer, boolean, text) TO service_role;
    END IF;
END $$;

COMMIT;
