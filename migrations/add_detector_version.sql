-- 0257 · detector_version — what produced a number. SPEC-immutable-provenance §3.1.
--
-- THE DANGER THIS CLOSES, in the founder's own words: "I have a system that
-- compares across databases, so if fillers are corrupted all my data goes
-- nuts." The entire filler detector is a bare module-level list in
-- utils/metrics.py with no version anywhere. Add one word and every `fillers`
-- figure ever computed becomes incomparable with every figure computed
-- afterwards — and nothing in the schema can separate the two eras, so the
-- drift layer reads the step change as the SPEAKER's behaviour, not ours.
--
-- `definition_hash` IS THE LOAD-BEARING COLUMN. A version string is a promise
-- a human can forget to keep; the hash is a fact about what the code actually
-- is. Boot hashes the live definition and compares it to the row for the
-- current version; a mismatch is logged CRITICAL and every row written after
-- it is stamped provenance='suspect' (founder decision 2026-08-10: mark, do
-- not refuse to start — LIVE LOOP).
--
-- THE HASH IS OVER THE CANONICAL FORM, NOT THIS JSONB VERBATIM. Canonical =
-- sorted keys, SORTED lists, no whitespace (services/provenance.py) — sorted
-- because every definition here is a set, so a cosmetic reorder must not read
-- as a behaviour change. Hand-verifying? Hash the canonical string, not the
-- stored definition column.
--
-- `fit_stage` answers a DIFFERENT question from `version`: not "which one"
-- but "how much should you trust it". bootstrap = first pass, expected to
-- move; provisional = stable but not defended; frozen = never changes again,
-- a change mints a new version. Analysis can filter on it — today it cannot
-- filter on anything at all.
--
-- NO BACKFILL. Rows written before this shipped genuinely have unknown
-- provenance; stamping them with today's version would be a FABRICATED
-- provenance, strictly worse than a null. Pre-provenance rows stay NULL.
--
-- AC-9. INTERNAL ONLY — never client-facing. RLS ON, no policies; the
-- service role is the only intended writer.
--
-- Idempotent. Safe to re-run. Safe before or after the code deploys: the
-- writer stamps only when this table is readable, and degrades to today's
-- behaviour (unstamped rows) when it is not.

BEGIN;

CREATE TABLE IF NOT EXISTS public.detector_version (
    detector_id      TEXT        NOT NULL,   -- 'fillers', 'pause_ms', …
    version          TEXT        NOT NULL,   -- 'fillers-v1'
    definition       JSONB       NOT NULL,   -- the lexicon/parameters, VERBATIM
    definition_hash  TEXT        NOT NULL,   -- sha256 of the CANONICAL form
    fit_stage        TEXT        NOT NULL DEFAULT 'bootstrap',
    effective_from   TIMESTAMPTZ NOT NULL DEFAULT now(),
    retired_at       TIMESTAMPTZ NULL,       -- NULL = the current version
    note             TEXT        NULL,
    PRIMARY KEY (detector_id, version)
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'ck_detector_version_fit_stage'
    ) THEN
        ALTER TABLE public.detector_version
            ADD CONSTRAINT ck_detector_version_fit_stage
            CHECK (fit_stage IN ('bootstrap', 'provisional', 'frozen'));
    END IF;
END$$;

-- The boot check's read: "the current (unretired) version of detector X".
CREATE INDEX IF NOT EXISTS idx_detector_version_current
    ON public.detector_version (detector_id, effective_from DESC)
    WHERE retired_at IS NULL;

ALTER TABLE public.detector_version ENABLE ROW LEVEL SECURITY;

-- ── SEED: fillers-v1, the lexicon in force today ────────────────────────────
--
-- Definition VERBATIM from utils/metrics.py DEFAULT_FILLERS (code order).
-- Hash computed by services/provenance.py definition_hash() over the
-- canonical form — reproduce with:
--   python3 -c "from services.provenance import definition_hash, live_definition;
--               print(definition_hash(live_definition('fillers')))"
--
-- 'provisional', not 'frozen': the list is stable but not defended — "so" is
-- a filler AND a conjunction, so a tightening pass is a live prospect. The
-- day it happens mints fillers-v2; this row is retired, never edited.
INSERT INTO public.detector_version
    (detector_id, version, definition, definition_hash, fit_stage, note)
VALUES (
    'fillers',
    'fillers-v1',
    '{"lexicon": ["um", "uh", "like", "you know", "er", "ah", "so"], "match": "whole_word_ci"}'::jsonb,
    '205b3bd38bb9fa9ad7d59bff38893779f2e55846ba8b30b94d75b683b4a58d1f',
    'provisional',
    'DEFAULT_FILLERS as of 2026-08-10. Whole-word, case-insensitive. '
    'Known precision question: "so" is also a conjunction.'
)
ON CONFLICT (detector_id, version) DO NOTHING;

-- ── The stamp on measurement rows ───────────────────────────────────────────
--
-- Both NULLable, deliberately: NULL = pre-provenance (written before this
-- shipped, or while the table was unreachable) and is honest. 'suspect' is
-- NOT the same as NULL — it means the writer LOOKED and found the live code
-- disagreeing with its own version stamp.
ALTER TABLE public.dimension_evaluations
    ADD COLUMN IF NOT EXISTS detector_version TEXT NULL,
    ADD COLUMN IF NOT EXISTS provenance       TEXT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'ck_dimension_evaluations_provenance'
    ) THEN
        ALTER TABLE public.dimension_evaluations
            ADD CONSTRAINT ck_dimension_evaluations_provenance
            CHECK (provenance IS NULL OR provenance IN ('ok', 'suspect'));
    END IF;
END$$;

COMMENT ON TABLE public.detector_version IS
    'SPEC-immutable-provenance §3.1. Append-only versions of every detector '
    'definition that changes a number. definition_hash is sha256 of the '
    'CANONICAL form (services/provenance.py) — a version string is a promise, '
    'the hash is a fact. Rows are retired (retired_at), never edited. '
    'INTERNAL — AC-9: never client-facing.';

COMMENT ON COLUMN public.dimension_evaluations.provenance IS
    'NULL = pre-provenance (honest unknown). ok = live definition hashed to '
    'its recorded version at write time. suspect = it did not — separable '
    'forever, per founder decision 2026-08-10 (mark, never refuse to boot).';

COMMIT;

-- ROLLBACK:
--   ALTER TABLE public.dimension_evaluations
--       DROP COLUMN IF EXISTS detector_version,
--       DROP COLUMN IF EXISTS provenance;
--   DROP TABLE IF EXISTS public.detector_version;
