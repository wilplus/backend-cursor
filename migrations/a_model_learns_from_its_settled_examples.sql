-- a_model_learns_from_its_settled_examples (a model answers from a small
-- head trained on its own settled examples; founder, the Claude Code chat,
-- 10 November 2026: N615 items 2 and 3, N616 items 8, 9, 10 and 23, N620;
-- the stories LEARN-01 to LEARN-06 and PIPE-06 of
-- docs/design/the-blank-setup-2026-11-10/stories.json).
--
-- Builds on a_person_can_teach_and_start_ai_models (0516) and
-- a_business_can_buy_a_model_s_answers (0521). The rules live in
-- services/model_head.py, which has no storage of its own; these columns
-- and this table only hold what it reads.
--
--   ai_model_example_vectors  Each example read ONCE by the shared reader
--                             for its kind (text, or a voice clip's words
--                             and its stored voice measures) and the vector
--                             kept, so a refit never calls the reader again.
--                             One row per example; it goes with its example
--                             (ON DELETE CASCADE).
--   ai_model_versions (6 columns)
--                             head         the fitted head: its answers,
--                                          weights and bias (JSON numbers)
--                             confidence   how often the head was right at
--                                          each probability level, measured
--                                          by cross-validation when fitted;
--                                          "sure" is read from it
--                             example_ids  the examples it was fitted on
--                                          (PIPE-06), so a deletion finds
--                                          every version it touches
--                             retrain_at   set when an example it learned
--                                          from is deleted or withdrawn: the
--                                          next fit leaves it out
--                             owner_check  the owner's check of ten unseen
--                                          examples (N616 item 23)
--                             owner_checked_at  when the owner passed it
--                                          (gate one, N616 item 10)
--   ai_models (1 column)      retrain_at: WillpowerLab's founder asked for a
--                             new fit; the background job takes it.
--
-- A trigger keeps PIPE-06 whatever deletes an example: a withdrawn training
-- yes (services/model_examples_from_takes.py), a deleted Take, an erased
-- account (ON DELETE CASCADE from auth.users), a deleted model. After each
-- deleted example, every version whose example_ids holds it is marked to
-- retrain (retrain_at, kept if already set). It writes nothing else.
--
-- Read and written by the backend (service role) only; nothing for anon or
-- authenticated. RLS on, no policies, like the neighbouring model tables. No
-- environment variable needed. No new ring row: everything here sits behind
-- the ring row ai_models (0516).
--
-- Idempotent and additive: CREATE ... IF NOT EXISTS, ADD COLUMN IF NOT
-- EXISTS, constraints and the trigger added only when missing, CREATE OR
-- REPLACE for the trigger's function; nothing is dropped and no existing row
-- is written, rewritten or removed. One transaction.
--
-- Rollback (a new forward migration): leave the table and columns; dropping
-- them is a separate, previewed retention operation. The trigger can be
-- disabled with ALTER TABLE ... DISABLE TRIGGER.

BEGIN;

CREATE TABLE IF NOT EXISTS public.ai_model_example_vectors (
    example_id  UUID              PRIMARY KEY REFERENCES public.ai_model_examples(id) ON DELETE CASCADE,
    reader      TEXT              NOT NULL,
    vector      DOUBLE PRECISION[] NOT NULL,
    created_at  TIMESTAMPTZ       NOT NULL DEFAULT now(),
    CONSTRAINT ai_model_example_vectors_reader_len CHECK (char_length(reader) BETWEEN 1 AND 120),
    CONSTRAINT ai_model_example_vectors_dims CHECK (cardinality(vector) BETWEEN 1 AND 4096)
);

ALTER TABLE public.ai_model_versions ADD COLUMN IF NOT EXISTS head             JSONB       NULL;
ALTER TABLE public.ai_model_versions ADD COLUMN IF NOT EXISTS confidence       JSONB       NULL;
ALTER TABLE public.ai_model_versions ADD COLUMN IF NOT EXISTS example_ids      UUID[]      NOT NULL DEFAULT '{}'::uuid[];
ALTER TABLE public.ai_model_versions ADD COLUMN IF NOT EXISTS retrain_at       TIMESTAMPTZ NULL;
ALTER TABLE public.ai_model_versions ADD COLUMN IF NOT EXISTS owner_check      JSONB       NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE public.ai_model_versions ADD COLUMN IF NOT EXISTS owner_checked_at TIMESTAMPTZ NULL;

ALTER TABLE public.ai_models ADD COLUMN IF NOT EXISTS retrain_at TIMESTAMPTZ NULL;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ai_model_versions_head_object') THEN
        ALTER TABLE public.ai_model_versions
            ADD CONSTRAINT ai_model_versions_head_object CHECK (head IS NULL OR jsonb_typeof(head) = 'object');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ai_model_versions_confidence_object') THEN
        ALTER TABLE public.ai_model_versions
            ADD CONSTRAINT ai_model_versions_confidence_object
            CHECK (confidence IS NULL OR jsonb_typeof(confidence) = 'object');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ai_model_versions_owner_check_object') THEN
        ALTER TABLE public.ai_model_versions
            ADD CONSTRAINT ai_model_versions_owner_check_object CHECK (jsonb_typeof(owner_check) = 'object');
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_ai_model_versions_example_ids
    ON public.ai_model_versions USING GIN (example_ids);
CREATE INDEX IF NOT EXISTS idx_ai_model_versions_retrain
    ON public.ai_model_versions (model_id) WHERE retrain_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_ai_models_retrain
    ON public.ai_models (id) WHERE retrain_at IS NOT NULL;

-- PIPE-06: a deleted example marks every version that learned from it.
CREATE OR REPLACE FUNCTION public.ai_model_versions_mark_retrain()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    UPDATE public.ai_model_versions
       SET retrain_at = now()
     WHERE example_ids @> ARRAY[OLD.id]
       AND retrain_at IS NULL;
    RETURN OLD;
END
$$;

REVOKE ALL ON FUNCTION public.ai_model_versions_mark_retrain() FROM PUBLIC, anon, authenticated;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger
                    WHERE tgname = 'ai_model_examples_mark_retrain'
                      AND tgrelid = 'public.ai_model_examples'::regclass) THEN
        CREATE TRIGGER ai_model_examples_mark_retrain
            AFTER DELETE ON public.ai_model_examples
            FOR EACH ROW EXECUTE FUNCTION public.ai_model_versions_mark_retrain();
    END IF;
END
$$;

ALTER TABLE public.ai_model_example_vectors ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.ai_model_example_vectors FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.ai_model_example_vectors TO service_role;

COMMIT;
