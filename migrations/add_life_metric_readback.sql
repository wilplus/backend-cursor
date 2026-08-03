-- Life Panel — the metric read-back (piece 3 of the founder-agreed program,
-- 2026-08-02: the evening check-out holds the day against the goal's OWN
-- measure, qualitatively).
--
-- TWO COLUMNS, ONE SEAM. A goal gains `measure` — "how you will know it
-- happened", the founder's own words ("3 talks, 10kg, one draft") — and the
-- day gains `evening_measure`, the free-text answer to where the day landed
-- against it. Both are the person's language end to end: nothing here is a
-- number the system computes, no percentage, no completion ratio, no score
-- (AC-9 / N4). The system's whole job is to hold the two sentences next to
-- each other at 23:00.
--
-- WHY life_items AND NOT THE SETUP ANSWERS. The wizard has always ASKED for
-- the metric ("How much", "How you will know it happened") and then stored it
-- only inside the setup answers blob — no item row ever carried it, which is
-- why the evening could not ask. The column makes it first-class on the row
-- the day card actually reads.
--
-- ORDERING IS NOT A DEPLOY BLOCKER. Both write paths degrade: a ticked row
-- whose insert is refused retries without `measure` (the row is the job), and
-- the evening PATCH retries without `evening_measure` (the tick is the job).
-- A migration nobody ran costs the metric, never the data.
--
-- RUN THIS IN THE SUPABASE SQL EDITOR. Idempotent — re-running is a no-op.
-- Nothing is dropped. Both tables already carry RLS (add_life_panel.sql §5).

ALTER TABLE life_items
    ADD COLUMN IF NOT EXISTS measure text;

ALTER TABLE life_days
    ADD COLUMN IF NOT EXISTS evening_measure text;

-- ─────────────────────────────────────────────────────────────────────────
-- POST-CONDITION — verify both columns landed. A half-applied migration
-- would let one side of the seam silently drop what the other stores; raise
-- instead, so a partial run is a failed run.
-- ─────────────────────────────────────────────────────────────────────────
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = 'public' AND table_name = 'life_items'
           AND column_name = 'measure'
    ) THEN
        RAISE EXCEPTION 'life_items.measure was not created';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = 'public' AND table_name = 'life_days'
           AND column_name = 'evening_measure'
    ) THEN
        RAISE EXCEPTION 'life_days.evening_measure was not created';
    END IF;
END $$;
