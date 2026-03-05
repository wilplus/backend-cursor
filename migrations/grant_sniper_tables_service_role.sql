-- Grant backend (service role) access to Sniper tables.
-- Run this in Supabase SQL Editor if you get "permission denied for table user_sniper_profile"
-- or "permission denied for table session_sniper_metrics" (PostgreSQL 42501).
-- The backend uses SUPABASE_SERVICE_ROLE_KEY; in Supabase the corresponding role is usually "service_role".
-- If your project uses a different role for the service key, replace service_role below.

GRANT ALL ON TABLE user_sniper_profile TO service_role;
GRANT ALL ON TABLE session_sniper_metrics TO service_role;
