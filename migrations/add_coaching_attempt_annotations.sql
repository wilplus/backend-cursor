-- Phase 9 of the snippet-CTA learning loop: admin annotations on coaching attempts.
--
-- The LLM scores each contextual /chat turn-1 exchange (Phase 2)
-- but those scores are an automated guess. Admins need a structured
-- way to say "the LLM nailed it" / "the LLM was generous" / "the
-- specificity score is wrong, here's mine" — both to keep the
-- pipeline honest in production and to produce labelled training
-- data for fine-tuning the evaluator.
--
-- The existing admin_annotation_events table is keyed on
-- (session_id, section_type, field_name) and is for AI-generated
-- DRAFT TEXT that an admin edits (report sections, coaching
-- insights). It doesn't fit the per-attempt review use case: an
-- attempt has a numeric score, three sub-scores, optional entities,
-- and a fact-check result — that's a different shape. A separate
-- table keeps both pipelines clean and lets the fine-tuning export
-- scripts pick the right source for each labelling task.
--
-- Why a row-per-annotation (not a column on coaching_attempts)
-- ------------------------------------------------------------
-- One attempt may be reviewed by multiple admins (peer review,
-- senior coach audit) — we want every verdict, not just the last
-- one. Row-per-annotation also lets us measure inter-rater
-- agreement and per-admin throughput (which is what the future
-- bulk-approve threshold is gated on).
--
-- Idempotent.

CREATE TABLE IF NOT EXISTS coaching_attempt_annotations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    coaching_attempt_id UUID NOT NULL
        REFERENCES coaching_attempts(id) ON DELETE CASCADE,
    admin_user_id UUID NOT NULL,

    -- 'approved' / 'edited' / 'flagged' / 'rejected'. Kept as TEXT
    -- so we can add new actions without a migration. The frontend
    -- enforces the closed set client-side.
    admin_action TEXT NOT NULL,

    -- The admin's own headline score in [0, 1]. NULL means the
    -- admin didn't dispute the LLM's number (the action is the
    -- whole signal — typically a plain "approved" with no rescore).
    admin_score NUMERIC(5, 4),

    -- Per-component sub-scores when the admin disagrees with the
    -- LLM at a more granular level. Shape mirrors
    -- coaching_attempts.components so downstream consumers can
    -- diff them apples-to-apples.
    admin_components JSONB,

    -- Optional free-text rationale. Capped at 2000 chars at the
    -- API boundary — no DB constraint so admins can paste larger
    -- notes when needed.
    admin_note TEXT,

    -- Boolean verdict on the LLM's overall score (separate from
    -- admin_score so an admin can say "score is right but the
    -- rationale missed the point" by leaving admin_score NULL but
    -- ai_score_was_correct = TRUE).
    ai_score_was_correct BOOLEAN,

    -- Optional reason chip for tooling (matches the pattern of the
    -- existing admin_annotation_events table).
    reason_chip TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Most-common query: "what has THIS admin annotated?" — drives the
-- bulk-approve gate (count >= 100) and the per-admin throughput
-- dashboard.
CREATE INDEX IF NOT EXISTS idx_coaching_attempt_annotations_admin
    ON coaching_attempt_annotations (admin_user_id, created_at DESC);

-- Per-attempt fetch for the review UI.
CREATE INDEX IF NOT EXISTS idx_coaching_attempt_annotations_attempt
    ON coaching_attempt_annotations (coaching_attempt_id, created_at DESC);

COMMENT ON TABLE coaching_attempt_annotations IS
    'Admin RLHF annotations on coaching_attempts rows. One row per '
    'review action so multi-admin review and per-admin throughput '
    'stay queryable. Feeds the fine-tuning export pipeline alongside '
    'the existing admin_annotation_events table.';
