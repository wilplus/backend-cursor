-- Life Panel — the monthly + quarterly reviews (piece 5 of the founder-agreed
-- program, 2026-08-02: the review that reads the reflections layer).
--
-- ONE TABLE FOR BOTH CADENCES. A month review and a quarter review are the
-- same shape at different range — the period held against its own strategy
-- document, with the period's reflections re-read alongside it. `period`
-- discriminates ('month' | 'quarter'); `period_start` is the fold key (the
-- first day of the month, or of the quarter: Jan/Apr/Jul/Oct 1), exactly as
-- life_weeks folds every date to its Monday.
--
-- THE ROW STORES ONLY WHAT THE FOUNDER TYPED. The document, the reflections,
-- the weeks and the goals in the review payload are assembled at read time
-- from the tables that already own them — nothing is copied in, nothing is
-- derived, no model is called (L-1/N5: the system never authors the review).
-- `goals_moved` and `becoming_sentence` are the person's own answers, verbatim;
-- `reviewed_on` is the day they said the review happened. No percentage, no
-- completion ratio, no score anywhere (AC-9 / N4).
--
-- WHY NOT WIDEN life_weeks. week_start is the week table's identity — NOT
-- NULL, uniquely indexed, and read by name everywhere. Overloading it with
-- month/quarter rows would make every existing week query subtly wrong; a
-- second small table keeps both honest, and the CHECK below keeps this one
-- from quietly becoming a junk drawer of ad-hoc cadences.
--
-- ORDERING IS NOT A DEPLOY BLOCKER. Every read of this table degrades to the
-- skeleton payload and every write returns None when the table is absent —
-- deploying the code before running this file costs the saved review, never
-- a 500 on the GET and never any other panel surface.
--
-- RUN THIS IN THE SUPABASE SQL EDITOR. Idempotent — re-running is a no-op.
-- Nothing is dropped.

CREATE TABLE IF NOT EXISTS life_period_reviews (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           uuid        NOT NULL,
    period            text        NOT NULL,
    period_start      date        NOT NULL,
    goals_moved       jsonb       NOT NULL DEFAULT '[]'::jsonb,
    becoming_sentence text,
    reviewed_on       date,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
);

-- One review per user per period per start date — the upsert key.
CREATE UNIQUE INDEX IF NOT EXISTS life_period_reviews_user_period_uniq
    ON life_period_reviews (user_id, period, period_start);

-- CHECK rather than a PG enum (house precedent: the lounge-kind and
-- journal_post CHECKs — a CHECK amends with a plain ALTER later). Added
-- defensively so re-running against an existing table is a no-op.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'life_period_reviews_period_check'
    ) THEN
        ALTER TABLE life_period_reviews
            ADD CONSTRAINT life_period_reviews_period_check
            CHECK (period IN ('month', 'quarter'));
    END IF;
END $$;

-- RLS in the creating file, not a follow-up sweep (N1). No policies ON
-- PURPOSE: with RLS enabled and zero policies, `anon` and `authenticated`
-- can do nothing at all, while the backend's service-role key bypasses RLS —
-- every read/write is served only through /v2/life/*, where the consent gate
-- and the owner filter apply (add_life_panel.sql §RLS).
ALTER TABLE life_period_reviews ENABLE ROW LEVEL SECURITY;

-- ─────────────────────────────────────────────────────────────────────────
-- POST-CONDITION — a migration that silently half-applies is how a table
-- ends up exposed. Raise, so a partial run is a failed run.
-- ─────────────────────────────────────────────────────────────────────────
DO $$
DECLARE
    has_rls boolean;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
         WHERE table_schema = 'public'
           AND table_name = 'life_period_reviews'
    ) THEN
        RAISE EXCEPTION 'life_period_reviews was not created';
    END IF;

    SELECT relrowsecurity INTO has_rls
      FROM pg_class
     WHERE oid = 'public.life_period_reviews'::regclass;
    IF NOT has_rls THEN
        RAISE EXCEPTION 'life_period_reviews has RLS disabled';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_indexes
         WHERE schemaname = 'public'
           AND indexname = 'life_period_reviews_user_period_uniq'
    ) THEN
        RAISE EXCEPTION 'life_period_reviews unique index was not created';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'life_period_reviews_period_check'
    ) THEN
        RAISE EXCEPTION 'life_period_reviews period CHECK was not created';
    END IF;
END $$;
