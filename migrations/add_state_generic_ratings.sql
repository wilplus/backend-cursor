-- willab — STATE-GENERIC TERNARY RATINGS (SPEC.md v3 §6, slice 1).
--
-- Extends confidence_labels in place. Deliberately NOT a new table.
--
-- WHY EXTEND RATHER THAN REPLACE. The existing table is already the right
-- shape for what the spec asks: keyed (snippet_id, rater_id) so multiple
-- raters per snippet can be aggregated, and carrying `source` so the coach's
-- truth stays distinguishable from a game answer. A parallel table would mean
-- either dual-writing (drift) or a hard cutover (loses the rows already
-- collected). Neither is worth it for columns that add cleanly.
--
-- The physical table keeps its name. `state_ratings` is added as a VIEW so
-- the generic name exists without renaming a live table.
--
-- WHAT CHANGES, AND WHY EACH ONE
--
--   state_id      SPEC §1: the schema is state-generic, populated with one
--                 state. v1.0 writes only 'confidence'. A second state is
--                 then a config row, not a migration.
--
--   value         SPEC §3.2 (D3): the instrument is TERNARY — yes/no/neutral.
--                 `confident BOOLEAN` cannot carry three values. The boolean
--                 is KEPT and backfilled from, never dropped.
--
--                 'neutral' is not a hedge. It is a judgment that the moment
--                 reads as middling, and it is a real class the model must
--                 learn — a recogniser that has never seen the middle has
--                 never seen the boundary it exists to find.
--
--   unrateable    SPEC §3.2: a SEPARATE CONTROL, not a fourth value. 'neutral'
--                 is a judgment about the moment; 'unrateable' is a judgment
--                 about the rater's ability to make one. Folding them books
--                 unclear audio as a real middling rating and quietly poisons
--                 the one class that defines the boundary. Kept out of the
--                 answer space so the ternary stays clean, and kept as data so
--                 abstention rate survives as a rater-quality signal.
--
--   lane          SPEC §6.2: bootstrap | coach | game_peer | game_owner.
--                 The bootstrap lane is one rater on a model-proposed
--                 candidate — NOT panel-grade — and must be excludable from
--                 agreement statistics and from the gold set by query. Without
--                 this column that exclusion is impossible after the fact.
--
--   question_id / question_version
--                 SPEC §1.4 + §17: the question wording IS the operational
--                 definition. Changing it starts a new corpus. Unversioned
--                 rows cannot be split later, so a wording change would
--                 silently blend two constructs — the exact failure the
--                 version stamp on voice_confidence.py exists to prevent.
--
--   saw_model_output / latency_ms / probe_score_at_time /
--   model_version_at_time
--                 SPEC I9, full label provenance. Without it a contaminated
--                 labelling period cannot be identified, and one bad stretch
--                 poisons the corpus permanently because you cannot find it.
--                 saw_model_output MUST be false for every rating step (I1) —
--                 it is stored so the invariant is auditable, not assumed.
--
-- WHAT IS NOT DROPPED. `confident` and `intensity` stay. intensity is the
-- 1-5 Jiang & Pell scale and remains the human side of the validation gate.
-- Nothing here drops a column or a table (standing constraint).
--
-- ONE CONSTRAINT IS RELAXED: confident loses NOT NULL, because a 'neutral' or
-- unrateable row has no boolean to store and writing false would be a
-- fabricated label. Relaxing a constraint is reversible; fabricating training
-- data is not.
--
-- Idempotent; safe to re-run. RLS ON with no policies = service-role only.

ALTER TABLE public.confidence_labels
    ADD COLUMN IF NOT EXISTS state_id              TEXT NOT NULL DEFAULT 'confidence',
    ADD COLUMN IF NOT EXISTS value                 TEXT NULL,
    ADD COLUMN IF NOT EXISTS unrateable            BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS lane                  TEXT NULL,
    ADD COLUMN IF NOT EXISTS question_id           TEXT NULL,
    ADD COLUMN IF NOT EXISTS question_version      TEXT NULL,
    ADD COLUMN IF NOT EXISTS saw_model_output      BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS latency_ms            INTEGER NULL,
    ADD COLUMN IF NOT EXISTS probe_score_at_time   REAL NULL,
    ADD COLUMN IF NOT EXISTS model_version_at_time TEXT NULL;

