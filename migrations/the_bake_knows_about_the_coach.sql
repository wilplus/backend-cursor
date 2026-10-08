-- 0428 · What a coach makes of a bookmark retires the stored bookmark set.
--
-- FOUND 2026-10-05: a coach's share never reached a page whose feedback was
-- stored. The bake (0345) serves the Manager's block until anything is
-- written to the arc's mutable feedback surface after it, and 0351 named
-- that surface as four tables, all of them the SPEAKER's writes. The block
-- also carries the COACH's.
--
-- WHAT THE STORED BLOCK CARRIES FROM THE COACH. On a V3 Take whose owner
-- allows personalised practice, the block's practice stage
-- (`_practice_offer` -> `attach_v3_exercise_offer` ->
-- `_annotate_coach_answers`, services/confident_voice_practice.py) puts on
-- each Confident Voice bookmark what came of the moment's coach request:
--
--   * `coach_request` {status: open | answered, kind}: the request exists
--     (the promise "Your coach is working on your exercise.") or the coach
--     has answered it;
--   * `practice_exercise` with `chosen_by_coach`: the exercise the coach
--     resolved the request with and shared, as the moment's practice;
--   * `coach_answer` {kind, text, video_url}: the coach's words, and the
--     video with them, once shared.
--
-- All three pass the served-row allowlist (`CLIENT_ROW_FIELDS`), so they are
-- stored with the block and served from it. Each comes from a write to
-- `exercise_coach_requests`, which the rule never read: the request rises
-- (`created_at`, at the open or at the judgement), the coach answers
-- (`resolved_at`), the coach shares (`shared_at`, at the answer or later).
-- So a share made after the speaker's last answer stayed off the page until
-- the speaker answered something else, and the page kept the promise up over
-- an exercise that was already there.
--
-- THE BRANCH. The newest of those three times, for a request on any take of
-- this arc, reaching the arc through v2_sessions like the two branches above
-- it. The take id is TEXT on the request and UUID on the session, so the
-- session's id is cast to text and never the request's text to uuid: a
-- malformed id must not make the freshness read raise.
--
-- WHAT IS NOT IN IT, AND WHY.
--   * A withdrawal: none exists. 0385's guard refuses to unset `shared_at`
--     or to change a resolution once set, so there is no revocation time to
--     read. (The `revoked_at` in services/db.py belongs to the speaker's
--     Album lending, `voice_album_shares`, which the block does not read.)
--   * `answer_video_ref` has no time of its own, but a video can only be
--     added before the answer (services/coach_answer_video.py refuses a
--     resolved request) and rides only once shared, so `shared_at` covers it.
--   * `answered_at` (0408) is the speaker's judgement, which the answer
--     routes above already count; the block does not read `answer_kind`.
--   * `drafted_at` (0402) is the model's draft for the coach; it never rides.
--   * The coach's word for a Take (`coach_take_words`, 0403) is served by the
--     enrichment's `journey` section, read live on every request and never
--     stored with the bake.
--
-- ONLY THE FRESHNESS RULE CHANGES: 0351's body plus one UNION ALL branch.
-- The writer, the reader and what a bake stores are untouched. A coach write
-- costs the next open one live computation, which backfills a fresh bake:
-- the behaviour of every miss today.
--
-- NOT A CACHE OF THE DOCUMENT. Nothing here touches the words (L1); the
-- Manager still arbitrates exactly as before (L2); no provenance moves (L3):
-- a coach's answer reaches the speaker only as it already did, shared.
-- Nothing surfaces a score, a number or a coach's blind label (AC-9, BLIND
-- COACH). Additive and idempotent (CREATE OR REPLACE). No env var.
BEGIN;

-- ── The mutable surface, now including what the coach made of it ─────────
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
  ) AS surface;
$$;

-- ── GRANTS — the door, restated ───────────────────────────────────────────
-- CREATE OR REPLACE keeps the function's ACL, so this changes nothing; it is
-- restated, as in 0351, so the file is self-describing. Roles are guarded:
-- anon / authenticated / service_role exist on Supabase but not on a bare
-- Postgres.
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
