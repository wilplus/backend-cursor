-- Grant backend (PostgREST / service role) access to focus task tables.
-- Run in Supabase SQL Editor if admin GET/POST /v2/admin/students/<id>/task-focus
-- or /focus-tasks fails with PostgreSQL 42501 "permission denied for table v2_focus_tasks".
--
-- The Flask app uses SUPABASE_SERVICE_ROLE_KEY; PostgREST still needs table GRANTs
-- (RLS bypass does not imply superuser). Same pattern as grant_sniper_tables_service_role.sql.

GRANT ALL ON TABLE public.v2_focus_tasks TO service_role;
GRANT ALL ON TABLE public.v2_focus_task_pool TO service_role;
