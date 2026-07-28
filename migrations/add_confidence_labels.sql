-- willab — the CONFIDENCE LABEL (founder 2026-07-28).
--
-- THE core training signal for the app's core function: is this snippet
-- confident, and how much. Two fields, deliberately:
--
--   confident  BOOLEAN   the call. Binary, because the model's job is a
--                        binary recognition and a rater who must commit
--                        gives a cleaner boundary than one who can hedge.
--   intensity  1..5      how strongly. Same scale Jiang & Pell (2017) put in
--                        front of their listeners (means 4.52 / 3.24 / 2.05
--                        across confident / close-to-confident / unconfident),
--                        so these numbers are directly comparable to the
--                        published anchor — and they are the human side of
--                        the voice-confidence validation gate that has been
--                        waiting for a rating set.
--
-- SEPARATE FROM training_labels ON PURPOSE. training_labels is the
-- challenge/threat direction lane (a different construct, feeding the shadow
-- direction classifier). Folding confidence into it would silently change
-- what that model is trained on. Two constructs, two tables.
--
-- KEYED PER RATER, not per snippet: (snippet_id, rater_id) unique. The
-- agreement aggregator this corpus exists to enable — "the more peers agree,
-- the stronger the annotation" — needs multiple rows per snippet to have
-- anything to aggregate. `source` distinguishes the coach's truth from a
-- future game/peer answer, so the weighting stays possible without a
-- migration.
--
-- FENCES. AC-9: intensity is a NUMBER and is coach->machine ONLY — it must
-- never reach a student payload, in any form. BLIND COACH: the labeling
-- surface shows the moment and nothing else; the machine's own confidence
-- read is never displayed beside it (it is used to STRATIFY which pieces get
-- queued, never to suggest an answer).
--
-- Idempotent; safe to re-run. RLS ON with no policies = service-role only.

CREATE TABLE IF NOT EXISTS public.confidence_labels (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snippet_id   UUID NOT NULL,
    rater_id     UUID NULL,               -- NULL = anonymous rater
    source       TEXT NOT NULL DEFAULT 'coach',   -- coach | game | peer
    confident    BOOLEAN NOT NULL,
    intensity    INTEGER NULL,            -- 1..5, NULL when not given
    note         TEXT NULL,               -- optional free text, never surfaced
    session_id   UUID NULL,               -- denormalized for corpus pulls
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One label per rater per snippet; re-rating UPDATES (the corpus wants their
-- current view). COALESCE so anonymous raters don't all collide on NULL.
CREATE UNIQUE INDEX IF NOT EXISTS uq_confidence_labels_snippet_rater
    ON public.confidence_labels (
        snippet_id, COALESCE(rater_id, '00000000-0000-0000-0000-000000000000'::uuid)
    );

-- Named constraint, drop-then-re-add so the range converges on re-run. If it
-- ever changes, edit THIS file rather than adding a second alter_ migration
-- (a stale older constraint re-applied after a newer one fails 23514).
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'confidence_labels_intensity_check'
    ) THEN
        ALTER TABLE public.confidence_labels
            DROP CONSTRAINT confidence_labels_intensity_check;
    END IF;
    ALTER TABLE public.confidence_labels
        ADD CONSTRAINT confidence_labels_intensity_check
        CHECK (intensity IS NULL OR (intensity >= 1 AND intensity <= 5));
END$$;

ALTER TABLE public.confidence_labels ENABLE ROW LEVEL SECURITY;

CREATE INDEX IF NOT EXISTS idx_confidence_labels_snippet
    ON public.confidence_labels (snippet_id);
CREATE INDEX IF NOT EXISTS idx_confidence_labels_session
    ON public.confidence_labels (session_id);
-- The corpus pull + the future agreement aggregator.
CREATE INDEX IF NOT EXISTS idx_confidence_labels_source_created
    ON public.confidence_labels (source, created_at DESC);
