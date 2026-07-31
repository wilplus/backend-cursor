-- willab — remember WHICH Stripe subscription a tier came from.
-- Follows migrations/add_token_pricing.sql. Additive and idempotent.
--
-- ─────────────────────────────────────────────────────────────────────
-- WHY THE TIER COLUMN WAS NOT ENOUGH
--
-- `tier` says what someone is entitled to. It cannot say whether that
-- entitlement is a LIVE STRIPE SUBSCRIPTION they can cancel or switch, or just
-- the default everyone starts on. Those two states need different controls in
-- front of them — "upgrade" versus "manage your plan" — and the FE was left
-- unable to tell them apart (FE handoff 2026-07-31 §2).
--
-- Deriving it from the ledger was the alternative and it is wrong: a cancelled
-- subscription and an active one both leave a `tier_change` row behind, so the
-- ledger answers "what happened" and never "what is true now".
--
-- ⚠️ NOTHING HERE IS REQUIRED FOR THE BALANCE TO READ. The application reads
-- these columns in a SEPARATE best-effort query that returns empty on failure,
-- so a deploy that lands before this migration runs shows `managed: false`
-- (today's behaviour, upgrade-only) rather than a broken wallet. Standing
-- constraint: "on main" is not "run in prod" — this one must be run by hand.

ALTER TABLE public.v2_student_details
    ADD COLUMN IF NOT EXISTS stripe_customer_id            TEXT,
    ADD COLUMN IF NOT EXISTS stripe_subscription_id        TEXT,
    ADD COLUMN IF NOT EXISTS stripe_subscription_status    TEXT,
    ADD COLUMN IF NOT EXISTS subscription_cancel_at_period_end BOOLEAN,
    ADD COLUMN IF NOT EXISTS subscription_current_period_end   TIMESTAMPTZ;

COMMENT ON COLUMN public.v2_student_details.stripe_customer_id IS
    'Stripe Customer id. The key the billing portal is opened against — without '
    'it there is no way to hand someone their own cancellation flow.';
COMMENT ON COLUMN public.v2_student_details.stripe_subscription_id IS
    'Stripe Subscription id backing the current paid tier. NULL = the tier is '
    'the default, not a managed subscription.';
COMMENT ON COLUMN public.v2_student_details.stripe_subscription_status IS
    'Raw Stripe status: active | trialing | past_due | canceled | unpaid | '
    'incomplete | incomplete_expired. Stored verbatim rather than collapsed to '
    'a boolean so a past_due card can be told apart from a cancellation — the '
    'first is fixable in the portal, the second is not.';
COMMENT ON COLUMN public.v2_student_details.subscription_cancel_at_period_end IS
    'They cancelled but have paid through the end of the period. The date they '
    'actually lose the tier is subscription_current_period_end.';
COMMENT ON COLUMN public.v2_student_details.subscription_current_period_end IS
    'End of the period Stripe has already billed. Shown to the user as the date '
    'a cancelled plan lapses. NOT the token renewal date — that is derived from '
    'period_start, and the two agree because set_tier anchors to Stripe.';

-- One subscription belongs to one user. A partial unique index (rather than a
-- constraint) leaves the NULLs — everyone on free — completely unaffected.
CREATE UNIQUE INDEX IF NOT EXISTS uq_v2_student_details_stripe_subscription
    ON public.v2_student_details (stripe_subscription_id)
    WHERE stripe_subscription_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_v2_student_details_stripe_customer
    ON public.v2_student_details (stripe_customer_id)
    WHERE stripe_customer_id IS NOT NULL;

-- Rollback (manual, never automatic):
--   DROP INDEX IF EXISTS public.uq_v2_student_details_stripe_subscription;
--   DROP INDEX IF EXISTS public.idx_v2_student_details_stripe_customer;
--   ALTER TABLE public.v2_student_details
--       DROP COLUMN IF EXISTS stripe_customer_id,
--       DROP COLUMN IF EXISTS stripe_subscription_id,
--       DROP COLUMN IF EXISTS stripe_subscription_status,
--       DROP COLUMN IF EXISTS subscription_cancel_at_period_end,
--       DROP COLUMN IF EXISTS subscription_current_period_end;
