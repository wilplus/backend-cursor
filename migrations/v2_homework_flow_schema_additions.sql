-- ============================================================================
-- Homework flow: assigned_warm_up_task_id + context_long_entries (append with timestamps)
-- Run after v2_homework_flow.sql. See docs/V2_FLOW_UNDERSTANDING_AND_IMPLEMENTATION_PLAN.md.
-- ============================================================================

-- 1) Admin assigns which warm-up task the student sees (one from the list)
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_student_overrides' AND column_name = 'assigned_warm_up_task_id') THEN
    ALTER TABLE v2_student_overrides
    ADD COLUMN assigned_warm_up_task_id UUID REFERENCES v2_warm_up_tasks(id) ON DELETE SET NULL;
  END IF;
END $$;

-- 2) Append-only report history (list of { "at": "ISO8601", "text": "..." })
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'context_long_entries') THEN
    ALTER TABLE v2_sessions ADD COLUMN context_long_entries JSONB DEFAULT '[]';
  END IF;
END $$;

COMMENT ON COLUMN v2_student_overrides.assigned_warm_up_task_id IS 'The single warm-up task the student sees for the next homework run. Admin sets this on student profile.';
COMMENT ON COLUMN v2_sessions.context_long_entries IS 'Append-only list of report entries: [{ "at": "ISO8601", "text": "..." }]. Latest = last element.';
