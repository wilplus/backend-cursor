-- PRICING v3 — the sold ladder widens (founder 2026-08-14).
--
-- WHAT THIS DOES, AND ALL IT DOES: widens the tier CHECK constraint so the
-- three new sold keys are storable. Nothing is renamed, nothing is migrated,
-- and NO LIVE ROW IS REWRITTEN.
--
--   sold now:  free · practice · coaching · intensive
--   retired:   starter · pro · max   (kept VALID on purpose — see below)
--
-- WHY THE RETIRED KEYS STAY IN THE CONSTRAINT. The grandfathering *scheme*
-- was dropped by founder ruling — no aliases, no legacy cards, no special
-- entitlement rules, and checkout refuses to open a NEW subscription on a
-- retired key. But an EXISTING subscription still renews through the Stripe
-- webhook, which resolves a price id to a tier key and writes it here. Making
-- those keys invalid would fail that write, and the account would carry a
-- paid subscription with no grant. Dropping a value from a CHECK is also the
-- kind of change that cannot be undone once a write has failed.
--
-- If there are no legacy subscribers left, the three keys can be removed from
-- this constraint and from services/token_prices.TIERS in one later change.
--
-- Idempotent: drops the constraint by name and re-adds it, both guarded, so a
-- re-run is a no-op and a fresh database gets the same end state.

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
         WHERE table_schema = 'public' AND table_name = 'v2_student_details'
    ) THEN
        ALTER TABLE public.v2_student_details
            DROP CONSTRAINT IF EXISTS v2_student_details_tier_valid;

        ALTER TABLE public.v2_student_details
            ADD CONSTRAINT v2_student_details_tier_valid
            CHECK (tier IS NULL OR tier IN (
                -- sold
                'free', 'practice', 'coaching', 'intensive',
                -- retired, still resolvable for existing subscriptions
                'starter', 'pro', 'max'
            ));
    END IF;
END$$;

COMMENT ON COLUMN public.v2_student_details.tier IS
    'Subscription tier. SOLD: free, practice, coaching, intensive (pricing v3, '
    'founder 2026-08-14). RETIRED but still valid so existing subscriptions '
    'renew and grant: starter, pro, max. No key is ever aliased onto another — '
    'an alias silently rewrites a paying user''s entitlements.';
