-- Optional: when recording_1_processing_status = 'failed', store a stable error code for logs and frontend.
-- Run in Supabase SQL Editor after add_recording_1_processing_status.sql.
ALTER TABLE v2_sessions ADD COLUMN IF NOT EXISTS recording_1_processing_error_code TEXT;
COMMENT ON COLUMN v2_sessions.recording_1_processing_error_code IS 'When recording_1_processing_status = failed: transcription_failed, storage_error, context_generation_failed, db_error, session_missing, or unknown. For logging and optional frontend message.';
