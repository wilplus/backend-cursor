-- 0420 · A package is bought once (founder 2026-10-05, "Packages"; contract
--        §8, items 48-50; decisions log N44).
--
-- Every purchase is a one-time package of tokens and any coach reviews it
-- includes; balances stay until spent and never renew. The tokens go into
-- the existing bonus_balance bucket, which no period roll touches. The coach
-- reviews need a bucket of their own that never resets either: this column.
-- The allowance a coach action is checked against becomes the tier's own
-- (the free tier's is 0) plus these credits, against coach_reviews_used,
-- which no longer resets.
--
-- Adds one nullable-safe column with a default. Changes no rows. Idempotent.

ALTER TABLE IF EXISTS public.v2_student_details
    ADD COLUMN IF NOT EXISTS coach_review_credits INTEGER NOT NULL DEFAULT 0;

DO $$
BEGIN
    IF to_regclass('public.v2_student_details') IS NOT NULL THEN
        COMMENT ON COLUMN public.v2_student_details.coach_review_credits IS
            'Coach reviews bought in one-time packages (0420). Never reset; '
            'spent against coach_reviews_used.';
    END IF;
END
$$;
