-- willab — the coach STAR VERDICT (founder 2026-07-27).
--
-- THE GAP THIS CLOSES. Every voice-text analytic the system produces is either
-- a fixed threshold (delivery stars: |z| >= 1.2 vs the speaker's own baseline)
-- or a stateless LLM prompt (say-it-stronger, moment suggestions, structural
-- devices). The coach can already correct the COPY — the (draft, final) pairs
-- ride admin_annotation_events into the DPO/fine-tune exports. But nothing can
-- correct the DECISION: whether a star should have fired at all, and whether it
-- fired as the right kind. A preference pair over two strings can never teach a
-- detector to stay quiet.
--
-- So this is the decision-layer corpus: one coach judgment per fired star.
--
--   keep              the star was right — the strongest signal we have that a
--                     trigger is calibrated (mirrors 'approved_as_is' on the
--                     prose side: leaving it alone IS the endorsement)
--   wrong_kind        a star belonged here, but not THIS one. corrected_device
--                     carries what it should have been — a labeled confusion
--                     pair, worth more than a bare rejection
--   should_not_fire   the trigger was wrong; this moment deserved silence
--
-- KNOWN GAP, DELIBERATE (founder 2026-07-27): this captures false positives and
-- confusions, NOT false negatives. A star that should have fired and didn't
-- leaves no row, because there is no object for the coach to judge. Missed
-- detections need their own surface (the coach marking an unstarred moment) and
-- were scoped out of this pass. Do not read a corpus of these rows as a
-- balanced sample of the detector's behaviour — it is precision data only.
--
-- FENCES.
--   BLIND COACH — this surface SHOWS the coach the machine's guess and asks
--     them to judge it. That is safe for the ANALYTICS lane (a star is not a
--     confidence label) and unsafe anywhere near the labeling lane. It must
--     stay a separate endpoint from the blind confidence/direction labeling
--     surface, and this table is NEVER joined into training_labels. Pinned by
--     test (test_star_verdicts.py), not by convention.
--   AC-9 — a verdict is coach->machine only. It is never surfaced back to the
--     student, in any form, ever.
--   L1 — a verdict never mutates text. It records a judgment about a star; the
--     student's copy is untouched.
--
-- One row per star. moment_suggestions is itself keyed by snippet_id (one star
-- per snippet), so snippet_id is the natural key here too and a re-judgment
-- UPDATES rather than appending — the corpus wants the coach's current view,
-- not their deliberation history.
--
-- Idempotent; safe to re-run. RLS ON with no policies = service-role only
-- (writes go through the coach-gated backend route; reads are training-side).

CREATE TABLE IF NOT EXISTS public.star_verdicts (
    snippet_id       UUID PRIMARY KEY,        -- the starred piece (= moment_suggestions.snippet_id)
    session_id       UUID NULL,               -- denormalized for session-level pulls
    arc_id           TEXT NULL,               -- denormalized for arc-level pulls
    coach_user_id    UUID NULL,               -- who judged (inter-rater signal later)
    star_kind        TEXT NOT NULL,           -- emphasize | replace | structure | delivery
    star_device      TEXT NULL,               -- emphasis|pace_fast|pace_slow|pause|
                                              -- congruence|contrast|list_of_three
    verdict          TEXT NOT NULL,
    corrected_device TEXT NULL,               -- verdict='wrong_kind' -> what it should have been
    note             TEXT NULL,               -- optional free-text (never shown to the student)
    star_version     TEXT NULL,               -- generator provenance at judgment time
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Named constraint, dropped-then-re-added so the value list converges on
-- re-run. NOTE: a CHECK-rewrite migration is not replay-safe alongside an
-- older copy of itself — if this list ever widens, edit THIS file rather than
-- adding a second alter_ migration (a stale older constraint re-applied after
-- the newer one fails with 23514 on existing rows).
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'star_verdicts_verdict_check'
    ) THEN
        ALTER TABLE public.star_verdicts
            DROP CONSTRAINT star_verdicts_verdict_check;
    END IF;
    ALTER TABLE public.star_verdicts
        ADD CONSTRAINT star_verdicts_verdict_check
        CHECK (verdict IN ('keep', 'wrong_kind', 'should_not_fire'));
END$$;

ALTER TABLE public.star_verdicts ENABLE ROW LEVEL SECURITY;

CREATE INDEX IF NOT EXISTS idx_star_verdicts_session
    ON public.star_verdicts (session_id);
CREATE INDEX IF NOT EXISTS idx_star_verdicts_arc
    ON public.star_verdicts (arc_id);
-- The corpus pull: "every judgment on this star family", newest first.
CREATE INDEX IF NOT EXISTS idx_star_verdicts_kind_verdict
    ON public.star_verdicts (star_kind, verdict, created_at DESC);
