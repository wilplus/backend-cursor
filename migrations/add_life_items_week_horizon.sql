-- Life Panel — "week" joins the item horizon vocabulary (2026-07-31).
--
-- WHY. The setup flow folds drafted items onto the eight STRATEGY screens via
-- lp.ITEM_TO_STRATEGY_HORIZON. Seven of the eight had an item horizon that
-- reached them; "weekly" had none, because nothing in HORIZONS meant "this
-- week". A weekly screen could therefore never pre-fill from an uploaded
-- document — every such goal fell to the FE's remainder review, no matter how
-- plainly the document said "this week". That was shipped knowingly in #299
-- with a test pinning the gap; this closes it.
--
-- WHY NOT ALIAS AN EXISTING HORIZON. Pointing "now" at the weekly screen was
-- the cheap fix and the wrong one: it would move every [NOW] goal already
-- written off the daily screen it renders on today. That is a change to what
-- people already wrote, made on their behalf, to fix a screen they never
-- complained about. "now" still means now.
--
-- WHAT THIS TOUCHES. One CHECK constraint. No column is added, no column is
-- dropped, no row is rewritten, and no existing horizon value changes meaning.
-- Every row in the table stays valid: the new constraint is a strict SUPERSET
-- of the old one, so this widens what is accepted and forbids nothing that was
-- allowed before.
--
-- ORDERING IS NOT A DEPLOY BLOCKER. The application degrades rather than
-- failing if this has not run: /v2/life/setup/apply-proposed retries a
-- rejected "week" row with a NULL horizon, which is exactly the behaviour
-- users had before this migration existed (the row lands, and it lands in the
-- remainder review). A migration nobody has run costs the weekly screen its
-- pre-fill; it never costs the row the user ticked. Tested.
--
-- RUN THIS IN THE SUPABASE SQL EDITOR. Idempotent — re-running is a no-op.
-- life_items already has RLS enabled (add_life_panel.sql §5); altering a CHECK
-- constraint does not disturb it, and this file creates no table.

DO $$
BEGIN
    -- Re-runnable by construction: drop the old definition only when one
    -- exists, then add the widened one. Dropping a CHECK constraint removes a
    -- rule, never data — and it is re-added in the same transaction, so there
    -- is no window in which life_items accepts an unlisted horizon.
    IF EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'life_items_horizon_check'
    ) THEN
        ALTER TABLE life_items DROP CONSTRAINT life_items_horizon_check;
    END IF;

    ALTER TABLE life_items
        ADD CONSTRAINT life_items_horizon_check
        CHECK (horizon IS NULL OR horizon IN
               ('now', 'week', 'month', 'quarter', 'year', 'five_year',
                'ten_year', 'twenty_year'));
END $$;

-- ─────────────────────────────────────────────────────────────────────────
-- POST-CONDITION — verify the constraint actually accepts 'week'. A
-- half-applied migration would leave apply-proposed silently downgrading
-- every weekly goal to the remainder review, which looks exactly like the bug
-- this file fixes. Raise instead, so a partial run is a failed run.
--
-- Checked by reading the constraint's own definition rather than by inserting
-- a probe row: a probe would need a real user_id to satisfy the FK, and a
-- migration must not invent one.
-- ─────────────────────────────────────────────────────────────────────────
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM pg_constraint
         WHERE conname = 'life_items_horizon_check'
           AND pg_get_constraintdef(oid) LIKE '%''week''%'
    ) THEN
        RAISE EXCEPTION
            'life_items_horizon_check does not accept the week horizon';
    END IF;
END $$;
