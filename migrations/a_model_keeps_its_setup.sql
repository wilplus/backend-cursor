-- a_model_keeps_its_setup (starting a model; founder, the Claude Code chat,
-- 5 to 9 November 2026: N528 item 4, N566 items 2 to 5, N570, N571, N582,
-- N585; the locked prototype docs/design/model-launchpad-2026-11-09/,
-- version 8). Builds on 0516 (a_person_can_teach_and_start_ai_models).
--
-- The rules live in services/model_setup.py; the store in
-- services/model_setup_store.py.
--
--   ai_models.setup     What the owner said and chose while starting the
--                       model, kept from step to step so a draft survives
--                       ✕ (N566 item 2) and the checklist on its page knows
--                       what is left: the three answers (the problem, how
--                       they solve it today, how they will teach it), the
--                       parts it does, the AI for each part, the starting
--                       rules with their sources and cuts (N585), the
--                       uploaded data's column map and check (N566 item 4),
--                       the two experts of the final exam (N566 item 5),
--                       the teachers' steps, the owner's first 10 (N570 item
--                       3), who was invited, and whether the first Take
--                       filled it (N571). The recipe card stays in
--                       ai_models.recipe; this column never reaches a
--                       teacher.
--   ai_model_examples_take_moment_once
--                       A moment of a Take is gathered into one model once
--                       (MOD-02's job, services/model_examples_from_takes.py),
--                       so a rerun adds nothing twice.
--
--   ai_models_owner_left
--                       When a model's owner is erased (owner_id set to NULL
--                       by the purge or by the foreign key), what they wrote
--                       goes: the description, their name, and the setup's
--                       own words (the three answers, a study's name, an
--                       uploaded file's rows and name, their first answers).
--                       The model's name, its recipe card and the setup's
--                       structure stay, for the teachers it serves (N528
--                       item 11). A draft that loses its owner is archived:
--                       nobody else could finish it.
--
-- Read and written by the backend (service role) only, as 0516's tables.
-- No environment variable needed. The setup keeps no user id
-- (services/model_setup_store.py); a deleted Take's examples go through the
-- purge registry (ai_model_examples_take).
--
-- Idempotent and additive: ADD COLUMN IF NOT EXISTS, a guarded constraint,
-- CREATE UNIQUE INDEX IF NOT EXISTS, CREATE OR REPLACE FUNCTION, and the
-- trigger made only when it is missing. Nothing is dropped, no existing row is rewritten
-- (the new column's default fills it). One transaction.
--
-- Rollback (a new forward migration): leave the column and the index.

BEGIN;

ALTER TABLE public.ai_models
    ADD COLUMN IF NOT EXISTS setup JSONB NOT NULL DEFAULT '{}'::jsonb;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'ai_models_setup_object'
                      AND conrelid = 'public.ai_models'::regclass) THEN
        ALTER TABLE public.ai_models
            ADD CONSTRAINT ai_models_setup_object CHECK (jsonb_typeof(setup) = 'object');
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS ai_model_examples_take_moment_once
    ON public.ai_model_examples (model_id, snippet_id)
    WHERE source = 'takes' AND snippet_id IS NOT NULL;

CREATE OR REPLACE FUNCTION public.ai_models_owner_left() RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
    IF OLD.owner_id IS NOT NULL AND NEW.owner_id IS NULL THEN
        NEW.description := NULL;
        NEW.owner_name := NULL;
        NEW.setup := COALESCE(NEW.setup, '{}'::jsonb)
            - ARRAY['problem', 'today', 'teach', 'from_first_take', 'study_name', 'data',
                    'first_ten', 'similar_seen', 'part_lines'];
        IF NEW.status = 'draft' THEN
            NEW.status := 'archived';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.ai_models_owner_left() FROM PUBLIC, anon, authenticated;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger
                    WHERE tgname = 'ai_models_owner_left'
                      AND tgrelid = 'public.ai_models'::regclass) THEN
        CREATE TRIGGER ai_models_owner_left
            BEFORE UPDATE OF owner_id ON public.ai_models
            FOR EACH ROW EXECUTE FUNCTION public.ai_models_owner_left();
    END IF;
END $$;

COMMIT;
