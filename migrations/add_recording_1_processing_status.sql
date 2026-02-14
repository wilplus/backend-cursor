-- Add recording_1_processing_status to v2_sessions for async recording-1 flow.
-- Values: 'pending' | 'completed' | 'failed'. NULL = legacy sync flow (treated as ready when score/task set).
-- Optional: recording_1_re_enqueue_attempted for at-most-once re-enqueue when stuck.
-- Run after v2_sessions exists. Canonical schema: .taskmaster/docs/schema.sql.

ALTER TABLE v2_sessions ADD COLUMN IF NOT EXISTS recording_1_processing_status TEXT;
ALTER TABLE v2_sessions ADD COLUMN IF NOT EXISTS recording_1_re_enqueue_attempted BOOLEAN DEFAULT FALSE;

COMMENT ON COLUMN v2_sessions.recording_1_processing_status IS 'pending | completed | failed. Used when POST recording-1 returns fast and job runs in background.';
COMMENT ON COLUMN v2_sessions.recording_1_re_enqueue_attempted IS 'True if we already re-enqueued recording-1 job once (stuck recovery).';
