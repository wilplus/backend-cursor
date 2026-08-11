-- Slice 2 of the transcript review deck (founder 2026-08-11): each part
-- carries its MATURITY counter — how many lock-in cycles it has survived.
-- Bumped by the lock endpoint on every locked=true transition, never on
-- unlock; a chunk can sit at 0 forever (good from the start) or reach 5
-- after repeated lock/unlock/restyle rounds. A process count, not a score:
-- the FE kickers render "Locked in · N iterations" (AC-9 clean — it counts
-- work done, it ranks nothing).
ALTER TABLE public.ideal_text_part
    ADD COLUMN IF NOT EXISTS iteration integer NOT NULL DEFAULT 0;
