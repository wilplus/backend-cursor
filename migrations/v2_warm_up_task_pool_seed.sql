-- ============================================================================
-- Seed warm-up task pool from existing v2_warm_up_tasks
-- Run after v2_warm_up_task_pool.sql. Ensures the modal (which loads the pool)
-- shows the same tasks as the v2_warm_up_tasks table.
-- ============================================================================

-- 1) Insert into pool one row per distinct text from v2_warm_up_tasks not already in pool
INSERT INTO v2_warm_up_task_pool (text, order_index, max_performance_score)
SELECT w.text, w.order_index, COALESCE(w.max_performance_score::numeric, 1.00)
FROM (
  SELECT DISTINCT ON (text) text, order_index, max_performance_score
  FROM v2_warm_up_tasks
  ORDER BY text, created_at
) w
WHERE NOT EXISTS (SELECT 1 FROM v2_warm_up_task_pool p WHERE p.text = w.text);

-- 2) Link existing student tasks to pool (set pool_task_id where text matches)
UPDATE v2_warm_up_tasks w
SET pool_task_id = p.id
FROM v2_warm_up_task_pool p
WHERE w.text = p.text
  AND w.pool_task_id IS NULL;
