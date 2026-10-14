-- Step 3 of the admin plan (founder 2026-10-14): a special plan price for
-- one person, shown on their pricing screen until an end date, and two more
-- in-app asks that tell them about it ('promo') or about their lesson price
-- ('lesson').
--
-- One row per person; ending a promotion sets ends_at to now, so the row
-- stays as history. Additive and safe to re-run. The kind check is widened
-- (dropped and re-added with more values); no data is touched.

CREATE TABLE IF NOT EXISTS public.plan_promotions (
    user_id      UUID PRIMARY KEY,
    plan         TEXT NOT NULL,
    price_cents  INTEGER NOT NULL CHECK (price_cents >= 100),
    ends_at      TIMESTAMPTZ NOT NULL,
    created_by   UUID,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.plan_promotions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.plan_promotions FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON TABLE public.plan_promotions TO service_role;

ALTER TABLE public.person_asks DROP CONSTRAINT IF EXISTS person_asks_kind_check;
ALTER TABLE public.person_asks ADD CONSTRAINT person_asks_kind_check
    CHECK (kind IN ('whatsapp', 'home_screen', 'consent', 'promo', 'lesson'));
