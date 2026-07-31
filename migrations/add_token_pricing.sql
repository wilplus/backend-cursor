-- willab — token pricing, Phase 1: the user-facing balance.
-- docs/PRICING-TOKENS-PLAN.md §7. Founder-approved 2026-07-27/28.
--
-- Distinct from `llm_usage` (Phase 0), which records what WE pay OpenAI.
-- That table is a cost ledger and is NEVER a source for these numbers: user
-- prices are FLAT published per-action figures (plan §2), because a
-- cost-derived price varies with how the user performed, and that is an AC-9
-- score wearing a billing costume (fence §6.2). Two ledgers, no join.
--
-- ─────────────────────────────────────────────────────────────────────
-- THE MODEL (founder 2026-07-28: EVERYTHING resets monthly)
--
--   tier      tokens/month   coach reviews/month
--   free          12,000            0
--   starter $5    50,000            1
--   pro     $25  300,000            6
--   max    $100 1,500,000          10
--
-- Nothing rolls over. Every tier — including free — re-grants on the user's
-- own monthly anchor. This REPLACES the earlier "packs never expire" decision.
--
-- ⚠️ CONSEQUENCE THE SCHEMA CANNOT SOFTEN: a $5/$25 allowance that resets
-- monthly is a SUBSCRIPTION, not a pack. Selling it as "buy 50,000 tokens" and
-- then deleting the remainder after 30 days is the kind of thing that produces
-- chargebacks. The Stripe Prices for starter/pro must be RECURRING, and the
-- copy must say "per month". See docs/PROMPT-BE-token-pricing.md §1.
--
-- ─────────────────────────────────────────────────────────────────────
-- WHY THERE IS NO CRON
--
-- The reset is LAZY: computed on read, in the application, via
-- `ensure_period_current(user_id)`. Nothing in this file schedules anything.
--
-- A monthly reset cron is the obvious design and the wrong one here. It is a
-- single point of failure that fails SILENTLY (nobody notices a grant that
-- did not happen until a user complains they have no tokens), it needs its own
-- Railway service, and this repo has a standing habit of infrastructure that
-- was set up in a migration and never actually wired. Lazy reset is
-- self-healing: a process that has been down for three months rolls the period
-- forward correctly on the next read.
--
-- The rule is JUMP, NEVER LOOP: if four months elapsed, advance period_start
-- by four months and SET the balance to the tier grant once. Do not iterate
-- granting per month — that would hand back-dated users a windfall.
--
-- Concurrency: two requests can observe the same stale period. The reset is a
-- compare-and-swap on period_start (UPDATE ... WHERE period_start = <observed>)
-- so exactly one wins, mirroring deduct_credits_strict's existing CAS.
--
-- ─────────────────────────────────────────────────────────────────────
-- `credits` IS LEFT ALONE. The legacy column stays exactly where it is —
-- standing constraint: never auto-drop. It is read by the retired $25 arc
-- path and the moments unlock until those are migrated. Conversion is a
-- separate, reversible backfill at the bottom of this file, commented out.

-- ── 1. The account: additive columns on the existing student row ─────

ALTER TABLE public.v2_student_details
    ADD COLUMN IF NOT EXISTS token_balance      BIGINT,
    ADD COLUMN IF NOT EXISTS tier               TEXT,
    ADD COLUMN IF NOT EXISTS period_start       TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS coach_reviews_used INTEGER;

COMMENT ON COLUMN public.v2_student_details.token_balance IS
    'Willab tokens remaining THIS period. NULL = never initialised; the app '
    'seeds it on first touch. Set (never incremented) at period roll — there '
    'is no rollover.';
COMMENT ON COLUMN public.v2_student_details.tier IS
    'free | starter | pro | max. NULL is read as free.';
COMMENT ON COLUMN public.v2_student_details.period_start IS
    'Anchor of the current monthly period (signup date for free, Stripe '
    'billing anchor for paid). The reset is lazy — see ensure_period_current.';
COMMENT ON COLUMN public.v2_student_details.coach_reviews_used IS
    'Human-coach reviews consumed THIS period. A SECOND limit, independent of '
    'token_balance: at 15 min of founder time each, the cap protects the '
    'calendar, not the margin (plan §5.1). NEVER rolls over — three quiet '
    'months must not bank 30 reviews into one week.';

