-- willab — the PEER-REVIEW VALIDATION LOOP (founder 2026-08-03).
--
-- Stress recognition is dead. What the acoustic stress lane is pivoted INTO:
-- a user or peer sees the AI's confidence choice on one snippet and flags
-- whether it got that call right. One boolean, `ai_correct`. That is the
-- whole capture.
--
-- PROVENANCE IS THE WHOLE GAME — why this is its own table and not a row in
-- confidence_labels or training_labels:
--
--   * These flags are NON-BLIND. The reviewer saw the AI's choice BEFORE
--     answering, so the label correlates with the prediction it is grading.
--     The coach labels (confidence_labels / training_labels) are BLIND and
--     stay that way (N1/N2, untouched by this migration). Blended
--     indistinguishably, the model would be grading its own homework and
--     every later agreement number would be circular.
--   * Whether — and how heavily — a peer flag should weigh against a blind
--     coach label is a founder/BE decision that has NOT been made. The
--     schema's only job is to keep every option open: separate table,
--     separate provenance string ('peer_review'), model_version recorded per
--     row so a future trainer can ask "which prediction was validated".
--   * training_labels is keyed (session_id, snippet_id) — one row per
--     snippet. A peer row written there would COLLIDE with and overwrite the
--     coach's truth for that snippet. It can never live there.
--
-- REPLACE-ON-REFLAG, not append: one row per (snippet_id, reviewer_user_id).
-- A reviewer who changes their mind UPDATES their row. Duplicate peer rows
-- from one rater are junk labels — the same N3 rule the voice game follows.
-- Multiple DIFFERENT reviewers still get their own rows, so peer agreement
-- stays computable.
--
-- model_version records WHICH prediction was validated. Absent from the
-- request → the route stamps the currently-shadowed model version
-- server-side, because "the AI got this right" is meaningless without
-- knowing which AI.
--
-- FENCES. AC-9: nothing here is ever surfaced back to a user as a score,
-- verdict or ratio — this table is capture-only. BLIND COACH: this is the
-- non-blind lane and it must stay labelled as such; it never merges into the
-- coach's blind corpus without an explicit founder decision on weighting.
--
-- Idempotent; safe to re-run. RLS ON with no policies = service-role only.

CREATE TABLE IF NOT EXISTS public.snippet_confidence_reviews (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- `charisma_snippets` IS the snippets table in this schema (the same one
    -- confidence_labels.snippet_id and training_labels.snippet_id point at).
    -- CASCADE because a review of a re-cut/deleted snippet is junk data.
    snippet_id        UUID NOT NULL
                      REFERENCES public.charisma_snippets(id) ON DELETE CASCADE,
    reviewer_user_id  UUID NOT NULL,
    ai_correct        BOOLEAN NOT NULL,
    model_version     TEXT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per reviewer per snippet; a re-flag UPDATES it.
--
-- MUST be a plain composite CONSTRAINT, not an expression index: the writer
-- upserts with ON CONFLICT (snippet_id, reviewer_user_id), and Postgres's
-- arbiter inference cannot match an expression index. add_confidence_labels
-- .sql learned this the hard way — every save failed 42P10 and the surface
-- misread it as "migration not run". Do not "improve" this into an index.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'uq_snippet_confidence_reviews_snippet_reviewer'
    ) THEN
        ALTER TABLE public.snippet_confidence_reviews
            ADD CONSTRAINT uq_snippet_confidence_reviews_snippet_reviewer
            UNIQUE (snippet_id, reviewer_user_id);
    END IF;
END$$;

ALTER TABLE public.snippet_confidence_reviews ENABLE ROW LEVEL SECURITY;

CREATE INDEX IF NOT EXISTS idx_snippet_confidence_reviews_snippet
    ON public.snippet_confidence_reviews (snippet_id);
CREATE INDEX IF NOT EXISTS idx_snippet_confidence_reviews_reviewer
    ON public.snippet_confidence_reviews (reviewer_user_id, created_at DESC);
-- The corpus pull: "how many peer_review rows, split by verdict and by which
-- model version they validated" (services/learning_trace.py).
CREATE INDEX IF NOT EXISTS idx_snippet_confidence_reviews_version_created
    ON public.snippet_confidence_reviews (model_version, created_at DESC);
