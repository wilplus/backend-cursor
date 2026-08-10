-- 0260 · charisma_snippets → snippets. The name was always wrong.
--
-- DO NOT RUN THIS UNTIL THE CODE CARRYING services/snippet_tables.py IS
-- DEPLOYED. The cutover is three ordered steps and this file is step 2:
--
--   1. deploy the code that reads the name from SNIPPETS_TABLE  (no-op)
--   2. run THIS migration                                       (renames)
--   3. set SNIPPETS_TABLE=snippets in Railway                   (seconds)
--
-- Between 2 and 3 the running code queries a table that no longer exists.
-- PostgREST answers 404 and this codebase swallows those exceptions BY
-- DESIGN, so the failure is SILENT — snippet writes would simply stop. Step 3
-- is a config change, not a deploy, so hold that window to seconds and have
-- the Railway tab already open before running this.
--
-- ROLLBACK IS THE SAME TWO STEPS BACKWARDS and equally fast: unset
-- SNIPPETS_TABLE, then run the rename in reverse (bottom of this file).
--
-- ── WHY THERE IS NO COMPATIBILITY VIEW ────────────────────────────────────
-- The obvious kindness — leave a `charisma_snippets` view behind so old code
-- keeps working — is specifically DANGEROUS on this table.
-- add_rls_all_public_tables.sql names charisma_snippets as one `anon` can
-- reach directly through PostgREST, where "RLS is the only control on it". A
-- view executes with its OWNER's rights unless declared
-- `security_invoker = true`, so a naive compat view silently reopens that
-- hole — and nothing would look wrong, because the backend connects with the
-- service-role key and bypasses RLS anyway. The env-var cutover above buys
-- the same safety with no view at all.
--
-- ── WHAT MOVES WITH THE TABLE, AUTOMATICALLY ──────────────────────────────
-- ALTER TABLE ... RENAME carries the RLS enablement and policies, every
-- index, every constraint, the three inbound foreign keys
-- (coaching_attempts, coaching_sessions, snippet_confidence_reviews) and all
-- grants. Nothing needs re-granting and no dependent needs editing.
--
-- INDEX AND CONSTRAINT NAMES ARE LEFT ALONE on purpose. They still read
-- idx_charisma_snippets_*, which is cosmetic; renaming them adds churn and
-- risk to a step whose whole value is being boring and reversible.
--
-- ── WHAT IS DELIBERATELY NOT RENAMED ──────────────────────────────────────
-- The STORAGE prefix `charisma_snippets/<session>/...`. Those object keys are
-- immutable history: every clip already uploaded lives under that prefix, and
-- rewriting the prefix would point at nothing. Storage keys are history; the
-- table name is a pointer. Only the pointer moves.
-- Columns keep their names too — `user_charisma_label`, `snippet_type` — for
-- the same reason: this migration renames ONE thing.
--
-- Idempotent: re-running after a successful rename is a no-op, and it will
-- not fire if a table called `snippets` already exists for any other reason.

BEGIN;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
         WHERE table_schema = 'public' AND table_name = 'charisma_snippets'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.tables
         WHERE table_schema = 'public' AND table_name = 'snippets'
    ) THEN
        ALTER TABLE public.charisma_snippets RENAME TO snippets;
        RAISE NOTICE 'renamed charisma_snippets -> snippets';
    ELSE
        RAISE NOTICE 'no rename performed (already done, or snippets exists)';
    END IF;
END$$;

COMMENT ON TABLE public.snippets IS
    'Audio snippets. Four producers, distinguished by source_type: interview '
    'turns and funnel cold-start rows and willab Lab auto-cuts all leave it '
    'NULL; the retired ML generator set student/internet (deleted 2026-08-10, '
    'its rows kept). Named charisma_snippets until 2026-08-10, after the one '
    'producer that no longer exists. Storage keys still carry the old prefix '
    'and are NOT renamed — those object paths are immutable history.';

COMMIT;

-- ROLLBACK (run this, THEN unset SNIPPETS_TABLE in Railway):
--   ALTER TABLE public.snippets RENAME TO charisma_snippets;
