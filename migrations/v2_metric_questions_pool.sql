-- ============================================================================
-- Metric questions pool: 3 editable questions (metric_question_1, 2, 3)
-- Same mechanics as warm-up-task-pool: list in admin, add/edit/delete.
-- Student flow uses first 3 by order_index as metric_question_1, 2, 3.
-- ============================================================================

CREATE TABLE IF NOT EXISTS v2_metric_questions_pool (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  text TEXT NOT NULL,
  order_index INT NOT NULL DEFAULT 0,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_v2_metric_questions_pool_order ON v2_metric_questions_pool(order_index);

COMMENT ON TABLE v2_metric_questions_pool IS 'Pool of metric questions. Admin can add/edit/delete (same as warm-up-task-pool). Student flow uses first 3 by order_index as metric_question_1, metric_question_2, metric_question_3.';

-- Seed 3 default questions in one go when pool is empty (so 3 questions always exist for flow)
INSERT INTO v2_metric_questions_pool (text, order_index)
SELECT v.text, v.order_index
FROM (VALUES
  ('How would you rate your pacing in that take?', 1),
  ('How would you rate your vocal strength?', 2),
  ('How would you rate your clarity and articulation?', 3)
) AS v(text, order_index)
WHERE NOT EXISTS (SELECT 1 FROM v2_metric_questions_pool LIMIT 1);
