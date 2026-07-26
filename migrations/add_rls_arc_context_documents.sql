-- RLS for arc_context_documents (follow-up to X-1 / PR #252, 2026-07-25).
--
-- The original migration (add_arc_context_documents.sql) created the table
-- without enabling row level security. That table stores the EXTRACTED TEXT of
-- documents users upload about their talk (a brief, case metrics, a Q&A pack) —
-- their own private material.
--
-- Why that matters: the FE ships NEXT_PUBLIC_SUPABASE_ANON_KEY inlined into the
-- browser bundle, so anyone can read it out of the JS and call PostgREST
-- directly. With RLS off, the default public-schema grants to `anon` would allow
--     GET /rest/v1/arc_context_documents?select=*
-- returning every user's uploaded document text — bypassing Flask entirely, so
-- the API's owner check cannot defend it.
--
-- No policies are added on purpose: with RLS enabled and zero policies, `anon`
-- and `authenticated` can do nothing at all, while the backend — which connects
-- with SUPABASE_SERVICE_ROLE_KEY (services/db.py) — bypasses RLS and keeps full
-- access. Verified before writing this: the backend never uses the anon key,
-- and the FE performs no direct table reads (its only .from() calls are
-- supabase.storage.from(bucket)). So enabling RLS cannot break any live reader.
--
-- Idempotent: ENABLE ROW LEVEL SECURITY is a no-op when already enabled, and
-- the guard keeps this safe to run before the table exists.

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables
         WHERE schemaname = 'public' AND tablename = 'arc_context_documents'
    ) THEN
        ALTER TABLE public.arc_context_documents ENABLE ROW LEVEL SECURITY;
    END IF;
END $$;
