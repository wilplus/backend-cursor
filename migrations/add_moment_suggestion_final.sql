-- willab — coach-corrected star TEXT (founder 2026-07-28).
--
-- The star verdict (add_star_verdicts.sql) let the coach judge whether a
-- fired star was RIGHT; this lets them fix its WORDS — "review how the
-- comment was written" — the same draft/final twin pattern as
-- say_it_stronger / say_it_stronger_final on charisma_snippets:
--
--   why / replacement_text              the machine's draft (write-once,
--                                       generation-owned, NEVER edited)
--   why_final / replacement_text_final  the coach's corrected wording
--                                       (re-editable until they're done)
--
-- The (draft, final) pair is the writer-model correction corpus; it enters
-- admin_annotation_events when the coach KEEPS the star (the keep verdict is
-- the "this is finished" moment — see the star-verdict route). Serve-side,
-- every reader folds FINAL over DRAFT at the one DB reader
-- (get_moment_suggestions_by_arc), so the student always sees the coach's
-- wording without any row mutation (L1: the draft column is untouched).
--
-- AC-9 note: the PUT route runs coach input through the SAME qualitative
-- guard as generation (say_it_stronger._guard_copy) and 400s on a violation
-- — digits and retired-construct vocabulary cannot enter user-facing copy
-- through the coach door either.
--
-- Idempotent; RLS is already ON for this table (service-role only).
ALTER TABLE public.moment_suggestions
    ADD COLUMN IF NOT EXISTS why_final              TEXT NULL,
    ADD COLUMN IF NOT EXISTS replacement_text_final TEXT NULL,
    ADD COLUMN IF NOT EXISTS text_final_by          UUID NULL,
    ADD COLUMN IF NOT EXISTS text_final_updated_at  TIMESTAMPTZ NULL;
