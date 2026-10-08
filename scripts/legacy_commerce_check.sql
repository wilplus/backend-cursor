-- Legacy commerce check: is anyone still paying through a path we remove?
-- Read-only; changes nothing.
-- Founder 2026-10-05 (decisions log N48.3, "Q13 A"): "after a check for live
-- subscriptions, the subscription and credit-pack paths, the arc checkout and
-- the Best Presentation builder are removed". This file is that check. The
-- removal (branch w2e-legacy) is held until every line below reads 0, or the
-- founder decides what happens to the people a line counts.
--
-- RUN IN THE SUPABASE SQL EDITOR. Every statement is a SELECT. One row per
-- question; nothing is listed by person.
--
-- WHAT EACH LINE MEANS
--   1. Subscriptions. A live Stripe subscription is a v2_student_details row
--      with stripe_subscription_id set and stripe_subscription_status one of
--      active, trialing, past_due (the three statuses the code treated as
--      "managed": services/token_account.MANAGED_STATUSES). past_due counts:
--      the card failed but Stripe will still try to charge it. The other
--      lines in this group say whether anything renewed recently (a
--      'tier_change' ledger row is written by the subscription webhook and by
--      nothing else) and whether anyone still holds a paid tier, which grants
--      coach reviews by tier and would keep doing so after the removal.
--   2. Credit packs. stripe_checkout_credit_grants holds one row per paid
--      credit-pack checkout (its only columns are the session id and when).
--      Any row in the last 90 days means a pack was bought recently, so a
--      Stripe Payment Link for packs may still be live.
--   3. Arc checkout. arc_purchases rows bought through Stripe (kind 'paid',
--      source 'stripe'); invite-code passes are not purchases and are not
--      counted here.
--
-- BEFORE THE REMOVAL SHIPS, ALSO IN THE STRIPE DASHBOARD (not visible here):
--   * no subscription is active, trialing or past_due;
--   * every Payment Link for a credit pack or an audit is deactivated;
--   * the webhook endpoint no longer needs customer.subscription.* events.

WITH cut AS (
    SELECT now() - interval '90 days' AS recent_cut,
           now() - interval '35 days' AS renewal_cut
)
SELECT 1 AS grp, 'live subscriptions (active, trialing, past_due)' AS question,
       (SELECT count(*) FROM public.v2_student_details
         WHERE stripe_subscription_id IS NOT NULL
           AND lower(stripe_subscription_status) IN ('active', 'trialing', 'past_due')) AS how_many
UNION ALL
SELECT 1, 'of which past_due (card failed, Stripe still retrying)',
       (SELECT count(*) FROM public.v2_student_details
         WHERE stripe_subscription_id IS NOT NULL
           AND lower(stripe_subscription_status) = 'past_due')
UNION ALL
SELECT 1, 'of which set to cancel at period end',
       (SELECT count(*) FROM public.v2_student_details
         WHERE stripe_subscription_id IS NOT NULL
           AND lower(stripe_subscription_status) IN ('active', 'trialing', 'past_due')
           AND subscription_cancel_at_period_end IS TRUE)
UNION ALL
SELECT 1, 'subscription rows in any other status (canceled, unpaid, incomplete...)',
       (SELECT count(*) FROM public.v2_student_details
         WHERE stripe_subscription_id IS NOT NULL
           AND COALESCE(lower(stripe_subscription_status), '')
               NOT IN ('active', 'trialing', 'past_due'))
UNION ALL
SELECT 1, 'subscription renewals or tier changes in the last 35 days',
       (SELECT count(*) FROM public.token_ledger, cut
         WHERE action = 'tier_change' AND created_at >= cut.renewal_cut)
UNION ALL
SELECT 1, 'subscription renewals or tier changes in the last 90 days',
       (SELECT count(*) FROM public.token_ledger, cut
         WHERE action = 'tier_change' AND created_at >= cut.recent_cut)
UNION ALL
SELECT 1, 'accounts on a paid tier (not free)',
       (SELECT count(*) FROM public.v2_student_details
         WHERE tier IS NOT NULL AND tier <> 'free')
UNION ALL
SELECT 1, 'accounts on a paid tier with no live subscription behind it',
       (SELECT count(*) FROM public.v2_student_details
         WHERE tier IS NOT NULL AND tier <> 'free'
           AND NOT (stripe_subscription_id IS NOT NULL
                    AND COALESCE(lower(stripe_subscription_status), '')
                        IN ('active', 'trialing', 'past_due')))
UNION ALL
SELECT 2, 'credit-pack purchases in the last 90 days',
       (SELECT count(*) FROM public.stripe_checkout_credit_grants, cut
         WHERE created_at >= cut.recent_cut)
UNION ALL
SELECT 2, 'credit-pack purchases ever',
       (SELECT count(*) FROM public.stripe_checkout_credit_grants)
UNION ALL
SELECT 3, 'arc checkout purchases (Stripe) in the last 90 days',
       (SELECT count(*) FROM public.arc_purchases, cut
         WHERE kind = 'paid' AND source = 'stripe'
           AND created_at >= cut.recent_cut)
UNION ALL
SELECT 3, 'arc checkout purchases (Stripe) ever',
       (SELECT count(*) FROM public.arc_purchases
         WHERE kind = 'paid' AND source = 'stripe');
