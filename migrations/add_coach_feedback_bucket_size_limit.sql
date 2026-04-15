-- Ensure coach feedback bucket accepts large reference videos (default app limit: 500MB).
-- Run in Supabase SQL Editor. Safe/idempotent.

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'storage'
      AND table_name = 'buckets'
      AND column_name = 'file_size_limit'
  ) THEN
    UPDATE storage.buckets
    SET file_size_limit = 524288000  -- 500 MB
    WHERE id = 'coach_feedback_videos';
  END IF;
END $$;
