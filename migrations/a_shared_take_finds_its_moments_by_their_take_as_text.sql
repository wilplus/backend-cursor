-- a_shared_take_finds_its_moments_by_their_take_as_text (0481)
--
-- The peer queue ("Other speakers · 1 of 1" in the Feedback walk) reads
-- the view community_clips_live (0432), which joins a shared Take to its
-- moments with
--
--     JOIN public.snippets sn ON sn.session_id::text = s.take_session_id
--
-- take_shares.take_session_id is text; snippets.session_id is a UUID with
-- a plain index on it. A btree on `session_id` cannot serve a predicate on
-- `session_id::text`, so the join has no index to use and reads the whole
-- snippets table, every moment of every Take, on every open of that
-- screen. 0478 fixed the same shape on v2_sessions.arc_id for the Ideal
-- Text read (1.69 s to 0.28 s); this is the same fix for the queue.
--
-- ONE EXPRESSION INDEX, NO VIEW CHANGE. `uuid::text` is an immutable cast,
-- so it can be indexed as written and the view's join becomes an index
-- lookup without the view being redefined. The view is only created where
-- public.snippets exists (0432's guard), so the index takes the same guard
-- and a database without the table gets a notice, never a failure.
--
-- Plain CREATE INDEX, not CONCURRENTLY, for 0474's reason: the runner sends
-- a file as one transaction block, where CONCURRENTLY is refused. The build
-- holds a SHARE lock on snippets (writes wait, reads continue) while it
-- runs; snippets is the largest table on the hot path, so merge this at a
-- quiet moment.
--
-- Idempotent + additive, per the standing constraint: safe to re-run.
-- Nothing dropped; no env var.

DO $$
BEGIN
    IF to_regclass('public.snippets') IS NOT NULL THEN
        CREATE INDEX IF NOT EXISTS idx_snippets_session_text
            ON public.snippets ((session_id::text));
    ELSE
        RAISE NOTICE 'idx_snippets_session_text: public.snippets is not here; the index waits for it';
    END IF;
END $$;
