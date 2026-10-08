-- 0425 · The purge can delete the job plumbing it lists (decided 2026-10-05
--        on W3-B1's finding: these three tables stay "delete with the
--        account", the registry's policy since 0312; retention schedule
--        v1.4 is unchanged).
--
-- WHAT WAS WRONG. services/data_purge_registry.py lists three Phase-1 tables
-- for deletion with the account, and the purge deletes their rows directly
-- with the service key (DataPurgeOrchestrator._resolve_dependency):
--
--   phase1_processing_outbox   each job's delivery row      (phase1_outbox)
--   processing_job_carryovers  a job carried across a new
--                              policy                      (policy_carryovers)
--   processing_orphan_objects  an orphaned audio object's
--                              metadata, after its object  (orphan_metadata)
--
-- 0310 left the service role SELECT and nothing else on all three. Nothing
-- reached those deletes while an erasure of anyone who recorded stopped for
-- review first, at the append-only feedback tables (N14.3). Once retention
-- schedule v1.4's rules decide those tables (0424), the erasure would reach
-- these deletes and fail with InsufficientPrivilege after the person's audio
-- was already gone.
--
-- WHAT THIS DOES, AND ONLY THAT. The purge's door, as the rings (0394) and
-- the practice and training tables (training_copies_are_copies,
-- an_exercise_is_seen and their siblings) have it: DELETE for the service
-- role on exactly these three tables. SELECT stays as it is. No INSERT or
-- UPDATE: intake and the job sync keep writing them through their functions.
-- phase1_processing_jobs and phase1_processing_job_events get nothing: v1.4
-- keeps them as job evidence, and the events are append-only by trigger.
-- PUBLIC, anon and authenticated stay without access. RLS is unchanged; the
-- service role bypasses it, as everywhere.
--
-- No row changes, and no statement here removes one. Idempotent: GRANT is a
-- no-op when the privilege is already held. Each grant is guarded on its
-- table existing, as 0336 does.

BEGIN;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'phase1_processing_outbox'
  ) THEN
    GRANT DELETE ON TABLE public.phase1_processing_outbox TO service_role;
  END IF;

  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'processing_job_carryovers'
  ) THEN
    GRANT DELETE ON TABLE public.processing_job_carryovers TO service_role;
  END IF;

  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'processing_orphan_objects'
  ) THEN
    GRANT DELETE ON TABLE public.processing_orphan_objects TO service_role;
  END IF;
END $$;

COMMIT;
