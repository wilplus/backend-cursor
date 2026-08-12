-- 0268 · user_acoustic_baseline — the speaker's own reference, kept.
--
-- Founder 2026-08-12, the KPI ruling: "MEASURE AGAINST THE USER'S BASELINE".
--
-- ── THE BASELINE IS NOT NEW; KEEPING IT IS ─────────────────────────────────
--
-- services/acoustic_read.py::build_user_baseline has computed exactly this
-- since 2026-07-14: {feature: (mean, sd)} over the speaker's OWN historical
-- pieces, for the four control components (f0_sd, pause_regularity,
-- dynamic_db, voiced_ratio). It runs SYNCHRONOUSLY on the upload path, costs
-- 1 + N queries (up to _BASELINE_MAX_SESSIONS sessions, each a
-- get_snippets_by_session), and is DISCARDED the moment the take finishes.
--
-- So the KPI does not need a new measurement. It needs the existing one to
-- stop being thrown away — and the moving average cannot exist at all until
-- the thing it is an average AGAINST survives longer than one request.
--
-- ── WHY ONE JSONB ROW AND NOT ROW-PER-FEATURE ──────────────────────────────
--
-- The baseline is READ AS A UNIT: all four features z-score the same piece in
-- the same pass. Row-per-feature admits a state where two features come from
-- one computation and two from another, which reads as a valid baseline and
-- is not one — the worst kind of wrong, because nothing about it looks wrong.
-- One row is one atomic snapshot; there is no partial read to have.
--
-- ── APPEND-ONLY. NEVER UPDATE IN PLACE ─────────────────────────────────────
--
-- Founder standing constraint: "treat source data and detector definitions as
-- versioned/immutable. Never silently overwrite labels, lexicons, thresholds,
-- or historical calculations."
--
-- A baseline IS a historical calculation, and this one is load-bearing in a
-- way that makes overwriting worse than usual: the KPI's whole claim is a
-- COMPARISON ("this part is now above where you were"). A comparison whose
-- reference has since been silently recomputed cannot be reproduced, checked,
-- or explained — and the founder's cross-database comparisons would be
-- reading two different regimes as one series.
--
-- So: a new computation INSERTS a row and stamps `superseded_at` on the
-- previous one. Nothing is ever destroyed. `detector_version` is the same
-- immutability key migration 0257 introduced, deliberately reused: a weights
-- change starts a NEW REGIME rather than mixing two, and every consumer can
-- filter to one regime without knowing when the change landed.
--
-- ── COLD START IS A REAL STATE, NOT AN ERROR ───────────────────────────────
--
-- A guest, a first take, or a speaker with fewer than _BASELINE_MIN_SAMPLES
-- usable pieces has NO row here, and that is correct. Readers degrade to the
-- behaviour that exists today (within-take z-scores, no single-point focus).
-- The live loop never depends on this table existing (LIVE LOOP).
--
-- Idempotent. Safe to re-run. Non-destructive: new table only.

BEGIN;

CREATE TABLE IF NOT EXISTS public.user_acoustic_baseline (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           TEXT        NOT NULL,

    -- {feature_key: {"mean": float, "sd": float, "n": int}}
    -- Shaped as an object per feature rather than the in-memory (mean, sd)
    -- tuple so `n` — the evidence behind each feature — survives the write.
    -- A feature backed by 8 pieces and one backed by 80 are not the same
    -- claim, and the tuple could not say so.
    features          JSONB       NOT NULL,

    -- Provenance of the pool this was computed over.
    n_sessions        INTEGER     NOT NULL DEFAULT 0,
    n_samples         INTEGER     NOT NULL DEFAULT 0,

    -- The immutability key (migration 0257). Rows from different versions are
    -- different regimes and must never be averaged together.
    detector_version  TEXT        NOT NULL,

    computed_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- NULL = this is the current baseline for the user. Set when a newer
    -- snapshot lands. The row itself is never deleted or rewritten.
    superseded_at     TIMESTAMPTZ NULL
);

-- The read every consumer performs: "this user's CURRENT baseline".
-- Partial on superseded_at IS NULL because the current set is the small one
-- and the question is never asked the other way round.
CREATE INDEX IF NOT EXISTS idx_user_acoustic_baseline_current
    ON public.user_acoustic_baseline (user_id, detector_version)
    WHERE superseded_at IS NULL;

-- The history read: one user's baselines over time, newest first. This is the
-- reason the table is append-only, so it gets an index rather than a comment
-- promising one later.
CREATE INDEX IF NOT EXISTS idx_user_acoustic_baseline_history
    ON public.user_acoustic_baseline (user_id, computed_at DESC);

ALTER TABLE public.user_acoustic_baseline ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE public.user_acoustic_baseline IS
    'Founder 2026-08-12 KPI ruling — the speaker''s OWN acoustic reference, '
    'persisted instead of recomputed-and-discarded on every upload. One JSONB '
    'row per snapshot because the four features are read as a unit and a '
    'half-written baseline reads as a valid one. APPEND-ONLY: a new '
    'computation inserts and stamps superseded_at on the previous row, never '
    'overwrites — the KPI is a comparison, and a comparison whose reference '
    'was silently recomputed cannot be reproduced. Absent = cold start, which '
    'is a real state: readers degrade to within-take z-scores.';

COMMENT ON COLUMN public.user_acoustic_baseline.features IS
    '{feature_key: {"mean", "sd", "n"}} over the speaker''s own pieces. `n` '
    'is carried per feature because a feature backed by 8 samples and one '
    'backed by 80 are not the same claim.';

COMMENT ON COLUMN public.user_acoustic_baseline.superseded_at IS
    'NULL = current. Set when a newer snapshot lands. The row is never '
    'deleted or rewritten (founder immutability rule).';

COMMIT;
