-- Idempotent credit charge on homework completion (not at session start).
-- Run in Supabase SQL Editor after v2_sessions exists.

ALTER TABLE public.v2_sessions
  ADD COLUMN IF NOT EXISTS homework_credits_charged_at TIMESTAMPTZ;

COMMENT ON COLUMN public.v2_sessions.homework_credits_charged_at IS
  'When 5 homework credits were deducted for this session. Set once when status becomes completed with a report; prevents double charge.';

-- Already-finished sessions: treat as charged under the old "deduct at start" model so deploy does not deduct again.
UPDATE public.v2_sessions
SET homework_credits_charged_at = COALESCE(completed_at, created_at, NOW())
WHERE status = 'completed'
  AND homework_credits_charged_at IS NULL;
