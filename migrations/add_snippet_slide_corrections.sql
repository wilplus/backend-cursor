-- THE COACH'S WORD→SLIDE GROUND TRUTH (founder 2026-08-11).
--
-- The pipeline buckets every word to the slide that was on screen when it was
-- spoken, from the tap timeline. Nothing has ever checked that against a human.
-- services/slide_boundary_metrics.py says so in its own header: "There is no
-- ground truth here... The only real labels available are COACH CORRECTIONS —
-- when a coach moves text between slides, a human has said 'this was bucketed
-- wrong'." That correction did not exist as data. This table is it.
--
-- WHAT A ROW MEANS, EXACTLY — and it is not what it looks like.
--   "The slide ON SCREEN while this snippet was spoken was N."
-- NOT "these words are about slide N". The north star defines correctness as
-- what the audience was looking at, so a speaker who ran ahead of their own
-- deck is NOT a bucketing error and must never be corrected here. A corpus
-- that mixes the two teaches the opposite of the thing we measure.
--
-- APPEND-ONLY. No UPDATE, no DELETE: the latest row for a snippet wins, and
-- the ones before it stay as the audit trail of what the pipeline said and
-- what the human said instead. Labels are versioned/immutable by standing
-- rule — a silently overwritten label is a corpus nobody can compare across
-- time, which is exactly the failure mode the filler-rate rule exists to stop.
--
-- slide_index NULL is a REVERT: the coach withdrew their correction and the
-- pipeline's own answer stands again. Stored rather than deleted, because
-- "a human looked at this and decided the pipeline was right" is a label too,
-- and a rarer one than a correction.
--
-- was_slide_index records what the pipeline said at the moment of correction.
-- Without it the table can only say where the words belong, never how far off
-- the timeline was — and the size of the miss is the measurement.
CREATE TABLE IF NOT EXISTS public.snippet_slide_corrections (
    id              BIGSERIAL PRIMARY KEY,
    session_id      TEXT NOT NULL,
    snippet_id      TEXT NOT NULL,
    -- What the pipeline assigned when the coach looked (NULL = it had none).
    was_slide_index INTEGER,
    -- What the coach says was on screen. NULL = revert to the pipeline.
    slide_index     INTEGER,
    -- Who said so, for a corpus that can be filtered by labeller later.
    corrected_by    TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The read is always "the latest correction per snippet, for one session".
CREATE INDEX IF NOT EXISTS idx_ssc_session_created
    ON public.snippet_slide_corrections (session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ssc_snippet_created
    ON public.snippet_slide_corrections (snippet_id, created_at DESC);

-- The corpus is coach-authored and coach-only. The backend holds the
-- service-role key and bypasses RLS, so no policy is needed — but without
-- this line the table is readable, and often writable, by anyone holding the
-- anon key out of the browser bundle (docs/RLS-AUDIT.md). Labels an outsider
-- can write are not labels.
ALTER TABLE public.snippet_slide_corrections ENABLE ROW LEVEL SECURITY;
