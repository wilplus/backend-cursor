-- ============================================================================
-- Add missing column: max_performance_score on v2_warm_up_tasks and v2_focus_tasks
--
-- Error: "Could not find the 'max_performance_score' column ... in the schema
-- cache" (PGRST204) → 503 on admin Save.
--
-- Two possible causes:
-- 1) Column really missing (table created without it). Fix: run the ALTERs below.
-- 2) Column exists but PostgREST is using a stale schema cache. Fix: run
--    NOTIFY pgrst, 'reload schema'; then wait 5–10 seconds and retry.
--
-- Type: we use DECIMAL(3,2) 0–1 to match the backend. If the column already
-- exists with another type (e.g. INTEGER), ADD COLUMN IF NOT EXISTS does
-- nothing; run NOTIFY anyway — often the cache is the only problem.
-- ============================================================================

-- 1) Warm-up tasks
ALTER TABLE public.v2_warm_up_tasks
ADD COLUMN IF NOT EXISTS max_performance_score DECIMAL(3,2) DEFAULT 1.00
CHECK (max_performance_score >= 0 AND max_performance_score <= 1);

-- 2) Focus tasks (in case table was created without this column)
ALTER TABLE public.v2_focus_tasks
ADD COLUMN IF NOT EXISTS max_performance_score DECIMAL(3,2) DEFAULT 1.00
CHECK (max_performance_score >= 0 AND max_performance_score <= 1);

-- 3) CRITICAL: Reload PostgREST schema cache. Wait 5–10 seconds after this
--    before retrying the admin Save. PGRST204 often means cache was stale.
NOTIFY pgrst, 'reload schema';
