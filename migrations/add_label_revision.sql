-- 0258 · label_revision — append-only coach labels. SPEC-immutable-provenance §3.2.
--
-- Coach labels are currently OVERWRITTEN: a re-rate replaces the rater's row
-- in confidence_labels (the physical table behind state_ratings). So "did
-- this coach change their mind, and when?" is unanswerable, and a mistaken
-- bulk edit is unrecoverable. This table is written ALONGSIDE the existing
-- write; nothing is deleted, ever. A re-rate appends a new revision and
-- points `supersedes_id` at what it replaced.
--
-- NO READ PATH CHANGES. confidence_labels stays exactly as it is and remains
-- the "current answer" read for every existing consumer.
--
-- WHY THIS MATTERS BEYOND TIDINESS: invariant I1 hard-codes
-- saw_model_output=false. If a surface ever regresses and shows a machine
-- read next to the controls, revisions let you find EXACTLY WHICH ROWS were
-- written in that window. With overwrite-in-place you can only throw the
-- whole corpus away.
--
-- THE SEED IS AN HONEST SNAPSHOT, NOT A FABRICATED HISTORY. Current
-- confidence_labels rows are copied once as revision 1 with origin='snapshot'
-- — those rows ARE the current answer, so recording them as such is true.
-- What we do NOT do is invent the revisions that led to them: rated_at
-- carries the source row's updated_at, created_at is the snapshot moment,
-- and origin says exactly how the row got here.
--
-- COLUMN TYPES MATCH THE PHYSICAL TABLE (UUID keys), not the spec draft's
-- TEXT — the snapshot is a straight INSERT..SELECT and the live writer sends
-- the same strings PostgREST already casts for confidence_labels. (§10-style
-- divergence, recorded here.)
--
-- BLIND COACH / AC-9: labels are training data, never user-facing. RLS ON,
-- no policies; the service role is the only intended writer.
--
-- Idempotent. Safe to re-run: the snapshot fires only when no snapshot rows
-- exist yet. Safe before or after the code deploys: the live writer degrades
-- to today's behaviour when this table is absent.

BEGIN;

CREATE TABLE IF NOT EXISTS public.label_revision (
    id                    BIGSERIAL PRIMARY KEY,

    snippet_id            UUID    NOT NULL,
    rater_id              UUID    NULL,      -- NULL = anonymous rater
    state_id              TEXT    NOT NULL DEFAULT 'confidence',

    -- The instrument, verbatim from the write it shadows.
    value                 TEXT    NULL,      -- yes | no | neutral
    unrateable            BOOLEAN NOT NULL DEFAULT false,
    confident             BOOLEAN NULL,      -- legacy binary continuity
    intensity             INTEGER NULL,
    note                  TEXT    NULL,
    lane                  TEXT    NULL,      -- bootstrap | coach | game
    source                TEXT    NULL,
    question_id           TEXT    NULL,
    question_version      TEXT    NULL,
    saw_model_output      BOOLEAN NOT NULL DEFAULT false,
    latency_ms            INTEGER NULL,
    session_id            UUID    NULL,
    model_version_at_time TEXT    NULL,
    probe_score_at_time   REAL    NULL,

    -- live     written by the rating write path, in the moment
    -- snapshot the one-time revision-1 copy below
    origin                TEXT    NOT NULL DEFAULT 'live',
    supersedes_id         BIGINT  NULL REFERENCES public.label_revision(id),
    rated_at              TIMESTAMPTZ NULL,  -- the judgment's own timestamp
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'ck_label_revision_origin'
    ) THEN
        ALTER TABLE public.label_revision
            ADD CONSTRAINT ck_label_revision_origin
            CHECK (origin IN ('live', 'snapshot'));
    END IF;
END$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'ck_label_revision_value'
    ) THEN
        ALTER TABLE public.label_revision
            ADD CONSTRAINT ck_label_revision_value
            CHECK (value IS NULL OR value IN ('yes', 'no', 'neutral'));
    END IF;
END$$;

-- "The newest revision per (snippet, rater, state)" — the read that makes
-- the current confidence_labels row a derivable view of this table.
CREATE INDEX IF NOT EXISTS idx_label_revision_key
    ON public.label_revision (snippet_id, rater_id, state_id, id DESC);

CREATE INDEX IF NOT EXISTS idx_label_revision_created
    ON public.label_revision (created_at DESC);

ALTER TABLE public.label_revision ENABLE ROW LEVEL SECURITY;

-- ── SEED: one-time snapshot of the current answers as revision 1 ────────────
INSERT INTO public.label_revision
    (snippet_id, rater_id, state_id, value, unrateable, confident, intensity,
     note, lane, source, question_id, question_version, saw_model_output,
     latency_ms, session_id, model_version_at_time, probe_score_at_time,
     origin, rated_at)
SELECT cl.snippet_id, cl.rater_id, cl.state_id, cl.value, cl.unrateable,
       cl.confident, cl.intensity, cl.note, cl.lane, cl.source,
       cl.question_id, cl.question_version, cl.saw_model_output,
       cl.latency_ms, cl.session_id, cl.model_version_at_time,
       cl.probe_score_at_time, 'snapshot', cl.updated_at
  FROM public.confidence_labels cl
 WHERE NOT EXISTS (
        SELECT 1 FROM public.label_revision lr WHERE lr.origin = 'snapshot');

COMMENT ON TABLE public.label_revision IS
    'SPEC-immutable-provenance §3.2. Append-only shadow of every coach '
    'rating write. confidence_labels remains the current-answer read; this '
    'table answers "what did the rater say BEFORE, and when". Nothing here '
    'is ever updated or deleted. INTERNAL — BLIND COACH / AC-9: never '
    'client-facing.';

COMMIT;

-- ROLLBACK:
--   DROP TABLE IF EXISTS public.label_revision;
