-- Removes internal ML labeling tables (session/import reviews + span annotations).
-- Run in Supabase SQL Editor only after deploying backend that no longer references these tables.
-- Destructive: backup first if you still need the data.

DROP TABLE IF EXISTS public.recording_review_annotations;
DROP TABLE IF EXISTS public.recording_reviews;
