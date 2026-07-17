-- willab — the key-moments unlock (founder re-shape 2026-07-17: the single
-- deliverable). The ONLY paid item in the app: opening the key-moment
-- explanations (coach note/video per moment) — 5 credits ($5), one-time per
-- presentation (arc), covering all current AND future moments of it.
--
-- DELIBERATELY a separate table from arc_purchases: the $25 arc unlock is
-- RETIRED with NO grandfathering (founder-explicit) — old entitlements never
-- open the moments. unique(arc_id) is the atomic double-charge guard
-- (mirrors arc_purchases' claim semantics).
--
-- Idempotent; RLS on, no policy (service-role only).
CREATE TABLE IF NOT EXISTS public.moment_unlocks (
    arc_id        TEXT PRIMARY KEY,
    user_id       UUID NOT NULL,
    credits_spent INTEGER NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE public.moment_unlocks ENABLE ROW LEVEL SECURITY;
