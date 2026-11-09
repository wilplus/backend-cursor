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
-- Read and written by the backend (service role) only, as 0516's tables.
-- No environment variable needed. Account erasure: unchanged; the setup goes
-- with its model, and the model's owner is cleared as 0516 has it.
--
-- Idempotent and additive: ADD COLUMN IF NOT EXISTS, a guarded constraint,
-- CREATE UNIQUE INDEX IF NOT EXISTS. Nothing is dropped, no existing row is
-- rewritten (the new column's default fills it). One transaction.
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

COMMIT;
