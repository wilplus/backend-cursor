-- willab — one-off testing bump (founder 2026-07-13): give every existing
-- user AT LEAST 25 credits so they can unlock one $25 arc during testing.
-- New users are seeded 25 automatically (config.WILLAB_FREE_CREDIT_GRANT);
-- this only lifts the already-seeded lower balances, never lowers anyone.
-- Safe to re-run (idempotent — GREATEST never reduces).
UPDATE public.v2_student_details
    SET credits = GREATEST(COALESCE(credits, 0), 25),
        updated_at = now()
    WHERE COALESCE(credits, 0) < 25;
