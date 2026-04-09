-- Private Supabase Storage bucket for annotation export JSONL files.
-- Run in Supabase SQL Editor. Set env: ANNOTATION_EXPORT_BUCKET=annotation_exports
--
-- Backend uploads with SUPABASE_SERVICE_ROLE_KEY (service_role normally bypasses Storage RLS).

INSERT INTO storage.buckets (id, name, public)
VALUES ('annotation_exports', 'annotation_exports', false)
ON CONFLICT (id) DO NOTHING;

-- Optional: tighten object size / MIME types (uncomment if your storage.buckets has these columns)
-- UPDATE storage.buckets
-- SET
--   file_size_limit = 52428800,
--   allowed_mime_types = ARRAY['application/x-ndjson', 'application/json', 'text/plain']::text[]
-- WHERE id = 'annotation_exports';
