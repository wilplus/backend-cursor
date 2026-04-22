-- Add is_archived flag to v2_student_details.
-- When true the student is hidden from all Training Studio / cohort lists.
-- Safe to run multiple times.

ALTER TABLE public.v2_student_details
  ADD COLUMN IF NOT EXISTS is_archived BOOLEAN NOT NULL DEFAULT false;

CREATE INDEX IF NOT EXISTS idx_v2_student_details_is_archived
  ON public.v2_student_details (is_archived)
  WHERE is_archived = true;
