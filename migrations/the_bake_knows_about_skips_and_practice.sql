-- 0430 · A skip or a practice settles a bookmark, and retires the stored set.
--
-- FOUND 2026-10-05, beside the coach's share (0428): a skip or a finished
-- practice came back as undecided after a reload. With judgement after
-- feedback on (Config.JUDGEMENT_AFTER_FEEDBACK_ENABLED, a code constant set
-- True), the block marks a bookmark settled without a Path 1 answer
-- (`_mark_settled_without_answer`, services/ideal_text_changes.py, reading
-- `services.moment_events.settled_status_by_moment`):
--
--   * a skip, a `moment_events` row with event 'skipped': dismissed;
--   * a practice closed as completed with Yes or In-between: approved;
--     completed otherwise, or dismissed: dismissed.
--
-- The exercise offer on the same bookmark reads the moment's practice too
-- (`_attach_exercises` and `_annotate_coach_answers`,
-- services/confident_voice_practice.py): a closed practice ends the offer,
-- an open one is named in it (`practice_id`, `resume`). All of this is
-- stored with the bake, and neither table was in the rule, so the reload
-- served the moment as still waiting on the speaker, until some other write.
--
-- THE TWO BRANCHES, joined to the arc through the take like every branch.
--   * `moment_events.created_at` for a skip only. The table is insert-once
--     per (take, moment, event) and dated by the database. An open is not
--     counted: it settles nothing, and a speaker opens bookmarks all the
--     time. (Under F1 an open may raise the moment's coach request; that
--     write is counted since 0428.) The take id is TEXT here, so the
--     session's id is cast to text, never the event's text to uuid.
--   * `confident_voice_practice.created_at` and `closed_at`, the start and
--     the close. Every write that changes `status` or `final_user_answer`
--     is a close from 'open' (dismissal, the complete route, a judged
--     attempt) and stamps `closed_at` in the same patch; nothing reopens a
--     practice; and no SQL function writes the table. `updated_at` is not
--     read: every write moves it, including the ones that change nothing
--     the block shows (a coach's review, the chat receipt, the after-practice
--     line). An attempt writes `confident_voice_practice_attempt` and leaves
--     the practice row alone, so attempts never retire the bake.
--
-- ONE CLOCK CAVEAT, the one `intervention_decisions.updated_at` has carried
-- since 0345: `closed_at` is dated by the app server's clock, `baked_at` by
-- the database's. A close committed within the clocks' skew (milliseconds;
-- both are NTP-disciplined) of the computation's start could be read as
-- already seen. Everything else here is dated by the database.
--
-- WHAT IS NOT IN IT: a deletion leaves no time, as for every branch.
-- Practice rows go only with the retention sweep or the speaker's
-- withdrawal of personalised practice; skips only with a purge.
--
-- ONLY THE FRESHNESS RULE CHANGES: 0428's body plus two UNION ALL branches.
-- The writer, the reader and what a bake stores are untouched. A skip, a
-- practice start or a close costs the next open one live computation, which
-- backfills a fresh bake.
--
-- NOT A CACHE OF THE DOCUMENT. Nothing here touches the words (L1); the
-- Manager still arbitrates exactly as before (L2); no provenance moves (L3).
-- Nothing surfaces a score, a number or a coach's blind label (AC-9, BLIND
-- COACH). Additive and idempotent (CREATE OR REPLACE). No env var.
BEGIN;

-- ── The mutable surface, now including a moment settled without an answer
CREATE OR REPLACE FUNCTION public.ideal_text_feedback_surface_touched_at_v1(
    p_arc_id TEXT
) RETURNS TIMESTAMPTZ
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public AS $$
  SELECT max(touched) FROM (
    SELECT max(GREATEST(decision.created_at, decision.updated_at)) AS touched
      FROM public.intervention_decisions decision
     WHERE decision.arc_id = p_arc_id
    UNION ALL
    SELECT max(tap.created_at) AS touched
      FROM public.user_suggestion_feedback tap
      JOIN public.v2_sessions session ON session.id = tap.session_id
     WHERE session.arc_id::text = p_arc_id
    UNION ALL
    -- The legacy answer route. `arc_id` is stored on the row itself.
    SELECT max(report.created_at) AS touched
      FROM public.take_feedback_self_report report
     WHERE report.arc_id = p_arc_id
    UNION ALL
    -- The service answer route. An answer names its membership; the
    -- membership names its take; the take names the arc.
    SELECT max(answer.created_at) AS touched
      FROM public.feedback_v3_owner_responses answer
      JOIN public.feedback_v3_memberships membership
        ON membership.id = answer.membership_id
      JOIN public.v2_sessions session ON session.id = membership.take_id
     WHERE session.arc_id::text = p_arc_id
    UNION ALL
    -- What the coach made of a bookmark (0428): the request rose, the coach
    -- answered, the coach shared. A request names its take by text; the
    -- take names the arc.
    SELECT max(GREATEST(request.created_at, request.resolved_at,
                        request.shared_at)) AS touched
      FROM public.exercise_coach_requests request
      JOIN public.v2_sessions session
        ON session.id::text = request.take_session_id
     WHERE session.arc_id::text = p_arc_id
    UNION ALL
    -- A moment settled without an answer: the speaker skipped it. An open
    -- settles nothing and is not counted. An event names its take by text;
    -- the take names the arc.
    SELECT max(moment.created_at) AS touched
      FROM public.moment_events moment
      JOIN public.v2_sessions session
        ON session.id::text = moment.take_session_id
     WHERE session.arc_id::text = p_arc_id
       AND moment.event = 'skipped'
    UNION ALL
    -- Or the speaker practised it: a practice started (the offer names the
    -- practice it resumes) or closed, completed or dismissed (the moment
    -- settles, the offer goes). Never `updated_at`, which every write to a
    -- practice moves. A practice names its take by uuid.
    SELECT max(GREATEST(practice.created_at, practice.closed_at)) AS touched
      FROM public.confident_voice_practice practice
      JOIN public.v2_sessions session ON session.id = practice.take_session_id
     WHERE session.arc_id::text = p_arc_id
  ) AS surface;
$$;

-- ── GRANTS — the door, restated ───────────────────────────────────────────
-- CREATE OR REPLACE keeps the function's ACL, so this changes nothing; it is
-- restated, as in 0351 and 0428, so the file is self-describing. Roles are
-- guarded: anon / authenticated / service_role exist on Supabase but not on
-- a bare Postgres.
REVOKE ALL ON FUNCTION public.ideal_text_feedback_surface_touched_at_v1(
    TEXT) FROM PUBLIC;

DO $$
DECLARE
    r   text;
    sig text := 'public.ideal_text_feedback_surface_touched_at_v1(text)';
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON FUNCTION %s FROM %I', sig, r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO service_role', sig);
    END IF;
END $$;

COMMIT;
