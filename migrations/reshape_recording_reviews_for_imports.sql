-- Make recording_reviews usable for standalone imported recordings.
-- Keeps session-based reviews working while allowing recording-only rows.
-- Run in Supabase SQL Editor. Idempotent.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

ALTER TABLE public.recording_reviews
  ADD COLUMN IF NOT EXISTS id UUID DEFAULT uuid_generate_v4();

UPDATE public.recording_reviews
SET id = uuid_generate_v4()
WHERE id IS NULL;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conrelid = 'public.recording_reviews'::regclass
      AND conname = 'recording_reviews_pkey'
  ) THEN
    ALTER TABLE public.recording_reviews DROP CONSTRAINT recording_reviews_pkey;
  END IF;
END $$;

ALTER TABLE public.recording_reviews
  ALTER COLUMN id SET NOT NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conrelid = 'public.recording_reviews'::regclass
      AND conname = 'recording_reviews_pkey'
  ) THEN
    ALTER TABLE public.recording_reviews ADD CONSTRAINT recording_reviews_pkey PRIMARY KEY (id);
  END IF;
END $$;

ALTER TABLE public.recording_reviews
  ALTER COLUMN session_id DROP NOT NULL;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'recording_reviews'
      AND column_name = 'overall_quality'
      AND data_type <> 'text'
  ) THEN
    ALTER TABLE public.recording_reviews
      ALTER COLUMN overall_quality TYPE TEXT
      USING overall_quality::TEXT;
  END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_recording_reviews_unique_session
  ON public.recording_reviews(session_id)
  WHERE session_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_recording_reviews_recording_id
  ON public.recording_reviews(recording_id);

COMMENT ON TABLE public.recording_reviews IS
'Admin-only ML labels for either a homework session review or a standalone imported recording.';

COMMENT ON COLUMN public.recording_reviews.session_id IS
'Optional linkage to a homework session. Null for standalone admin imports.';

COMMENT ON COLUMN public.recording_reviews.recording_id IS
'Recording being reviewed. Used for imported recordings and may also point at a session recording.';

COMMENT ON COLUMN public.recording_reviews.overall_quality IS
'Internal categorical quality label, e.g. good, bad, unclear.';
