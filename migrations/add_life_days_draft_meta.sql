-- Life Panel — the day card learns from corrections (founder-agreed
-- contract, 2026-08-02: docs/life-checkin-learning-contract.md).
--
-- WHY ONE JSONB COLUMN. The card now DRAFTS a day-sized action per slot, and
-- the contract needs three things kept apart per day: what was DRAFTED (the
-- silent learner's input), what was ACCEPTED after editing (its output side),
-- and whether a SWAP displaced the ranked one-thing (the gate's counter —
-- which must never reach the learner, and vice versa). They are one shape
-- written together at generation and touched by one PATCH, so they live in
-- one nullable jsonb rather than four columns:
--
--   { "one_thing": {"goal_id", "goal", "drafted", "accepted"},
--     "focus":     [{"goal_id", "goal", "drafted"}, ...],
--     "displaced_goal_id": "<set once, on the day's first swap>" }
--
-- NONE OF IT IS DISPLAY DATA. serialize_day lifts only the goal name and id
-- (so the card can say what an action is toward); drafted, accepted and the
-- displacement never reach the wire. No score, no accuracy, no "the model
-- learned" — the learning is internal or it is not allowed (AC-9 / N4).
--
-- ORDERING IS NOT A DEPLOY BLOCKER. If this has not run, the write path
-- retries without the field: a migration nobody ran costs that day's
-- learning record, never the card (same ladder as
-- add_life_items_origin_document.sql).
--
-- RUN THIS IN THE SUPABASE SQL EDITOR. Idempotent — re-running is a no-op.
-- Nothing is dropped. life_days already has RLS enabled (add_life_panel.sql
-- §5); adding a column does not disturb it.

ALTER TABLE life_days
    ADD COLUMN IF NOT EXISTS draft_meta jsonb;

-- ─────────────────────────────────────────────────────────────────────────
-- POST-CONDITION — verify the column landed. A half-applied migration would
-- silently discard every day's learning record while the card kept working,
-- which looks exactly like "the drafts never improve". Raise instead.
-- ─────────────────────────────────────────────────────────────────────────
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name = 'life_days'
           AND column_name = 'draft_meta'
    ) THEN
        RAISE EXCEPTION 'life_days.draft_meta was not created';
    END IF;
END $$;
