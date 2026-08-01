-- willab — honour the legacy credit balances as non-expiring tokens.
-- Founder-approved 2026-08-01. Supersedes the (never-run) §4 conversion in
-- migrations/add_token_pricing.sql, which used a 400:1 rate.
--
-- ─────────────────────────────────────────────────────────────────────
-- WHY A SEPARATE BUCKET AND NOT `token_balance`
--
-- The monthly reset does `token_balance = grant_for(tier)` — SET, never add
-- (add_token_pricing.sql: "nothing rolls over"). So tokens added to
-- token_balance are DELETED at the user's next monthly roll. Honouring 688,000
-- tokens that way would honour them for at most 30 days, and for a dormant user
-- they would evaporate before they ever logged in again. That is not honouring
-- a balance, it is a gesture with an expiry date.
--
-- `bonus_balance` is therefore its own bucket: granted once, never re-granted,
-- and NEVER touched by the period roll. Spending order is monthly-allowance
-- FIRST, bonus second — the expiring money goes first, which is the only order
-- that does not quietly burn the non-expiring balance (services/token_account
-- .py charge()).
--
-- ─────────────────────────────────────────────────────────────────────
-- WHY `credits - 25` AND NOT `credits`
--
-- Nothing in this schema can tell a PURCHASED credit from a GRANTED one:
-- stripe_checkout_credit_grants stores only checkout_session_id + created_at,
-- with no user and no amount. Meanwhile WILLAB_FREE_CREDIT_GRANT seeded 25 to
-- every new user and bump_all_credits_to_25.sql lifted every existing user to
-- at least 25 (founder 2026-07-13, a testing bump).
--
-- So a flat `credits * 1600` would hand EVERY account that ever signed up
-- 40,000 non-expiring tokens — 3.3× the entire free monthly tier of 12,000 —
-- whether or not it ever paid anything. The floor is the only separator
-- available, and it is the honest one: the free 25 already delivered its value
-- as the free tier. Founder decision 2026-08-01.
--
-- THE RATE (1,600/credit) is arc-equivalence, from this product's own prices:
-- an arc unlock cost 25 credits, and its four deliverables come to 40,000
-- tokens (insights 1,000 + game 1,500 + moment_explanation 2,500 +
-- coach_review 35,000). 40,000 / 25 = 1,600. Kept in step with
-- services/token_prices.py::legacy_credit_tokens, which a test pins.
--
-- ⚠️ `credits` IS NOT ZEROED AND NOT DROPPED. Standing constraint: never
-- auto-drop. The column stays exactly as it is, so this is reversible and so
-- the original balances remain auditable after the fact.

-- ── 1. The bucket ────────────────────────────────────────────────────

ALTER TABLE public.v2_student_details
    ADD COLUMN IF NOT EXISTS bonus_balance BIGINT;

COMMENT ON COLUMN public.v2_student_details.bonus_balance IS
    'Non-expiring tokens. NEVER reset by the monthly period roll, unlike '
    'token_balance. Currently sourced only from the one-time legacy credit '
    'conversion. Spent AFTER the monthly allowance, so the expiring balance '
    'is always used first.';

-- ── 2. PREVIEW — run this alone first, it grants nothing ─────────────
--
--   SELECT count(*) AS users,
--          sum(GREATEST(COALESCE(credits,0) - 25, 0)) AS credits_honoured,
--          sum(GREATEST(COALESCE(credits,0) - 25, 0) * 1600) AS tokens_granted
--   FROM public.v2_student_details
--   WHERE COALESCE(credits, 0) > 25;

-- ── 3. The conversion. ONE statement, so it is atomic ────────────────
--
-- Idempotent by the ledger, not by a flag column. The partial unique index
-- uq_token_ledger_once_per_ref on (user_id, action, ref_id) already makes a
-- second row impossible, and the NOT EXISTS guard means a re-run updates
-- nothing rather than relying on the insert to fail. Both halves are in a
-- single statement: a two-statement version that died in between would
-- double-grant on the retry.

WITH converted AS (
    UPDATE public.v2_student_details d
       SET bonus_balance = COALESCE(d.bonus_balance, 0)
                         + (GREATEST(COALESCE(d.credits, 0) - 25, 0) * 1600)
     WHERE GREATEST(COALESCE(d.credits, 0) - 25, 0) > 0
       AND NOT EXISTS (
             SELECT 1 FROM public.token_ledger l
              WHERE l.user_id = d.user_id::text
                AND l.action  = 'legacy_credit_conversion'
           )
    RETURNING d.user_id,
              (GREATEST(COALESCE(d.credits, 0) - 25, 0) * 1600) AS granted,
              d.bonus_balance,
              d.tier
)
INSERT INTO public.token_ledger
       (user_id, delta, balance_after, action, ref_id, price_version, tier)
SELECT c.user_id::text,
       c.granted,
       c.bonus_balance,
       'legacy_credit_conversion',
       -- Fixed ref: one conversion per user, ever. Re-running is a no-op.
       'legacy-credits-1600-v1',
       '2026-07-28-v1',
       c.tier
  FROM converted c;

-- ── 4. Verify ────────────────────────────────────────────────────────
--
--   SELECT count(*) AS rows_written, sum(delta) AS tokens_granted
--   FROM public.token_ledger WHERE action = 'legacy_credit_conversion';
--
-- Re-running this whole file must leave those two numbers unchanged.

-- Rollback (manual, never automatic — and note that any bonus already SPENT
-- cannot be recovered by this, so reverse promptly or not at all):
--   UPDATE public.v2_student_details d
--      SET bonus_balance = GREATEST(COALESCE(d.bonus_balance,0)
--                        - (GREATEST(COALESCE(d.credits,0) - 25, 0) * 1600), 0)
--    WHERE EXISTS (SELECT 1 FROM public.token_ledger l
--                   WHERE l.user_id = d.user_id::text
--                     AND l.action = 'legacy_credit_conversion');
--   DELETE FROM public.token_ledger WHERE action = 'legacy_credit_conversion';
--   -- and only if you are abandoning the feature entirely:
--   -- ALTER TABLE public.v2_student_details DROP COLUMN IF EXISTS bonus_balance;
