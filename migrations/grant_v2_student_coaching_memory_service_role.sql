-- Grant backend (service role) access to v2_student_coaching_memory.
-- Run in Supabase SQL Editor if admin GET /v2/admin/students/<id> fails with
-- PostgreSQL 42501 "permission denied for table v2_student_coaching_memory".
--
-- PostgREST uses the JWT role. The Flask backend uses SUPABASE_SERVICE_ROLE_KEY,
-- which maps to role service_role. That role must have table privileges; RLS
-- alone does not grant them. Same pattern as grant_sniper_tables_service_role.sql.

GRANT ALL ON TABLE public.v2_student_coaching_memory TO service_role;
