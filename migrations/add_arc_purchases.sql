-- willab — Paid Audits, entitlement core (BE chunk A1).
--
-- An "audit" = the commercial unit = an explore ARC (3 takes + the
-- ideal-text report, up to ~10 min). One row here = one PAID/passed arc;
-- the row IS the entitlement. take-1 is ALWAYS free (live-loop fence) —
-- a purchase unlocks take-2 feedback, take-3, and the ideal-text report
-- for that arc.
--
-- DISTINCT from credits (homework, v2_student_details.credits) and from
-- user_audits (the retired coach-PDF deliverable) — do NOT touch either.
--
-- kind:   'paid'          — bought via Stripe Checkout
--         'founding_pass' — redeemed an invite code (existing users' free pass)
-- source: 'stripe' | 'invite_code' | 'manual'
-- amount_minor: integer minor units (e.g. 15000 = 150.00 PLN); NULL for passes.
--
-- Idempotent; safe to re-run.
CREATE TABLE IF NOT EXISTS arc_purchases (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    arc_id             UUID NOT NULL,
    user_id            UUID NOT NULL,
    kind               TEXT NOT NULL DEFAULT 'paid',     -- 'paid' | 'founding_pass'
    source             TEXT NOT NULL DEFAULT 'stripe',   -- 'stripe' | 'invite_code' | 'manual'
    currency           TEXT,                             -- e.g. 'pln'
    amount_minor       INTEGER,                          -- minor units; NULL for free passes
    stripe_session_id  TEXT,                             -- Checkout Session id; NULL for non-stripe
    delivered_at       TIMESTAMPTZ,                      -- coach marked the audit delivered
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One purchase per arc — a re-checkout / replayed webhook no-ops on conflict.
CREATE UNIQUE INDEX IF NOT EXISTS idx_arc_purchases_arc
    ON arc_purchases (arc_id);

-- Stripe idempotency — a replayed webhook for the same Checkout Session
-- no-ops. Partial so the many non-stripe NULLs never collide.
CREATE UNIQUE INDEX IF NOT EXISTS idx_arc_purchases_stripe_session
    ON arc_purchases (stripe_session_id)
    WHERE stripe_session_id IS NOT NULL;

-- "my purchased arcs" read.
CREATE INDEX IF NOT EXISTS idx_arc_purchases_user
    ON arc_purchases (user_id);

-- Rollback (manual):
--   DROP TABLE IF EXISTS arc_purchases;
