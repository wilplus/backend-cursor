-- willab — coach-corrected "Say It Stronger" card (Engine 1 completion,
-- founder 2026-07-11). The AUTO card (charisma_snippets.say_it_stronger,
-- write-once draft) stays untouched; the coach's corrected version lives
-- beside it and the user readout folds FINAL over AUTO when present.
-- Keeping BOTH columns preserves the (draft, final) pair — the future
-- correction corpus, same philosophy as the AI-Commentator comment clone.
--
-- Re-editable (plain update, not write-once — the coach may revise).
-- Nullable + additive; writers degrade gracefully pre-migration.
-- Idempotent — safe to re-run.

ALTER TABLE public.charisma_snippets
    ADD COLUMN IF NOT EXISTS say_it_stronger_final JSONB NULL;

-- Rollback (manual):
--   ALTER TABLE public.charisma_snippets DROP COLUMN IF EXISTS say_it_stronger_final;
