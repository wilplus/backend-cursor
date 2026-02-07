-- ============================================================================
-- RESET PUBLIC SCHEMA — run this BEFORE supabase-schema-complete-app.sql
-- Deletes all tables (and everything else) in the public schema. Does NOT touch auth.users.
-- Run in Supabase SQL Editor. After this, run supabase-schema-complete-app.sql.
-- ============================================================================

DROP SCHEMA public CASCADE;
CREATE SCHEMA public;

-- Restore default grants (Supabase expects these)
GRANT USAGE ON SCHEMA public TO postgres;
GRANT USAGE ON SCHEMA public TO anon;
GRANT USAGE ON SCHEMA public TO authenticated;
GRANT USAGE ON SCHEMA public TO service_role;
GRANT ALL ON SCHEMA public TO postgres;
GRANT ALL ON SCHEMA public TO anon;
GRANT ALL ON SCHEMA public TO authenticated;
GRANT ALL ON SCHEMA public TO service_role;

-- Re-enable RLS if you use it (optional)
-- ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO postgres;
