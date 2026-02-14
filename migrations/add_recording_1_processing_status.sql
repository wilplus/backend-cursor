-- Async recording-1: fast POST returns task_block; job sets status when done.
ALTER TABLE v2_sessions ADD COLUMN IF NOT EXISTS recording_1_processing_status TEXT;
ALTER TABLE v2_sessions ADD COLUMN IF NOT EXISTS recording_1_re_enqueue_attempted BOOLEAN DEFAULT FALSE;
