-- 0261 · stress_snippets — RETIRED IN PLACE. Founder decision 2026-08-10.
--
-- NO DROP. NO DELETE. NO TRUNCATE. This migration writes a comment and
-- nothing else. The rows stay exactly where they are, readable forever by
-- anyone who opens the table.
--
-- WHY RETIRE RATHER THAN DROP. The stress lane produced real coach labels
-- against real recordings. That is training data a human generated, and it
-- cannot be re-derived — the clip generator that produced the candidates was
-- deleted (PR #368) and the model that ranked them was deleted before that.
-- Dropping the table would destroy the only surviving record of that work to
-- reclaim a rounding error of disk.
--
-- WHAT "RETIRED IN PLACE" MEANS, PRECISELY:
--   * nothing WRITES it. The label writer went in #368; the AI-draft writer
--     (set_stress_snippet_ai_draft_notes) goes with this change.
--   * nothing READS it. Two readers existed and both are gone: the coach
--     prefill draft generator, and the stress branch of the publish-time
--     annotation capture in record_snippet_publish_annotations.
--   * the rows are FROZEN — not archived, not moved, not compressed.
--   * the table keeps its RLS enablement, so retirement does not widen access.
--
-- THE ONE THING THAT WOULD MAKE THIS A LIE is a new writer. There is no
-- constraint here forbidding one, deliberately — a trigger that raises on
-- INSERT would be a live failure mode on a table nobody touches, which is a
-- worse trade than a comment. The enforcement lives in the test suite
-- (test_stress_snippets_retired), where a reintroduced call site fails CI
-- before it can reach production.
--
-- IF THE DATA IS EVER WANTED: it is a plain table, so
--   SELECT * FROM public.stress_snippets;
-- still works, today and in five years. Retirement is a statement about the
-- CODE, not a change to the DATA.
--
-- Idempotent. Safe to re-run. Non-destructive by construction — the only
-- statement is a COMMENT.

BEGIN;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
         WHERE table_schema = 'public' AND table_name = 'stress_snippets'
    ) THEN
        COMMENT ON TABLE public.stress_snippets IS
            'RETIRED IN PLACE 2026-08-10 (founder decision). No writer, no '
            'reader, rows FROZEN and deliberately kept: they are '
            'human-generated coach labels that cannot be re-derived, since '
            'the clip generator and the model that ranked it were both '
            'deleted. Do not DROP. Do not add a writer — if this lane is ever '
            'revived, mint a new table rather than mixing new rows into a '
            'frozen corpus, exactly as detector_version handles a changed '
            'definition. Query it freely; it is a normal table.';
        RAISE NOTICE 'stress_snippets marked retired-in-place';
    ELSE
        RAISE NOTICE 'stress_snippets not present — nothing to mark';
    END IF;
END$$;

COMMIT;

-- ROLLBACK: none needed. This migration changes no data and no structure.
--   COMMENT ON TABLE public.stress_snippets IS NULL;   -- if you must
