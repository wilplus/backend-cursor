-- the_bake_freshness_read_is_indexed (0515)
--
-- Every open of an Ideal Text asks the enrichment for `document_layers`,
-- and a stored bake is served only after
-- `ideal_text_feedback_surface_touched_at_v1` (0429, through
-- `read_ideal_text_feedback_bake_v1`, 0345) proves nothing was written to
-- the feedback surface since it was made. That function reads seven
-- tables. Five reach the arc through an index: intervention_decisions
-- (arc_id, ...), the memberships and owner responses (their UNIQUE keys
-- lead with take_id and membership_id), exercise_coach_requests and
-- moment_events (take_session_id), confident_voice_practice
-- (take_session_id, status), with v2_sessions found by idx_v2_sessions_arc_text
-- (0478). Two do not:
--
--   * user_suggestion_feedback, joined on `session_id`, which has no index
--     (only snippet_id and user_id do, add_user_suggestion_feedback.sql).
--     The join reads the whole table: every Apply/✓/revert tap ever made.
--     `get_suggestion_feedback_by_session` filters on the same column.
--   * take_feedback_self_report, filtered on `arc_id`, which has no index
--     (its UNIQUE key leads with take_session_id). Every answer ever given.
--
-- The founder's stopwatch (2026-11-09, the enrichment request of an open
-- Ideal Text): 1.77 s in all, `section_document_layers` 1.47 s, and one
-- database call 1.09 s of it; the bake read is that lane's first call and
-- these two table reads are the part of it that grows with the product.
--
-- TWO PLAIN INDEXES, NO FUNCTION CHANGE, as 0478 and 0483: the function
-- (0429) is applied and checksum-pinned, and both predicates are already
-- index-shaped as written.
--
-- Plain CREATE INDEX, not CONCURRENTLY, for 0474's reason: the runner sends
-- a file as one transaction block, where CONCURRENTLY is refused. Each build
-- holds a SHARE lock on its table (writes wait, reads continue) while it
-- runs; merge at a quiet moment. A database without either table gets a
-- notice, never a failure.
--
-- To see it taken up, in the Supabase SQL editor on an arc with a bake:
--   EXPLAIN (ANALYZE, BUFFERS)
--   SELECT public.ideal_text_feedback_surface_touched_at_v1('<arc id>');
--
-- Idempotent + additive, per the standing constraint: safe to re-run.
-- Nothing dropped; no env var.

DO $$
BEGIN
    IF to_regclass('public.user_suggestion_feedback') IS NOT NULL THEN
        CREATE INDEX IF NOT EXISTS idx_user_suggestion_feedback_session
            ON public.user_suggestion_feedback (session_id);
    ELSE
        RAISE NOTICE 'idx_user_suggestion_feedback_session: public.user_suggestion_feedback is not here; the index waits for it';
    END IF;
    IF to_regclass('public.take_feedback_self_report') IS NOT NULL THEN
        CREATE INDEX IF NOT EXISTS idx_take_feedback_self_report_arc
            ON public.take_feedback_self_report (arc_id);
    ELSE
        RAISE NOTICE 'idx_take_feedback_self_report_arc: public.take_feedback_self_report is not here; the index waits for it';
    END IF;
END $$;
