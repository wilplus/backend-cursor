-- Homework credits balance (used by Stripe webhook / claim-checkout and session/status).
-- Safe to run multiple times in Supabase SQL Editor.

ALTER TABLE public.v2_student_details
  ADD COLUMN IF NOT EXISTS credits integer;

COMMENT ON COLUMN public.v2_student_details.credits IS
  'Homework credits; NULL means app default (15). Required for Stripe top-ups and session/status.';
