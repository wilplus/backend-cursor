-- =============================================================================
-- Behavioral recommendation engine v1 / Phase 4: coach approval columns
-- =============================================================================
-- Context:
--   Phase 3 populates ai_suggested_profile + ai_suggested_task_id on session
--   completion. Phase 4 adds the coach-approved counterparts so the admin
--   dashboard can capture Approve / Override decisions.
--
--   Both pairs (ai_* and coach_approved_*) coexist on purpose:
--     * ai_suggested_*       = the machine's guess, never overwritten
--     * coach_approved_*     = the human-locked label (ground truth)
--   This separation is what lets us compute the delta for RLHF/DPO training.
--
--   Every approve/override also lands a row in admin_annotation_events
--   (see routes/v2_routes.py PATCH handler) — this migration only adds the
--   columns that hold the final approved state on the session itself.
--
-- Safe rollback: drop the three columns and their constraint. No data in
--   existing columns is mutated.
-- =============================================================================

BEGIN;

ALTER TABLE public.v2_sessions
  ADD COLUMN IF NOT EXISTS coach_approved_profile TEXT;

ALTER TABLE public.v2_sessions
  ADD COLUMN IF NOT EXISTS coach_approved_task_id UUID;

ALTER TABLE public.v2_sessions
  ADD COLUMN IF NOT EXISTS coach_approved_at TIMESTAMPTZ;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'v2_sessions_coach_approved_task_id_fkey'
      AND conrelid = 'public.v2_sessions'::regclass
  ) THEN
    ALTER TABLE public.v2_sessions
      ADD CONSTRAINT v2_sessions_coach_approved_task_id_fkey
      FOREIGN KEY (coach_approved_task_id)
      REFERENCES public.tasks_pool(id) ON DELETE SET NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'v2_sessions_coach_approved_profile_check'
      AND conrelid = 'public.v2_sessions'::regclass
  ) THEN
    ALTER TABLE public.v2_sessions
      ADD CONSTRAINT v2_sessions_coach_approved_profile_check
      CHECK (
        coach_approved_profile IS NULL
        OR coach_approved_profile IN ('The Overwhelmed', 'The Stressor', 'The Drifter', 'The Master')
      );
  END IF;
END $$;

COMMENT ON COLUMN public.v2_sessions.coach_approved_profile IS
  'Human-locked behavioral profile (Phase 4). Coexists with ai_suggested_profile so the delta feeds RLHF via admin_annotation_events.';
COMMENT ON COLUMN public.v2_sessions.coach_approved_task_id IS
  'Coach-approved behavioral task from tasks_pool (is_behavioral = TRUE). Pre-fills the Send Assignment flow downstream.';
COMMENT ON COLUMN public.v2_sessions.coach_approved_at IS
  'When the coach approved or overrode the AI suggestion. NULL until Phase 4 UI records a decision.';

-- PostgREST schema cache (Supabase)
NOTIFY pgrst, 'reload schema';

COMMIT;
