-- 0259 · threshold_version — what a number was judged against.
-- SPEC-immutable-provenance §3.3.
--
-- Every `fire_at` in dimension_registry is None today, so NOTHING has been
-- judged against a threshold yet — which makes this the cheapest possible
-- moment to add the stamp. The FIRST real threshold is itself a versioning
-- event (version-0 → version-1), and D24 already says T1/T2 thresholds must
-- never adapt; this table is where that stops being a comment and becomes a
-- row.
--
-- NO SEED, deliberately. There is no threshold in force to record, and a
-- placeholder row would be a fabricated provenance — the exact defect this
-- family of tables exists to prevent.
--
-- Append-only like detector_version: a change RETIRES the old row and mints
-- a new version; rows are never edited.
--
-- AC-9. INTERNAL ONLY. RLS ON, no policies; the service role is the only
-- intended writer.
--
-- Idempotent. Safe to re-run, safe before or after the code deploys.

BEGIN;

CREATE TABLE IF NOT EXISTS public.threshold_version (
    dimension_id     TEXT        NOT NULL,
    version          TEXT        NOT NULL,
    fire_at          DOUBLE PRECISION NULL,
    clear_at         DOUBLE PRECISION NULL,
    tier             TEXT        NULL,       -- T1 | T2 | T3 | CORPUS_REL
    fit_stage        TEXT        NOT NULL DEFAULT 'bootstrap',
    effective_from   TIMESTAMPTZ NOT NULL DEFAULT now(),
    retired_at       TIMESTAMPTZ NULL,       -- NULL = the current version
    note             TEXT        NULL,
    PRIMARY KEY (dimension_id, version)
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'ck_threshold_version_fit_stage'
    ) THEN
        ALTER TABLE public.threshold_version
            ADD CONSTRAINT ck_threshold_version_fit_stage
            CHECK (fit_stage IN ('bootstrap', 'provisional', 'frozen'));
    END IF;
END$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'ck_threshold_version_tier'
    ) THEN
        ALTER TABLE public.threshold_version
            ADD CONSTRAINT ck_threshold_version_tier
            CHECK (tier IS NULL
                   OR tier IN ('T1', 'T2', 'T3', 'CORPUS_REL'));
    END IF;
END$$;

CREATE INDEX IF NOT EXISTS idx_threshold_version_current
    ON public.threshold_version (dimension_id, effective_from DESC)
    WHERE retired_at IS NULL;

ALTER TABLE public.threshold_version ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE public.threshold_version IS
    'SPEC-immutable-provenance §3.3. Append-only versions of every judgment '
    'threshold. Empty on purpose until the first threshold is set — that '
    'first value is itself a versioning event. Rows are retired, never '
    'edited. INTERNAL — AC-9: never client-facing.';

COMMIT;

-- ROLLBACK:
--   DROP TABLE IF EXISTS public.threshold_version;
