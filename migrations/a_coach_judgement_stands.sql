-- a_coach_judgement_stands (founder 2026-10-05, W6: LOCKIN §5c, contract 34;
-- decisions log K9).
--
-- 1. A COACH'S ORIGINAL JUDGMENT STANDS. Contract 34: "The original coach
--    judgment is never editable; reconsideration is a separately
--    timestamped, provenance-bearing revision." A re-label used to upsert
--    over the rater's row in confidence_labels, and since the walk's Read
--    screen records the coach's exposure, the new row was stamped not
--    blind: the original blind judgment left every quorum, Album leg and
--    measure. The rating route now appends a later answer by the same rater
--    to label_revision, marked `reconsideration`, superseding the newest
--    revision of that (snippet, rater, state); confidence_labels keeps the
--    original. No read path changes.
--
-- 2. K9: WHY THE CLIP WAS ASKED. Each rating carries the selection policy
--    version, the selection reason and the sampling probability, stamped
--    server-side when the coach answers and never shown before the
--    judgment: a corpus labelling cohort's own record, or the walk's census
--    of the bookmarks that reached the speaker (probability 1). Both on
--    confidence_labels and on its label_revision shadow.
--
-- Nothing here reaches a speaker; nothing is a score (AC-9); a stamp is
-- provenance, never a label (L3). One transaction, additive, idempotent, no
-- env var. label_revision may be absent in a rehearsal lane: its half then
-- degrades to a no-op, as the writers do.

BEGIN;

-- ── 2. K9 on the judgment of record ──────────────────────────────────────

ALTER TABLE public.confidence_labels
    ADD COLUMN IF NOT EXISTS selection_policy_version TEXT NULL,
    ADD COLUMN IF NOT EXISTS selection_reason TEXT NULL,
    ADD COLUMN IF NOT EXISTS sampling_probability DOUBLE PRECISION NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'confidence_labels_sampling_probability_range'
    ) THEN
        ALTER TABLE public.confidence_labels
            ADD CONSTRAINT confidence_labels_sampling_probability_range
            CHECK (sampling_probability IS NULL
                   OR (sampling_probability > 0 AND sampling_probability <= 1));
    END IF;
END $$;

COMMENT ON COLUMN public.confidence_labels.selection_policy_version IS
    'K9 (W6, 2026-10-05): the policy that put this clip in front of the rater, stamped server-side; never shown before the judgment.';
COMMENT ON COLUMN public.confidence_labels.selection_reason IS
    'K9: why the clip was asked (reached_bookmark, a cohort''s model_boundary / band_balance / random_exploration, outside_walk, unknown).';
COMMENT ON COLUMN public.confidence_labels.sampling_probability IS
    'K9: the inclusion probability under that policy, in (0, 1]; NULL when not known. A census row is 1.';

-- ── 1 and 2 on the shadow ────────────────────────────────────────────────

DO $$
BEGIN
    IF to_regclass('public.label_revision') IS NULL THEN
        RETURN;
    END IF;
    ALTER TABLE public.label_revision
        ADD COLUMN IF NOT EXISTS reconsideration BOOLEAN NOT NULL DEFAULT false,
        ADD COLUMN IF NOT EXISTS selection_policy_version TEXT NULL,
        ADD COLUMN IF NOT EXISTS selection_reason TEXT NULL,
        ADD COLUMN IF NOT EXISTS sampling_probability DOUBLE PRECISION NULL;
    COMMENT ON COLUMN public.label_revision.reconsideration IS
        'LOCKIN §5c, contract 34 (W6, 2026-10-05): a later answer by the same rater, kept as its own revision; the original judgment in confidence_labels is never written over.';
END $$;

COMMIT;
