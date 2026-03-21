-- Add metadata support for admin-imported recordings.
-- Run in Supabase SQL Editor. Idempotent.

ALTER TABLE public.recordings
  ADD COLUMN IF NOT EXISTS recording_origin TEXT NULL,
  ADD COLUMN IF NOT EXISTS source_metadata JSONB NULL;

COMMENT ON COLUMN public.recordings.recording_origin IS
'Marks how the recording entered the system, e.g. admin_import or homework.';

COMMENT ON COLUMN public.recordings.source_metadata IS
'JSON metadata for imported/external recordings (source_kind, source_url, source_title, speaker_label, language_code, transcript_text, import_notes, imported_by, imported_at).';
