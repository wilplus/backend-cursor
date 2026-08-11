-- Slice 2 of the transcript review deck (founder 2026-08-11): the decisions
-- ledger grows the PROPOSAL TEXT, so the EDITOR modal can show "proposals
-- from earlier iterations" and offer "Use this wording". Until now the row
-- held only the change_key — enough to spend a slot, not enough to re-read
-- what was proposed (the moment_suggestions row is DELETED on dismiss, so
-- without this the history is unrecoverable).
--
-- Additive and idempotent; NULL on every pre-existing row (history begins
-- when this ships — no backfill, nothing invented).
ALTER TABLE public.intervention_decisions
    ADD COLUMN IF NOT EXISTS quote text;
ALTER TABLE public.intervention_decisions
    ADD COLUMN IF NOT EXISTS proposed_text text;
ALTER TABLE public.intervention_decisions
    ADD COLUMN IF NOT EXISTS why_key text;