-- tier is a small closed vocabulary; a typo'd tier would silently grant the
-- fallback amount forever. Guarded here rather than in app code only.
-- NOT replay-safe if the vocabulary ever changes — drop and recreate, keeping
-- only the newest definition (this repo has hit ERROR 23514 doing otherwise).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'v2_student_details_tier_valid'
    ) THEN
        ALTER TABLE public.v2_student_details
            ADD CONSTRAINT v2_student_details_tier_valid
            CHECK (tier IS NULL OR tier IN ('free', 'starter', 'pro', 'max'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_v2_student_details_period
    ON public.v2_student_details (period_start);

-- ── 2. The ledger: append-only, every movement ───────────────────────
--
-- Append-only on purpose. token_balance is a cache that any bug can corrupt;
-- the ledger is the record that lets you prove what a user was charged and
-- rebuild the balance if it ever disagrees. Deltas are signed: grants
-- positive, spends negative.

CREATE TABLE IF NOT EXISTS public.token_ledger (
    id            BIGSERIAL PRIMARY KEY,
    user_id       TEXT        NOT NULL,
    -- Signed. -3000 for a take, +50000 for a period grant.
    delta         BIGINT      NOT NULL,
    -- Balance AFTER this movement. Denormalised deliberately: it makes
    -- "when did this go wrong" answerable by reading one column down the
    -- page, without re-summing the whole history.
    balance_after BIGINT      NULL,
    -- Stable lower_snake action key: 'take_short', 'take_medium', 'chat',
    -- 'game', 'insights', 'moment_explanation', 'coach_review',
    -- 'period_grant', 'tier_change', 'admin_adjust'.
    action        TEXT        NOT NULL,
    -- What it applied to (session_id / arc_id / stripe event). Free-form by
    -- design: this is an audit trail, not a foreign-key graph.
    ref_id        TEXT        NULL,
    -- Which price table produced `delta`, so a repricing stays auditable and
    -- historical charges never silently re-interpret.
    price_version TEXT        NULL,
    tier          TEXT        NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.token_ledger ENABLE ROW LEVEL SECURITY;

CREATE INDEX IF NOT EXISTS idx_token_ledger_user_created
    ON public.token_ledger (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_token_ledger_action
    ON public.token_ledger (action, created_at DESC);
-- Idempotency: one grant per user per period, one charge per action+ref.
-- Partial unique index rather than a table constraint so rows with no ref_id
-- (chat turns, which are legitimately repeatable) are unaffected.
CREATE UNIQUE INDEX IF NOT EXISTS uq_token_ledger_once_per_ref
    ON public.token_ledger (user_id, action, ref_id)
    WHERE ref_id IS NOT NULL;

COMMENT ON TABLE public.token_ledger IS
    'Append-only record of every token movement. The balance on '
    'v2_student_details is a cache; THIS is the truth. Never a source for '
    'per-user pricing decisions (fence AC-9 / plan §6.2).';

-- ── 3. Seed existing users onto the new model ────────────────────────
--
-- Everyone starts free with a period anchored now. Paid tiers are set by the
-- Stripe webhook, not here. Idempotent: only touches rows not yet migrated.

UPDATE public.v2_student_details
SET tier               = COALESCE(tier, 'free'),
    token_balance      = COALESCE(token_balance, 12000),
    period_start       = COALESCE(period_start, now()),
    coach_reviews_used = COALESCE(coach_reviews_used, 0)
WHERE tier IS NULL
   OR token_balance IS NULL
   OR period_start IS NULL
   OR coach_reviews_used IS NULL;

-- ── 4. OPTIONAL, NOT RUN: legacy credit conversion ───────────────────
--
-- Plan §4 converts 1 legacy credit → 400 tokens (a 25-credit balance becomes
-- 10,000 ≈ the new free grant). Deliberately left commented: the seed above
-- already gives everyone a full free period, so running this as well would
-- DOUBLE-grant. Uncomment only if you decide legacy balances should be
-- honoured ON TOP of the first free period.
--
--   UPDATE public.v2_student_details
--   SET token_balance = token_balance + (COALESCE(credits, 0) * 400)
--   WHERE COALESCE(credits, 0) > 0;

-- Rollback (manual, never automatic):
--   DROP TABLE IF EXISTS public.token_ledger;
--   ALTER TABLE public.v2_student_details
--       DROP CONSTRAINT IF EXISTS v2_student_details_tier_valid,
--       DROP COLUMN IF EXISTS token_balance,
--       DROP COLUMN IF EXISTS tier,
--       DROP COLUMN IF EXISTS period_start,
--       DROP COLUMN IF EXISTS coach_reviews_used;