-- confident: NOT NULL -> NULL. See the header. Guarded so a re-run is a no-op.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name   = 'confidence_labels'
           AND column_name  = 'confident'
           AND is_nullable  = 'NO'
    ) THEN
        ALTER TABLE public.confidence_labels
            ALTER COLUMN confident DROP NOT NULL;
    END IF;
END$$;

-- The ternary domain. 'neutral' is a first-class answer, not an absence.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'ck_confidence_labels_value'
    ) THEN
        ALTER TABLE public.confidence_labels
            ADD CONSTRAINT ck_confidence_labels_value
            CHECK (value IS NULL OR value IN ('yes', 'no', 'neutral'));
    END IF;
END$$;

-- An unrateable row carries no answer, and an answered row is not unrateable.
-- Enforced in the database because this is the pair most likely to drift: a
-- future FE that sends both would otherwise write a row that is simultaneously
-- a rating and a refusal to rate.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'ck_confidence_labels_unrateable_exclusive'
    ) THEN
        ALTER TABLE public.confidence_labels
            ADD CONSTRAINT ck_confidence_labels_unrateable_exclusive
            CHECK (NOT (unrateable AND value IS NOT NULL));
    END IF;
END$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'ck_confidence_labels_lane'
    ) THEN
        ALTER TABLE public.confidence_labels
            ADD CONSTRAINT ck_confidence_labels_lane
            CHECK (lane IS NULL
                   OR lane IN ('bootstrap', 'coach', 'game_peer', 'game_owner'));
    END IF;
END$$;

-- BACKFILL. Existing rows are binary coach calls; map them onto the ternary
-- so the corpus is continuous across the cutover. They genuinely produced no
-- 'neutral' — the old instrument had no way to express one — so the absence
-- is honest rather than a gap to be filled.
UPDATE public.confidence_labels
   SET value = CASE WHEN confident THEN 'yes' ELSE 'no' END
 WHERE value IS NULL
   AND confident IS NOT NULL;

-- Pre-existing rows predate the versioned question and predate the lanes.
-- Stamp them as such rather than guessing: 'conf-q-v0' is explicitly "the
-- binary instrument", which is what makes them separable from v1 later.
UPDATE public.confidence_labels
   SET question_id      = COALESCE(question_id, 'confidence'),
       question_version = COALESCE(question_version, 'conf-q-v0')
 WHERE question_version IS NULL;

UPDATE public.confidence_labels
   SET lane = CASE WHEN source = 'coach' THEN 'coach' ELSE 'game_peer' END
 WHERE lane IS NULL;

ALTER TABLE public.confidence_labels ENABLE ROW LEVEL SECURITY;

CREATE INDEX IF NOT EXISTS idx_confidence_labels_state_snippet
    ON public.confidence_labels (state_id, snippet_id);
-- The agreement pull: every rating on a snippet for one state, panel lanes
-- only. bootstrap is excluded by the caller, not here — the index serves both.
CREATE INDEX IF NOT EXISTS idx_confidence_labels_state_lane_created
    ON public.confidence_labels (state_id, lane, created_at DESC);
-- The corpus pull for training: answered rows for one state, in order.
CREATE INDEX IF NOT EXISTS idx_confidence_labels_state_value
    ON public.confidence_labels (state_id, value)
    WHERE value IS NOT NULL;

-- The generic name, without renaming a live table.
CREATE OR REPLACE VIEW public.state_ratings AS
    SELECT id, snippet_id, session_id, rater_id, state_id, lane, source,
           value, unrateable, question_id, question_version,
           saw_model_output, latency_ms, probe_score_at_time,
           model_version_at_time, confident, intensity, note,
           created_at, updated_at
      FROM public.confidence_labels;

COMMENT ON VIEW public.state_ratings IS
    'SPEC.md v3 §6 — state-generic ternary ratings. Physical table is '
    'confidence_labels, extended in place by add_state_generic_ratings.sql. '
    'v1.0 populates state_id=''confidence'' only.';
