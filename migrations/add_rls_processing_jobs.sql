-- RLS on public.processing_jobs — the one table the 2026-07-25 sweep missed.
--
-- Found by test_migration_security_rules.py (PR #328) while freezing the
-- legacy allowlist: `processing_jobs` landed 2026-08-03 with the durable
-- Redis/RQ queue (#322), which is AFTER the sweep the founder ran on
-- 2026-07-25. docs/RLS-AUDIT.md does not list it, so nothing covers it — it
-- is readable AND writable today by anyone holding NEXT_PUBLIC_SUPABASE_ANON_KEY
-- from the browser bundle.
--
-- WHY THIS IS A SEPARATE MIGRATION rather than a line added to 0239
-- (add_processing_jobs.sql): 0239 is already in manifest.txt and may already
-- be recorded in schema_migrations. Editing an applied file changes its
-- sha256, which `migrate.py status` reports as drift — that check is the
-- point of the new migration runner, and tripping it to save one file would
-- teach everyone to ignore it. Append instead.
--
-- Consequence, stated so nobody is surprised: 0239 keeps its entry in
-- LEGACY_TABLES_WITHOUT_RLS, because that entry describes the FILE accurately
-- (it does create the table without RLS). The exposure is closed here.
--
-- Safe: the backend connects with SUPABASE_SERVICE_ROLE_KEY, which bypasses
-- RLS, and the RQ worker reaches this table through the same client. Zero
-- policies is the correct shape — anon can do nothing, the backend is
-- unaffected. Same reasoning as migrations/add_rls_all_public_tables.sql.
--
-- Idempotent: ENABLE ROW LEVEL SECURITY on a table that already has it is a
-- no-op, and the guard means a database without the table degrades to a
-- notice rather than aborting the run.

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relname = 'processing_jobs'
          AND c.relkind IN ('r', 'p')
    ) THEN
        ALTER TABLE public.processing_jobs ENABLE ROW LEVEL SECURITY;
        RAISE NOTICE 'processing_jobs: row level security enabled';
    ELSE
        RAISE NOTICE 'processing_jobs: table not present — nothing to do';
    END IF;
END $$;
