-- ============================================================================
-- Focus tasks: clone of warm-up tasks (pool + per-student list)
-- Same mechanics as v2_warm_up_task_pool + v2_warm_up_tasks.
-- Run after v2_schema_unified.sql (or equivalent) so auth.users exists.
-- ============================================================================

-- 1) Global pool (no user_id); admin adds/edits here
CREATE TABLE IF NOT EXISTS v2_focus_task_pool (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  text TEXT NOT NULL,
  order_index INT NOT NULL DEFAULT 0,
  max_performance_score DECIMAL(3,2) DEFAULT 1.00 CHECK (max_performance_score >= 0 AND max_performance_score <= 1),
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_v2_focus_task_pool_order ON v2_focus_task_pool(order_index);

COMMENT ON TABLE v2_focus_task_pool IS 'Global pool of focus tasks. Admin assigns which pool items apply to each student (same pattern as warm-up tasks).';

-- 2) Per-student focus tasks (one row per task per student)
CREATE TABLE IF NOT EXISTS v2_focus_tasks (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  text TEXT NOT NULL,
  order_index INT NOT NULL DEFAULT 0,
  pool_task_id UUID REFERENCES v2_focus_task_pool(id) ON DELETE SET NULL,
  max_performance_score DECIMAL(3,2) DEFAULT 1.00 CHECK (max_performance_score >= 0 AND max_performance_score <= 1),
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_v2_focus_tasks_user ON v2_focus_tasks(user_id);

COMMENT ON TABLE v2_focus_tasks IS 'Per-student focus tasks. Admin adds/edits/deletes on student profile (same UX as warm-up tasks).';
COMMENT ON COLUMN v2_focus_tasks.pool_task_id IS 'When set, this row was assigned from the focus task pool.';
