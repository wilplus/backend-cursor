-- a_moment_is_found_by_its_id_as_text (0483)
--
-- The feedback-policy writer that runs when an Ideal Text opens after a
-- Take, `record_take_feedback_policy_v3_shadow_v3` (0309, carried through
-- the shadow-writer files to 0441), joins each candidate's moment with
--
--     JOIN public.snippets snippet ON snippet.id::text = candidate ->> 'snippet_id'
--
-- three times per call, and `record_v4_willfidence_reads_v1` (0449) and
-- `mark_feedback_pairs_trained_v1` (0406) join the same way. snippets.id is
-- the table's UUID primary key, whose index cannot serve a predicate on
-- `id::text`, so each of those joins reads the whole snippets table, every
-- moment of every Take.
--
-- The founder's stopwatch (2026-10-20, the Ideal Text opening right after
-- Take 3): the fast lane's two primary-key fence reads took 940 ms and one
-- indexed select 579 ms, while the bookmarks lane ran that writer on the
-- same database. Nothing in those reads can be slow on its own; they were
-- waiting behind the table reads.
--
-- ONE EXPRESSION INDEX, NO FUNCTION CHANGE, as 0478 (v2_sessions.arc_id)
-- and 0481 (snippets.session_id): `uuid::text` is an immutable cast, so it
-- can be indexed as written and every join above becomes an index lookup.
-- The same guard as 0481: a database without public.snippets gets a
-- notice, never a failure.
--
-- Plain CREATE INDEX, not CONCURRENTLY, for 0474's reason: the runner sends
-- a file as one transaction block, where CONCURRENTLY is refused. The build
-- holds a SHARE lock on snippets (writes wait, reads continue) while it
-- runs; merge at a quiet moment.
--
-- Idempotent + additive, per the standing constraint: safe to re-run.
-- Nothing dropped; no env var.

DO $$
BEGIN
    IF to_regclass('public.snippets') IS NOT NULL THEN
        CREATE INDEX IF NOT EXISTS idx_snippets_id_text
            ON public.snippets ((id::text));
    ELSE
        RAISE NOTICE 'idx_snippets_id_text: public.snippets is not here; the index waits for it';
    END IF;
END $$;
