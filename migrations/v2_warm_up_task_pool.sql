-- ============================================================================
-- Warm-up task pool: global pool + per-student assignment
-- Run after v2_all_in_one.sql. Enables "Select Warm-up Tasks" modal: show all
-- pool tasks, tick which apply to each student, confirm to sync.
-- ============================================================================

-- 1) Global pool (no user_id); admin adds/edits here
CREATE TABLE IF NOT EXISTS v2_warm_up_task_pool (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  text TEXT NOT NULL,
  order_index INT NOT NULL DEFAULT 0,
  max_performance_score DECIMAL(3,2) DEFAULT 1.00 CHECK (max_performance_score >= 0 AND max_performance_score <= 1),
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_v2_warm_up_task_pool_order ON v2_warm_up_task_pool(order_index);

COMMENT ON TABLE v2_warm_up_task_pool IS 'Global pool of warm-up tasks. Admin selects which pool items apply to each student via Select Warm-up Tasks modal.';

-- 2) Link student tasks to pool (optional); when set, task was assigned from pool
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_warm_up_tasks' AND column_name = 'pool_task_id') THEN
    ALTER TABLE v2_warm_up_tasks
    ADD COLUMN pool_task_id UUID REFERENCES v2_warm_up_task_pool(id) ON DELETE SET NULL;
  END IF;
END $$;

COMMENT ON COLUMN v2_warm_up_tasks.pool_task_id IS 'When set, this student task was assigned from the warm-up task pool. Used to show which pool items are selected for this student.';
