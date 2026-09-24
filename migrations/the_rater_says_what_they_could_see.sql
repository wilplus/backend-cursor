-- The rater says what they could see.
--
-- FOUNDER 2026-09-24 put the slide on the coach's BLIND judgement screen:
-- "I want as a coach to see the slide at the top; to know on which slide they
-- are talking about." That is an explicit override of the blind-coach fence,
-- taken after being shown both the fence and a compliant alternative, and only
-- the founder can move it.
--
-- WHY THE OVERRIDE NEEDS A COLUMN. Every confidence label collected before
-- that ruling came from the voice alone. Every label after it comes from the
-- voice and the slide together. That is one instrument replacing another
-- mid-collection, and once stored the two are indistinguishable — the same
-- defect `saw_model_output` exists to prevent for the machine read, and the
-- same thing SPEC §1.4 means by one question asking exactly one thing. Without
-- this column the corpus silently merges two instruments into one and no later
-- analysis can unpick it.
--
-- So: `saw_slide`, beside `saw_model_output`, written the same way — supplied
-- by the route, never by the payload, defaulting to blind. A row that predates
-- this migration reads false, which is the truth about how it was collected.
--
-- Both tables. `confidence_labels` is the rater's current answer;
-- `label_revision` is the append-only shadow of what each write replaced, and
-- a shadow that cannot say which instrument collected the row it shadows is
-- not a record of anything.
--
-- Idempotent and additive: no backfill, no rewrite, no drop.

ALTER TABLE public.confidence_labels
    ADD COLUMN IF NOT EXISTS saw_slide BOOLEAN NOT NULL DEFAULT false;

ALTER TABLE public.label_revision
    ADD COLUMN IF NOT EXISTS saw_slide BOOLEAN NOT NULL DEFAULT false;

COMMENT ON COLUMN public.confidence_labels.saw_slide IS
    'Whether the surface that collected this rating showed the slide the '
    'moment was spoken over. Server-supplied, defaults false (blind). '
    'Founder override of the blind-coach fence, 2026-09-24.';
