-- willab — arc unlock via CREDITS (founder re-price 2026-07-06: $50 Stripe-
-- direct → $25 = 25 credits, spent from the existing credits balance).
--
-- Reuses the existing arc_purchases row/entitlement (unique(arc_id) already
-- IS the atomic double-charge guard — see services/db.create_arc_purchase).
-- No new charge_type/unlocked_at columns: `source` already distinguishes the
-- payment path ('stripe' | 'invite_code' | 'manual' | NEW 'credits'), and
-- `created_at` already marks when the row landed. Only the credit amount is
-- new information.
--
-- Legacy $50 Stripe-direct rows (source='stripe', credits_charged=NULL) are
-- untouched and remain fully entitled — is_arc_entitled only checks row
-- existence, never the charge shape.
ALTER TABLE public.arc_purchases
    ADD COLUMN IF NOT EXISTS credits_charged INTEGER NULL;

-- Rollback (manual):
--   ALTER TABLE public.arc_purchases DROP COLUMN IF EXISTS credits_charged;
