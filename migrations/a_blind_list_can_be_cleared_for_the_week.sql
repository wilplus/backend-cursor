-- a_blind_list_can_be_cleared_for_the_week (0482)
--
-- The founder's ⋯ on the coach queue's blind lists (2026-10-20): "Clear
-- what's waiting in {line}? New ones come next week. Answers already given
-- stay." The four lines (0411's error_presence_audit and coach_block_pick,
-- 0453's v4_moment_pick_sheets and v4_surer_sheets) refill themselves up to
-- a weekly cap whenever they are empty, so a clear has to be remembered for
-- the week or the line fills again within fifteen minutes.
--
-- ONE NULLABLE COLUMN PER TABLE: cleared_week, the ISO week (week_key,
-- "2026-W43") in which the founder cleared a waiting item. Null while an
-- item waits and on every answered item, so every existing row reads as
-- before. A cleared item is never shown again and is never an answer (its
-- answer columns stay null, so no reader of answers sees it); a line with an
-- item cleared this week does not refill until next week.
--
-- No index: the reads that use it already filter on the coach (or rater)
-- column these tables index.
--
-- Deploy together with the backend that reads it (same PR); with
-- MIGRATE_ON_BOOT=1 the column exists before the new code serves. The code
-- before this PR never reads the column, so applying it early is harmless.
--
-- Idempotent + additive, per the standing constraint: safe to re-run.
-- Nothing dropped; no env var.

ALTER TABLE IF EXISTS public.error_presence_audit
    ADD COLUMN IF NOT EXISTS cleared_week text NULL;

ALTER TABLE IF EXISTS public.coach_block_pick
    ADD COLUMN IF NOT EXISTS cleared_week text NULL;

ALTER TABLE IF EXISTS public.v4_moment_pick_sheets
    ADD COLUMN IF NOT EXISTS cleared_week text NULL;

ALTER TABLE IF EXISTS public.v4_surer_sheets
    ADD COLUMN IF NOT EXISTS cleared_week text NULL;
